"""Tests for the small maneuver-node utility helpers.

Coverage of ``execute_node`` (the bulk of helpers/maneuver_node.py) lives
in ``test_maneuver_node.py``. This file targets the smaller utilities
that were extracted from per-action bodies:

- ``find_maneuver_node_by_ut``: locate the node an action created.
- ``fail_if_node_has_no_thrust``: post-execute_node thrust-out check.
"""

from __future__ import annotations

from ksp_mission_control.control.actions.base import (
    ActionStatus,
    ManeuverNode,
    State,
    VesselCommands,
)
from ksp_mission_control.control.actions.helpers.maneuver_node import (
    fail_if_node_has_no_thrust,
    find_maneuver_node_by_ut,
)


def _make_node(ut: float, delta_v_remaining: float = 100.0) -> ManeuverNode:
    """Minimal ManeuverNode for tests that only care about ut / delta_v."""
    return ManeuverNode(
        index=0,
        ut=ut,
        time_to=10.0,
        delta_v=100.0,
        delta_v_remaining=delta_v_remaining,
        prograde=100.0,
        normal=0.0,
        radial=0.0,
        burn_vector=(0.0, 100.0, 0.0),
        burn_vector_remaining=(0.0, delta_v_remaining, 0.0),
        burn_time_estimate=10.0,
        post_burn_orbit_apoapsis=0.0,
        post_burn_orbit_periapsis=0.0,
        post_burn_orbit_eccentricity=0.0,
        post_burn_orbit_inclination=0.0,
        post_burn_orbit_period=0.0,
        post_burn_orbit_semi_major_axis=0.0,
    )


class TestFindManeuverNodeByUt:
    def test_returns_none_when_node_ut_is_none(self) -> None:
        # Action has not requested a node yet.
        state = State(nodes=(_make_node(ut=500.0),))
        assert find_maneuver_node_by_ut(state, None) is None

    def test_returns_none_when_no_node_matches(self) -> None:
        state = State(nodes=(_make_node(ut=500.0),))
        assert find_maneuver_node_by_ut(state, 999.0) is None

    def test_finds_matching_node_within_tolerance(self) -> None:
        # Float jitter on the kRPC round-trip: helper must tolerate small drift.
        node = _make_node(ut=500.000_5)
        state = State(nodes=(node,))
        assert find_maneuver_node_by_ut(state, 500.0) is node

    def test_rejects_node_outside_tolerance(self) -> None:
        state = State(nodes=(_make_node(ut=500.5),))
        assert find_maneuver_node_by_ut(state, 500.0) is None

    def test_picks_correct_node_among_many(self) -> None:
        # Other nodes may exist if a plan inserted them between ticks.
        target = _make_node(ut=750.0)
        state = State(nodes=(_make_node(ut=100.0), target, _make_node(ut=1000.0)))
        assert find_maneuver_node_by_ut(state, 750.0) is target

    def test_custom_tolerance_widens_match(self) -> None:
        state = State(nodes=(_make_node(ut=510.0),))
        # Default 0.001 would not match, but a wider tolerance does.
        assert find_maneuver_node_by_ut(state, 500.0, tolerance=20.0) is not None


class TestFailIfNodeHasNoThrust:
    def test_returns_none_when_thrust_available(self) -> None:
        # Healthy burn: helper does not interfere.
        state = State(thrust_available=50_000.0)
        node = _make_node(ut=500.0)
        commands = VesselCommands()
        assert fail_if_node_has_no_thrust(state, commands, node) is None

    def test_returns_failed_when_no_thrust_and_no_pending_stage(self) -> None:
        # Engine flamed out and no inactive engine waiting: burn is dead.
        state = State(thrust_available=0.0)
        node = _make_node(ut=500.0, delta_v_remaining=42.5)
        commands = VesselCommands()
        result = fail_if_node_has_no_thrust(state, commands, node)
        assert result is not None
        assert result.status == ActionStatus.FAILED
        assert "42.5" in result.message  # remaining dv surfaced in the message

    def test_returns_none_when_no_thrust_but_stage_pending(self) -> None:
        # auto_stage just queued a stage. state.thrust_available is still 0
        # (read before this tick's command applies), but the next tick will
        # ignite the new engine. Failing now would kill the burn early.
        state = State(thrust_available=0.0)
        node = _make_node(ut=500.0)
        commands = VesselCommands(stage=True)
        assert fail_if_node_has_no_thrust(state, commands, node) is None

    def test_does_not_modify_commands(self) -> None:
        # Helper is read-only with respect to commands; the FAILED return
        # is enough signal for the runner to invoke stop().
        state = State(thrust_available=0.0)
        node = _make_node(ut=500.0)
        commands = VesselCommands(throttle=0.5)
        fail_if_node_has_no_thrust(state, commands, node)
        assert commands.throttle == 0.5
