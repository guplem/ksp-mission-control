"""Tests for the ChangeApseAction vis-viva apse-raising/lowering burn."""

from __future__ import annotations

import math

import pytest

from ksp_mission_control.control.actions.base import (
    ActionLogger,
    ActionStatus,
    ManeuverNode,
    State,
    VesselCommands,
)
from ksp_mission_control.control.actions.change_apse.action import ApseTarget, ChangeApseAction

# A roughly 80 km Kerbin orbit used as a baseline starting point.
_KERBIN_RADIUS = 600_000.0
_KERBIN_GM = 3.5316e12


def _orbit_state(
    *,
    apoapsis_alt: float = 100_000.0,
    periapsis_alt: float = 80_000.0,
    time_to_apoapsis: float = 60.0,
    time_to_periapsis: float = 1000.0,
    universal_time: float = 1_000.0,
) -> State:
    """Build a State with the orbital fields the change_apse math needs."""
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


def _node_for(action: ChangeApseAction, delta_v_remaining: float = 100.0) -> ManeuverNode:
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
        post_burn_orbit_apoapsis=260_000_000.0,
        post_burn_orbit_periapsis=80_000.0,
        post_burn_orbit_eccentricity=0.9,
        post_burn_orbit_inclination=0.0,
        post_burn_orbit_period=5500.0,
        post_burn_orbit_semi_major_axis=_KERBIN_RADIUS + 100_000.0,
    )


class TestChangeApseMetadata:
    def test_action_id(self) -> None:
        assert ChangeApseAction.action_id == "change_apse"

    def test_target_param_is_optional_with_default(self) -> None:
        param = next(p for p in ChangeApseAction.params if p.param_id == "target")
        assert param.required is False
        assert param.default == "apoapsis"

    def test_target_altitude_param_is_required(self) -> None:
        param = next(p for p in ChangeApseAction.params if p.param_id == "target_altitude")
        assert param.required is True
        assert param.unit == "m"


class TestChangeApseStartValidation:
    def test_accepts_valid_target_values(self) -> None:
        action = ChangeApseAction()
        action.start(_orbit_state(), {"target": "apoapsis", "target_altitude": 200_000.0})
        assert action._target is ApseTarget.APOAPSIS

        action_p = ChangeApseAction()
        action_p.start(_orbit_state(), {"target": "periapsis", "target_altitude": 50_000.0})
        assert action_p._target is ApseTarget.PERIAPSIS

    def test_normalizes_case(self) -> None:
        action = ChangeApseAction()
        action.start(_orbit_state(), {"target": "APOAPSIS", "target_altitude": 200_000.0})
        assert action._target is ApseTarget.APOAPSIS

    def test_raises_on_invalid_target(self) -> None:
        action = ChangeApseAction()
        with pytest.raises(ValueError, match="Unknown target"):
            action.start(_orbit_state(), {"target": "ascending_node", "target_altitude": 200_000.0})

    def test_unreachable_apoapsis_target_sets_fail_message(self) -> None:
        """Lowering apoapsis below the current periapsis would flip which apse is which."""
        action = ChangeApseAction()
        action.start(
            _orbit_state(apoapsis_alt=200_000.0, periapsis_alt=100_000.0),
            {"target": "apoapsis", "target_altitude": 50_000.0},
        )
        commands = VesselCommands()
        result = action.tick(_orbit_state(), commands, dt=0.5, log=ActionLogger())
        assert result.status == ActionStatus.FAILED

    def test_unreachable_periapsis_target_sets_fail_message(self) -> None:
        """Raising periapsis above the current apoapsis would flip which apse is which."""
        action = ChangeApseAction()
        action.start(
            _orbit_state(apoapsis_alt=200_000.0, periapsis_alt=100_000.0),
            {"target": "periapsis", "target_altitude": 300_000.0},
        )
        commands = VesselCommands()
        result = action.tick(_orbit_state(), commands, dt=0.5, log=ActionLogger())
        assert result.status == ActionStatus.FAILED


