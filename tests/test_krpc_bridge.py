"""Tests for the kRPC bridge: apply_controls, read_vessel_state, filter_commands."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ksp_mission_control.control.actions.base import (
    AutopilotConfig,
    AutopilotDirection,
    ReferenceFrame,
    VesselCommands,
    VesselState,
)
from ksp_mission_control.control.krpc_bridge import (
    NoActiveVesselError,
    apply_controls,
    filter_commands,
    read_vessel_state,
)

# ---------------------------------------------------------------------------
# Mock kRPC connection
# ---------------------------------------------------------------------------


def _make_mock_part(stage: int) -> SimpleNamespace:
    return SimpleNamespace(stage=stage)


def _make_mock_conn(
    *,
    active_vessel: bool = True,
    sas_mode: str = "SASMode.stability_assist",
    speed_mode: str = "SpeedMode.orbit",
    situation: str = "VesselSituation.flying",
) -> SimpleNamespace:
    """Build a mock kRPC connection with nested attribute access.

    All numeric fields default to 0.0, booleans to False, strings to "".
    """
    control = SimpleNamespace(
        throttle=0.0,
        sas=False,
        sas_mode=sas_mode,
        rcs=False,
        gear=False,
        legs=False,
        lights=False,
        brakes=False,
        abort=False,
        current_stage=0,
        solar_panels=False,
        antennas=False,
        cargo_bays=False,
        intakes=False,
        parachutes=False,
        radiators=False,
        # Writable axis properties (apply_controls writes to these)
        pitch=0.0,
        yaw=0.0,
        roll=0.0,
        forward=0.0,
        right=0.0,
        up=0.0,
        wheels=False,
    )

    body_ref_frame = SimpleNamespace()
    body_non_rotating_ref_frame = SimpleNamespace()
    body = SimpleNamespace(
        name="Kerbin",
        equatorial_radius=600000.0,
        surface_gravity=9.81,
        has_atmosphere=True,
        atmosphere_depth=70000.0,
        reference_frame=body_ref_frame,
        non_rotating_reference_frame=body_non_rotating_ref_frame,
    )

    orbit = SimpleNamespace(
        speed=2200.0,
        apoapsis_altitude=80000.0,
        periapsis_altitude=70000.0,
        inclination=0.5,
        eccentricity=0.007,
        period=2400.0,
        time_to_apoapsis=300.0,
        time_to_periapsis=900.0,
        body=body,
    )

    flight = SimpleNamespace(
        mean_altitude=75000.0,
        surface_altitude=74800.0,
        vertical_speed=1.5,
        speed=2180.0,
        dynamic_pressure=5000.0,
        static_pressure=10000.0,
        drag=(100.0, 100.0, 100.0),
        lift=(25.0, 25.0, 25.0),
        g_force=1.2,
        latitude=-0.1,
        longitude=74.5,
        pitch=45.0,
        heading=90.0,
        roll=0.0,
    )

    auto_pilot = SimpleNamespace(
        error=2.5,
        pitch_error=1.0,
        heading_error=-1.5,
        roll_error=0.3,
        target_pitch=0.0,
        target_heading=0.0,
        target_roll=0.0,
        target_direction=(0.0, 0.0, 0.0),
        reference_frame=None,
        auto_tune=True,
        time_to_peak=(3.0, 3.0, 3.0),
        overshoot=(0.01, 0.01, 0.01),
        stopping_time=(0.5, 0.5, 0.5),
        deceleration_time=(5.0, 5.0, 5.0),
        attenuation_angle=(1.0, 1.0, 1.0),
        roll_threshold=5.0,
        pitch_pid_gains=(0.0, 0.0, 0.0),
        yaw_pid_gains=(0.0, 0.0, 0.0),
        roll_pid_gains=(0.0, 0.0, 0.0),
        _engaged=False,
    )

    def engage() -> None:
        auto_pilot._engaged = True

    def disengage() -> None:
        auto_pilot._engaged = False

    auto_pilot.engage = engage
    auto_pilot.disengage = disengage

    vessel_surface_ref = SimpleNamespace()
    vessel_orbital_ref = SimpleNamespace()
    vessel_ref = SimpleNamespace()

    mock_engines = [
        SimpleNamespace(active=True, has_fuel=True),
        SimpleNamespace(active=True, has_fuel=False),
        SimpleNamespace(active=False, has_fuel=True),
    ]
    parts = SimpleNamespace(
        all=[_make_mock_part(0), _make_mock_part(1), _make_mock_part(2)],
        engines=mock_engines,
    )

    resources = SimpleNamespace(
        amount=lambda name: {
            "ElectricCharge": 150.0,
            "LiquidFuel": 400.0,
            "Oxidizer": 480.0,
            "MonoPropellant": 50.0,
        }.get(name, 0.0),
    )

    vessel: SimpleNamespace | None = None
    if active_vessel:
        vessel = SimpleNamespace(
            control=control,
            orbit=orbit,
            auto_pilot=auto_pilot,
            met=120.0,
            name="Test Vessel",
            situation=situation,
            mass=5000.0,
            dry_mass=2000.0,
            available_thrust=50000.0,
            max_thrust=60000.0,
            specific_impulse=320.0,
            surface_reference_frame=vessel_surface_ref,
            orbital_reference_frame=vessel_orbital_ref,
            reference_frame=vessel_ref,
            parts=parts,
            resources=resources,
            flight=lambda ref: flight,
        )

    _stages_called: list[bool] = []

    def activate_next_stage() -> None:
        _stages_called.append(True)

    if vessel is not None:
        vessel.control.activate_next_stage = activate_next_stage
        vessel._stages_called = _stages_called

    navball = SimpleNamespace(speed_mode=speed_mode)

    # kRPC enums as attributes on space_center
    sas_modes = SimpleNamespace(
        stability_assist="sas_stability_assist",
        radial="sas_radial",
        prograde="sas_prograde",
    )
    speed_modes = SimpleNamespace(
        orbit="speed_orbit",
        surface="speed_surface",
    )

    space_center = SimpleNamespace(
        active_vessel=vessel,
        navball=navball,
        SASMode=sas_modes,
        SpeedMode=speed_modes,
    )

    return SimpleNamespace(space_center=space_center)


# ---------------------------------------------------------------------------
# read_vessel_state tests
# ---------------------------------------------------------------------------


class TestReadVesselState:
    """Tests for read_vessel_state()."""

    def test_reads_autopilot_error_fields(self) -> None:
        conn = _make_mock_conn()
        state = read_vessel_state(conn)
        assert state.autopilot_error == 2.5
        assert state.autopilot_pitch_error == 1.0
        assert state.autopilot_heading_error == -1.5
        assert state.autopilot_roll_error == 0.3

    def test_autopilot_errors_default_when_not_engaged(self) -> None:
        """Autopilot error properties raise when not engaged; bridge returns 0."""
        conn = _make_mock_conn()
        ap = conn.space_center.active_vessel.auto_pilot

        class _NotEngagedError(Exception):
            pass

        # Replace error properties with descriptors that raise
        error_prop = property(lambda self: (_ for _ in ()).throw(_NotEngagedError))
        patched_type = type(
            "PatchedAP",
            (),
            {
                **{k: v for k, v in vars(ap).items()},
                "error": error_prop,
                "pitch_error": error_prop,
                "heading_error": error_prop,
                "roll_error": error_prop,
            },
        )
        patched_ap = patched_type()
        conn.space_center.active_vessel.auto_pilot = patched_ap

        state = read_vessel_state(conn)
        assert state.autopilot_error == 0.0
        assert state.autopilot_pitch_error == 0.0
        assert state.autopilot_heading_error == 0.0
        assert state.autopilot_roll_error == 0.0

    def test_reads_orientation_fields(self) -> None:
        conn = _make_mock_conn()
        state = read_vessel_state(conn)
        assert state.pitch == 45.0
        assert state.heading == 90.0
        assert state.roll == 0.0

    def test_reads_atmospheric_data(self) -> None:
        conn = _make_mock_conn()
        state = read_vessel_state(conn)
        assert state.dynamic_pressure == 5000.0
        assert state.static_pressure == 10000.0
        assert state.drag == (100.0, 100.0, 100.0)
        assert state.lift == (25.0, 25.0, 25.0)
        assert state.g_force == 1.2

    def test_reads_orbital_timing(self) -> None:
        conn = _make_mock_conn()
        state = read_vessel_state(conn)
        assert state.time_to_apoapsis == 300.0
        assert state.time_to_periapsis == 900.0

    def test_reads_vessel_mass_and_thrust(self) -> None:
        conn = _make_mock_conn()
        state = read_vessel_state(conn)
        assert state.mass == 5000.0
        assert state.dry_mass == 2000.0
        assert state.available_thrust == 50000.0
        assert state.max_thrust == 60000.0
        assert state.specific_impulse == 320.0

    def test_reads_body_properties(self) -> None:
        conn = _make_mock_conn()
        state = read_vessel_state(conn)
        assert state.body_radius == 600000.0
        assert state.surface_gravity == 9.81
        assert state.body == "Kerbin"
        assert state.body_has_atmosphere is True
        assert state.body_atmosphere_depth == 70000.0

    def test_reads_body_without_atmosphere(self) -> None:
        conn = _make_mock_conn()
        conn.space_center.active_vessel.orbit.body.has_atmosphere = False
        state = read_vessel_state(conn)
        assert state.body_has_atmosphere is False
        assert state.body_atmosphere_depth == 0.0

    def test_no_active_vessel_raises(self) -> None:
        conn = _make_mock_conn(active_vessel=False)
        with pytest.raises(NoActiveVesselError):
            read_vessel_state(conn)


# ---------------------------------------------------------------------------
# apply_controls tests: autopilot/SAS mutual exclusivity
# ---------------------------------------------------------------------------


class TestApplyControlsAutopilotSAS:
    """Tests for autopilot/SAS mutual exclusivity in apply_controls()."""

    def test_engaging_autopilot_disables_sas(self) -> None:
        conn = _make_mock_conn()
        conn.space_center.active_vessel.control.sas = True
        commands = VesselCommands(autopilot=True)
        apply_controls(conn, commands)
        assert conn.space_center.active_vessel.control.sas is False
        assert conn.space_center.active_vessel.auto_pilot._engaged is True

    def test_enabling_sas_disengages_autopilot(self) -> None:
        conn = _make_mock_conn()
        conn.space_center.active_vessel.auto_pilot._engaged = True
        commands = VesselCommands(sas=True)
        apply_controls(conn, commands)
        assert conn.space_center.active_vessel.auto_pilot._engaged is False
        assert conn.space_center.active_vessel.control.sas is True

    def test_disabling_sas_does_not_touch_autopilot(self) -> None:
        conn = _make_mock_conn()
        conn.space_center.active_vessel.auto_pilot._engaged = True
        commands = VesselCommands(sas=False)
        apply_controls(conn, commands)
        assert conn.space_center.active_vessel.auto_pilot._engaged is True
        assert conn.space_center.active_vessel.control.sas is False

    def test_disengaging_autopilot(self) -> None:
        conn = _make_mock_conn()
        conn.space_center.active_vessel.auto_pilot._engaged = True
        commands = VesselCommands(autopilot=False)
        apply_controls(conn, commands)
        assert conn.space_center.active_vessel.auto_pilot._engaged is False

    def test_no_autopilot_or_sas_commands_leaves_both_unchanged(self) -> None:
        conn = _make_mock_conn()
        conn.space_center.active_vessel.auto_pilot._engaged = True
        conn.space_center.active_vessel.control.sas = True
        commands = VesselCommands(throttle=0.5)
        apply_controls(conn, commands)
        assert conn.space_center.active_vessel.auto_pilot._engaged is True
        assert conn.space_center.active_vessel.control.sas is True


# ---------------------------------------------------------------------------
# apply_controls tests: autopilot targeting
# ---------------------------------------------------------------------------


class TestApplyControlsAutopilotTargeting:
    """Tests for autopilot pitch/heading/roll/direction in apply_controls()."""

    def test_sets_autopilot_pitch(self) -> None:
        conn = _make_mock_conn()
        commands = VesselCommands(autopilot_pitch=45.0)
        apply_controls(conn, commands)
        assert conn.space_center.active_vessel.auto_pilot.target_pitch == 45.0

    def test_sets_autopilot_heading(self) -> None:
        conn = _make_mock_conn()
        commands = VesselCommands(autopilot_heading=270.0)
        apply_controls(conn, commands)
        assert conn.space_center.active_vessel.auto_pilot.target_heading == 270.0

    def test_sets_autopilot_roll(self) -> None:
        conn = _make_mock_conn()
        commands = VesselCommands(autopilot_roll=30.0)
        apply_controls(conn, commands)
        assert conn.space_center.active_vessel.auto_pilot.target_roll == 30.0

    def test_none_fields_leave_targets_unchanged(self) -> None:
        conn = _make_mock_conn()
        ap = conn.space_center.active_vessel.auto_pilot
        ap.target_pitch = 10.0
        ap.target_heading = 20.0
        ap.target_roll = 30.0
        commands = VesselCommands()  # all None
        apply_controls(conn, commands)
        assert ap.target_pitch == 10.0
        assert ap.target_heading == 20.0
        assert ap.target_roll == 30.0


class TestApplyControlsAutopilotDirection:
    """Tests for autopilot direction vector targeting in apply_controls()."""

    def test_sets_direction_with_vessel_surface_frame(self) -> None:
        conn = _make_mock_conn()
        vessel = conn.space_center.active_vessel
        commands = VesselCommands(
            autopilot_direction=AutopilotDirection(
                vector=(0.0, 1.0, 0.0),
                reference_frame=ReferenceFrame.VESSEL_SURFACE,
            )
        )
        apply_controls(conn, commands)
        assert vessel.auto_pilot.target_direction == (0.0, 1.0, 0.0)
        assert vessel.auto_pilot.reference_frame is vessel.surface_reference_frame

    def test_sets_direction_with_vessel_orbital_frame(self) -> None:
        conn = _make_mock_conn()
        vessel = conn.space_center.active_vessel
        commands = VesselCommands(
            autopilot_direction=AutopilotDirection(
                vector=(1.0, 0.0, 0.0),
                reference_frame=ReferenceFrame.VESSEL_ORBITAL,
            )
        )
        apply_controls(conn, commands)
        assert vessel.auto_pilot.reference_frame is vessel.orbital_reference_frame

    def test_sets_direction_with_vessel_frame(self) -> None:
        conn = _make_mock_conn()
        vessel = conn.space_center.active_vessel
        commands = VesselCommands(
            autopilot_direction=AutopilotDirection(
                vector=(0.0, 0.0, 1.0),
                reference_frame=ReferenceFrame.VESSEL,
            )
        )
        apply_controls(conn, commands)
        assert vessel.auto_pilot.reference_frame is vessel.reference_frame

    def test_sets_direction_with_body_frame(self) -> None:
        conn = _make_mock_conn()
        vessel = conn.space_center.active_vessel
        commands = VesselCommands(
            autopilot_direction=AutopilotDirection(
                vector=(1.0, 0.0, 0.0),
                reference_frame=ReferenceFrame.BODY,
            )
        )
        apply_controls(conn, commands)
        assert vessel.auto_pilot.reference_frame is vessel.orbit.body.reference_frame

    def test_sets_direction_with_body_non_rotating_frame(self) -> None:
        conn = _make_mock_conn()
        vessel = conn.space_center.active_vessel
        commands = VesselCommands(
            autopilot_direction=AutopilotDirection(
                vector=(0.0, 1.0, 0.0),
                reference_frame=ReferenceFrame.BODY_NON_ROTATING,
            )
        )
        apply_controls(conn, commands)
        assert vessel.auto_pilot.reference_frame is vessel.orbit.body.non_rotating_reference_frame

    def test_none_direction_leaves_frame_unchanged(self) -> None:
        conn = _make_mock_conn()
        ap = conn.space_center.active_vessel.auto_pilot
        original_frame = ap.reference_frame
        commands = VesselCommands()  # direction is None
        apply_controls(conn, commands)
        assert ap.reference_frame is original_frame


# ---------------------------------------------------------------------------
# apply_controls tests: autopilot config
# ---------------------------------------------------------------------------


class TestApplyControlsAutopilotConfig:
    """Tests for autopilot PID configuration in apply_controls()."""

    def test_auto_config_resets_to_defaults(self) -> None:
        conn = _make_mock_conn()
        ap = conn.space_center.active_vessel.auto_pilot
        # Simulate prior manual settings
        ap.auto_tune = False
        ap.time_to_peak = (1.0, 1.0, 1.0)
        commands = VesselCommands(autopilot_config=AutopilotConfig.AUTO)
        apply_controls(conn, commands)
        assert ap.auto_tune is True
        assert ap.time_to_peak == (3.0, 3.0, 3.0)
        assert ap.overshoot == (0.01, 0.01, 0.01)
        assert ap.stopping_time == (0.5, 0.5, 0.5)
        assert ap.deceleration_time == (5.0, 5.0, 5.0)
        assert ap.attenuation_angle == (1.0, 1.0, 1.0)
        assert ap.roll_threshold == 5.0

    def test_custom_auto_tune_targets(self) -> None:
        conn = _make_mock_conn()
        ap = conn.space_center.active_vessel.auto_pilot
        commands = VesselCommands(
            autopilot_config=AutopilotConfig(
                time_to_peak=(1.0, 1.0, 1.0),
                overshoot=(0.05, 0.05, 0.05),
            )
        )
        apply_controls(conn, commands)
        assert ap.auto_tune is True
        assert ap.time_to_peak == (1.0, 1.0, 1.0)
        assert ap.overshoot == (0.05, 0.05, 0.05)

    def test_manual_pid_gains(self) -> None:
        conn = _make_mock_conn()
        ap = conn.space_center.active_vessel.auto_pilot
        commands = VesselCommands(
            autopilot_config=AutopilotConfig(
                auto_tune=False,
                pitch_pid_gains=(2.0, 0.0, 0.5),
                yaw_pid_gains=(2.0, 0.0, 0.5),
                roll_pid_gains=(1.0, 0.0, 0.3),
            )
        )
        apply_controls(conn, commands)
        assert ap.auto_tune is False
        assert ap.pitch_pid_gains == (2.0, 0.0, 0.5)
        assert ap.yaw_pid_gains == (2.0, 0.0, 0.5)
        assert ap.roll_pid_gains == (1.0, 0.0, 0.3)

    def test_none_pid_gains_leaves_existing(self) -> None:
        """When pid_gains fields are None, they should not overwrite existing values."""
        conn = _make_mock_conn()
        ap = conn.space_center.active_vessel.auto_pilot
        ap.pitch_pid_gains = (5.0, 5.0, 5.0)
        commands = VesselCommands(autopilot_config=AutopilotConfig(auto_tune=False))
        apply_controls(conn, commands)
        # pitch_pid_gains was None in config, so existing value preserved
        assert ap.pitch_pid_gains == (5.0, 5.0, 5.0)

    def test_none_config_leaves_all_unchanged(self) -> None:
        conn = _make_mock_conn()
        ap = conn.space_center.active_vessel.auto_pilot
        ap.auto_tune = False
        ap.time_to_peak = (9.0, 9.0, 9.0)
        commands = VesselCommands()  # config is None
        apply_controls(conn, commands)
        assert ap.auto_tune is False
        assert ap.time_to_peak == (9.0, 9.0, 9.0)

    def test_stopping_time_and_deceleration_time(self) -> None:
        conn = _make_mock_conn()
        ap = conn.space_center.active_vessel.auto_pilot
        commands = VesselCommands(
            autopilot_config=AutopilotConfig(
                stopping_time=(0.2, 0.2, 0.2),
                deceleration_time=(2.0, 2.0, 2.0),
            )
        )
        apply_controls(conn, commands)
        assert ap.stopping_time == (0.2, 0.2, 0.2)
        assert ap.deceleration_time == (2.0, 2.0, 2.0)


# ---------------------------------------------------------------------------
# apply_controls tests: no active vessel
# ---------------------------------------------------------------------------


class TestApplyControlsNoVessel:
    """Tests for apply_controls when no vessel is active."""

    def test_raises_no_active_vessel_error(self) -> None:
        conn = _make_mock_conn(active_vessel=False)
        with pytest.raises(NoActiveVesselError):
            apply_controls(conn, VesselCommands(throttle=0.5))


# ---------------------------------------------------------------------------
# filter_commands tests
# ---------------------------------------------------------------------------


class TestFilterCommands:
    """Tests for filter_commands() comparing commands against vessel state."""

    def test_filters_redundant_sas(self) -> None:
        """SAS already True in state should be filtered out."""
        commands = VesselCommands(sas=True)
        state = VesselState(sas=True)
        filtered, applied = filter_commands(commands, state)
        assert filtered.sas is None
        assert "sas" not in applied

    def test_passes_changed_throttle(self) -> None:
        commands = VesselCommands(throttle=0.8)
        state = VesselState(throttle=0.0)
        filtered, applied = filter_commands(commands, state)
        assert filtered.throttle == 0.8
        assert "throttle" in applied

    def test_autopilot_pitch_always_applied(self) -> None:
        """autopilot_pitch is not in _COMPARABLE_FIELDS, so always passes through."""
        commands = VesselCommands(autopilot_pitch=45.0)
        state = VesselState(pitch=45.0)  # Same angle, but not comparable
        filtered, applied = filter_commands(commands, state)
        assert filtered.autopilot_pitch == 45.0
        assert "autopilot_pitch" in applied

    def test_autopilot_heading_always_applied(self) -> None:
        commands = VesselCommands(autopilot_heading=90.0)
        state = VesselState(heading=90.0)
        filtered, applied = filter_commands(commands, state)
        assert filtered.autopilot_heading == 90.0
        assert "autopilot_heading" in applied

    def test_autopilot_roll_always_applied(self) -> None:
        commands = VesselCommands(autopilot_roll=10.0)
        state = VesselState()
        filtered, applied = filter_commands(commands, state)
        assert filtered.autopilot_roll == 10.0
        assert "autopilot_roll" in applied

    def test_autopilot_direction_always_applied(self) -> None:
        direction = AutopilotDirection(vector=(1.0, 0.0, 0.0), reference_frame=ReferenceFrame.VESSEL_ORBITAL)
        commands = VesselCommands(autopilot_direction=direction)
        state = VesselState()
        filtered, applied = filter_commands(commands, state)
        assert filtered.autopilot_direction == direction
        assert "autopilot_direction" in applied

    def test_autopilot_config_always_applied(self) -> None:
        commands = VesselCommands(autopilot_config=AutopilotConfig.AUTO)
        state = VesselState()
        filtered, applied = filter_commands(commands, state)
        assert filtered.autopilot_config == AutopilotConfig.AUTO
        assert "autopilot_config" in applied

    def test_all_none_returns_empty(self) -> None:
        commands = VesselCommands()
        state = VesselState()
        filtered, applied = filter_commands(commands, state)
        assert len(applied) == 0
