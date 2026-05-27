"""Tests for the execute_node helper that drives the vessel through a maneuver node."""

from __future__ import annotations

import pytest

from ksp_mission_control.control.actions.base import (
    ActionLogger,
    ManeuverNode,
    PartInfo,
    Parts,
    ReferenceFrame,
    State,
    VesselCommands,
)
from ksp_mission_control.control.actions.helpers.maneuver_node import execute_node
from ksp_mission_control.control.actions.helpers.staging import StagingMode


def _make_node(
    *,
    ut: float = 1000.0,
    delta_v: float = 100.0,
    delta_v_remaining: float = 100.0,
    burn_vector_remaining: tuple[float, float, float] = (0.0, 100.0, 0.0),
    burn_time_estimate: float = 10.0,
) -> ManeuverNode:
    """Build a ManeuverNode populated with the fields execute_node reads."""
    return ManeuverNode(
        index=0,
        ut=ut,
        time_to=ut,
        delta_v=delta_v,
        delta_v_remaining=delta_v_remaining,
        prograde=delta_v,
        normal=0.0,
        radial=0.0,
        burn_vector=(0.0, delta_v, 0.0),
        burn_vector_remaining=burn_vector_remaining,
        burn_time_estimate=burn_time_estimate,
        post_burn_orbit_apoapsis=80_000.0,
        post_burn_orbit_periapsis=80_000.0,
        post_burn_orbit_eccentricity=0.0,
        post_burn_orbit_inclination=0.0,
        post_burn_orbit_period=5500.0,
        post_burn_orbit_semi_major_axis=680_000.0,
    )


def _make_burning_state(
    *,
    universal_time: float = 500.0,
    thrust_available: float = 50_000.0,
    isp_vac: float = 300.0,
    mass: float = 5_000.0,
    stage_current: int = 3,
    engine_states: tuple[str, ...] = (),
    time_warp_rate: float = 1.0,
) -> State:
    """Build a State with vessel parameters that yield a finite burn time."""
    return State(
        universal_time=universal_time,
        thrust_available=thrust_available,
        engine_impulse_specific_vacuum=isp_vac,
        mass=mass,
        stage_current=stage_current,
        parts=Parts(engines=tuple(PartInfo(stage=0, state=s) for s in engine_states)),
        time_warp_rate=time_warp_rate,
    )


class TestExecuteNodeOrientation:
    """The autopilot direction must follow the remaining burn vector every tick."""

    def test_sets_autopilot_direction_to_remaining_burn_vector(self) -> None:
        node = _make_node(burn_vector_remaining=(10.0, 90.0, 0.0))
        commands = VesselCommands()
        execute_node(_make_burning_state(), commands, node, None, 0.5, ActionLogger())
        assert commands.autopilot is True
        assert commands.autopilot_direction is not None
        assert commands.autopilot_direction.vector == (10.0, 90.0, 0.0)
        assert commands.autopilot_direction.reference_frame is ReferenceFrame.BODY_NON_ROTATING

    def test_orientation_set_even_before_burn_window(self) -> None:
        """During the cold phase the autopilot direction must still be commanded."""
        # Node far in the future relative to current universal_time.
        node = _make_node(ut=10_000.0, burn_vector_remaining=(0.0, 100.0, 0.0))
        commands = VesselCommands()
        execute_node(_make_burning_state(universal_time=0.0), commands, node, None, 0.5, ActionLogger())
        assert commands.autopilot is True
        assert commands.autopilot_direction is not None


