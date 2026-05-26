"""Tests for the CircularizeAction vis-viva circularization burn."""

from __future__ import annotations

import math

import pytest

from ksp_mission_control.control.actions.base import (
    ActionLogger,
    ActionStatus,
    ManeuverNode,
    PartInfo,
    Parts,
    State,
    VesselCommands,
)
from ksp_mission_control.control.actions.circularize.action import Apse, CircularizeAction

# A roughly circular 80 km Kerbin orbit used as a baseline starting point.
_KERBIN_RADIUS = 600_000.0
_KERBIN_GM = 3.5316e12


def _orbit_state(
    *,
    apoapsis_alt: float = 100_000.0,
    periapsis_alt: float = 70_000.0,
    time_to_apoapsis: float = 60.0,
    time_to_periapsis: float = 1000.0,
    universal_time: float = 1_000.0,
) -> State:
    """Build a State with the orbital fields the circularize math needs."""
    r_apo = apoapsis_alt + _KERBIN_RADIUS
    r_peri = periapsis_alt + _KERBIN_RADIUS
    semi_major_axis = (r_apo + r_peri) / 2.0
    return State(
        orbit_apoapsis=apoapsis_alt,
        orbit_periapsis=periapsis_alt,
        orbit_apoapsis_time_to=time_to_apoapsis,
        orbit_periapsis_time_to=time_to_periapsis,
        orbit_semi_major_axis=semi_major_axis,
        universal_time=universal_time,
        body_radius=_KERBIN_RADIUS,
        body_gm=_KERBIN_GM,
    )


def _node_for(action: CircularizeAction, delta_v_remaining: float = 100.0) -> ManeuverNode:
    """Build a ManeuverNode at the ut that the action recorded."""
    assert action._node_ut is not None
    return ManeuverNode(
        index=0,
        ut=action._node_ut,
        time_to=10.0,
        delta_v=100.0,
        delta_v_remaining=delta_v_remaining,
        prograde=100.0,
        normal=0.0,
        radial=0.0,
        burn_vector=(0.0, 100.0, 0.0),
        burn_vector_remaining=(0.0, delta_v_remaining, 0.0),
        burn_time_estimate=10.0,
        post_burn_orbit_apoapsis=100_000.0,
        post_burn_orbit_periapsis=100_000.0,
        post_burn_orbit_eccentricity=0.0,
        post_burn_orbit_inclination=0.0,
        post_burn_orbit_period=5500.0,
        post_burn_orbit_semi_major_axis=_KERBIN_RADIUS + 100_000.0,
    )


class TestCircularizeMetadata:
    def test_action_id(self) -> None:
        assert CircularizeAction.action_id == "circularize"

    def test_apse_param_is_optional_with_default(self) -> None:
        param = next(p for p in CircularizeAction.params if p.param_id == "apse")
        assert param.required is False
        assert param.default == "apoapsis"


class TestCircularizeStartValidation:
    def test_accepts_valid_apse_values(self) -> None:
        action = CircularizeAction()
        action.start(State(), {"apse": "apoapsis", "staging_mode": None})
        assert action._apse.value == Apse.APOAPSIS.value

        action_p = CircularizeAction()
        action_p.start(State(), {"apse": "periapsis", "staging_mode": None})
        assert action_p._apse.value == Apse.PERIAPSIS.value

    def test_normalizes_case(self) -> None:
        action = CircularizeAction()
        action.start(State(), {"apse": "APOAPSIS", "staging_mode": None})
        assert action._apse.value == Apse.APOAPSIS.value

    def test_raises_on_invalid_apse(self) -> None:
        action = CircularizeAction()
        with pytest.raises(ValueError, match="Unknown apse"):
            action.start(State(), {"apse": "ascending_node", "staging_mode": None})


