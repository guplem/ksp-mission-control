"""DeorbitToTargetAction - retrograde burn timed for a target lat/lon impact.

The action runs a closed loop driven by ``State.predicted_impact``, which the
bridge fills with the ballistic lat/lon where the post-node trajectory crashes.

The burn point sets the impact, and it is chosen so the impact lands on the
target in **both** axes:

- **Latitude** comes from *where in the orbit* the burn happens. A retrograde
  burn makes the burn point the post-burn apoapsis; the trajectory then
  reaches sea level a fixed travel angle downtrack (180 deg minus the true
  anomaly of the sea-level crossing, ``_travel_angle_burn_to_impact_deg``).
  So the action burns at the point that places that crossing on the target
  latitude (``_burn_ut_for_target_latitude``). This requires inclination >=
  |target latitude|, which ``align_plane`` ensures.
- **Longitude** comes from *which lap* the burn happens on. Each whole orbit the
  body rotates under the track, so the impact's longitude shifts west by a fixed
  step per lap **without moving the burn's orbital position** (latitude stays
  put). The refinement picks the lap that lines longitude up, then a small
  sub-lap slide (``-lon_error / (omega_orbit - omega_body)``) cancels the
  leftover; near the latitude extreme that slide barely moves the latitude.

Earlier versions slid the burn UT continuously to fix longitude only, which
dragged the impact along the ground track to the wrong latitude (it landed near
the equator). Splitting longitude into whole laps + a small slide keeps the
latitude locked.

The target periapsis stays fixed, but the delta-v does **not**: a fixed dv at a
different burn radius yields a different periapsis (it can even rise above the
surface, leaving no impact). The action re-sizes dv via vis-viva for the burn's
actual radius (the post-burn apoapsis) so periapsis stays on target.

Atmospheric drag is not modelled; the predictor is ballistic. Drag pulls
the real impact short of the vacuum prediction. ``drag_bias_km`` shifts
the prediction target by that amount along the down-track direction so the
real impact lands on the user's target. Suggested starting values for
unpowered stock capsules (rough rule of thumb -- tune per craft after
one or two test flights):

- Kerbin (thick atmosphere): 40-80 km
- Duna (thin atmosphere): 10-25 km
- Eve (extremely thick): 80-150 km
- Laythe (Kerbin-like): 40-80 km
- Vacuum bodies (Mun, Minmus, Ike, etc.): 0
"""

from __future__ import annotations

import math
from typing import Any, ClassVar

from ksp_mission_control.control.actions.base import (
    Action,
    ActionLogger,
    ActionParam,
    ActionResult,
    ActionStatus,
    Maneuver,
    ManeuverNode,
    ParamType,
    State,
    VesselCommands,
)
from ksp_mission_control.control.actions.helpers.controls import release_controls
from ksp_mission_control.control.actions.helpers.maneuver_node import (
    execute_node,
    fail_if_node_has_no_thrust,
    find_maneuver_node_by_ut,
)
from ksp_mission_control.control.actions.helpers.staging import (
    STAGING_MODE_PARAM,
    StagingMode,
    parse_staging_mode,
)
from ksp_mission_control.control.actions.helpers.warp import (
    drop_warp_for_critical_section,
    restore_user_warp,
)

# Stop refining the node this many seconds before the burn would start.
# kRPC needs a moment to commit a node, and we want the burn to start on
# the converged plan, not on a half-applied refinement.
_REFINEMENT_DEADLINE_SECONDS: float = 5.0

# Minimum inclination (rad) for latitude targeting. Below this the orbit is
# effectively equatorial: AN/DN are undefined and the impact latitude cannot be
# steered by burn position, so the action falls back to a plain apoapsis burn.
_MIN_INCLINATION_FOR_TARGETING_RAD: float = 0.001

# Laps to schedule the initial burn ahead of the first latitude-correct pass.
# The longitude search shifts the burn by whole laps (at most ~half a rotation
# cycle, ~6 laps), so starting this many laps out keeps every correction in the
# future without a separate "burn in the past" failure.
_INITIAL_LAP_BUFFER: int = 7