class TestExecuteNodeThrottle:
    """Throttle behavior across the cold / burn / done phases."""

    def test_cold_phase_keeps_throttle_zero(self) -> None:
        """When universal_time is well before node.ut, throttle must be 0."""
        node = _make_node(ut=10_000.0, delta_v_remaining=100.0)
        commands = VesselCommands()
        complete = execute_node(_make_burning_state(universal_time=0.0), commands, node, None, 0.5, ActionLogger())
        assert commands.throttle == 0.0
        assert complete is False

    def test_burn_phase_opens_throttle(self) -> None:
        """When universal_time is at the node, the burn window is open."""
        # burn_time_estimate=10s, dt=0.5s; remaining burn >> taper window, so full throttle.
        node = _make_node(ut=500.0, delta_v_remaining=100.0, burn_time_estimate=10.0)
        commands = VesselCommands()
        complete = execute_node(_make_burning_state(universal_time=500.0), commands, node, None, 0.5, ActionLogger())
        assert commands.throttle == 1.0
        assert complete is False

    def test_completion_when_delta_v_below_threshold(self) -> None:
        """When delta_v_remaining is at or below the deadband, helper returns True."""
        node = _make_node(delta_v_remaining=0.05)
        commands = VesselCommands()
        complete = execute_node(_make_burning_state(universal_time=500.0), commands, node, None, 0.5, ActionLogger())
        assert complete is True
        assert commands.throttle == 0.0

    def test_completion_when_burn_vector_flips_retrograde(self) -> None:
        """When burn_vector_remaining flips retrograde of the planned burn_vector, stop.

        Regression for the circularize-loop bug: at end of burn the remaining
        vector becomes tiny and noise-dominated; if it points opposite to the
        original planned direction we have overshot and any further burn
        deposits dv in the wrong direction. dv_remaining alone never reaches
        the 0.1 m/s threshold because the magnitude grows back as the burn
        oscillates.
        """
        # Original plan: +100 m/s along +y. Live remaining vector points -y
        # with a small magnitude. dot = -2.0 < 0 -> overshoot.
        node = _make_node(
            ut=500.0,
            delta_v_remaining=2.0,
            burn_vector_remaining=(0.0, -2.0, 0.0),
            burn_time_estimate=0.1,
        )
        commands = VesselCommands()
        complete = execute_node(_make_burning_state(universal_time=500.0), commands, node, None, 0.5, ActionLogger())
        assert complete is True
        assert commands.throttle == 0.0

    def test_no_overshoot_when_remaining_still_prograde(self) -> None:
        """A small but still-prograde remaining vector keeps burning."""
        # Same magnitude as the overshoot test but still pointing along +y.
        node = _make_node(
            ut=500.0,
            delta_v_remaining=2.0,
            burn_vector_remaining=(0.0, 2.0, 0.0),
            burn_time_estimate=0.1,
        )
        commands = VesselCommands()
        complete = execute_node(_make_burning_state(universal_time=500.0), commands, node, None, 0.5, ActionLogger())
        assert complete is False
        assert commands.throttle is not None
        assert commands.throttle > 0.0

    def test_burn_start_is_centered_on_node_ut(self) -> None:
        """burn_start_ut = node.ut - burn_time_estimate/2; well before that is still cold."""
        # burn_time_estimate is 20s, so burn_start = ut - 10. At ut=500, burn starts at 490.
        node = _make_node(ut=500.0, delta_v_remaining=100.0, burn_time_estimate=20.0)
        state = _make_burning_state(universal_time=480.0)
        assert state.universal_time < 500.0 - 20.0 / 2.0  # 480 < 490, cold

        commands = VesselCommands()
        execute_node(state, commands, node, None, 0.5, ActionLogger())
        assert commands.throttle == 0.0

    def test_throttle_tapers_near_completion(self) -> None:
        """When burn_time_estimate < dt * _TAPER_MARGIN, throttle ramps down.

        With dt=0.5s and _TAPER_MARGIN=3, the taper window is 1.5s of burn.
        burn_time_estimate=0.6s -> throttle = 0.6 / (0.5 * 3) = 0.4.
        """
        node = _make_node(ut=500.0, delta_v_remaining=8.0, burn_time_estimate=0.6)
        commands = VesselCommands()
        complete = execute_node(_make_burning_state(universal_time=500.0), commands, node, None, 0.5, ActionLogger())
        assert complete is False
        assert commands.throttle == pytest.approx(0.4)

    def test_throttle_clamps_at_one_when_burn_long(self) -> None:
        """When burn_time_estimate >> dt * margin, the formula clamps to 1.0."""
        node = _make_node(ut=500.0, delta_v_remaining=100.0, burn_time_estimate=30.0)
        commands = VesselCommands()
        execute_node(_make_burning_state(universal_time=500.0), commands, node, None, 0.5, ActionLogger())
        assert commands.throttle == 1.0


