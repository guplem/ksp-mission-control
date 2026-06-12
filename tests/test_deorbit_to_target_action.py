"""Tests for DeorbitToTargetAction."""

from __future__ import annotations

import math

import pytest

from ksp_mission_control.control.actions.base import (
    ActionLogger,
    ActionStatus,
    ImpactPrediction,
    ManeuverNode,
    State,
    VesselCommands,
)
from ksp_mission_control.control.actions.deorbit_to_target.action import (
    _INITIAL_LAP_BUFFER,
    DeorbitToTargetAction,
    _burn_ut_for_target_latitude,
    _travel_angle_burn_to_impact_deg,
)

_KERBIN_RADIUS = 600_000.0
_KERBIN_GM = 3.5316e12
_KERBIN_ROTATIONAL_PERIOD = 21_549.425


def _params(
    *,
    target_latitude: float = -15.0,
    target_longitude: float = -70.0,
    target_periapsis_altitude: float = -5_000.0,
    drag_bias_km: float = 0.0,
    tolerance_deg: float = 0.5,
    max_planning_ticks: int = 60,
    staging_mode: str | None = None,
) -> dict[str, object]:
    return {
        "target_latitude": target_latitude,
        "target_longitude": target_longitude,
        "target_periapsis_altitude": target_periapsis_altitude,
        "drag_bias_km": drag_bias_km,
        "tolerance_deg": tolerance_deg,
        "max_planning_ticks": max_planning_ticks,
        "staging_mode": staging_mode,
    }


def _orbit_state(
    *,
    inclination_deg: float = 20.0,
    universal_time: float = 1_000.0,
    apoapsis_alt: float = 100_000.0,
    periapsis_alt: float = 95_000.0,
    apoapsis_time_to: float = 600.0,
    period: float = 1_800.0,
    predicted_impact: ImpactPrediction | None = None,
) -> State:
    r_apo = apoapsis_alt + _KERBIN_RADIUS
    r_peri = periapsis_alt + _KERBIN_RADIUS
    return State(
        orbit_inclination=math.radians(inclination_deg),
        orbit_apoapsis=apoapsis_alt,
        orbit_periapsis=periapsis_alt,
        orbit_apoapsis_time_to=apoapsis_time_to,
        orbit_periapsis_time_to=apoapsis_time_to + period / 2.0,
        orbit_period=period,
        orbit_semi_major_axis=(r_apo + r_peri) / 2.0,
        universal_time=universal_time,
        body_radius=_KERBIN_RADIUS,
        body_gm=_KERBIN_GM,
        body_rotational_period=_KERBIN_ROTATIONAL_PERIOD,
        predicted_impact=predicted_impact,
    )


def _node_for(
    action: DeorbitToTargetAction,
    *,
    delta_v_remaining: float = 100.0,
    burn_time_estimate: float = 5.0,
) -> ManeuverNode:
    assert action._node_ut is not None
    return ManeuverNode(
        index=0,
        ut=action._node_ut,
        time_to=10.0,
        delta_v=100.0,
        delta_v_remaining=delta_v_remaining,
        prograde=-100.0,
        normal=0.0,
        radial=0.0,
        burn_vector=(0.0, -100.0, 0.0),
        burn_vector_remaining=(0.0, -delta_v_remaining, 0.0),
        burn_time_estimate=burn_time_estimate,
        post_burn_orbit_apoapsis=100_000.0,
        post_burn_orbit_periapsis=-5_000.0,
        post_burn_orbit_eccentricity=0.2,
        post_burn_orbit_inclination=math.radians(20.0),
        post_burn_orbit_period=1_500.0,
        post_burn_orbit_semi_major_axis=_KERBIN_RADIUS + 47_500.0,
    )


class TestDeorbitMetadata:
    def test_action_id(self) -> None:
        assert DeorbitToTargetAction.action_id == "deorbit_to_target"

    def test_required_params(self) -> None:
        required = {p.param_id for p in DeorbitToTargetAction.params if p.required}
        assert required == {"target_latitude", "target_longitude"}