# Defaults
_DEFAULT_TARGET_PERIAPSIS_ALTITUDE: float = -5_000.0  # below sea level guarantees a ballistic impact
_DEFAULT_DRAG_BIAS_KM: float = 0.0
_DEFAULT_TOLERANCE_DEG: float = 0.5
_DEFAULT_MAX_PLANNING_TICKS: int = 60

# Re-trim the burn dv when the planned post-burn periapsis sits more than this
# above the target. Catches the case where a longitude shift slid the burn off
# apoapsis and the apoapsis-sized dv left periapsis above the surface (no impact
# to target, so the predictor returns nothing and refinement would stall).
_PERIAPSIS_RETRIM_TOLERANCE_M: float = 500.0


def _deorbit_burn_dv(mu: float, r_burn: float, sma_preburn: float, r_target_periapsis: float) -> float:
    """Prograde dv (negative = retrograde) that drops periapsis to ``r_target_periapsis``.

    Vis-viva at the burn radius ``r_burn``: a retrograde burn makes the burn
    point the post-burn apoapsis and lowers the opposite apse to the target.
    The same sizing must be redone whenever the burn radius changes, because a
    fixed dv applied at a different radius yields a different periapsis.
    """
    new_sma = (r_burn + r_target_periapsis) / 2.0
    v_current = math.sqrt(mu * (2.0 / r_burn - 1.0 / sma_preburn))
    v_new = math.sqrt(mu * (2.0 / r_burn - 1.0 / new_sma))
    return v_new - v_current


def _travel_angle_burn_to_impact_deg(r_burn: float, r_periapsis: float, body_radius: float) -> float:
    """Degrees of true anomaly traveled from the burn point to the sea-level crossing.

    A retrograde burn makes the burn point the apoapsis of the post-burn
    ellipse (apoapsis radius ``r_burn``, periapsis radius ``r_periapsis``).
    The trajectory crosses sea level (radius ``body_radius``) at true anomaly
    ``nu0`` where ``cos(nu0) = (p / body_radius - 1) / e`` (orbit equation,
    ``p`` the semi-latus rectum), so the descent from apoapsis covers
    ``180 - nu0`` degrees. With periapsis exactly at sea level the crossing
    IS periapsis (the full 180); the deeper the periapsis, the earlier the
    crossing. Falls back to 180 for degenerate geometry (circular post-burn
    orbit or periapsis above sea level).
    """
    if r_burn <= r_periapsis or body_radius <= 0.0:
        return 180.0
    semi_major = (r_burn + r_periapsis) / 2.0
    eccentricity = (r_burn - r_periapsis) / (r_burn + r_periapsis)
    semi_latus_rectum = semi_major * (1.0 - eccentricity**2)
    cos_nu = (semi_latus_rectum / body_radius - 1.0) / eccentricity
    cos_nu = max(-1.0, min(1.0, cos_nu))
    return 180.0 - math.degrees(math.acos(cos_nu))