class TestCircularizeRequestsNode:
    """The first tick (no node yet) should request creation with the right dv."""

    def test_apoapsis_dv_is_positive_and_matches_vis_viva(self) -> None:
        action = CircularizeAction()
        state = _orbit_state(apoapsis_alt=100_000.0, periapsis_alt=70_000.0, time_to_apoapsis=300.0)
        action.start(state, {"apse": "apoapsis", "staging_mode": None})

        commands = VesselCommands()
        result = action.tick(state, commands, dt=0.5, log=ActionLogger())

        assert result.status == ActionStatus.RUNNING
        assert commands.create_node is not None
        # Expected dv: v_circular - v_current at apoapsis radius.
        r = 100_000.0 + _KERBIN_RADIUS
        a = (r + 70_000.0 + _KERBIN_RADIUS) / 2.0
        expected_dv = math.sqrt(_KERBIN_GM / r) - math.sqrt(_KERBIN_GM * (2.0 / r - 1.0 / a))
        assert expected_dv > 0.0  # apoapsis circularization is always prograde
        assert commands.create_node.prograde == pytest.approx(expected_dv, rel=1e-6)
        # Node ut equals current ut + time_to_apoapsis.
        assert commands.create_node.ut == pytest.approx(state.universal_time + 300.0)

    def test_periapsis_dv_is_negative(self) -> None:
        action = CircularizeAction()
        state = _orbit_state(apoapsis_alt=100_000.0, periapsis_alt=70_000.0, time_to_periapsis=500.0)
        action.start(state, {"apse": "periapsis", "staging_mode": None})

        commands = VesselCommands()
        action.tick(state, commands, dt=0.5, log=ActionLogger())

        assert commands.create_node is not None
        # Circularizing at periapsis requires lowering apoapsis: retrograde burn.
        assert commands.create_node.prograde < 0.0

    def test_records_node_ut_for_later_matching(self) -> None:
        action = CircularizeAction()
        state = _orbit_state(time_to_apoapsis=60.0, universal_time=1_000.0)
        action.start(state, {"apse": "apoapsis", "staging_mode": None})

        commands = VesselCommands()
        action.tick(state, commands, dt=0.5, log=ActionLogger())
        assert action._node_ut == pytest.approx(1_060.0)

    def test_fails_when_body_gm_is_zero(self) -> None:
        action = CircularizeAction()
        state = State(orbit_semi_major_axis=680_000.0, body_radius=_KERBIN_RADIUS, body_gm=0.0)
        action.start(state, {"apse": "apoapsis", "staging_mode": None})

        commands = VesselCommands()
        result = action.tick(state, commands, dt=0.5, log=ActionLogger())
        assert result.status == ActionStatus.FAILED
        assert commands.create_node is None


class TestCircularizeExecutesNode:
    """After the node exists in State.nodes the action should drive execute_node."""

    def test_running_burn_returns_running(self) -> None:
        action = CircularizeAction()
        state = _orbit_state()
        action.start(state, {"apse": "apoapsis", "staging_mode": None})
        # First tick: requests node creation, records ut.
        action.tick(state, VesselCommands(), dt=0.5, log=ActionLogger())

        # Second tick: node exists with dv remaining; expect RUNNING and throttle commanded.
        node = _node_for(action, delta_v_remaining=100.0)
        # Build a State with vessel-thrust fields so the burn window is open at node ut.
        burn_state = State(
            universal_time=action._node_ut or 0.0,
            thrust_available=50_000.0,
            engine_impulse_specific_vacuum=300.0,
            mass=5_000.0,
            body_radius=_KERBIN_RADIUS,
            body_gm=_KERBIN_GM,
            orbit_semi_major_axis=680_000.0,
            nodes=(node,),
        )
        commands = VesselCommands()
        result = action.tick(burn_state, commands, dt=0.5, log=ActionLogger())

        assert result.status == ActionStatus.RUNNING
        assert commands.throttle == 1.0
        assert commands.autopilot is True

    def test_completion_succeeds_and_removes_node(self) -> None:
        action = CircularizeAction()
        seed_state = _orbit_state()
        action.start(seed_state, {"apse": "apoapsis", "staging_mode": None})
        action.tick(seed_state, VesselCommands(), dt=0.5, log=ActionLogger())

        # Node remains but its delta-v is exhausted; helper returns True.
        node = _node_for(action, delta_v_remaining=0.0)
        done_state = State(
            universal_time=action._node_ut or 0.0,
            thrust_available=50_000.0,
            engine_impulse_specific_vacuum=300.0,
            mass=5_000.0,
            body_radius=_KERBIN_RADIUS,
            body_gm=_KERBIN_GM,
            orbit_semi_major_axis=680_000.0,
            orbit_eccentricity=0.0001,
            nodes=(node,),
        )
        commands = VesselCommands()
        result = action.tick(done_state, commands, dt=0.5, log=ActionLogger())

        assert result.status == ActionStatus.SUCCEEDED
        assert commands.remove_node_at_ut == pytest.approx(action._node_ut)
        assert commands.throttle == 0.0
        assert commands.autopilot is False


