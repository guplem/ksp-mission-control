"""LaunchAction - ascent to target apoapsis with gravity turn.

Launches the vessel from the pad (or ground) and performs a gravity turn
to reach a target apoapsis altitude. Cuts engines once the apoapsis is
reached, leaving circularization to a separate action.

Gravity turn approach
---------------------
Pitch is driven by ``orbit_apoapsis`` progress toward ``target_altitude``,
not by current altitude. This guarantees the turn always finishes exactly
when the target is met, regardless of the rocket's thrust profile:

  progress = orbit_apoapsis / target_altitude   (clamped to [0, 1])
  shaped   = progress ** turn_exponent
  pitch    = cos(shaped * 90 deg) * (90 - final_pitch) + final_pitch

At apoapsis = 0 the pitch is 90 deg (straight up). At apoapsis =
target_altitude the pitch reaches ``final_pitch`` deg, at which point the
action also completes. With ``final_pitch = 0`` (the default) the turn
ends horizontal; with ``final_pitch = 45`` the turn ends at a 45 deg
climb, still gaining altitude as apoapsis is reached.

``turn_exponent`` reshapes how fast the turn happens between those
endpoints. At ``1.0`` progress is used as-is: the original cosine curve.
Below ``1.0`` the pitch drops to horizontal earlier in the climb, so the
vessel builds horizontal velocity sooner and reaches the target apoapsis
nearly orbital (small circularization burn). Above ``1.0`` it stays
vertical longer. The default is ``0.7`` (a moderately aggressive turn that
suits most launches); a high-thrust vessel whose apoapsis still outruns its
horizontal velocity wants a lower value, tuned in-game against the
periapsis at engine cutoff.

Phases
------
1. **Vertical ascent**: Full throttle straight up until sea altitude
   reaches turn_start_altitude.
2. **Gravity turn**: Pitch is updated every tick based on apoapsis
   progress toward target_altitude, following the target inclination
   heading.
3. **Complete**: Cut engines when apoapsis reaches target_altitude.

Parameter defaults
------------------
All parameters are nullable. When None, they are inferred from the current
body's properties at start():

- target_altitude: body_atmosphere_depth * 1.1 (or 50km if no atmosphere)
- target_inclination: abs(latitude) (lowest-energy eastward launch)
- turn_start_altitude: initial altitude + 50m (just enough to clear the pad)
- final_pitch: 0 (horizontal at end of turn)
- turn_exponent: 0.7 (moderately aggressive; 1.0 is the original cosine curve)
"""

from __future__ import annotations

from math import asin, cos, degrees, radians
from typing import Any, ClassVar

from ksp_mission_control.control.actions.base import (
    Action,
    ActionLogger,
    ActionParam,
    ActionResult,
    ActionStatus,
    ParamType,
    SpeedMode,
    State,
    VesselCommands,
)
from ksp_mission_control.control.actions.helpers.staging import (
    STAGING_MODE_PARAM,
    StagingMode,
    auto_stage,
    parse_staging_mode,
)

_APOAPSIS_TOLERANCE_MULTIPLIER = 0.002  # fraction of target altitude to consider "close enough" to apoapsis
_GRAVITY_TURN_CLEARANCE = 50  # meters: default vertical climb above the launch altitude before the turn begins
_DEFAULT_ALTITUDE_ATMOSPHERE_MULTIPLIER = 1.1  # multiplier: default target = atmosphere_depth * this
_DEFAULT_ALTITUDE_AIRLESS_BODY = 50_000.0  # meters: default target when body has no atmosphere
_DEFAULT_TURN_EXPONENT = 0.7  # gravity-turn pitch-curve shape; <1 turns earlier (more aggressive), 1.0 = original cosine curve


def _inclination_to_heading(inclination_deg: float, latitude_deg: float = 0.0) -> float:
    """Convert an orbital inclination (degrees) to a launch compass heading.

    Uses the spherical geometry relation:
        sin(heading) = cos(inclination) / cos(latitude)

    0 deg inclination = due east (heading 90).
    90 deg inclination = due north (heading 0).
    Negative inclination = launch southeast (heading > 90).

    If the desired inclination is less than the launch latitude (geometrically
    impossible), clamps to the nearest reachable heading (due east/west).

    Returns heading in [0, 360).
    """
    cos_inc = cos(radians(abs(inclination_deg)))
    cos_lat = cos(radians(latitude_deg))

    # Clamp for impossible inclinations (inc < latitude).
    sin_heading = min(1.0, cos_inc / cos_lat) if cos_lat > 0 else 1.0

    heading = degrees(asin(sin_heading))

    # Negative inclination means launch southeast instead of northeast.
    if inclination_deg < 0:
        heading = 180.0 - heading

    return heading % 360.0