def _burn_ut_for_target_latitude(state: State, target_latitude_deg: float, target_periapsis_altitude: float) -> float | None:
    """UT of the next burn whose ballistic impact lands at ``target_latitude_deg``.

    A retrograde burn makes the burn point the post-burn apoapsis; the impact
    follows a fixed travel angle downtrack (``_travel_angle_burn_to_impact_deg``,
    roughly 150 deg for a low orbit deorbiting to -5 km). To land at the target
    latitude we must burn that angle ahead of a point at that latitude.

    Using the orbit's argument of latitude ``u`` (0 at the ascending node, +90°
    at the north extreme): ``latitude(u) = asin(sin(i) * sin(u))``. The impact is
    at ``u_impact`` where ``sin(u_impact) = sin(target) / sin(i)``; the burn is
    one travel angle before it. The vessel reaches ``u_burn`` at
    ``ascending_node_ut + (u_burn / 360) * period``.

    Returns ``None`` when the orbit is too equatorial to steer latitude, or when
    the ascending-node time or period are unavailable. The target latitude must
    be reachable (``|target| <= inclination``); the ratio is clamped so a small
    overshoot from align_plane still resolves to the nearest extreme.
    """
    inclination = state.orbit_inclination
    if inclination < _MIN_INCLINATION_FOR_TARGETING_RAD:
        return None
    an_ut = state.orbit_ascending_node_ut
    period = state.orbit_period
    if not math.isfinite(an_ut) or period <= 0.0:
        return None
    sin_u_impact = math.sin(math.radians(target_latitude_deg)) / math.sin(inclination)
    sin_u_impact = max(-1.0, min(1.0, sin_u_impact))
    u_impact_deg = math.degrees(math.asin(sin_u_impact))
    travel_deg = _travel_angle_burn_to_impact_deg(
        state.orbit_apoapsis + state.body_radius,
        target_periapsis_altitude + state.body_radius,
        state.body_radius,
    )
    u_burn_deg = (u_impact_deg - travel_deg) % 360.0
    return an_ut + (u_burn_deg / 360.0) * period