class TestExecuteNodeEdgeCases:
    """Defensive behavior when burn-time inputs are degenerate."""

    def test_infinite_burn_time_estimate_stays_cold(self) -> None:
        """If the bridge could not compute burn_time (no thrust, no Isp), stay cold."""
        node = _make_node(ut=500.0, delta_v_remaining=100.0, burn_time_estimate=float("inf"))
        state = _make_burning_state(universal_time=500.0, thrust_available=0.0)
        commands = VesselCommands()
        complete = execute_node(state, commands, node, None, 0.5, ActionLogger())
        assert commands.throttle == 0.0
        assert complete is False


class TestExecuteNodeStaging:
    """``staging_mode`` is delegated to ``auto_stage`` before throttle decisions."""

    def test_none_mode_does_not_stage(self) -> None:
        """Mode None short-circuits even when a stage swap would help."""
        node = _make_node(ut=500.0, delta_v_remaining=100.0)
        state = _make_burning_state(universal_time=500.0, engine_states=("flameout", "inactive"))
        commands = VesselCommands()
        execute_node(state, commands, node, None, 0.5, ActionLogger())
        assert commands.stage is None

    def test_any_flameout_stages_mid_burn(self) -> None:
        """ANY_FLAMEOUT drops a spent corner booster while other engines still thrust."""
        node = _make_node(ut=500.0, delta_v_remaining=100.0, burn_time_estimate=10.0)
        state = _make_burning_state(
            universal_time=500.0,
            thrust_available=80_000.0,
            engine_states=("active", "flameout"),
        )
        commands = VesselCommands()
        execute_node(state, commands, node, StagingMode.ANY_FLAMEOUT, 0.5, ActionLogger())
        assert commands.stage is True
        # Throttle is still commanded after staging so the next tick keeps burning.
        assert commands.throttle == 1.0

    def test_full_depletion_stages_when_thrust_is_zero(self) -> None:
        """FULL_DEPLETION fires when no thrust remains and an inactive engine waits."""
        node = _make_node(ut=500.0, delta_v_remaining=100.0, burn_time_estimate=float("inf"))
        state = _make_burning_state(
            universal_time=500.0,
            thrust_available=0.0,
            engine_states=("flameout", "inactive"),
        )
        commands = VesselCommands()
        execute_node(state, commands, node, StagingMode.FULL_DEPLETION, 0.5, ActionLogger())
        assert commands.stage is True

    def test_full_depletion_does_not_stage_on_partial_flameout(self) -> None:
        """FULL_DEPLETION holds back while any thrust remains."""
        node = _make_node(ut=500.0, delta_v_remaining=100.0)
        state = _make_burning_state(
            universal_time=500.0,
            thrust_available=80_000.0,
            engine_states=("active", "flameout"),
        )
        commands = VesselCommands()
        execute_node(state, commands, node, StagingMode.FULL_DEPLETION, 0.5, ActionLogger())
        assert commands.stage is None