class TestChangeApseRequestsNode:
    """The first tick (no node yet) should request creation at the opposite apse."""

    def test_raise_apoapsis_burns_at_periapsis_with_positive_dv(self) -> None:
        action = ChangeApseAction()
        state = _orbit_state(
            apoapsis_alt=100_000.0,
            periapsis_alt=80_000.0,
            time_to_periapsis=500.0,
            time_to_apoapsis=60.0,
        )
        action.start(state, {"target": "apoapsis", "target_altitude": 260_000_000.0})

        commands = VesselCommands()
        result = action.tick(state, commands, dt=0.5, log=ActionLogger())

        assert result.status == ActionStatus.RUNNING
        assert commands.create_node is not None
        # Burn radius is the periapsis radius (we burn at the opposite apse).
        r_burn = 80_000.0 + _KERBIN_RADIUS
        r_target = 260_000_000.0 + _KERBIN_RADIUS
        a_new = (r_burn + r_target) / 2.0
        a_current = (100_000.0 + _KERBIN_RADIUS + r_burn) / 2.0
        expected_dv = math.sqrt(_KERBIN_GM * (2.0 / r_burn - 1.0 / a_new)) - math.sqrt(_KERBIN_GM * (2.0 / r_burn - 1.0 / a_current))
        assert expected_dv > 0.0  # raising apoapsis = prograde burn
        assert commands.create_node.prograde == pytest.approx(expected_dv, rel=1e-6)
        # Node ut equals current ut + time_to_periapsis (the burn apse).
        assert commands.create_node.ut == pytest.approx(state.universal_time + 500.0)

    def test_lower_periapsis_burns_at_apoapsis_with_negative_dv(self) -> None:
        action = ChangeApseAction()
        state = _orbit_state(
            apoapsis_alt=100_000.0,
            periapsis_alt=80_000.0,
            time_to_apoapsis=300.0,
        )
        action.start(state, {"target": "periapsis", "target_altitude": 35_000.0})

        commands = VesselCommands()
        action.tick(state, commands, dt=0.5, log=ActionLogger())

        assert commands.create_node is not None
        assert commands.create_node.prograde < 0.0
        # Burn happens at apoapsis.
        assert commands.create_node.ut == pytest.approx(state.universal_time + 300.0)

    def test_records_node_ut_for_later_matching(self) -> None:
        action = ChangeApseAction()
        state = _orbit_state(time_to_periapsis=120.0, universal_time=1_000.0)
        action.start(state, {"target": "apoapsis", "target_altitude": 500_000.0})

        commands = VesselCommands()
        action.tick(state, commands, dt=0.5, log=ActionLogger())
        assert action._node_ut == pytest.approx(1_120.0)

    def test_fails_when_body_gm_is_zero(self) -> None:
        action = ChangeApseAction()
        state = State(
            orbit_apoapsis=100_000.0,
            orbit_periapsis=80_000.0,
            orbit_semi_major_axis=680_000.0,
            body_radius=_KERBIN_RADIUS,
            body_gm=0.0,
        )
        action.start(state, {"target": "apoapsis", "target_altitude": 200_000.0})

        commands = VesselCommands()
        result = action.tick(state, commands, dt=0.5, log=ActionLogger())
        assert result.status == ActionStatus.FAILED
        assert commands.create_node is None


class TestChangeApseExecutesNode:
    """After the node exists in State.nodes the action should drive execute_node."""

    def test_running_burn_returns_running(self) -> None:
        action = ChangeApseAction()
        state = _orbit_state()
        action.start(state, {"target": "apoapsis", "target_altitude": 260_000_000.0})
        # First tick: requests node creation, records ut.
        action.tick(state, VesselCommands(), dt=0.5, log=ActionLogger())

        node = _node_for(action, delta_v_remaining=100.0)
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
        action = ChangeApseAction()
        seed_state = _orbit_state()
        action.start(seed_state, {"target": "apoapsis", "target_altitude": 260_000_000.0})
        action.tick(seed_state, VesselCommands(), dt=0.5, log=ActionLogger())

        node = _node_for(action, delta_v_remaining=0.0)
        done_state = State(
            universal_time=action._node_ut or 0.0,
            thrust_available=50_000.0,
            engine_impulse_specific_vacuum=300.0,
            mass=5_000.0,
            body_radius=_KERBIN_RADIUS,
            body_gm=_KERBIN_GM,
            orbit_semi_major_axis=680_000.0,
            orbit_apoapsis=260_000_000.0,
            orbit_periapsis=80_000.0,
            nodes=(node,),
        )
        commands = VesselCommands()
        result = action.tick(done_state, commands, dt=0.5, log=ActionLogger())

        assert result.status == ActionStatus.SUCCEEDED
        assert commands.remove_node_at_ut == pytest.approx(action._node_ut)
        assert commands.throttle == 0.0
        assert commands.autopilot is False


class TestChangeApseStop:
    def test_stop_removes_node_and_idles(self) -> None:
        action = ChangeApseAction()
        state = _orbit_state()
        action.start(state, {"target": "apoapsis", "target_altitude": 260_000_000.0})
        action.tick(state, VesselCommands(), dt=0.5, log=ActionLogger())

        commands = VesselCommands()
        action.stop(state, commands, log=ActionLogger())
        assert commands.throttle == 0.0
        assert commands.autopilot is False
        assert commands.remove_node_at_ut == pytest.approx(action._node_ut)

    def test_stop_before_node_was_requested_is_safe(self) -> None:
        """If start() ran but tick() did not, stop() should not try to remove a node."""
        action = ChangeApseAction()
        action.start(_orbit_state(), {"target": "apoapsis", "target_altitude": 260_000_000.0})
        commands = VesselCommands()
        action.stop(_orbit_state(), commands, log=ActionLogger())
        assert commands.throttle == 0.0
        assert commands.autopilot is False
        assert commands.remove_node_at_ut is None