class DeorbitToTargetAction(Action):
    """Plan and execute a deorbit burn timed for a target lat/lon impact."""

    action_id: ClassVar[str] = "deorbit_to_target"
    label: ClassVar[str] = "Deorbit to Target"
    description: ClassVar[str] = "Retrograde burn timed so the impact lands at a target lat/lon"
    params: ClassVar[list[ActionParam]] = [
        ActionParam(
            param_id="target_latitude",
            label="Target Latitude",
            description="Desired landing latitude, in degrees. Must lie within +/- the orbit inclination.",
            required=True,
            param_type=ParamType.FLOAT,
            default=None,
            unit="deg",
        ),
        ActionParam(
            param_id="target_longitude",
            label="Target Longitude",
            description="Desired landing longitude, in degrees in (-180, 180].",
            required=True,
            param_type=ParamType.FLOAT,
            default=None,
            unit="deg",
        ),
        ActionParam(
            param_id="target_periapsis_altitude",
            label="Target Periapsis Altitude",
            description=(
                "Periapsis altitude (m above sea level) the deorbit burn pushes to. Default -5000 puts the "
                "vacuum periapsis below sea level so an impact prediction is always available. Use a less "
                "aggressive (higher) value such as 20_000 for a shallower atmospheric reentry; impact "
                "prediction will not be available in that case, so the action will not be able to refine."
            ),
            required=False,
            param_type=ParamType.FLOAT,
            default=_DEFAULT_TARGET_PERIAPSIS_ALTITUDE,
            unit="m",
        ),
        ActionParam(
            param_id="drag_bias_km",
            label="Drag Bias",
            description=(
                "Distance the real (drag-affected) impact is expected to land *short* of the vacuum "
                "prediction, in km along the orbital motion direction. Roughly: Kerbin stock capsule 40-80, "
                "Duna 10-25, Eve 80-150, vacuum bodies 0. Positive values shift the prediction target east "
                "(downtrack) so the dragged real impact lands at the user target."
            ),
            required=False,
            param_type=ParamType.FLOAT,
            default=_DEFAULT_DRAG_BIAS_KM,
            unit="km",
        ),
        ActionParam(
            param_id="tolerance_deg",
            label="Tolerance",
            description="Convergence threshold for the predicted lat/lon error, in degrees.",
            required=False,
            param_type=ParamType.FLOAT,
            default=_DEFAULT_TOLERANCE_DEG,
            unit="deg",
        ),
        ActionParam(
            param_id="max_planning_ticks",
            label="Max Planning Ticks",
            description=(
                "Maximum number of refinement ticks before the action fails. At a 0.5s poll rate, the default 60 gives 30s of iteration time."
            ),
            required=False,
            param_type=ParamType.INT,
            default=_DEFAULT_MAX_PLANNING_TICKS,
        ),
        STAGING_MODE_PARAM,
    ]

    def start(self, state: State, param_values: dict[str, Any]) -> None:
        self._target_latitude: float = float(param_values["target_latitude"])
        self._target_longitude: float = float(param_values["target_longitude"])
        self._target_periapsis_altitude: float = float(param_values["target_periapsis_altitude"])
        self._drag_bias_km: float = float(param_values["drag_bias_km"])
        self._tolerance_deg: float = float(param_values["tolerance_deg"])
        self._max_planning_ticks: int = int(param_values["max_planning_ticks"])
        self._staging_mode: StagingMode | None = parse_staging_mode(param_values["staging_mode"])

        if not -90.0 <= self._target_latitude <= 90.0:
            raise ValueError(f"target_latitude must be in [-90, 90], got {self._target_latitude}.")
        if not -180.0 <= self._target_longitude <= 180.0:
            raise ValueError(f"target_longitude must be in [-180, 180], got {self._target_longitude}.")
        if self._tolerance_deg <= 0.0:
            raise ValueError(f"tolerance_deg must be positive, got {self._tolerance_deg}.")
        if self._max_planning_ticks <= 0:
            raise ValueError(f"max_planning_ticks must be positive, got {self._max_planning_ticks}.")

        self._node_ut: float | None = None
        self._planning_ticks_used: int = 0
        self._converged: bool = False
        self._refinement_warp_resumed: bool = False
        self._fail_message: str | None = None

        # Reject infeasible plans up front (deferred to first tick).
        current_inclination_deg = math.degrees(state.orbit_inclination)
        # Orbit needs an inclination >= |target_latitude| to ever cross that latitude.
        if abs(self._target_latitude) > current_inclination_deg + self._tolerance_deg:
            self._fail_message = (
                f"Cannot land at latitude {self._target_latitude:+.2f}° from an orbit with inclination "
                f"{current_inclination_deg:.2f}°. Run align_plane first to raise inclination."
            )

    def tick(self, state: State, commands: VesselCommands, dt: float, log: ActionLogger) -> ActionResult:
        if self._fail_message is not None:
            return ActionResult(status=ActionStatus.FAILED, message=self._fail_message)

        node = find_maneuver_node_by_ut(state, self._node_ut)

        if node is None:
            # Pre-planning: force 1x so the initial node ends up at the
            # apoapsis the bridge reports right now, not one that the next
            # warp tick has already slid past.
            warp_result = drop_warp_for_critical_section(state, commands, "planning the deorbit node")
            if warp_result is not None:
                return warp_result
            return self._plan_initial_node(state, commands, log)

        # Decide whether there is still time to refine or we should commit
        # to the burn. burn_start_ut is the UT at which the burn window
        # opens; refining after we are within _REFINEMENT_DEADLINE_SECONDS
        # of it risks the bridge committing a stale plan to kRPC.
        burn_time_estimate = node.burn_time_estimate if math.isfinite(node.burn_time_estimate) else 0.0
        burn_start_ut = node.ut - burn_time_estimate / 2.0
        time_to_burn_start = burn_start_ut - state.universal_time

        if not self._converged and time_to_burn_start > _REFINEMENT_DEADLINE_SECONDS:
            # Refinement phase: must be at 1x. At higher warp each tick
            # covers tens to hundreds of seconds of game time, and the
            # iterative replanner cannot keep pace.
            warp_result = drop_warp_for_critical_section(state, commands, "deorbit refinement")
            if warp_result is not None:
                return warp_result
            return self._refine_node(state, commands, node, log)

        # Refinement done. Resume the user's intended warp once so the
        # cold coast to burn can fast-forward; execute_node will step it
        # back down again as the burn window approaches.
        if self._converged and not self._refinement_warp_resumed:
            restore_user_warp(state, commands)
            self._refinement_warp_resumed = True

        # Burn window is near or open. Execute.
        if execute_node(state, commands, node, self._staging_mode, dt, log):
            commands.remove_node_at_ut = node.ut
            commands.autopilot = False
            commands.throttle = 0.0
            if state.predicted_impact is not None:
                lat = state.predicted_impact.latitude
                lon = state.predicted_impact.longitude
                return ActionResult(
                    status=ActionStatus.SUCCEEDED,
                    message=f"Deorbit burn complete. Vacuum impact near ({lat:+.2f}, {lon:+.2f}).",
                )
            return ActionResult(status=ActionStatus.SUCCEEDED, message="Deorbit burn complete.")

        no_thrust = fail_if_node_has_no_thrust(state, commands, node)
        if no_thrust is not None:
            return no_thrust

        return ActionResult(
            status=ActionStatus.RUNNING,
            message=f"Burning to deorbit: dv_remaining={node.delta_v_remaining:.1f} m/s",
        )

    def stop(self, state: State, commands: VesselCommands, log: ActionLogger) -> None:
        release_controls(commands)
        if self._node_ut is not None:
            commands.remove_node_at_ut = self._node_ut

    # ---- Helpers ------------------------------------------------------

    def _plan_initial_node(self, state: State, commands: VesselCommands, log: ActionLogger) -> ActionResult:
        """First tick: place the burn for the target latitude and size dv via vis-viva.

        The burn point is chosen so the sea-level crossing lands on the
        target latitude, scheduled ``_INITIAL_LAP_BUFFER`` laps out so the
        longitude refinement can shift it by whole laps in either direction
        without ever landing in the past. The retrograde dv drops the
        periapsis to ``target_periapsis_altitude``.
        """
        if state.body_gm <= 0.0 or state.orbit_semi_major_axis <= 0.0:
            return ActionResult(
                status=ActionStatus.FAILED,
                message="Cannot deorbit: invalid orbit (no gravitational parameter or semi-major axis).",
            )
        if state.orbit_period <= 0.0:
            return ActionResult(
                status=ActionStatus.FAILED,
                message="Cannot deorbit: orbit period is non-positive (escape trajectory?).",
            )

        # Burn at the point whose antipode sits at the target latitude, so the
        # impact lands there. Schedule it several laps out: the longitude search
        # then shifts the burn by whole laps (which preserve the latitude) to
        # line the impact up east-west. Falls back to a plain apoapsis burn on an
        # equatorial orbit, where latitude cannot be steered.
        lat_burn_ut = _burn_ut_for_target_latitude(state, self._target_latitude, self._target_periapsis_altitude)
        if lat_burn_ut is not None:
            burn_ut = lat_burn_ut + _INITIAL_LAP_BUFFER * state.orbit_period
        else:
            burn_ut = state.universal_time + state.orbit_apoapsis_time_to + state.orbit_period
        r_burn = state.orbit_apoapsis + state.body_radius
        r_target_peri = self._target_periapsis_altitude + state.body_radius
        if r_burn <= 0.0 or r_target_peri <= 0.0:
            return ActionResult(
                status=ActionStatus.FAILED,
                message=(f"Cannot deorbit: non-positive radius (burn={r_burn:.0f}, target_peri={r_target_peri:.0f})."),
            )
        if r_target_peri >= r_burn:
            return ActionResult(
                status=ActionStatus.FAILED,
                message=(
                    f"target_periapsis_altitude ({self._target_periapsis_altitude:,.0f}m) must be below current "
                    f"apoapsis ({state.orbit_apoapsis:,.0f}m). Use change_apse to raise periapsis instead."
                ),
            )

        delta_v = _deorbit_burn_dv(state.body_gm, r_burn, state.orbit_semi_major_axis, r_target_peri)

        commands.create_node = Maneuver(ut=burn_ut, prograde=delta_v)
        self._node_ut = burn_ut

        log.info(
            f"Planned deorbit for target ({self._target_latitude:+.2f}, {self._target_longitude:+.2f}): "
            f"dv={delta_v:+.1f} m/s, peri -> {self._target_periapsis_altitude:,.0f}m, ut={burn_ut:.1f}"
        )
        return ActionResult(
            status=ActionStatus.RUNNING,
            message=(f"Planning deorbit to ({self._target_latitude:+.2f}, {self._target_longitude:+.2f}) (dv={delta_v:+.1f} m/s)"),
        )

    def _refine_node(
        self,
        state: State,
        commands: VesselCommands,
        node: ManeuverNode,
        log: ActionLogger,
    ) -> ActionResult:
        """Adjust burn UT toward the impact-longitude target, one step per tick."""
        self._planning_ticks_used += 1
        if self._planning_ticks_used > self._max_planning_ticks:
            self._fail_message = (
                f"Deorbit refinement did not converge in {self._max_planning_ticks} ticks. Tune drag_bias_km or target_periapsis_altitude and retry."
            )
            return ActionResult(status=ActionStatus.FAILED, message=self._fail_message)

        impact = state.predicted_impact
        # Prediction must come from the post-node orbit; otherwise we are
        # reading stale data from before the bridge picked up our node.
        if impact is None or impact.source != "next_node_orbit":
            # A common cause of "no prediction" is that a prior longitude shift
            # slid the burn off apoapsis, where the apoapsis-sized dv no longer
            # lowers periapsis below the surface, so there is no ground impact.
            # Re-size dv for the burn's actual radius (the burn point is the
            # post-burn apoapsis) at the same UT, restoring the target periapsis
            # so a prediction reappears next tick. Otherwise just wait.
            r_target_peri = self._target_periapsis_altitude + state.body_radius
            r_burn = node.post_burn_orbit_apoapsis + state.body_radius
            if (
                state.body_gm > 0.0
                and state.orbit_semi_major_axis > 0.0
                and r_burn > r_target_peri
                and node.post_burn_orbit_periapsis > self._target_periapsis_altitude + _PERIAPSIS_RETRIM_TOLERANCE_M
            ):
                dv = _deorbit_burn_dv(state.body_gm, r_burn, state.orbit_semi_major_axis, r_target_peri)
                commands.remove_node_at_ut = node.ut
                commands.create_node = Maneuver(ut=node.ut, prograde=dv)
                self._node_ut = node.ut
                log.debug(
                    f"Re-trimming deorbit dv: periapsis {node.post_burn_orbit_periapsis:,.0f}m -> "
                    f"{self._target_periapsis_altitude:,.0f}m at burn radius {r_burn:,.0f}m, dv={dv:+.1f} m/s."
                )
                return ActionResult(
                    status=ActionStatus.RUNNING,
                    message=(f"Re-trimming deorbit burn to restore periapsis (was {node.post_burn_orbit_periapsis:,.0f}m)."),
                )
            return ActionResult(
                status=ActionStatus.RUNNING,
                message=f"Waiting for post-burn impact prediction ({self._planning_ticks_used} ticks).",
            )

        drag_bias_lon = self._drag_bias_longitude_offset(state.body_radius)
        target_longitude_with_bias = self._wrap_longitude(self._target_longitude + drag_bias_lon)
        lat_error = impact.latitude - self._target_latitude
        lon_error = self._wrap_longitude(impact.longitude - target_longitude_with_bias)

        if abs(lat_error) <= self._tolerance_deg and abs(lon_error) <= self._tolerance_deg:
            self._converged = True
            log.info(
                f"Deorbit converged: predicted impact ({impact.latitude:+.3f}, {impact.longitude:+.3f}), "
                f"errors ({lat_error:+.3f}, {lon_error:+.3f}) within {self._tolerance_deg:.2f}°."
            )
            return ActionResult(
                status=ActionStatus.RUNNING,
                message=(f"Deorbit converged. Vacuum impact ({impact.latitude:+.2f}, {impact.longitude:+.2f}); awaiting burn window."),
            )

        # Body rotation rate (deg/s). Falls back to a failure if unavailable.
        if state.body_rotational_period <= 0.0 or state.orbit_period <= 0.0:
            self._fail_message = (
                "Cannot refine deorbit: orbit_period or body_rotational_period is non-positive. Ensure the vessel is in a stable orbit."
            )
            return ActionResult(status=ActionStatus.FAILED, message=self._fail_message)

        omega_orbit_deg = 360.0 / state.orbit_period
        omega_body_deg = 360.0 / state.body_rotational_period
        relative_rate = omega_orbit_deg - omega_body_deg
        if relative_rate <= 0.0:
            self._fail_message = (
                "Cannot refine deorbit: body rotates faster than orbital angular rate (very high orbit). "
                "Lower the orbit before attempting a targeted deorbit."
            )
            return ActionResult(status=ActionStatus.FAILED, message=self._fail_message)

        # Correct longitude in two parts so the latitude-correct burn position is
        # preserved. Whole laps shift the impact west by one body-rotation step
        # each WITHOUT moving the burn's orbital position (latitude unchanged); a
        # small sub-lap slide cancels the leftover (<= half a lap step), which
        # nudges the burn only a few degrees -> negligible latitude change near
        # the orbit's latitude extreme. Sliding the whole correction (the old
        # behaviour) instead dragged the burn far off the latitude-correct point.
        lap_lon_step = omega_body_deg * state.orbit_period  # deg the impact shifts west per +1 lap
        n_laps = round(lon_error / lap_lon_step)
        residual_lon = lon_error - n_laps * lap_lon_step
        delta_burn_ut = n_laps * state.orbit_period - residual_lon / relative_rate

        new_burn_ut = node.ut + delta_burn_ut
        # Don't ever schedule the burn in the past.
        if new_burn_ut <= state.universal_time + _REFINEMENT_DEADLINE_SECONDS:
            self._fail_message = (
                "Deorbit refinement pushed burn UT into the past. The current orbital geometry does not "
                "allow targeting that longitude on the next pass. Wait one orbit and retry."
            )
            return ActionResult(status=ActionStatus.FAILED, message=self._fail_message)

        commands.remove_node_at_ut = node.ut
        commands.create_node = Maneuver(ut=new_burn_ut, prograde=node.prograde)
        self._node_ut = new_burn_ut

        log.debug(
            f"Refining deorbit (tick {self._planning_ticks_used}): impact ({impact.latitude:+.3f}, "
            f"{impact.longitude:+.3f}), errors ({lat_error:+.3f}, {lon_error:+.3f}), "
            f"shift {n_laps:+d} laps + {-residual_lon / relative_rate:+.1f}s slide."
        )
        return ActionResult(
            status=ActionStatus.RUNNING,
            message=(f"Refining: impact ({impact.latitude:+.2f}, {impact.longitude:+.2f}), errors ({lat_error:+.2f}, {lon_error:+.2f})."),
        )

    def _drag_bias_longitude_offset(self, body_radius: float) -> float:
        """Convert drag_bias_km to a longitude offset in degrees at the target latitude.

        One degree of longitude at latitude L spans
        ``(pi/180) * body_radius * cos(L)`` meters. The drag shifts the
        impact short (westward for prograde orbits), so the prediction
        target is offset east by the same amount, which is what we apply.
        """
        if body_radius <= 0.0:
            return 0.0
        meters_per_deg_lon = (math.pi / 180.0) * body_radius * max(0.0, math.cos(math.radians(self._target_latitude)))
        if meters_per_deg_lon <= 0.0:
            return 0.0
        return (self._drag_bias_km * 1000.0) / meters_per_deg_lon

    @staticmethod
    def _wrap_longitude(longitude_deg: float) -> float:
        """Wrap a longitude into (-180, 180]."""
        wrapped = ((longitude_deg + 180.0) % 360.0) - 180.0
        # Use a half-open convention: -180 wraps to 180 for symmetry with kRPC.
        if wrapped == -180.0:
            return 180.0
        return wrapped
