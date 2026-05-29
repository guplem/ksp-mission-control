"""DeorbitToTargetAction - retrograde burn timed for a target lat/lon impact.

The action runs a closed loop between two signals:

- The kRPC predictor in the bridge fills ``State.predicted_impact`` with the
  ballistic lat/lon where the post-node trajectory would crash.
- Each tick before the burn window opens, the action compares the
  prediction against the desired target and nudges the burn UT to drive
  the longitude error toward zero. The delta-v (and therefore the post-
  burn periapsis) stays fixed at the value computed in ``start()``.

Why iterate on burn UT only:

Two free parameters (UT and delta-v) would theoretically let us hit any
``(lat, lon)`` exactly. In practice the relationship between delta-v and
impact latitude is steep and noisy (the trajectory's argument-of-impact
moves a lot when periapsis altitude changes), while the relationship
between burn UT and longitude is linear and well-modelled by

    impact_longitude_shift_per_delay = (omega_orbit - omega_body) * Δt

where the two angular velocities are the orbital and body rotation
rates. The action exploits that clean 1D control law to fix longitude;
latitude is governed by the orbit's inclination (set up by ``align_plane``
beforehand) and by the descent profile (set up by
``target_periapsis_altitude``).

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

# Hard cap on a single burn-UT correction. A control law that proposed
# more than half an orbit of shift is almost certainly diverging; clamping
# keeps the iteration stable and lets the user notice via the log.
_MAX_BURN_UT_ADJUSTMENT_FRACTION: float = 0.5

# Defaults
_DEFAULT_TARGET_PERIAPSIS_ALTITUDE: float = -5_000.0  # below sea level guarantees a ballistic impact
_DEFAULT_DRAG_BIAS_KM: float = 0.0
_DEFAULT_TOLERANCE_DEG: float = 0.5
_DEFAULT_MAX_PLANNING_TICKS: int = 60


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
        """First tick: pick burn UT one full orbit past the next apoapsis and compute retrograde dv via vis-viva.

        Scheduling the burn one full orbit out (rather than at the next
        apoapsis directly) gives the refinement loop a full orbit of
        game time to converge, which the action needs because each
        iteration of the loop only adjusts burn UT by a bounded amount
        (``_MAX_BURN_UT_ADJUSTMENT_FRACTION * orbit_period``) and the
        ground-track range we may need to cover spans nearly a full
        period of relative rotation. The lost efficiency from waiting an
        extra orbit is negligible against the targeting accuracy gain.
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

        mu = state.body_gm
        new_sma = (r_burn + r_target_peri) / 2.0
        v_current = math.sqrt(mu * (2.0 / r_burn - 1.0 / state.orbit_semi_major_axis))
        v_new = math.sqrt(mu * (2.0 / r_burn - 1.0 / new_sma))
        delta_v = v_new - v_current  # negative: retrograde

        commands.create_node = Maneuver(ut=burn_ut, prograde=delta_v)
        self._node_ut = burn_ut

        log.info(
            f"Planned deorbit at apoapsis: target ({self._target_latitude:+.2f}, {self._target_longitude:+.2f}), "
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

        # Delaying the burn by Δt shifts the impact east by relative_rate * Δt.
        # To cancel a +lon_error (impact too east), burn earlier (Δt < 0).
        delta_burn_ut = -lon_error / relative_rate
        max_adjustment = state.orbit_period * _MAX_BURN_UT_ADJUSTMENT_FRACTION
        delta_burn_ut = max(-max_adjustment, min(max_adjustment, delta_burn_ut))

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
            f"{impact.longitude:+.3f}), errors ({lat_error:+.3f}, {lon_error:+.3f}), burn_ut shift "
            f"{delta_burn_ut:+.2f}s."
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