class LaunchAction(Action):
    """Ascend from the pad to a target apoapsis via gravity turn."""

    action_id: ClassVar[str] = "launch"
    label: ClassVar[str] = "Launch"
    description: ClassVar[str] = "Ascend to target apoapsis with gravity turn"
    params: ClassVar[list[ActionParam]] = [
        ActionParam(
            param_id="target_altitude",
            label="Target Altitude",
            description=(
                f"Target apoapsis altitude (default: {_DEFAULT_ALTITUDE_ATMOSPHERE_MULTIPLIER:.0%} of atmosphere, "
                f"or {_DEFAULT_ALTITUDE_AIRLESS_BODY:,.0f}m)"
            ),
            required=False,
            param_type=ParamType.FLOAT,
            default=None,
            unit="m",
        ),
        ActionParam(
            param_id="target_inclination",
            label="Target Inclination",
            description=(
                "Orbital inclination in degrees: 0 = equatorial east, 90 = polar, 180 = equatorial west (default: current orbital inclination)"
            ),
            required=False,
            param_type=ParamType.FLOAT,
            default=None,
            unit="deg",
        ),
        ActionParam(
            param_id="turn_start_altitude",
            label="Turn Start Altitude",
            description=f"Sea altitude at which the gravity turn begins (default: initial altitude + {_GRAVITY_TURN_CLEARANCE}m)",
            required=False,
            param_type=ParamType.FLOAT,
            default=None,
            unit="m",
        ),
        ActionParam(
            param_id="final_pitch",
            label="Final Pitch",
            description=(
                "Pitch angle above the horizon when the target apoapsis is reached. 0 = horizontal, 45 = 45 deg climb, 90 = straight up (no turn)."
            ),
            required=False,
            param_type=ParamType.FLOAT,
            default=2.5,
            unit="deg",
        ),
        ActionParam(
            param_id="turn_exponent",
            label="Turn Exponent",
            description=(
                "Shapes the gravity-turn pitch curve. 1.0 = original cosine curve; below 1.0 turns to "
                "horizontal earlier (more aggressive, builds horizontal velocity sooner); above 1.0 stays "
                "vertical longer. Must be positive."
            ),
            required=False,
            param_type=ParamType.FLOAT,
            default=_DEFAULT_TURN_EXPONENT,
        ),
        STAGING_MODE_PARAM,
    ]

    def start(self, state: State, param_values: dict[str, Any]) -> None:
        # Resolve target_altitude: use provided value, or infer from body.
        raw_altitude = param_values["target_altitude"]
        if raw_altitude is not None:
            self._target_altitude: float = float(raw_altitude)
        elif state.body_has_atmosphere:
            self._target_altitude = state.body_atmosphere_depth * _DEFAULT_ALTITUDE_ATMOSPHERE_MULTIPLIER
        else:
            self._target_altitude = _DEFAULT_ALTITUDE_AIRLESS_BODY

        # Resolve target_inclination: use provided value, or default to the
        # minimum reachable inclination from the launch latitude (|latitude|),
        # which gives the lowest-energy eastward launch.
        raw_inclination = param_values["target_inclination"]
        if raw_inclination is not None:
            self._target_inclination: float = float(raw_inclination)
        else:
            self._target_inclination = abs(state.position_latitude)

        # Resolve turn_start_altitude: use provided value, or default to
        # clearance above the initial altitude (just enough to clear the pad).
        raw_turn_start = param_values["turn_start_altitude"]
        if raw_turn_start is not None:
            self._turn_start_altitude: float = float(raw_turn_start)
        else:
            self._turn_start_altitude = state.altitude_sea + _GRAVITY_TURN_CLEARANCE

        # Resolve final_pitch: angle above the horizon when the turn ends.
        raw_final_pitch = param_values["final_pitch"]
        self._final_pitch: float = float(raw_final_pitch) if raw_final_pitch is not None else 0.0

        # Resolve turn_exponent: reshapes the pitch curve. Must be positive;
        # a non-positive exponent makes ``progress ** exponent`` degenerate.
        raw_turn_exponent = param_values["turn_exponent"]
        self._turn_exponent: float = float(raw_turn_exponent) if raw_turn_exponent is not None else _DEFAULT_TURN_EXPONENT
        if self._turn_exponent <= 0.0:
            raise ValueError(f"turn_exponent must be positive (got {self._turn_exponent})")

        self._staging_mode: StagingMode | None = parse_staging_mode(param_values["staging_mode"])

        # Compute tolerance for considering apoapsis "close enough" to target.
        self._tolerance_altitude: float = self._target_altitude * _APOAPSIS_TOLERANCE_MULTIPLIER

        # Validate that the requested inclination is geometrically reachable
        # from the current latitude. The minimum reachable inclination from
        # latitude phi is |phi|; the maximum is 180 - |phi|.
        self._fail_message: str | None = None
        abs_inc = abs(self._target_inclination)
        abs_lat = abs(state.position_latitude)
        if abs_inc < abs_lat or abs_inc > 180.0 - abs_lat:
            self._fail_message = (
                f"Inclination {self._target_inclination:.1f} deg unreachable from latitude "
                f"{state.position_latitude:.1f} deg. Reachable range: "
                f"[{abs_lat:.1f}, {180.0 - abs_lat:.1f}] deg."
            )

        # Validate final_pitch is within a sensible range. 90 means no turn
        # at all (straight up), so we cap the upper bound just below it.
        if self._final_pitch < 0.0 or self._final_pitch >= 90.0:
            self._fail_message = f"Final pitch {self._final_pitch:.1f} deg out of range. Must be in [0, 90)."

        # Compute the launch heading from the target inclination.
        self._launch_heading: float = _inclination_to_heading(self._target_inclination, state.position_latitude)

    def tick(self, state: State, commands: VesselCommands, dt: float, log: ActionLogger) -> ActionResult:

        # Surface a start-time validation failure on the first tick.
        if self._fail_message is not None:
            return ActionResult(status=ActionStatus.FAILED, message=self._fail_message)

        # Check if finished.
        if state.orbit_apoapsis >= self._target_altitude - self._tolerance_altitude:
            return ActionResult(status=ActionStatus.SUCCEEDED, message=f"Target apoapsis reached ({state.orbit_apoapsis:,.1f} m)")

        # Auto-stage opportunistically. ANY_FLAMEOUT may stage even while
        # thrust is still available (drops empty side boosters); FULL_DEPLETION
        # only stages when thrust has dropped to zero with inactive engines waiting.
        if auto_stage(state, commands, self._staging_mode, log):
            return ActionResult(status=ActionStatus.RUNNING, message="Staging to next stage")

        # Check if remaining thrust.
        if state.thrust_available <= 0:
            return ActionResult(status=ActionStatus.FAILED, message="No thrust available")

        commands.ui_speed_mode = SpeedMode.ORBIT
        commands.autopilot = True
        commands.throttle = 1.0

        # Heading is the launch azimuth (constant throughout the ascent); the
        # autopilot rolls the vessel implicitly to align the body pitch axis
        # with the orbital plane, so the gravity turn only varies pitch.
        commands.autopilot_heading = self._launch_heading

        # Pitch: vertical until the vessel reaches turn_start_altitude, then
        # track apoapsis progress toward target_altitude. The curve interpolates
        # from 90 deg (straight up) down to final_pitch as progress goes 0 -> 1.
        # turn_exponent reshapes that curve: below 1.0 the turn happens earlier.
        progress = max(0.0, min(1.0, state.orbit_apoapsis / self._target_altitude))
        if state.altitude_sea < self._turn_start_altitude:
            commands.autopilot_pitch = 90.0
        else:
            shaped_progress = progress**self._turn_exponent
            commands.autopilot_pitch = cos(radians(shaped_progress * 90.0)) * (90.0 - self._final_pitch) + self._final_pitch

        log.debug(f"Dynamic pressure: {(state.pressure_dynamic / 1000):.1f}kPa")

        return ActionResult(
            status=ActionStatus.RUNNING,
            message=f"Apoapsis: {state.orbit_apoapsis:,.1f} m / {self._target_altitude:,.1f} m (progress: {progress:.1%})",
        )

    def stop(self, state: State, commands: VesselCommands, log: ActionLogger) -> None:
        # Cut engines and disengage autopilot on stop/abort.
        commands.autopilot = False
        commands.sas = False
        commands.throttle = 0.0