class TestCircularizeStaging:
    """staging_mode opt-in drives the auto_stage helper during the burn phase."""

    def _burn_state(
        self,
        action: CircularizeAction,
        engine_states: tuple[str, ...],
        stage_current: int = 3,
        thrust_available: float = 80_000.0,
    ) -> State:
        node = _node_for(action, delta_v_remaining=100.0)
        return State(
            universal_time=action._node_ut or 0.0,
            thrust_available=thrust_available,
            engine_impulse_specific_vacuum=300.0,
            mass=5_000.0,
            body_radius=_KERBIN_RADIUS,
            body_gm=_KERBIN_GM,
            orbit_semi_major_axis=680_000.0,
            stage_current=stage_current,
            parts=Parts(engines=tuple(PartInfo(stage=0, state=s) for s in engine_states)),
            nodes=(node,),
        )

    def test_no_staging_when_mode_is_none(self) -> None:
        action = CircularizeAction()
        seed = _orbit_state()
        action.start(seed, {"apse": "apoapsis", "staging_mode": None})
        action.tick(seed, VesselCommands(), dt=0.5, log=ActionLogger())

        commands = VesselCommands()
        action.tick(self._burn_state(action, engine_states=("active", "flameout")), commands, 0.5, ActionLogger())
        assert commands.stage is None

    def test_any_flameout_stages_mid_burn(self) -> None:
        action = CircularizeAction()
        seed = _orbit_state()
        action.start(seed, {"apse": "apoapsis", "staging_mode": "any_flameout"})
        action.tick(seed, VesselCommands(), dt=0.5, log=ActionLogger())

        commands = VesselCommands()
        action.tick(self._burn_state(action, engine_states=("active", "flameout")), commands, 0.5, ActionLogger())
        assert commands.stage is True

    def test_staging_mode_rejects_unknown_value(self) -> None:
        action = CircularizeAction()
        with pytest.raises(ValueError, match="Unknown staging_mode"):
            action.start(_orbit_state(), {"apse": "apoapsis", "staging_mode": "bogus"})

    def test_zero_thrust_with_pending_stage_returns_running(self) -> None:
        """auto_stage queues a stage in the same tick the engine flames out;
        state.thrust_available is still 0 (read before the command applies),
        so the action must defer the no-thrust failure to the next tick."""
        action = CircularizeAction()
        seed = _orbit_state()
        action.start(seed, {"apse": "apoapsis", "staging_mode": "any_flameout"})
        action.tick(seed, VesselCommands(), dt=0.5, log=ActionLogger())

        commands = VesselCommands()
        burn_state = self._burn_state(
            action,
            engine_states=("flameout", "inactive"),
            thrust_available=0.0,
        )
        result = action.tick(burn_state, commands, dt=0.5, log=ActionLogger())

        assert commands.stage is True
        assert result.status == ActionStatus.RUNNING

    def test_zero_thrust_without_pending_stage_fails(self) -> None:
        """When no inactive engine is waiting, auto_stage cannot queue a stage,
        so the action correctly fails on thrust exhaustion."""
        action = CircularizeAction()
        seed = _orbit_state()
        action.start(seed, {"apse": "apoapsis", "staging_mode": "any_flameout"})
        action.tick(seed, VesselCommands(), dt=0.5, log=ActionLogger())

        commands = VesselCommands()
        burn_state = self._burn_state(
            action,
            engine_states=("flameout",),
            thrust_available=0.0,
        )
        result = action.tick(burn_state, commands, dt=0.5, log=ActionLogger())

        assert commands.stage is None
        assert result.status == ActionStatus.FAILED


class TestCircularizeStop:
    def test_stop_removes_node_and_idles(self) -> None:
        action = CircularizeAction()
        state = _orbit_state()
        action.start(state, {"apse": "apoapsis", "staging_mode": None})
        action.tick(state, VesselCommands(), dt=0.5, log=ActionLogger())

        commands = VesselCommands()
        action.stop(state, commands, log=ActionLogger())
        assert commands.throttle == 0.0
        assert commands.autopilot is False
        assert commands.remove_node_at_ut == pytest.approx(action._node_ut)

    def test_stop_before_node_was_requested_is_safe(self) -> None:
        """If start() ran but tick() did not, stop() should not try to remove a node."""
        action = CircularizeAction()
        action.start(State(), {"apse": "apoapsis", "staging_mode": None})
        commands = VesselCommands()
        action.stop(State(), commands, log=ActionLogger())
        assert commands.throttle == 0.0
        assert commands.autopilot is False
        assert commands.remove_node_at_ut is None


class TestCircularizeWarpRestore:
    """The action restores the user's pre-action warp rate on completion (ADR 0012)."""

    def test_stop_restores_warp_when_captured_above_one(self) -> None:
        action = CircularizeAction()
        state = State(
            time_warp_rate=100.0,
            body_radius=_KERBIN_RADIUS,
            body_gm=_KERBIN_GM,
            orbit_semi_major_axis=680_000.0,
        )
        action.start(state, {"apse": "apoapsis", "staging_mode": None})
        commands = VesselCommands()
        action.stop(state, commands, log=ActionLogger())
        assert commands.time_warp_rate == 100.0

    def test_tick_max_tracks_warp_rate(self) -> None:
        action = CircularizeAction()
        action.start(_orbit_state(), {"apse": "apoapsis", "staging_mode": None})
        assert action._initial_warp_rate == _orbit_state().time_warp_rate
        action.tick(
            State(
                time_warp_rate=50.0,
                orbit_apoapsis=100_000.0,
                orbit_apoapsis_time_to=300.0,
                orbit_semi_major_axis=680_000.0,
                body_radius=_KERBIN_RADIUS,
                body_gm=_KERBIN_GM,
            ),
            VesselCommands(),
            dt=0.5,
            log=ActionLogger(),
        )
        assert action._initial_warp_rate == 50.0

    def test_stop_does_not_set_warp_when_captured_was_one(self) -> None:
        action = CircularizeAction()
        action.start(State(), {"apse": "apoapsis", "staging_mode": None})
        commands = VesselCommands()
        action.stop(State(), commands, log=ActionLogger())
        assert commands.time_warp_rate is None
