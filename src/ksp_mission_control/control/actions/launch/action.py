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
  pitch    = cos(progress * 90 deg) * 90 deg

At apoapsis = 0 the pitch is 90 deg (straight up). At apoapsis =
target_altitude the pitch reaches 0 deg (horizontal), at which point the
action also completes.

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

# ---------------------------------------------------------------------------
# Tuning constants
# ---------------------------------------------------------------------------

_APOAPSIS_TOLERANCE_MULTIPLIER = 0.002  # fraction of target altitude to consider "close enough" to apoapsis
_GRAVITY_TURN_CLEARANCE = 50  # meters: default vertical climb above the launch altitude before the turn begins
_DEFAULT_ALTITUDE_ATMOSPHERE_MULTIPLIER = 1.1  # multiplier: default target = atmosphere_depth * this
_DEFAULT_ALTITUDE_AIRLESS_BODY = 50_000.0  # meters: default target when body has no atmosphere


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Action
# ---------------------------------------------------------------------------


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
            param_id="auto_stage",
            label="Auto Stage",
            description="Automatically stage when thrust is lost (ignition, booster sep, flameout). Disable if staging manually.",
            required=False,
            param_type=ParamType.BOOL,
            default=False,
        ),
    ]

    # -- Lifecycle ------------------------------------------------------------

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

        self._auto_stage: bool = bool(param_values["auto_stage"])

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

        # Compute the launch heading from the target inclination.
        self._launch_heading: float = _inclination_to_heading(self._target_inclination, state.position_latitude)

    def tick(self, state: State, commands: VesselCommands, dt: float, log: ActionLogger) -> ActionResult:

        # Surface a start-time validation failure on the first tick.
        if self._fail_message is not None:
            return ActionResult(status=ActionStatus.FAILED, message=self._fail_message)

        # Check if finished.
        if state.orbit_apoapsis >= self._target_altitude - self._tolerance_altitude:
            return ActionResult(status=ActionStatus.SUCCEEDED, message=f"Target apoapsis reached ({state.orbit_apoapsis:,.1f} m)")

        # Check if remaining thrust.
        if state.thrust_available <= 0:
            if self._auto_stage:
                if state.parts.engines_inactive() > 0:
                    commands.stage = True
                    log.info(f"Staging: no thrust, {state.parts.engines_inactive()} inactive engine(s) available")
                    return ActionResult(status=ActionStatus.RUNNING, message="Staging to ignite engines")
                return ActionResult(status=ActionStatus.FAILED, message="No thrust available and no inactive engines to stage")
            return ActionResult(status=ActionStatus.FAILED, message="No thrust available")

        commands.ui_speed_mode = SpeedMode.ORBIT
        commands.autopilot = True
        commands.throttle = 1.0

        # Heading is the launch azimuth (constant throughout the ascent); the
        # autopilot rolls the vessel implicitly to align the body pitch axis
        # with the orbital plane, so the gravity turn only varies pitch.
        commands.autopilot_heading = self._launch_heading

        # Pitch: vertical until the vessel reaches turn_start_altitude, then
        # track apoapsis progress toward target_altitude.
        progress = max(0.0, min(1.0, state.orbit_apoapsis / self._target_altitude))
        if state.altitude_sea < self._turn_start_altitude:
            commands.autopilot_pitch = 90.0
        else:
            commands.autopilot_pitch = cos(radians(progress * 90.0)) * 90.0

        log.debug(f"Dynamic pressure: {(state.pressure_dynamic / 1000):.1f}kPa")
        log.debug(f"Apoapsis: {state.orbit_apoapsis:,.1f} m / {self._target_altitude:,.1f} m (progress: {progress:.1%})")

        return ActionResult(status=ActionStatus.RUNNING)

    def stop(self, state: State, commands: VesselCommands, log: ActionLogger) -> None:
        # Cut engines and disengage autopilot on stop/abort.
        commands.autopilot = False
        commands.sas = False
        commands.throttle = 0.0