class TestDeorbitStartValidation:
    def test_rejects_out_of_range_latitude(self) -> None:
        action = DeorbitToTargetAction()
        with pytest.raises(ValueError, match="target_latitude must be in"):
            action.start(_orbit_state(), _params(target_latitude=120.0))

    def test_rejects_out_of_range_longitude(self) -> None:
        action = DeorbitToTargetAction()
        with pytest.raises(ValueError, match="target_longitude must be in"):
            action.start(_orbit_state(), _params(target_longitude=200.0))

    def test_rejects_zero_tolerance(self) -> None:
        action = DeorbitToTargetAction()
        with pytest.raises(ValueError, match="tolerance_deg must be positive"):
            action.start(_orbit_state(), _params(tolerance_deg=0.0))

    def test_rejects_zero_max_planning_ticks(self) -> None:
        action = DeorbitToTargetAction()
        with pytest.raises(ValueError, match="max_planning_ticks must be positive"):
            action.start(_orbit_state(), _params(max_planning_ticks=0))

    def test_fails_when_target_latitude_exceeds_inclination(self) -> None:
        # inclination=5°, target_latitude=-30°: orbit cannot reach -30 lat.
        action = DeorbitToTargetAction()
        action.start(_orbit_state(inclination_deg=5.0), _params(target_latitude=-30.0))
        result = action.tick(_orbit_state(inclination_deg=5.0), VesselCommands(), dt=0.5, log=ActionLogger())
        assert result.status == ActionStatus.FAILED
        assert "align_plane" in result.message


class TestDeorbitInitialPlan:
    """First tick (no node yet) computes burn UT at apoapsis and retrograde dv."""

    def test_initial_node_at_apoapsis_one_orbit_out(self) -> None:
        action = DeorbitToTargetAction()
        state = _orbit_state(universal_time=1_000.0, apoapsis_time_to=400.0, period=1_800.0)
        action.start(state, _params(target_latitude=-15.0, target_longitude=-70.0))

        commands = VesselCommands()
        result = action.tick(state, commands, dt=0.5, log=ActionLogger())
        assert result.status == ActionStatus.RUNNING
        assert commands.create_node is not None
        # Burn UT = current_ut + apoapsis_time_to + orbit_period, scheduling the
        # burn one full orbit out so refinement has the full period to converge.
        assert commands.create_node.ut == pytest.approx(1_000.0 + 400.0 + 1_800.0)
        # Retrograde: prograde dv is negative.
        assert commands.create_node.prograde < 0.0

    def test_initial_dv_matches_vis_viva(self) -> None:
        action = DeorbitToTargetAction()
        state = _orbit_state(apoapsis_alt=100_000.0, periapsis_alt=100_000.0)  # circular
        action.start(state, _params(target_periapsis_altitude=-5_000.0))

        commands = VesselCommands()
        action.tick(state, commands, dt=0.5, log=ActionLogger())
        assert commands.create_node is not None

        r_burn = 100_000.0 + _KERBIN_RADIUS
        r_peri_target = -5_000.0 + _KERBIN_RADIUS
        new_sma = (r_burn + r_peri_target) / 2.0
        # Current circular orbit: sma == r_burn.
        v_current = math.sqrt(_KERBIN_GM / r_burn)
        v_new = math.sqrt(_KERBIN_GM * (2.0 / r_burn - 1.0 / new_sma))
        expected_dv = v_new - v_current
        assert commands.create_node.prograde == pytest.approx(expected_dv, rel=1e-4)

    def test_fails_when_target_periapsis_above_apoapsis(self) -> None:
        action = DeorbitToTargetAction()
        state = _orbit_state(apoapsis_alt=50_000.0)
        action.start(state, _params(target_periapsis_altitude=100_000.0))
        result = action.tick(state, VesselCommands(), dt=0.5, log=ActionLogger())
        assert result.status == ActionStatus.FAILED
        assert "change_apse" in result.message