class TestTsiolkovsky:
    """Direct tests for the Tsiolkovsky helper used by the bridge."""

    def test_returns_inf_for_zero_thrust(self) -> None:
        from ksp_mission_control.control.actions.helpers.maneuver_node import tsiolkovsky_burn_time

        assert tsiolkovsky_burn_time(delta_v=100.0, mass=5000.0, isp=300.0, thrust=0.0) == float("inf")

    def test_returns_inf_for_zero_isp(self) -> None:
        from ksp_mission_control.control.actions.helpers.maneuver_node import tsiolkovsky_burn_time

        assert tsiolkovsky_burn_time(delta_v=100.0, mass=5000.0, isp=0.0, thrust=50_000.0) == float("inf")

    def test_returns_finite_burn_time_for_normal_inputs(self) -> None:
        from ksp_mission_control.control.actions.helpers.maneuver_node import tsiolkovsky_burn_time

        burn_time = tsiolkovsky_burn_time(delta_v=100.0, mass=5000.0, isp=300.0, thrust=50_000.0)
        # exhaust = 300 * 9.80665 = 2941.995; m1 = 5000/exp(100/2941.995) ~= 4833;
        # flow = 50000/2941.995 ~= 16.99; burn ~= (5000-4833)/16.99 ~= 9.8s
        assert 9.0 < burn_time < 11.0


class TestExecuteNodeWarpStepDown:
    """When the burn window approaches, the helper steps warp down one
    rails-warp level per tick instead of jumping straight to 1x. This
    avoids the "drop early, idle for minutes at 1x" failure mode at high
    warp rates, where one tick at the original rate spans hundreds of
    game seconds.

    Threshold: drop one level when ``dt * rate * 2.0 + 5.0`` game seconds
    away from ``burn_start_ut`` (which is ``node.ut - burn_time / 2``).
    """

    def test_steps_down_one_level_from_low_rate(self) -> None:
        # dt=0.5s, rate=10x => tick_game_time=5; threshold = 5*2 + 5 = 15s.
        # burn_start_ut = 500 - 5 = 495; universal_time = 487 => 8s away,
        # inside the 15s threshold so the helper steps 10x -> 5x.
        node = _make_node(ut=500.0, delta_v_remaining=100.0, burn_time_estimate=10.0)
        state = _make_burning_state(universal_time=487.0, time_warp_rate=10.0)
        commands = VesselCommands()
        execute_node(state, commands, node, None, 0.5, ActionLogger())
        assert commands.time_warp_rate == 5.0

    def test_steps_down_one_level_from_high_rate(self) -> None:
        # dt=0.5s, rate=1000x => tick_game_time=500; threshold = 500*2 + 5 = 1005s.
        # burn_start_ut = 2000 - 5 = 1995; universal_time = 1000 => 995s away,
        # inside the 1005s threshold so the helper steps 1000x -> 100x.
        # At 1x or 5x the same situation would not trigger a drop, which
        # is what makes the per-tick scaling correct: high warp needs more
        # lead time precisely because each tick advances more game time.
        node = _make_node(ut=2000.0, delta_v_remaining=100.0, burn_time_estimate=10.0)
        state = _make_burning_state(universal_time=1000.0, time_warp_rate=1000.0)
        commands = VesselCommands()
        execute_node(state, commands, node, None, 0.5, ActionLogger())
        assert commands.time_warp_rate == 100.0

    def test_final_step_lands_on_one_x(self) -> None:
        # dt=0.5s, rate=5x => tick_game_time=2.5; threshold = 2.5*2 + 5 = 10s.
        # burn_start_ut = 500 - 5 = 495; universal_time = 490 => 5s away,
        # inside the 10s threshold. Next level below 5x is 1x.
        node = _make_node(ut=500.0, delta_v_remaining=100.0, burn_time_estimate=10.0)
        state = _make_burning_state(universal_time=490.0, time_warp_rate=5.0)
        commands = VesselCommands()
        execute_node(state, commands, node, None, 0.5, ActionLogger())
        assert commands.time_warp_rate == 1.0

    def test_does_not_drop_when_burn_is_far_away(self) -> None:
        # dt=0.5s, rate=10x => threshold = 15s. burn_start_ut = 5_000 - 5 = 4_995.
        # universal_time 100 => 4_895s away, well outside the threshold.
        node = _make_node(ut=5_000.0, delta_v_remaining=100.0, burn_time_estimate=10.0)
        state = _make_burning_state(universal_time=100.0, time_warp_rate=10.0)
        commands = VesselCommands()
        execute_node(state, commands, node, None, 0.5, ActionLogger())
        assert commands.time_warp_rate is None

    def test_threshold_scales_with_warp_rate(self) -> None:
        # At 200s away from burn_start_ut, 1000x should drop (threshold 1005s)
        # but 100x should not (threshold 105s). The progressive step-down
        # keeps each rate's threshold scaled to one tick at that rate.
        node = _make_node(ut=210.0, delta_v_remaining=100.0, burn_time_estimate=10.0)
        # burn_start_ut = 210 - 5 = 205. universal_time = 5 => 200s away.
        high_warp = _make_burning_state(universal_time=5.0, time_warp_rate=1000.0)
        low_warp = _make_burning_state(universal_time=5.0, time_warp_rate=100.0)

        high_commands = VesselCommands()
        execute_node(high_warp, high_commands, node, None, 0.5, ActionLogger())
        assert high_commands.time_warp_rate == 100.0

        low_commands = VesselCommands()
        execute_node(low_warp, low_commands, node, None, 0.5, ActionLogger())
        assert low_commands.time_warp_rate is None

    def test_no_op_when_already_at_real_time(self) -> None:
        # Even near the burn, the helper must not send a redundant warp=1x
        # command when warp is already 1x.
        node = _make_node(ut=500.0, delta_v_remaining=100.0, burn_time_estimate=10.0)
        state = _make_burning_state(universal_time=470.0, time_warp_rate=1.0)
        commands = VesselCommands()
        execute_node(state, commands, node, None, 0.5, ActionLogger())
        assert commands.time_warp_rate is None


