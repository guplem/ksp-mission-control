"""Tests for AlignPlaneAction."""

from __future__ import annotations

import math

import pytest

from ksp_mission_control.control.actions.align_plane.action import AlignPlaneAction
from ksp_mission_control.control.actions.base import (
    ActionLogger,
    ActionStatus,
    ManeuverNode,
    State,
    VesselCommands,
)

_KERBIN_RADIUS = 600_000.0
_KERBIN_GM = 3.5316e12


def _params(
    *,
    target_latitude: float,
    crossing: str = "cheaper",
    margin_deg: float = 0.5,
    staging_mode: str | None = None,
) -> dict[str, object]:
    return {
        "target_latitude": target_latitude,
        "crossing": crossing,
        "margin_deg": margin_deg,
        "staging_mode": staging_mode,
    }


def _inclined_orbit_state(
    *,
    inclination_deg: float = 5.0,
    universal_time: float = 1_000.0,
    an_ut: float = 1_100.0,
    dn_ut: float = 1_200.0,
    an_speed: float = 2_200.0,
    dn_speed: float = 1_800.0,
    apoapsis_alt: float = 100_000.0,
    periapsis_alt: float = 80_000.0,
) -> State:
    r_apo = apoapsis_alt + _KERBIN_RADIUS
    r_peri = periapsis_alt + _KERBIN_RADIUS
    return State(
        orbit_inclination=math.radians(inclination_deg),
        orbit_apoapsis=apoapsis_alt,
        orbit_periapsis=periapsis_alt,
        orbit_apoapsis_time_to=300.0,
        orbit_periapsis_time_to=900.0,
        orbit_semi_major_axis=(r_apo + r_peri) / 2.0,
        orbit_ascending_node_ut=an_ut,
        orbit_descending_node_ut=dn_ut,
        orbit_ascending_node_speed=an_speed,
        orbit_descending_node_speed=dn_speed,
        universal_time=universal_time,
        body_radius=_KERBIN_RADIUS,
        body_gm=_KERBIN_GM,
    )


def _equatorial_orbit_state(*, universal_time: float = 1_000.0, apoapsis_alt: float = 100_000.0) -> State:
    r_apo = apoapsis_alt + _KERBIN_RADIUS
    return State(
        orbit_inclination=0.0,
        orbit_apoapsis=apoapsis_alt,
        orbit_periapsis=apoapsis_alt,  # circular
        orbit_apoapsis_time_to=300.0,
        orbit_semi_major_axis=r_apo,
        orbit_ascending_node_ut=float("inf"),
        orbit_descending_node_ut=float("inf"),
        universal_time=universal_time,
        body_radius=_KERBIN_RADIUS,
        body_gm=_KERBIN_GM,
    )


def _node_for(action: AlignPlaneAction, delta_v_remaining: float = 100.0) -> ManeuverNode:
    assert action._node_ut is not None
    return ManeuverNode(
        index=0,
        ut=action._node_ut,
        time_to=10.0,
        delta_v=100.0,
        delta_v_remaining=delta_v_remaining,
        prograde=0.0,
        normal=100.0,
        radial=0.0,
        burn_vector=(0.0, 100.0, 0.0),
        burn_vector_remaining=(0.0, delta_v_remaining, 0.0),
        burn_time_estimate=10.0,
        post_burn_orbit_apoapsis=100_000.0,
        post_burn_orbit_periapsis=80_000.0,
        post_burn_orbit_eccentricity=0.01,
        post_burn_orbit_inclination=0.1,
        post_burn_orbit_period=2400.0,
        post_burn_orbit_semi_major_axis=_KERBIN_RADIUS + 90_000.0,
    )


class TestAlignPlaneMetadata:
    def test_action_id(self) -> None:
        assert AlignPlaneAction.action_id == "align_plane"

    def test_target_latitude_is_required(self) -> None:
        param = next(p for p in AlignPlaneAction.params if p.param_id == "target_latitude")
        assert param.required is True

    def test_crossing_default_is_cheaper(self) -> None:
        param = next(p for p in AlignPlaneAction.params if p.param_id == "crossing")
        assert param.default == "cheaper"