class TestDeorbitRefinement:
    """Once the bridge fills predicted_impact, the action nudges burn UT toward zero longitude error."""

    def _node_then_refine(
        self,
        action: DeorbitToTargetAction,
        seed_state: State,
        predicted_impact: ImpactPrediction,
    ) -> tuple[VesselCommands, ManeuverNode]:
        """Plan an initial node, then run one refinement tick with the given prediction."""
        action.tick(seed_state, VesselCommands(), dt=0.5, log=ActionLogger())  # initial plan
        node = _node_for(action)
        refine_state = _orbit_state(
            inclination_deg=20.0,
            universal_time=seed_state.universal_time + 1.0,  # one tick later
            apoapsis_time_to=599.0,  # node still in the future
            period=seed_state.orbit_period,
            predicted_impact=predicted_impact,
        )
        # Bridge would write nodes tuple too.
        refine_state = State(
            **{**refine_state.__dict__, "nodes": (node,), "predicted_impact": predicted_impact},
        )
        commands = VesselCommands()
        action.tick(refine_state, commands, dt=0.5, log=ActionLogger())
        return commands, node

    def test_shifts_burn_ut_earlier_when_predicted_east_of_target(self) -> None:
        action = DeorbitToTargetAction()
        seed = _orbit_state(universal_time=1_000.0, apoapsis_time_to=600.0, period=1_800.0)
        action.start(seed, _params(target_latitude=-15.0, target_longitude=-70.0, tolerance_deg=0.1))

        # Predicted impact 5° east of target -> action should burn earlier.
        impact = ImpactPrediction(
            latitude=-15.0,
            longitude=-65.0,  # 5° east of target -70
            altitude_terrain=200.0,
            time_to_ballistic_impact=1_500.0,
            source="next_node_orbit",
        )
        commands, original_node = self._node_then_refine(action, seed, impact)
        assert commands.create_node is not None
        assert commands.remove_node_at_ut == pytest.approx(original_node.ut)
        # New burn UT must be earlier (lower) than the original to drift impact west.
        assert commands.create_node.ut < original_node.ut

    def test_shifts_burn_ut_later_when_predicted_west_of_target(self) -> None:
        action = DeorbitToTargetAction()
        seed = _orbit_state(universal_time=1_000.0, apoapsis_time_to=600.0, period=1_800.0)
        action.start(seed, _params(target_latitude=-15.0, target_longitude=-70.0, tolerance_deg=0.1))

        impact = ImpactPrediction(
            latitude=-15.0,
            longitude=-75.0,  # 5° west of target -70
            altitude_terrain=200.0,
            time_to_ballistic_impact=1_500.0,
            source="next_node_orbit",
        )
        commands, original_node = self._node_then_refine(action, seed, impact)
        assert commands.create_node is not None
        assert commands.create_node.ut > original_node.ut

    def test_large_longitude_error_corrected_by_whole_laps(self) -> None:
        # A big longitude error must be corrected mostly by WHOLE laps (which keep
        # the burn at the latitude-correct orbital position), not a large
        # within-orbit slide that would drag the impact to the wrong latitude.
        action = DeorbitToTargetAction()
        seed = _orbit_state(universal_time=1_000.0, apoapsis_time_to=600.0, period=1_800.0)
        action.start(seed, _params(target_latitude=-15.0, target_longitude=-70.0, tolerance_deg=0.5))

        impact = ImpactPrediction(
            latitude=-15.0,  # latitude already on target
            longitude=60.0,  # ~130 deg east of target -> large longitude error
            altitude_terrain=200.0,
            time_to_ballistic_impact=1_500.0,
            source="next_node_orbit",
        )
        commands, original_node = self._node_then_refine(action, seed, impact)
        assert commands.create_node is not None

        shift = commands.create_node.ut - original_node.ut
        period = seed.orbit_period
        laps = round(shift / period)
        assert laps >= 1  # the bulk of the correction is whole laps
        # The leftover within-orbit slide (which moves latitude) must be small.
        slide = shift - laps * period
        assert abs(slide) < period * 0.25

    def test_converges_when_errors_within_tolerance(self) -> None:
        action = DeorbitToTargetAction()
        seed = _orbit_state(universal_time=1_000.0, apoapsis_time_to=600.0, period=1_800.0)
        action.start(seed, _params(target_latitude=-15.0, target_longitude=-70.0, tolerance_deg=0.5))

        # Both errors within tolerance: should mark converged and not replace node.
        impact = ImpactPrediction(
            latitude=-15.1,
            longitude=-70.1,
            altitude_terrain=200.0,
            time_to_ballistic_impact=1_500.0,
            source="next_node_orbit",
        )
        commands, original_node = self._node_then_refine(action, seed, impact)
        assert commands.create_node is None
        assert commands.remove_node_at_ut is None
        assert action._converged is True

    def test_waits_when_prediction_is_for_current_orbit(self) -> None:
        # source != "next_node_orbit" means the bridge has not yet picked up
        # our node; the action should wait one tick rather than refine.
        action = DeorbitToTargetAction()
        seed = _orbit_state(universal_time=1_000.0, apoapsis_time_to=600.0, period=1_800.0)
        action.start(seed, _params(target_latitude=-15.0, target_longitude=-70.0, tolerance_deg=0.5))
        impact = ImpactPrediction(
            latitude=-15.0,
            longitude=-70.0,
            altitude_terrain=0.0,
            time_to_ballistic_impact=1_500.0,
            source="current_orbit",
        )
        commands, _original = self._node_then_refine(action, seed, impact)
        assert commands.create_node is None
        assert action._converged is False

    def test_retrims_dv_when_periapsis_drifts_above_surface(self) -> None:
        # Regression (log_20260605_215353): the longitude refinement slides the
        # burn off apoapsis, where the apoapsis-sized dv under-lowers periapsis.
        # The post-burn periapsis rose above the surface (+6 km), so there was no
        # ground impact, the predictor returned None, and the action waited until
        # it failed at the tick cap. It must re-size dv for the burn's actual
        # radius so periapsis returns to target and a prediction reappears.
        action = DeorbitToTargetAction()
        seed = _orbit_state(
            universal_time=1_000.0,
            apoapsis_alt=200_000.0,
            periapsis_alt=75_000.0,
            apoapsis_time_to=600.0,
            period=1_800.0,
        )
        action.start(seed, _params(target_periapsis_altitude=-5_000.0))
        action.tick(seed, VesselCommands(), dt=0.5, log=ActionLogger())  # plan initial node
        assert action._node_ut is not None

        # The burn has been slid to near the current periapsis (r = 675 km), so
        # the old apoapsis-sized dv leaves post-burn periapsis above the surface
        # and there is no impact prediction.
        node = ManeuverNode(
            index=0,
            ut=action._node_ut,
            time_to=2_400.0,
            delta_v=72.0,
            delta_v_remaining=72.0,
            prograde=-72.0,
            normal=0.0,
            radial=0.0,
            burn_vector=(0.0, -72.0, 0.0),
            burn_vector_remaining=(0.0, -72.0, 0.0),
            burn_time_estimate=2.0,
            post_burn_orbit_apoapsis=75_000.0,  # burn point ~ current periapsis radius
            post_burn_orbit_periapsis=6_000.0,  # above sea level -> no impact
            post_burn_orbit_eccentricity=0.06,
            post_burn_orbit_inclination=math.radians(20.0),
            post_burn_orbit_period=1_700.0,
            post_burn_orbit_semi_major_axis=_KERBIN_RADIUS + 40_000.0,
        )
        refine_state = State(
            **{
                **_orbit_state(
                    universal_time=1_001.0,
                    apoapsis_alt=200_000.0,
                    periapsis_alt=75_000.0,
                    apoapsis_time_to=599.0,
                    period=1_800.0,
                ).__dict__,
                "nodes": (node,),
                "predicted_impact": None,
            }
        )
        commands = VesselCommands()
        result = action.tick(refine_state, commands, dt=0.5, log=ActionLogger())

        assert result.status == ActionStatus.RUNNING
        # Re-trim at the SAME burn UT (not a longitude shift).
        assert commands.create_node is not None
        assert commands.create_node.ut == pytest.approx(node.ut)
        assert commands.remove_node_at_ut == pytest.approx(node.ut)
        # New dv matches vis-viva for the burn radius (post-burn apoapsis), deeper
        # (more retrograde) than the old apoapsis-sized dv.
        r_burn = node.post_burn_orbit_apoapsis + _KERBIN_RADIUS
        r_target = -5_000.0 + _KERBIN_RADIUS
        sma_pre = refine_state.orbit_semi_major_axis
        new_sma = (r_burn + r_target) / 2.0
        v_current = math.sqrt(_KERBIN_GM * (2.0 / r_burn - 1.0 / sma_pre))
        v_new = math.sqrt(_KERBIN_GM * (2.0 / r_burn - 1.0 / new_sma))
        expected_dv = v_new - v_current
        assert commands.create_node.prograde == pytest.approx(expected_dv, rel=1e-4)
        assert commands.create_node.prograde < node.prograde

    def test_fails_after_max_planning_ticks_without_convergence(self) -> None:
        action = DeorbitToTargetAction()
        seed = _orbit_state(universal_time=1_000.0, apoapsis_time_to=600.0, period=1_800.0)
        action.start(seed, _params(target_latitude=-15.0, target_longitude=-70.0, tolerance_deg=0.0001, max_planning_ticks=2))
        action.tick(seed, VesselCommands(), dt=0.5, log=ActionLogger())  # plans node

        # Build a never-converging state: prediction sits at constant 5deg lon error.
        node = _node_for(action)
        for _ in range(3):
            impact = ImpactPrediction(
                latitude=-15.0,
                longitude=-65.0,  # always 5deg east
                altitude_terrain=0.0,
                time_to_ballistic_impact=1_500.0,
                source="next_node_orbit",
            )
            refine_state = State(
                orbit_inclination=math.radians(20.0),
                orbit_apoapsis=100_000.0,
                orbit_periapsis=95_000.0,
                orbit_apoapsis_time_to=600.0,
                orbit_period=1_800.0,
                orbit_semi_major_axis=_KERBIN_RADIUS + 97_500.0,
                universal_time=seed.universal_time + 1.0,
                body_radius=_KERBIN_RADIUS,
                body_gm=_KERBIN_GM,
                body_rotational_period=_KERBIN_ROTATIONAL_PERIOD,
                predicted_impact=impact,
                nodes=(node,),
            )
            result = action.tick(refine_state, VesselCommands(), dt=0.5, log=ActionLogger())
            node = _node_for(action)  # refresh against any new UT
        assert result.status == ActionStatus.FAILED
        assert "did not converge" in result.message

    def test_drag_bias_shifts_target_eastward(self) -> None:
        # With drag_bias_km > 0, vacuum prediction target is east of the
        # user-supplied target. So a prediction sitting AT the user target
        # is now WEST of the (biased) target and the action should burn later.
        action = DeorbitToTargetAction()
        seed = _orbit_state(universal_time=1_000.0, apoapsis_time_to=600.0, period=1_800.0)
        action.start(seed, _params(target_latitude=-15.0, target_longitude=-70.0, drag_bias_km=50.0, tolerance_deg=0.1))

        impact = ImpactPrediction(
            latitude=-15.0,
            longitude=-70.0,  # at the raw user target = west of the drag-biased target
            altitude_terrain=200.0,
            time_to_ballistic_impact=1_500.0,
            source="next_node_orbit",
        )
        commands, original_node = self._node_then_refine(action, seed, impact)
        assert commands.create_node is not None
        # Burn shifts later -> impact moves east (toward the drag-bias target).
        assert commands.create_node.ut > original_node.ut