class TestExecuteNodeWarpRestore:
    """When the burn completes, the helper restores the caller's pre-action warp."""

    def test_restores_warp_on_burn_complete(self) -> None:
        # delta_v_remaining below threshold -> burn-complete return path.
        node = _make_node(ut=500.0, delta_v_remaining=0.0, burn_time_estimate=10.0)
        state = _make_burning_state(universal_time=500.0, time_warp_rate=1.0)
        commands = VesselCommands()
        complete = execute_node(state, commands, node, None, 0.5, ActionLogger(), restore_warp_rate=100.0)
        assert complete is True
        assert commands.time_warp_rate == 100.0

    def test_restores_warp_on_overshoot_return(self) -> None:
        # burn_vector_remaining anti-parallel to burn_vector (helper default
        # burn_vector is (0, delta_v, 0), so a negative-y remaining vector
        # produces a non-positive dot product and trips the overshoot path).
        node = _make_node(
            ut=500.0,
            delta_v_remaining=2.0,
            burn_vector_remaining=(0.0, -2.0, 0.0),
        )
        state = _make_burning_state(universal_time=500.0, time_warp_rate=1.0)
        commands = VesselCommands()
        complete = execute_node(state, commands, node, None, 0.5, ActionLogger(), restore_warp_rate=50.0)
        assert complete is True
        assert commands.time_warp_rate == 50.0

    def test_does_not_restore_when_restore_rate_is_one(self) -> None:
        # Default restore_warp_rate=1.0 (caller did not pass anything).
        node = _make_node(ut=500.0, delta_v_remaining=0.0, burn_time_estimate=10.0)
        state = _make_burning_state(universal_time=500.0, time_warp_rate=1.0)
        commands = VesselCommands()
        execute_node(state, commands, node, None, 0.5, ActionLogger())
        assert commands.time_warp_rate is None

    def test_does_not_restore_while_still_burning(self) -> None:
        # delta_v_remaining > threshold and warp already at 1x: no restore command yet.
        node = _make_node(ut=500.0, delta_v_remaining=50.0, burn_time_estimate=5.0)
        state = _make_burning_state(universal_time=500.0, time_warp_rate=1.0)
        commands = VesselCommands()
        complete = execute_node(state, commands, node, None, 0.5, ActionLogger(), restore_warp_rate=100.0)
        assert complete is False
        # Mid-burn, restore must not fire; only the burn-complete return paths restore.
        assert commands.time_warp_rate is None