class TestAlignPlaneStartValidation:
    def test_accepts_valid_crossing_values(self) -> None:
        for value in ("cheaper", "next", "ascending_node", "descending_node"):
            action = AlignPlaneAction()
            action.start(_equatorial_orbit_state(), _params(target_latitude=10.0, crossing=value))
            assert action._crossing.value == value

    def test_normalizes_case(self) -> None:
        action = AlignPlaneAction()
        action.start(_equatorial_orbit_state(), _params(target_latitude=10.0, crossing="ASCENDING_NODE"))
        assert action._crossing.value == "ascending_node"

    def test_rejects_invalid_crossing(self) -> None:
        action = AlignPlaneAction()
        with pytest.raises(ValueError, match="Unknown crossing"):
            action.start(_equatorial_orbit_state(), _params(target_latitude=10.0, crossing="midpoint"))

    def test_rejects_out_of_range_latitude(self) -> None:
        action = AlignPlaneAction()
        with pytest.raises(ValueError, match="target_latitude must be in"):
            action.start(_equatorial_orbit_state(), _params(target_latitude=120.0))

    def test_rejects_negative_margin(self) -> None:
        action = AlignPlaneAction()
        with pytest.raises(ValueError, match="margin_deg must be non-negative"):
            action.start(_equatorial_orbit_state(), _params(target_latitude=10.0, margin_deg=-0.1))