class TestDeorbitExecutePhase:
    """When the burn window is near, the action stops refining and drives execute_node."""

    def test_executes_when_within_refinement_deadline(self) -> None:
        action = DeorbitToTargetAction()
        seed = _orbit_state(universal_time=1_000.0, apoapsis_time_to=600.0)
        action.start(seed, _params())
        action.tick(seed, VesselCommands(), dt=0.5, log=ActionLogger())  # plan node at 1600

        node = _node_for(action, delta_v_remaining=80.0, burn_time_estimate=10.0)
        # State at burn window: ut = node.ut, so burn_start = node.ut - 5 = ut - 5.
        # time_to_burn_start = -5, well past the deadline.
        burn_state = State(
            universal_time=node.ut + 0.0,  # at the node ut
            thrust_available=50_000.0,
            engine_impulse_specific_vacuum=300.0,
            mass=5_000.0,
            orbit_inclination=math.radians(20.0),
            orbit_semi_major_axis=_KERBIN_RADIUS + 97_500.0,
            body_radius=_KERBIN_RADIUS,
            body_gm=_KERBIN_GM,
            body_rotational_period=_KERBIN_ROTATIONAL_PERIOD,
            nodes=(node,),
        )
        commands = VesselCommands()
        result = action.tick(burn_state, commands, dt=0.5, log=ActionLogger())
        assert result.status == ActionStatus.RUNNING
        # execute_node drives the burn.
        assert commands.throttle == 1.0
        assert commands.autopilot is True

    def test_succeeds_when_burn_completes(self) -> None:
        action = DeorbitToTargetAction()
        seed = _orbit_state(universal_time=1_000.0, apoapsis_time_to=600.0)
        action.start(seed, _params())
        action.tick(seed, VesselCommands(), dt=0.5, log=ActionLogger())

        node = _node_for(action, delta_v_remaining=0.0)
        done_state = State(
            universal_time=node.ut,
            thrust_available=50_000.0,
            mass=5_000.0,
            orbit_inclination=math.radians(20.0),
            orbit_semi_major_axis=_KERBIN_RADIUS + 50_000.0,
            body_radius=_KERBIN_RADIUS,
            body_gm=_KERBIN_GM,
            body_rotational_period=_KERBIN_ROTATIONAL_PERIOD,
            nodes=(node,),
        )
        commands = VesselCommands()
        result = action.tick(done_state, commands, dt=0.5, log=ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED
        assert commands.remove_node_at_ut == pytest.approx(action._node_ut)
        assert commands.throttle == 0.0
        assert commands.autopilot is False


class TestDeorbitStop:
    def test_stop_removes_node(self) -> None:
        action = DeorbitToTargetAction()
        state = _orbit_state()
        action.start(state, _params())
        action.tick(state, VesselCommands(), dt=0.5, log=ActionLogger())

        commands = VesselCommands()
        action.stop(state, commands, log=ActionLogger())
        assert commands.throttle == 0.0
        assert commands.autopilot is False
        assert commands.remove_node_at_ut == pytest.approx(action._node_ut)

    def test_stop_before_planning_is_safe(self) -> None:
        action = DeorbitToTargetAction()
        action.start(_orbit_state(), _params())
        commands = VesselCommands()
        action.stop(_orbit_state(), commands, log=ActionLogger())
        assert commands.remove_node_at_ut is None


class TestDeorbitWarpHandling:
    """The action drops warp during refinement and restores on completion (ADR 0012)."""

    def _state_with_warp(self, time_warp_rate: float) -> State:
        base = _orbit_state()
        return State(**{**base.__dict__, "time_warp_rate": time_warp_rate})

    def test_drops_warp_before_planning_initial_node(self) -> None:
        action = DeorbitToTargetAction()
        state = self._state_with_warp(100.0)
        action.start(state, _params(target_latitude=-15.0, target_longitude=-70.0))
        commands = VesselCommands()
        result = action.tick(state, commands, dt=0.5, log=ActionLogger())
        assert result.status == ActionStatus.RUNNING
        assert commands.time_warp_rate == 1.0
        # No node planned yet — the drop happens first, planning waits a tick.
        assert commands.create_node is None

    def test_drops_warp_during_refinement(self) -> None:
        action = DeorbitToTargetAction()
        seed = self._state_with_warp(100.0)
        action.start(seed, _params(target_latitude=-15.0, target_longitude=-70.0, tolerance_deg=0.1))
        # Drive past the initial drop tick at 1x and let the node get planned.
        action.tick(_orbit_state(), VesselCommands(), dt=0.5, log=ActionLogger())

        # Now still warping when refinement is needed: should drop again.
        node = _node_for(action)
        refine_state = State(
            **{
                **_orbit_state(
                    universal_time=1_001.0,
                    apoapsis_time_to=599.0,
                ).__dict__,
                "nodes": (node,),
                "predicted_impact": ImpactPrediction(
                    latitude=-15.0,
                    longitude=-65.0,
                    altitude_terrain=0.0,
                    time_to_ballistic_impact=1_500.0,
                    source="next_node_orbit",
                ),
                "time_warp_rate": 100.0,
            }
        )
        commands = VesselCommands()
        result = action.tick(refine_state, commands, dt=0.5, log=ActionLogger())
        assert result.status == ActionStatus.RUNNING
        assert commands.time_warp_rate == 1.0
        assert commands.create_node is None  # no replan this tick; just dropping

    def test_resumes_warp_once_converged(self) -> None:
        action = DeorbitToTargetAction()
        seed = self._state_with_warp(100.0)
        action.start(seed, _params(target_latitude=-15.0, target_longitude=-70.0, tolerance_deg=0.5))
        action.tick(_orbit_state(), VesselCommands(), dt=0.5, log=ActionLogger())  # initial drop

        # Converged on a sufficiently-precise prediction; warp should now
        # resume to the user's target rate read from state.user_target_warp_rate.
        action._converged = True
        node = _node_for(action)
        coast_state = State(
            **{
                **_orbit_state(universal_time=1_500.0, apoapsis_time_to=99.0).__dict__,
                "nodes": (node,),
                "predicted_impact": ImpactPrediction(
                    latitude=-15.0,
                    longitude=-70.0,
                    altitude_terrain=0.0,
                    time_to_ballistic_impact=1_500.0,
                    source="next_node_orbit",
                ),
                "time_warp_rate": 1.0,  # currently 1x after refinement drop
                "user_target_warp_rate": 100.0,  # but the user wants 100x back
            }
        )
        commands = VesselCommands()
        action.tick(coast_state, commands, dt=0.5, log=ActionLogger())
        # Action requested 100x back; one-shot, so subsequent ticks should not re-issue.
        assert commands.time_warp_rate == 100.0
        assert action._refinement_warp_resumed is True

        # Next tick: don't repeat the resume command.
        commands2 = VesselCommands()
        action.tick(coast_state, commands2, dt=0.5, log=ActionLogger())
        assert commands2.time_warp_rate is None

    # Warp restore on stop is handled by the ActionRunner (ADR 0012);
    # see tests/test_action_runner.py for the centralized coverage. The
    # mid-tick "resume warp once refinement converged" call still belongs
    # to the action (see test_resumes_warp_once_converged above).


class TestDeorbitLatitudeBurnPoint:
    """The burn point is chosen so the impact lands at the target latitude."""

    def test_travel_angle_is_half_orbit_when_periapsis_at_sea_level(self) -> None:
        # Periapsis exactly at sea level: the crossing IS periapsis, half an
        # orbit (180 deg) after the apoapsis burn.
        assert _travel_angle_burn_to_impact_deg(700_000.0, 600_000.0, 600_000.0) == pytest.approx(180.0)

    def test_travel_angle_shrinks_when_periapsis_below_sea_level(self) -> None:
        # Hand-computed ellipse: r_burn=700km, r_peri=6.3e6/11 m (~572.7km)
        # around a 600km body -> e=0.1, p=630km, cos(nu0)=(630/600-1)/0.1=0.5
        # -> nu0=60 deg: the trajectory reaches sea level 120 deg after the
        # burn, well short of the 180-deg antipode.
        assert _travel_angle_burn_to_impact_deg(700_000.0, 6_300_000.0 / 11.0, 600_000.0) == pytest.approx(120.0)

    def test_burn_point_plus_travel_angle_sits_at_target_latitude(self) -> None:
        # The helper must return a burn whose orbital position, one travel
        # angle later (the sea-level crossing), is at the target latitude.
        # Checked as a property for the apex case (|target| == inclination)
        # and both hemispheres. Geometry as above: travel angle = 120 deg.
        inclination_deg = 10.0
        an_ut = 5_000.0
        period = 1_800.0
        target_periapsis_alt = 6_300_000.0 / 11.0 - _KERBIN_RADIUS
        state = State(
            orbit_inclination=math.radians(inclination_deg),
            orbit_ascending_node_ut=an_ut,
            orbit_period=period,
            orbit_apoapsis=100_000.0,
            body_radius=_KERBIN_RADIUS,
        )
        for target_lat in (-10.0, -6.6, 7.3):
            burn_ut = _burn_ut_for_target_latitude(state, target_lat, target_periapsis_alt)
            assert burn_ut is not None
            u_burn_deg = ((burn_ut - an_ut) / period) * 360.0
            u_impact_rad = math.radians(u_burn_deg + 120.0)
            impact_lat = math.degrees(math.asin(math.sin(math.radians(inclination_deg)) * math.sin(u_impact_rad)))
            assert abs(impact_lat - target_lat) < 0.01

    def test_returns_none_when_equatorial(self) -> None:
        state = State(orbit_inclination=0.0, orbit_ascending_node_ut=5_000.0, orbit_period=1_800.0)
        assert _burn_ut_for_target_latitude(state, -6.6, -5_000.0) is None

    def test_returns_none_when_ascending_node_unavailable(self) -> None:
        # Inclined but AN unknown (defaults to inf): cannot place the burn.
        state = State(orbit_inclination=math.radians(10.0), orbit_period=1_800.0)
        assert _burn_ut_for_target_latitude(state, -6.6, -5_000.0) is None

    def test_initial_node_uses_latitude_burn_point_not_apoapsis(self) -> None:
        action = DeorbitToTargetAction()
        an_ut = 5_000.0
        period = 1_800.0
        state = State(
            orbit_inclination=math.radians(10.0),
            orbit_ascending_node_ut=an_ut,
            orbit_period=period,
            orbit_apoapsis=100_000.0,
            orbit_periapsis=95_000.0,
            orbit_apoapsis_time_to=400.0,
            orbit_semi_major_axis=_KERBIN_RADIUS + 97_500.0,
            universal_time=1_000.0,
            body_radius=_KERBIN_RADIUS,
            body_gm=_KERBIN_GM,
            body_rotational_period=_KERBIN_ROTATIONAL_PERIOD,
        )
        action.start(state, _params(target_latitude=-6.6, target_periapsis_altitude=-5_000.0))

        commands = VesselCommands()
        action.tick(state, commands, dt=0.5, log=ActionLogger())
        assert commands.create_node is not None
        expected = _burn_ut_for_target_latitude(state, -6.6, -5_000.0) + _INITIAL_LAP_BUFFER * period
        assert commands.create_node.ut == pytest.approx(expected)
        # NOT the old "apoapsis one orbit out" schedule.
        apoapsis_ut = state.universal_time + state.orbit_apoapsis_time_to + period
        assert commands.create_node.ut != pytest.approx(apoapsis_ut)
