"""Tests for the kRPC bridge: apply_controls, read_vessel_state, filter_commands."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ksp_mission_control.control.actions.base import (
    AutopilotConfig,
    AutopilotDirection,
    ReferenceFrame,
    ScienceAction,
    ScienceCommand,
    State,
    VesselCommands,
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
        stage_lock=False,
        reaction_wheels=True,
        wheel_throttle=0.0,
        wheel_steering=0.0,
    )

    body_ref_frame = SimpleNamespace()
    body_non_rotating_ref_frame = SimpleNamespace()
    body = SimpleNamespace(
        name="Kerbin",
        equatorial_radius=600000.0,
        surface_gravity=9.81,
        has_atmosphere=True,
        atmosphere_depth=70000.0,
        gravitational_parameter=3.5316e12,
        sphere_of_influence=84159286.0,
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
        true_anomaly=1.0,
        time_to_soi_change=float("nan"),
        body=body,
    )

    flight = SimpleNamespace(
        mean_altitude=75000.0,
        surface_altitude=74800.0,
        vertical_speed=1.5,
        speed=2180.0,
        horizontal_speed=2179.0,
        dynamic_pressure=5000.0,
        static_pressure=10000.0,
        drag=(100.0, 100.0, 100.0),
        lift=(25.0, 25.0, 25.0),
        mach=6.5,
        angle_of_attack=2.3,
        terminal_velocity=250.0,
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
        auto_pilot.engaged = True

    def disengage() -> None:
        auto_pilot._engaged = False
        auto_pilot.engaged = False

    auto_pilot.engaged = False
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
    mock_experiments = [
        SimpleNamespace(
            name="temperatureScan",
            title="2HOT Thermometer",
            part=SimpleNamespace(title="2HOT Thermometer"),
            available=True,
            has_data=False,
            inoperable=False,
            rerunnable=True,
            deployed=False,
            biome="Shores",
            data=[],
            science_subject=SimpleNamespace(science_cap=8.0),
            _ran=False,
            _reset=False,
            _dumped=False,
            _transmitted=False,
        ),
        SimpleNamespace(
            name="mysteryGoo",
            title="Mystery Goo Observation",
            part=SimpleNamespace(title="Mystery Goo Containment Unit"),
            available=True,
            has_data=True,
            inoperable=False,
            rerunnable=False,
            deployed=False,
            biome="Shores",
            data=[SimpleNamespace(science_value=5.0)],
            science_subject=SimpleNamespace(science_cap=13.0),
            _ran=False,
            _reset=False,
            _dumped=False,
            _transmitted=False,
        ),
    ]
    for exp in mock_experiments:
        exp.run = lambda _exp=exp: setattr(_exp, "_ran", True)
        exp.reset = lambda _exp=exp: setattr(_exp, "_reset", True)
        exp.dump = lambda _exp=exp: setattr(_exp, "_dumped", True)
        exp.transmit = lambda _exp=exp: setattr(_exp, "_transmitted", True)

    mock_parachute_module_stowed = SimpleNamespace(
        name="ModuleParachute",
        fields=["Safe to deploy?", "Min Pressure", "Altitude"],
        events=["Deploy Chute"],
        actions=["Deploy Chute", "Cut Chute"],
        get_field=lambda field_name: {
            "Safe to deploy?": "Safe",
            "Min Pressure": "0.04",
            "Altitude": "1000",
        }[field_name],
    )
    mock_parachute_module_deployed = SimpleNamespace(
        name="ModuleParachute",
        fields=["Safe to deploy?", "Min Pressure", "Altitude"],
        events=["Cut Chute"],
        actions=["Deploy Chute", "Cut Chute"],
        get_field=lambda field_name: {
            "Safe to deploy?": "Safe",
            "Min Pressure": "0.04",
            "Altitude": "1000",
        }[field_name],
    )
    mock_parachutes = [
        SimpleNamespace(
            state="ParachuteState.stowed",
            part=SimpleNamespace(stage=3, decouple_stage=3, modules=[mock_parachute_module_stowed]),
        ),
        SimpleNamespace(
            state="ParachuteState.deployed",
            part=SimpleNamespace(stage=3, decouple_stage=3, modules=[mock_parachute_module_deployed]),
        ),
    ]
    mock_legs = [
        SimpleNamespace(state="LegState.retracted", part=SimpleNamespace(stage=1, decouple_stage=-1)),
        SimpleNamespace(state="LegState.deployed", part=SimpleNamespace(stage=1, decouple_stage=-1)),
    ]
    mock_fairings = [
        SimpleNamespace(jettisoned=False, part=SimpleNamespace(stage=5, decouple_stage=5)),
        SimpleNamespace(jettisoned=True, part=SimpleNamespace(stage=5, decouple_stage=5)),
    ]

    parts = SimpleNamespace(
        all=[_make_mock_part(0), _make_mock_part(1), _make_mock_part(2)],
        engines=mock_engines,
        experiments=mock_experiments,
        parachutes=mock_parachutes,
        legs=mock_legs,
        fairings=mock_fairings,
    )

    resources = SimpleNamespace(
        amount=lambda name: {
            "ElectricCharge": 150.0,
            "LiquidFuel": 400.0,
            "Oxidizer": 480.0,
            "MonoPropellant": 50.0,
        }.get(name, 0.0),
        max=lambda name: {
            "ElectricCharge": 200.0,
            "LiquidFuel": 800.0,
            "Oxidizer": 960.0,
            "MonoPropellant": 100.0,
        }.get(name, 0.0),
    )

    comms = SimpleNamespace(
        can_communicate=True,
        signal_strength=0.85,
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
            thrust=25000.0,
            available_thrust=50000.0,
            max_thrust=60000.0,
            specific_impulse=320.0,
            vacuum_specific_impulse=350.0,
            surface_reference_frame=vessel_surface_ref,
            orbital_reference_frame=vessel_orbital_ref,
            reference_frame=vessel_ref,
            parts=parts,
            resources=resources,
            comms=comms,
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
        ut=1000000.0,
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
        assert state.control_autopilot_error == 2.5
        assert state.control_autopilot_error_pitch == 1.0
        assert state.control_autopilot_error_heading == -1.5
        assert state.control_autopilot_error_roll == 0.3

    def test_autopilot_errors_none_when_not_engaged(self) -> None:
        """Autopilot error properties raise when not engaged; bridge returns None."""
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
        assert state.control_autopilot is False
        assert state.control_autopilot_error is None
        assert state.control_autopilot_error_pitch is None
        assert state.control_autopilot_error_heading is None
        assert state.control_autopilot_error_roll is None

    def test_reads_orientation_fields(self) -> None:
        conn = _make_mock_conn()
        state = read_vessel_state(conn)
        assert state.orientation_pitch == 45.0
        assert state.orientation_heading == 90.0
        assert state.orientation_roll == 0.0

    def test_reads_control_input_fields(self) -> None:
        conn = _make_mock_conn()
        conn.space_center.active_vessel.control.pitch = 0.75
        conn.space_center.active_vessel.control.yaw = -0.5
        conn.space_center.active_vessel.control.roll = 0.3
        state = read_vessel_state(conn)
        assert state.control_input_pitch == 0.75
        assert state.control_input_yaw == -0.5
        assert state.control_input_roll == 0.3

    def test_reads_atmospheric_data(self) -> None:
        conn = _make_mock_conn()
        state = read_vessel_state(conn)
        assert state.pressure_dynamic == 5000.0
        assert state.pressure_static == 10000.0
        assert state.aero_drag == (100.0, 100.0, 100.0)
        assert state.aero_lift == (25.0, 25.0, 25.0)
        assert state.aero_mach == 6.5
        assert state.aero_angle_of_attack == 2.3
        assert state.aero_terminal_velocity == 250.0
        assert state.g_force == 1.2

    def test_reads_orbital_timing_ascending(self) -> None:
        """Ascending toward apoapsis (true_anomaly in 0..pi)."""
        conn = _make_mock_conn()  # true_anomaly=1.0
        state = read_vessel_state(conn)
        assert state.orbit_apoapsis_time_to == 300.0
        assert state.orbit_apoapsis_time_from == 2400.0 - 300.0
        assert state.orbit_apoapsis_passed is False
        assert state.orbit_periapsis_time_to == 900.0
        assert state.orbit_periapsis_time_from == 2400.0 - 900.0
        assert state.orbit_periapsis_passed is True

    def test_reads_orbital_timing_descending_negative_anomaly(self) -> None:
        """Past apoapsis, descending (kRPC negative true_anomaly)."""
        conn = _make_mock_conn()
        conn.space_center.active_vessel.orbit.true_anomaly = -2.0
        state = read_vessel_state(conn)
        assert state.orbit_apoapsis_time_to == 300.0
        assert state.orbit_apoapsis_passed is True
        assert state.orbit_periapsis_time_to == 900.0
        assert state.orbit_periapsis_passed is False

    def test_reads_orbital_timing_descending_large_anomaly(self) -> None:
        """Past apoapsis, descending (true_anomaly > pi)."""
        conn = _make_mock_conn()
        conn.space_center.active_vessel.orbit.true_anomaly = 4.0
        state = read_vessel_state(conn)
        assert state.orbit_apoapsis_time_to == 300.0
        assert state.orbit_apoapsis_passed is True
        assert state.orbit_periapsis_time_to == 900.0
        assert state.orbit_periapsis_passed is False

    def test_reads_speed_horizontal(self) -> None:
        conn = _make_mock_conn()
        state = read_vessel_state(conn)
        assert state.speed_horizontal == 2179.0

    def test_reads_orbital_soi_time(self) -> None:
        conn = _make_mock_conn()
        state = read_vessel_state(conn)
        # Default mock has NaN -> should become inf
        assert state.orbit_soi_time_to_change == float("inf")

    def test_reads_orbital_soi_time_when_available(self) -> None:
        conn = _make_mock_conn()
        conn.space_center.active_vessel.orbit.time_to_soi_change = 5000.0
        state = read_vessel_state(conn)
        assert state.orbit_soi_time_to_change == 5000.0

    def test_reads_universal_time(self) -> None:
        conn = _make_mock_conn()
        state = read_vessel_state(conn)
        assert state.universal_time == 1000000.0

    def test_reads_vessel_mass_and_thrust(self) -> None:
        conn = _make_mock_conn()
        state = read_vessel_state(conn)
        assert state.mass == 5000.0
        assert state.mass_dry == 2000.0
        assert state.thrust == 25000.0
        assert state.thrust_available == 50000.0
        assert state.thrust_peak == 60000.0
        assert state.engine_impulse_specific == 320.0
        assert state.engine_impulse_specific_vacuum == 350.0

    def test_reads_body_properties(self) -> None:
        conn = _make_mock_conn()
        state = read_vessel_state(conn)
        assert state.body_radius == 600000.0
        assert state.body_gravity == 9.81
        assert state.body_name == "Kerbin"
        assert state.body_has_atmosphere is True
        assert state.body_atmosphere_depth == 70000.0
        assert state.body_gm == 3.5316e12
        assert state.body_soi == 84159286.0

    def test_reads_body_without_atmosphere(self) -> None:
        conn = _make_mock_conn()
        conn.space_center.active_vessel.orbit.body.has_atmosphere = False
        state = read_vessel_state(conn)
        assert state.body_has_atmosphere is False
        assert state.body_atmosphere_depth == 0.0

    def test_reads_comms(self) -> None:
        conn = _make_mock_conn()
        state = read_vessel_state(conn)
        assert state.comms_connected is True
        assert state.comms_signal_strength == 0.85

    def test_comms_defaults_when_unavailable(self) -> None:
        conn = _make_mock_conn()
        # Remove comms attribute to simulate unavailable
        del conn.space_center.active_vessel.comms
        state = read_vessel_state(conn)
        assert state.comms_connected is False
        assert state.comms_signal_strength == 0.0

    def test_reads_resource_max_capacities(self) -> None:
        conn = _make_mock_conn()
        state = read_vessel_state(conn)
        assert state.resource_electric_charge_max == 200.0
        assert state.resource_liquid_fuel_max == 800.0
        assert state.resource_oxidizer_max == 960.0
        assert state.resource_mono_propellant_max == 100.0

    def test_reads_new_control_fields(self) -> None:
        conn = _make_mock_conn()
        vc = conn.space_center.active_vessel.control
        vc.stage_lock = True
        vc.reaction_wheels = False
        vc.wheel_throttle = 0.5
        vc.wheel_steering = -0.3
        state = read_vessel_state(conn)
        assert state.control_stage_lock is True
        assert state.control_reaction_wheels is False
        assert state.control_wheel_throttle == 0.5
        assert state.control_wheel_steering == -0.3

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
# apply_controls tests: new Tier 1 commands
# ---------------------------------------------------------------------------


class TestApplyControlsNewCommands:
    """Tests for stage_lock, reaction_wheels, wheel_throttle, wheel_steering."""

    def test_sets_stage_lock(self) -> None:
        conn = _make_mock_conn()
        commands = VesselCommands(stage_lock=True)
        apply_controls(conn, commands)
        assert conn.space_center.active_vessel.control.stage_lock is True

    def test_sets_reaction_wheels(self) -> None:
        conn = _make_mock_conn()
        commands = VesselCommands(reaction_wheels=False)
        apply_controls(conn, commands)
        assert conn.space_center.active_vessel.control.reaction_wheels is False

    def test_sets_wheel_throttle(self) -> None:
        conn = _make_mock_conn()
        commands = VesselCommands(wheel_throttle=0.7)
        apply_controls(conn, commands)
        assert conn.space_center.active_vessel.control.wheel_throttle == 0.7

    def test_sets_wheel_steering(self) -> None:
        conn = _make_mock_conn()
        commands = VesselCommands(wheel_steering=-0.5)
        apply_controls(conn, commands)
        assert conn.space_center.active_vessel.control.wheel_steering == -0.5

    def test_none_leaves_unchanged(self) -> None:
        conn = _make_mock_conn()
        vc = conn.space_center.active_vessel.control
        vc.stage_lock = True
        vc.wheel_throttle = 0.3
        commands = VesselCommands()  # all None
        apply_controls(conn, commands)
        assert vc.stage_lock is True
        assert vc.wheel_throttle == 0.3


# ---------------------------------------------------------------------------
# filter_commands tests
# ---------------------------------------------------------------------------


class TestFilterCommands:
    """Tests for filter_commands() comparing commands against vessel state."""

    def test_filters_redundant_sas(self) -> None:
        """SAS already True in state should be filtered out."""
        commands = VesselCommands(sas=True)
        state = State(control_sas=True)
        filtered, applied = filter_commands(commands, state)
        assert filtered.sas is None
        assert "sas" not in applied

    def test_passes_changed_throttle(self) -> None:
        commands = VesselCommands(throttle=0.8)
        state = State(control_throttle=0.0)
        filtered, applied = filter_commands(commands, state)
        assert filtered.throttle == 0.8
        assert "throttle" in applied

    def test_autopilot_pitch_always_applied(self) -> None:
        """autopilot_pitch is not in _COMPARABLE_FIELDS, so always passes through."""
        commands = VesselCommands(autopilot_pitch=45.0)
        state = State(orientation_pitch=45.0)  # Same angle, but not comparable
        filtered, applied = filter_commands(commands, state)
        assert filtered.autopilot_pitch == 45.0
        assert "autopilot_pitch" in applied

    def test_autopilot_heading_always_applied(self) -> None:
        commands = VesselCommands(autopilot_heading=90.0)
        state = State(orientation_heading=90.0)
        filtered, applied = filter_commands(commands, state)
        assert filtered.autopilot_heading == 90.0
        assert "autopilot_heading" in applied

    def test_autopilot_roll_always_applied(self) -> None:
        commands = VesselCommands(autopilot_roll=10.0)
        state = State()
        filtered, applied = filter_commands(commands, state)
        assert filtered.autopilot_roll == 10.0
        assert "autopilot_roll" in applied

    def test_autopilot_direction_always_applied(self) -> None:
        direction = AutopilotDirection(vector=(1.0, 0.0, 0.0), reference_frame=ReferenceFrame.VESSEL_ORBITAL)
        commands = VesselCommands(autopilot_direction=direction)
        state = State()
        filtered, applied = filter_commands(commands, state)
        assert filtered.autopilot_direction == direction
        assert "autopilot_direction" in applied

    def test_autopilot_config_always_applied(self) -> None:
        commands = VesselCommands(autopilot_config=AutopilotConfig.AUTO)
        state = State()
        filtered, applied = filter_commands(commands, state)
        assert filtered.autopilot_config == AutopilotConfig.AUTO
        assert "autopilot_config" in applied

    def test_filters_redundant_stage_lock(self) -> None:
        commands = VesselCommands(stage_lock=True)
        state = State(control_stage_lock=True)
        filtered, applied = filter_commands(commands, state)
        assert filtered.stage_lock is None
        assert "stage_lock" not in applied

    def test_passes_changed_reaction_wheels(self) -> None:
        commands = VesselCommands(reaction_wheels=False)
        state = State(control_reaction_wheels=True)
        filtered, applied = filter_commands(commands, state)
        assert filtered.reaction_wheels is False
        assert "reaction_wheels" in applied

    def test_filters_redundant_wheel_throttle(self) -> None:
        commands = VesselCommands(wheel_throttle=0.0)
        state = State(control_wheel_throttle=0.0)
        filtered, applied = filter_commands(commands, state)
        assert filtered.wheel_throttle is None
        assert "wheel_throttle" not in applied

    def test_passes_changed_wheel_steering(self) -> None:
        commands = VesselCommands(wheel_steering=0.5)
        state = State(control_wheel_steering=0.0)
        filtered, applied = filter_commands(commands, state)
        assert filtered.wheel_steering == 0.5
        assert "wheel_steering" in applied

    def test_all_none_returns_empty(self) -> None:
        commands = VesselCommands()
        state = State()
        filtered, applied = filter_commands(commands, state)
        assert len(applied) == 0

    def test_all_science_always_applied(self) -> None:
        commands = VesselCommands(all_science=ScienceAction.RUN)
        state = State()
        filtered, applied = filter_commands(commands, state)
        assert filtered.all_science == ScienceAction.RUN
        assert "all_science" in applied

    def test_science_commands_always_applied(self) -> None:
        cmds = (ScienceCommand(experiment_index=0, action=ScienceAction.RUN),)
        commands = VesselCommands(science_commands=cmds)
        state = State()
        filtered, applied = filter_commands(commands, state)
        assert filtered.science_commands == cmds
        assert "science_commands" in applied


# ---------------------------------------------------------------------------
# read_vessel_state tests: science experiments
# ---------------------------------------------------------------------------


class TestReadVesselStateScience:
    """Tests for science experiment reading in read_vessel_state()."""

    def test_reads_science_experiments(self) -> None:
        conn = _make_mock_conn()
        state = read_vessel_state(conn)
        assert len(state.science_experiments) == 2

    def test_experiment_fields_populated(self) -> None:
        conn = _make_mock_conn()
        state = read_vessel_state(conn)
        exp = state.science_experiments[0]
        assert exp.index == 0
        assert exp.name == "temperatureScan"
        assert exp.title == "2HOT Thermometer"
        assert exp.part_title == "2HOT Thermometer"
        assert exp.available is True
        assert exp.has_data is False
        assert exp.biome == "Shores"
        assert exp.science_cap == 8.0

    def test_experiment_with_data(self) -> None:
        conn = _make_mock_conn()
        state = read_vessel_state(conn)
        exp = state.science_experiments[1]
        assert exp.has_data is True
        assert exp.science_value == 5.0
        assert exp.science_cap == 13.0

    def test_empty_experiments_when_none_on_vessel(self) -> None:
        conn = _make_mock_conn()
        conn.space_center.active_vessel.parts.experiments = []
        state = read_vessel_state(conn)
        assert state.science_experiments == ()


# ---------------------------------------------------------------------------
# apply_controls tests: science commands
# ---------------------------------------------------------------------------


class TestApplyControlsScience:
    """Tests for science experiment commands in apply_controls()."""

    def test_all_science_run_triggers_available_experiments(self) -> None:
        conn = _make_mock_conn()
        commands = VesselCommands(all_science=ScienceAction.RUN)
        apply_controls(conn, commands)
        experiments = conn.space_center.active_vessel.parts.experiments
        # First experiment: available=True, has_data=False -> should run
        assert experiments[0]._ran is True
        # Second experiment: has_data=True -> should NOT run
        assert experiments[1]._ran is False

    def test_all_science_reset_resets_all(self) -> None:
        conn = _make_mock_conn()
        commands = VesselCommands(all_science=ScienceAction.RESET)
        apply_controls(conn, commands)
        experiments = conn.space_center.active_vessel.parts.experiments
        assert experiments[0]._reset is True
        assert experiments[1]._reset is True

    def test_all_science_transmit_transmits_all(self) -> None:
        conn = _make_mock_conn()
        commands = VesselCommands(all_science=ScienceAction.TRANSMIT)
        apply_controls(conn, commands)
        experiments = conn.space_center.active_vessel.parts.experiments
        assert experiments[0]._transmitted is True
        assert experiments[1]._transmitted is True

    def test_science_command_targets_specific_experiment(self) -> None:
        conn = _make_mock_conn()
        cmds = (ScienceCommand(experiment_index=1, action=ScienceAction.DUMP),)
        commands = VesselCommands(science_commands=cmds)
        apply_controls(conn, commands)
        experiments = conn.space_center.active_vessel.parts.experiments
        assert experiments[0]._dumped is False
        assert experiments[1]._dumped is True

    def test_science_command_out_of_range_ignored(self) -> None:
        conn = _make_mock_conn()
        cmds = (ScienceCommand(experiment_index=99, action=ScienceAction.RUN),)
        commands = VesselCommands(science_commands=cmds)
        # Should not raise
        apply_controls(conn, commands)

    def test_science_command_run_guards_available_and_has_data(self) -> None:
        conn = _make_mock_conn()
        # Target experiment[1] which has_data=True
        cmds = (ScienceCommand(experiment_index=1, action=ScienceAction.RUN),)
        commands = VesselCommands(science_commands=cmds)
        apply_controls(conn, commands)
        assert conn.space_center.active_vessel.parts.experiments[1]._ran is False


# ---------------------------------------------------------------------------
# read_vessel_state tests: parts (parachutes, legs, fairings)
# ---------------------------------------------------------------------------


class TestReadVesselStateParts:
    """Tests for per-part state reading in read_vessel_state()."""

    def test_reads_parachutes(self) -> None:
        conn = _make_mock_conn()
        state = read_vessel_state(conn)
        assert len(state.parts_parachutes) == 2
        assert state.parts_parachutes[0].stage == 3
        assert state.parts_parachutes[0].decouple_stage == 3
        assert state.parts_parachutes[0].state == "stowed"
        assert state.parts_parachutes[0].safe_to_deploy is True
        assert state.parts_parachutes[0].deploy_semi_min_pressure == 0.04
        assert state.parts_parachutes[0].deploy_full_altitude == 1000.0
        assert state.parts_parachutes[1].state == "deployed"

    def test_reads_legs(self) -> None:
        conn = _make_mock_conn()
        state = read_vessel_state(conn)
        assert len(state.parts_legs) == 2
        assert state.parts_legs[0].stage == 1
        assert state.parts_legs[0].decouple_stage == -1
        assert state.parts_legs[0].state == "retracted"
        assert state.parts_legs[1].state == "deployed"

    def test_reads_fairings(self) -> None:
        conn = _make_mock_conn()
        state = read_vessel_state(conn)
        assert len(state.parts_fairings) == 2
        assert state.parts_fairings[0].stage == 5
        assert state.parts_fairings[0].decouple_stage == 5
        assert state.parts_fairings[0].state == "intact"
        assert state.parts_fairings[1].state == "jettisoned"

    def test_empty_parts(self) -> None:
        conn = _make_mock_conn()
        conn.space_center.active_vessel.parts.parachutes = []
        conn.space_center.active_vessel.parts.legs = []
        conn.space_center.active_vessel.parts.fairings = []
        state = read_vessel_state(conn)
        assert state.parts_parachutes == ()
        assert state.parts_legs == ()
        assert state.parts_fairings == ()

    def test_resilient_to_missing_parachutes_attr(self) -> None:
        conn = _make_mock_conn()
        del conn.space_center.active_vessel.parts.parachutes
        state = read_vessel_state(conn)
        assert state.parts_parachutes == ()

    def test_resilient_to_missing_legs_attr(self) -> None:
        conn = _make_mock_conn()
        del conn.space_center.active_vessel.parts.legs
        state = read_vessel_state(conn)
        assert state.parts_legs == ()

    def test_resilient_to_missing_fairings_attr(self) -> None:
        conn = _make_mock_conn()
        del conn.space_center.active_vessel.parts.fairings
        state = read_vessel_state(conn)
        assert state.parts_fairings == ()