class TestAlignPlaneAlreadyAligned:
    """When inclination already matches target within margin, action succeeds without burning."""

    def test_succeeds_when_inclination_within_margin(self) -> None:
        action = AlignPlaneAction()
        state = _inclined_orbit_state(inclination_deg=10.0)
        action.start(state, _params(target_latitude=10.2, margin_deg=0.5))

        commands = VesselCommands()
        result = action.tick(state, commands, dt=0.5, log=ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED
        assert commands.create_node is None

    def test_proceeds_when_outside_margin(self) -> None:
        action = AlignPlaneAction()
        state = _inclined_orbit_state(inclination_deg=10.0)
        action.start(state, _params(target_latitude=25.0, margin_deg=0.5))

        commands = VesselCommands()
        result = action.tick(state, commands, dt=0.5, log=ActionLogger())
        assert result.status == ActionStatus.RUNNING
        assert commands.create_node is not None


class TestAlignPlanePicksCrossing:
    """The crossing param controls which equatorial node hosts the burn."""

    def test_cheaper_picks_lower_speed_node(self) -> None:
        # DN has lower speed (1800 < 2200): cheaper to plane-change there.
        action = AlignPlaneAction()
        state = _inclined_orbit_state(inclination_deg=5.0, an_speed=2_200.0, dn_speed=1_800.0)
        action.start(state, _params(target_latitude=20.0, crossing="cheaper"))

        commands = VesselCommands()
        action.tick(state, commands, dt=0.5, log=ActionLogger())
        assert commands.create_node is not None
        # Burn UT matches DN UT from state.
        assert commands.create_node.ut == state.orbit_descending_node_ut
        # At DN, raising inclination requires -normal.
        assert commands.create_node.normal < 0.0

    def test_next_picks_earlier_node(self) -> None:
        # AN is earlier in time.
        action = AlignPlaneAction()
        state = _inclined_orbit_state(an_ut=1_100.0, dn_ut=1_500.0)
        action.start(state, _params(target_latitude=20.0, crossing="next"))

        commands = VesselCommands()
        action.tick(state, commands, dt=0.5, log=ActionLogger())
        assert commands.create_node is not None
        assert commands.create_node.ut == 1_100.0
        # At AN, raising inclination uses +normal.
        assert commands.create_node.normal > 0.0

    def test_ascending_node_forces_an(self) -> None:
        action = AlignPlaneAction()
        state = _inclined_orbit_state(an_speed=2_500.0, dn_speed=1_500.0)
        action.start(state, _params(target_latitude=20.0, crossing="ascending_node"))

        commands = VesselCommands()
        action.tick(state, commands, dt=0.5, log=ActionLogger())
        assert commands.create_node is not None
        assert commands.create_node.ut == state.orbit_ascending_node_ut

    def test_descending_node_forces_dn(self) -> None:
        action = AlignPlaneAction()
        state = _inclined_orbit_state(an_speed=1_500.0, dn_speed=2_500.0)
        action.start(state, _params(target_latitude=20.0, crossing="descending_node"))

        commands = VesselCommands()
        action.tick(state, commands, dt=0.5, log=ActionLogger())
        assert commands.create_node is not None
        assert commands.create_node.ut == state.orbit_descending_node_ut


class TestAlignPlaneDvDirection:
    """Verify the sign of the normal burn for each (crossing, delta_inc) combination."""

    def test_an_raise_inclination_uses_positive_normal(self) -> None:
        action = AlignPlaneAction()
        state = _inclined_orbit_state(inclination_deg=5.0)
        action.start(state, _params(target_latitude=20.0, crossing="ascending_node"))
        commands = VesselCommands()
        action.tick(state, commands, dt=0.5, log=ActionLogger())
        assert commands.create_node is not None
        assert commands.create_node.normal > 0.0

    def test_an_lower_inclination_uses_negative_normal(self) -> None:
        action = AlignPlaneAction()
        state = _inclined_orbit_state(inclination_deg=30.0)
        action.start(state, _params(target_latitude=10.0, crossing="ascending_node"))
        commands = VesselCommands()
        action.tick(state, commands, dt=0.5, log=ActionLogger())
        assert commands.create_node is not None
        assert commands.create_node.normal < 0.0

    def test_dn_raise_inclination_uses_negative_normal(self) -> None:
        action = AlignPlaneAction()
        state = _inclined_orbit_state(inclination_deg=5.0)
        action.start(state, _params(target_latitude=20.0, crossing="descending_node"))
        commands = VesselCommands()
        action.tick(state, commands, dt=0.5, log=ActionLogger())
        assert commands.create_node is not None
        assert commands.create_node.normal < 0.0

    def test_dn_lower_inclination_uses_positive_normal(self) -> None:
        action = AlignPlaneAction()
        state = _inclined_orbit_state(inclination_deg=30.0)
        action.start(state, _params(target_latitude=10.0, crossing="descending_node"))
        commands = VesselCommands()
        action.tick(state, commands, dt=0.5, log=ActionLogger())
        assert commands.create_node is not None
        assert commands.create_node.normal > 0.0


class TestAlignPlaneEquatorialOrbit:
    """When starting equatorial, the action burns at apoapsis regardless of crossing param."""

    def test_burns_at_apoapsis_when_orbit_is_equatorial(self) -> None:
        action = AlignPlaneAction()
        state = _equatorial_orbit_state(universal_time=1_000.0, apoapsis_alt=100_000.0)
        action.start(state, _params(target_latitude=15.0, crossing="cheaper"))

        commands = VesselCommands()
        action.tick(state, commands, dt=0.5, log=ActionLogger())
        assert commands.create_node is not None
        assert commands.create_node.ut == pytest.approx(state.universal_time + state.orbit_apoapsis_time_to)

    def test_positive_target_latitude_uses_positive_normal(self) -> None:
        # apoapsis becomes new AN: +normal raises inclination.
        action = AlignPlaneAction()
        state = _equatorial_orbit_state()
        action.start(state, _params(target_latitude=20.0))

        commands = VesselCommands()
        action.tick(state, commands, dt=0.5, log=ActionLogger())
        assert commands.create_node is not None
        assert commands.create_node.normal > 0.0

    def test_negative_target_latitude_uses_negative_normal(self) -> None:
        # apoapsis becomes new DN: -normal raises inclination (orbit goes south).
        action = AlignPlaneAction()
        state = _equatorial_orbit_state()
        action.start(state, _params(target_latitude=-20.0))

        commands = VesselCommands()
        action.tick(state, commands, dt=0.5, log=ActionLogger())
        assert commands.create_node is not None
        assert commands.create_node.normal < 0.0

    def test_dv_magnitude_matches_2v_sin_half_inc(self) -> None:
        action = AlignPlaneAction()
        state = _equatorial_orbit_state(apoapsis_alt=100_000.0)
        action.start(state, _params(target_latitude=20.0))

        commands = VesselCommands()
        action.tick(state, commands, dt=0.5, log=ActionLogger())
        assert commands.create_node is not None
        # v at apoapsis for circular orbit at 100km: v = sqrt(mu / r).
        r = 100_000.0 + _KERBIN_RADIUS
        v = math.sqrt(_KERBIN_GM / r)
        expected_dv = 2.0 * v * math.sin(math.radians(20.0) / 2.0)
        assert abs(abs(commands.create_node.normal) - expected_dv) < 0.5


class TestAlignPlaneExecutesNode:
    """After the node exists the action drives execute_node."""

    def test_running_burn_returns_running(self) -> None:
        action = AlignPlaneAction()
        state = _inclined_orbit_state(inclination_deg=5.0)
        action.start(state, _params(target_latitude=20.0))
        action.tick(state, VesselCommands(), dt=0.5, log=ActionLogger())  # plans node

        node = _node_for(action, delta_v_remaining=80.0)
        burn_state = State(
            universal_time=action._node_ut or 0.0,
            thrust_available=50_000.0,
            engine_impulse_specific_vacuum=300.0,
            mass=5_000.0,
            orbit_inclination=math.radians(5.0),
            body_radius=_KERBIN_RADIUS,
            body_gm=_KERBIN_GM,
            orbit_semi_major_axis=690_000.0,
            nodes=(node,),
        )
        commands = VesselCommands()
        result = action.tick(burn_state, commands, dt=0.5, log=ActionLogger())
        assert result.status == ActionStatus.RUNNING
        assert commands.throttle == 1.0
        assert commands.autopilot is True

    def test_completion_succeeds_and_removes_node(self) -> None:
        action = AlignPlaneAction()
        seed = _inclined_orbit_state(inclination_deg=5.0)
        action.start(seed, _params(target_latitude=20.0))
        action.tick(seed, VesselCommands(), dt=0.5, log=ActionLogger())

        node = _node_for(action, delta_v_remaining=0.0)
        done_state = State(
            universal_time=action._node_ut or 0.0,
            thrust_available=50_000.0,
            engine_impulse_specific_vacuum=300.0,
            mass=5_000.0,
            orbit_inclination=math.radians(19.9),
            body_radius=_KERBIN_RADIUS,
            body_gm=_KERBIN_GM,
            orbit_semi_major_axis=690_000.0,
            nodes=(node,),
        )
        commands = VesselCommands()
        result = action.tick(done_state, commands, dt=0.5, log=ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED
        assert commands.remove_node_at_ut == pytest.approx(action._node_ut)
        assert commands.throttle == 0.0
        assert commands.autopilot is False


class TestAlignPlaneStop:
    def test_stop_removes_node(self) -> None:
        action = AlignPlaneAction()
        state = _inclined_orbit_state(inclination_deg=5.0)
        action.start(state, _params(target_latitude=20.0))
        action.tick(state, VesselCommands(), dt=0.5, log=ActionLogger())

        commands = VesselCommands()
        action.stop(state, commands, log=ActionLogger())
        assert commands.throttle == 0.0
        assert commands.autopilot is False
        assert commands.remove_node_at_ut == pytest.approx(action._node_ut)

    def test_stop_before_planning_is_safe(self) -> None:
        action = AlignPlaneAction()
        action.start(_equatorial_orbit_state(), _params(target_latitude=10.0))
        commands = VesselCommands()
        action.stop(State(), commands, log=ActionLogger())
        assert commands.remove_node_at_ut is None


class TestAlignPlaneWarpRestore:
    """The action restores ``state.user_target_warp_rate`` on stop (ADR 0012)."""

    def test_stop_restores_user_target_warp_rate(self) -> None:
        action = AlignPlaneAction()
        action.start(
            State(body_radius=_KERBIN_RADIUS, body_gm=_KERBIN_GM, orbit_semi_major_axis=600_100_000.0),
            _params(target_latitude=10.0),
        )
        commands = VesselCommands()
        # stop() reads the live state's user_target_warp_rate, not anything
        # captured at start(). This is the change that makes the restore
        # robust against KSP refusing the initial warp set.
        action.stop(State(user_target_warp_rate=100.0), commands, log=ActionLogger())
        assert commands.time_warp_rate == 100.0

    def test_stop_does_not_set_warp_when_user_target_is_one(self) -> None:
        action = AlignPlaneAction()
        action.start(
            State(body_radius=_KERBIN_RADIUS, body_gm=_KERBIN_GM, orbit_semi_major_axis=600_100_000.0),
            _params(target_latitude=10.0),
        )
        commands = VesselCommands()
        action.stop(State(user_target_warp_rate=1.0), commands, log=ActionLogger())
        assert commands.time_warp_rate is None
