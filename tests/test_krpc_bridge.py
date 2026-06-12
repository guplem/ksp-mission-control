"""Tests for the kRPC bridge: apply_controls, read_vessel_state, filter_commands."""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from ksp_mission_control.control.actions.base import (
    AutopilotConfig,
    AutopilotDirection,
    ReferenceFrame,
    ScienceAction,
    ScienceCommand,
    ScienceSituation,
    State,
    VesselCommands,
)
from ksp_mission_control.control.krpc_bridge import (
    NoActiveVesselError,
    apply_controls,
    filter_commands,
    launch_vessel_from_vab,
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
        # Maneuver nodes (read by bridge; write tests can override)
        nodes=[],
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
        flying_high_altitude_threshold=18000.0,
        space_high_altitude_threshold=250000.0,
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
        semi_major_axis=675000.0,
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
    vessel_surface_velocity_ref = SimpleNamespace()
    vessel_orbital_ref = SimpleNamespace()
    vessel_ref = SimpleNamespace()

    mock_engines = [
        SimpleNamespace(active=True, has_fuel=True, part=SimpleNamespace(stage=0, decouple_stage=0)),
        SimpleNamespace(active=True, has_fuel=False, part=SimpleNamespace(stage=0, decouple_stage=0)),
        SimpleNamespace(active=False, has_fuel=True, part=SimpleNamespace(stage=0, decouple_stage=0)),
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
    mock_decouplers = [
        SimpleNamespace(decoupled=False, part=SimpleNamespace(stage=4, decouple_stage=4)),
        SimpleNamespace(decoupled=True, part=SimpleNamespace(stage=4, decouple_stage=4)),
    ]
    mock_launch_clamps = [
        SimpleNamespace(part=SimpleNamespace(stage=6, decouple_stage=6)),
    ]
    mock_rcs = [
        SimpleNamespace(enabled=True, part=SimpleNamespace(stage=0, decouple_stage=-1)),
        SimpleNamespace(enabled=False, part=SimpleNamespace(stage=0, decouple_stage=-1)),
    ]
    mock_intakes = [
        SimpleNamespace(open=True, part=SimpleNamespace(stage=0, decouple_stage=-1)),
    ]
    mock_solar_panels = [
        SimpleNamespace(state="SolarPanelState.extended", part=SimpleNamespace(stage=0, decouple_stage=-1)),
        SimpleNamespace(state="SolarPanelState.retracted", part=SimpleNamespace(stage=0, decouple_stage=-1)),
    ]
    mock_radiators = [
        SimpleNamespace(state="RadiatorState.extended", part=SimpleNamespace(stage=0, decouple_stage=-1)),
    ]
    mock_cargo_bays = [
        SimpleNamespace(open=False, part=SimpleNamespace(stage=0, decouple_stage=-1)),
    ]
    mock_docking_ports = [
        SimpleNamespace(state="DockingPortState.ready", part=SimpleNamespace(stage=0, decouple_stage=-1)),
    ]
    mock_reaction_wheels = [
        SimpleNamespace(active=True, part=SimpleNamespace(stage=0, decouple_stage=-1)),
    ]
    mock_sensors = [
        SimpleNamespace(active=True, part=SimpleNamespace(stage=0, decouple_stage=-1)),
    ]
    mock_wheels = [
        SimpleNamespace(state="WheelState.deployed", part=SimpleNamespace(stage=0, decouple_stage=-1)),
    ]
    mock_lights = [
        SimpleNamespace(active=False, part=SimpleNamespace(stage=0, decouple_stage=-1)),
    ]
    mock_antennas = [
        SimpleNamespace(state="AntennaState.deployed", part=SimpleNamespace(stage=0, decouple_stage=-1)),
    ]
    mock_resource_converters = [
        SimpleNamespace(active=lambda index: False, part=SimpleNamespace(stage=0, decouple_stage=-1)),
    ]
    mock_resource_harvesters = [
        SimpleNamespace(active=False, part=SimpleNamespace(stage=0, decouple_stage=-1)),
    ]

    parts = SimpleNamespace(
        all=[_make_mock_part(0), _make_mock_part(1), _make_mock_part(2)],
        engines=mock_engines,
        experiments=mock_experiments,
        parachutes=mock_parachutes,
        legs=mock_legs,
        fairings=mock_fairings,
        decouplers=mock_decouplers,
        launch_clamps=mock_launch_clamps,
        rcs=mock_rcs,
        intakes=mock_intakes,
        solar_panels=mock_solar_panels,
        radiators=mock_radiators,
        cargo_bays=mock_cargo_bays,
        docking_ports=mock_docking_ports,
        reaction_wheels=mock_reaction_wheels,
        sensors=mock_sensors,
        wheels=mock_wheels,
        lights=mock_lights,
        antennas=mock_antennas,
        resource_converters=mock_resource_converters,
        resource_harvesters=mock_resource_harvesters,
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

    # Vessel forward direction per reference frame. Each ref-frame namespace
    # carries its own ``_direction`` attribute; ``vessel.direction(ref)`` just
    # reads that field. Tests can override by mutating
    # ``vessel.orbital_reference_frame._direction`` etc.
    vessel_orbital_ref._direction = (0.0, 1.0, 0.0)
    vessel_surface_velocity_ref._direction = (0.0, 1.0, 0.0)
    body_non_rotating_ref_frame._direction = (1.0, 0.0, 0.0)

    def _read_direction(ref: object) -> tuple[float, float, float]:
        return getattr(ref, "_direction", (0.0, 1.0, 0.0))

    vessel: SimpleNamespace | None = None
    if active_vessel:
        vessel = SimpleNamespace(
            control=control,
            orbit=orbit,
            auto_pilot=auto_pilot,
            met=120.0,
            name="Test Vessel",
            biome="Shores",
            situation=situation,
            mass=5000.0,
            dry_mass=2000.0,
            thrust=25000.0,
            available_thrust=50000.0,
            max_thrust=60000.0,
            specific_impulse=320.0,
            vacuum_specific_impulse=350.0,
            surface_reference_frame=vessel_surface_ref,
            surface_velocity_reference_frame=vessel_surface_velocity_ref,
            orbital_reference_frame=vessel_orbital_ref,
            reference_frame=vessel_ref,
            parts=parts,
            resources=resources,
            comms=comms,
            flight=lambda ref: flight,
            direction=_read_direction,
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

    def test_reads_position(self) -> None:
        conn = _make_mock_conn()
        state = read_vessel_state(conn)
        assert state.position_biome == "Shores"
        assert state.position_latitude == -0.1
        assert state.position_longitude == 74.5

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


class TestReadScienceSituation:
    """Tests for derivation of science_situation from kRPC telemetry."""

    def test_surface_landed_when_situation_landed(self) -> None:
        conn = _make_mock_conn(situation="VesselSituation.landed")
        state = read_vessel_state(conn)
        assert state.science_situation == ScienceSituation.SURFACE_LANDED

    def test_surface_landed_when_situation_pre_launch(self) -> None:
        conn = _make_mock_conn(situation="VesselSituation.pre_launch")
        state = read_vessel_state(conn)
        assert state.science_situation == ScienceSituation.SURFACE_LANDED

    def test_surface_splashed_when_situation_splashed(self) -> None:
        conn = _make_mock_conn(situation="VesselSituation.splashed")
        state = read_vessel_state(conn)
        assert state.science_situation == ScienceSituation.SURFACE_SPLASHED

    def test_atmosphere_low_when_flying_below_threshold(self) -> None:
        conn = _make_mock_conn(situation="VesselSituation.flying")
        conn.space_center.active_vessel.flight(None).mean_altitude = 5_000.0  # below 18km
        state = read_vessel_state(conn)
        assert state.science_situation == ScienceSituation.ATMOSPHERE_LOW

    def test_atmosphere_high_when_flying_above_threshold(self) -> None:
        conn = _make_mock_conn(situation="VesselSituation.flying")
        conn.space_center.active_vessel.flight(None).mean_altitude = 25_000.0  # above 18km
        state = read_vessel_state(conn)
        assert state.science_situation == ScienceSituation.ATMOSPHERE_HIGH

    def test_space_low_when_sub_orbital_below_threshold(self) -> None:
        conn = _make_mock_conn(situation="VesselSituation.sub_orbital")
        conn.space_center.active_vessel.flight(None).mean_altitude = 100_000.0  # below 250km
        state = read_vessel_state(conn)
        assert state.science_situation == ScienceSituation.SPACE_LOW

    def test_space_high_when_orbiting_above_threshold(self) -> None:
        conn = _make_mock_conn(situation="VesselSituation.orbiting")
        conn.space_center.active_vessel.flight(None).mean_altitude = 500_000.0  # above 250km
        state = read_vessel_state(conn)
        assert state.science_situation == ScienceSituation.SPACE_HIGH

    def test_space_low_when_docked(self) -> None:
        conn = _make_mock_conn(situation="VesselSituation.docked")
        conn.space_center.active_vessel.flight(None).mean_altitude = 200_000.0
        state = read_vessel_state(conn)
        assert state.science_situation == ScienceSituation.SPACE_LOW

    def test_space_when_escaping_above_threshold(self) -> None:
        conn = _make_mock_conn(situation="VesselSituation.escaping")
        conn.space_center.active_vessel.flight(None).mean_altitude = 10_000_000.0
        state = read_vessel_state(conn)
        assert state.science_situation == ScienceSituation.SPACE_HIGH


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

    def test_sets_direction_with_vessel_surface_velocity_frame(self) -> None:
        conn = _make_mock_conn()
        vessel = conn.space_center.active_vessel
        commands = VesselCommands(
            autopilot_direction=AutopilotDirection(
                vector=(-1.0, 0.0, 0.0),
                reference_frame=ReferenceFrame.VESSEL_SURFACE_VELOCITY,
            )
        )
        apply_controls(conn, commands)
        assert vessel.auto_pilot.reference_frame is vessel.surface_velocity_reference_frame

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
# Maneuver node tests
# ---------------------------------------------------------------------------


def _make_mock_krpc_node(
    *,
    ut: float = 1000.0,
    delta_v: float = 100.0,
    remaining_delta_v: float = 100.0,
    burn_vector: tuple[float, float, float] = (0.0, 100.0, 0.0),
    remaining_burn_vector: tuple[float, float, float] = (0.0, 100.0, 0.0),
    post_orbit: SimpleNamespace | None = None,
) -> SimpleNamespace:
    if post_orbit is None:
        post_orbit = SimpleNamespace(
            apoapsis_altitude=100_000.0,
            periapsis_altitude=100_000.0,
            eccentricity=0.0,
            inclination=0.0,
            period=5500.0,
            semi_major_axis=700_000.0,
        )
    return SimpleNamespace(
        ut=ut,
        time_to=ut,
        delta_v=delta_v,
        remaining_delta_v=remaining_delta_v,
        prograde=delta_v,
        normal=0.0,
        radial=0.0,
        burn_vector=lambda _frame, _bv=burn_vector: _bv,
        remaining_burn_vector=lambda _frame, _rbv=remaining_burn_vector: _rbv,
        orbit=post_orbit,
        _removed=False,
    )


class TestReadVesselStateNodes:
    """Tests for reading maneuver nodes from vessel.control.nodes."""

    def test_empty_nodes_by_default(self) -> None:
        conn = _make_mock_conn()
        state = read_vessel_state(conn)
        assert state.nodes == ()

    def test_reads_single_node(self) -> None:
        conn = _make_mock_conn()
        krpc_node = _make_mock_krpc_node(ut=12345.6, delta_v=150.0, remaining_delta_v=80.0)
        conn.space_center.active_vessel.control.nodes = [krpc_node]

        state = read_vessel_state(conn)
        assert len(state.nodes) == 1
        node = state.nodes[0]
        assert node.index == 0
        assert node.ut == 12345.6
        assert node.delta_v == 150.0
        assert node.delta_v_remaining == 80.0
        assert node.post_burn_orbit_apoapsis == 100_000.0
        assert node.post_burn_orbit_semi_major_axis == 700_000.0
        # burn_time_estimate is computed by the bridge from vessel mass/Isp/thrust.
        # The mock vessel has mass=5000, available_thrust=50000, vacuum_isp=350.
        # Tsiolkovsky for 80 m/s should produce a finite, sub-minute estimate.
        assert math.isfinite(node.burn_time_estimate)
        assert 0.0 < node.burn_time_estimate < 60.0

    def test_indexes_in_iteration_order(self) -> None:
        conn = _make_mock_conn()
        first = _make_mock_krpc_node(ut=1000.0)
        second = _make_mock_krpc_node(ut=2000.0)
        conn.space_center.active_vessel.control.nodes = [first, second]

        state = read_vessel_state(conn)
        assert tuple(n.index for n in state.nodes) == (0, 1)
        assert tuple(n.ut for n in state.nodes) == (1000.0, 2000.0)


class TestApplyControlsManeuverNodes:
    """Tests for the create_node and remove_node_at_ut commands."""

    def test_creates_node(self) -> None:
        from ksp_mission_control.control.actions.base import Maneuver

        added: list[tuple[float, float, float, float]] = []

        def add_node(ut: float, prograde: float = 0.0, normal: float = 0.0, radial: float = 0.0) -> SimpleNamespace:
            added.append((ut, prograde, normal, radial))
            return SimpleNamespace()

        conn = _make_mock_conn()
        conn.space_center.active_vessel.control.add_node = add_node

        commands = VesselCommands(create_node=Maneuver(ut=1234.5, prograde=42.0))
        apply_controls(conn, commands)
        assert added == [(1234.5, 42.0, 0.0, 0.0)]

    def test_removes_matching_node_by_ut(self) -> None:
        conn = _make_mock_conn()
        keep = _make_mock_krpc_node(ut=2000.0)
        drop = _make_mock_krpc_node(ut=1000.0)
        keep.remove = lambda _k=keep: setattr(_k, "_removed", True)
        drop.remove = lambda _d=drop: setattr(_d, "_removed", True)
        conn.space_center.active_vessel.control.nodes = [keep, drop]

        commands = VesselCommands(remove_node_at_ut=1000.0)
        apply_controls(conn, commands)
        assert drop._removed is True
        assert keep._removed is False

    def test_remove_before_create_when_both_set(self) -> None:
        """A single tick may remove + create to atomically replace a node."""
        from ksp_mission_control.control.actions.base import Maneuver

        order: list[str] = []
        existing = _make_mock_krpc_node(ut=500.0)
        existing.remove = lambda: order.append("remove")
        conn = _make_mock_conn()
        conn.space_center.active_vessel.control.nodes = [existing]
        conn.space_center.active_vessel.control.add_node = lambda *_a, **_kw: order.append("create") or SimpleNamespace()

        commands = VesselCommands(
            create_node=Maneuver(ut=600.0, prograde=10.0),
            remove_node_at_ut=500.0,
        )
        apply_controls(conn, commands)
        assert order == ["remove", "create"]


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
        assert len(state.parts.parachutes) == 2
        assert state.parts.parachutes[0].stage == 3
        assert state.parts.parachutes[0].decouple_stage == 3
        assert state.parts.parachutes[0].state == "stowed"
        assert state.parts.parachutes[0].safe_to_deploy is True
        assert state.parts.parachutes[0].deploy_semi_min_pressure == 0.04
        assert state.parts.parachutes[0].deploy_full_altitude == 1000.0
        assert state.parts.parachutes[1].state == "deployed"

    def test_reads_legs(self) -> None:
        conn = _make_mock_conn()
        state = read_vessel_state(conn)
        assert len(state.parts.legs) == 2
        assert state.parts.legs[0].stage == 1
        assert state.parts.legs[0].decouple_stage == -1
        assert state.parts.legs[0].state == "retracted"
        assert state.parts.legs[1].state == "deployed"

    def test_reads_fairings(self) -> None:
        conn = _make_mock_conn()
        state = read_vessel_state(conn)
        assert len(state.parts.fairings) == 2
        assert state.parts.fairings[0].stage == 5
        assert state.parts.fairings[0].decouple_stage == 5
        assert state.parts.fairings[0].state == "intact"
        assert state.parts.fairings[1].state == "jettisoned"

    def test_reads_engines(self) -> None:
        conn = _make_mock_conn()
        state = read_vessel_state(conn)
        assert len(state.parts.engines) == 3
        assert state.parts.engines[0].state == "active"
        assert state.parts.engines[1].state == "flameout"
        assert state.parts.engines[2].state == "inactive"

    def test_reads_decouplers(self) -> None:
        conn = _make_mock_conn()
        state = read_vessel_state(conn)
        assert len(state.parts.decouplers) == 2
        assert state.parts.decouplers[0].state == "attached"
        assert state.parts.decouplers[1].state == "decoupled"

    def test_reads_launch_clamps(self) -> None:
        conn = _make_mock_conn()
        state = read_vessel_state(conn)
        assert len(state.parts.launch_clamps) == 1
        assert state.parts.launch_clamps[0].state == "attached"

    def test_reads_rcs(self) -> None:
        conn = _make_mock_conn()
        state = read_vessel_state(conn)
        assert len(state.parts.rcs) == 2
        assert state.parts.rcs[0].state == "enabled"
        assert state.parts.rcs[1].state == "disabled"

    def test_reads_intakes(self) -> None:
        conn = _make_mock_conn()
        state = read_vessel_state(conn)
        assert len(state.parts.intakes) == 1
        assert state.parts.intakes[0].state == "open"

    def test_reads_solar_panels(self) -> None:
        conn = _make_mock_conn()
        state = read_vessel_state(conn)
        assert len(state.parts.solar_panels) == 2
        assert state.parts.solar_panels[0].state == "extended"
        assert state.parts.solar_panels[1].state == "retracted"

    def test_reads_radiators(self) -> None:
        conn = _make_mock_conn()
        state = read_vessel_state(conn)
        assert len(state.parts.radiators) == 1
        assert state.parts.radiators[0].state == "extended"

    def test_reads_cargo_bays(self) -> None:
        conn = _make_mock_conn()
        state = read_vessel_state(conn)
        assert len(state.parts.cargo_bays) == 1
        assert state.parts.cargo_bays[0].state == "closed"

    def test_reads_docking_ports(self) -> None:
        conn = _make_mock_conn()
        state = read_vessel_state(conn)
        assert len(state.parts.docking_ports) == 1
        assert state.parts.docking_ports[0].state == "ready"

    def test_reads_reaction_wheels(self) -> None:
        conn = _make_mock_conn()
        state = read_vessel_state(conn)
        assert len(state.parts.reaction_wheels) == 1
        assert state.parts.reaction_wheels[0].state == "active"

    def test_reads_sensors(self) -> None:
        conn = _make_mock_conn()
        state = read_vessel_state(conn)
        assert len(state.parts.sensors) == 1
        assert state.parts.sensors[0].state == "active"

    def test_reads_wheels(self) -> None:
        conn = _make_mock_conn()
        state = read_vessel_state(conn)
        assert len(state.parts.wheels) == 1
        assert state.parts.wheels[0].state == "deployed"

    def test_reads_lights(self) -> None:
        conn = _make_mock_conn()
        state = read_vessel_state(conn)
        assert len(state.parts.lights) == 1
        assert state.parts.lights[0].state == "off"

    def test_reads_antennas(self) -> None:
        conn = _make_mock_conn()
        state = read_vessel_state(conn)
        assert len(state.parts.antennas) == 1
        assert state.parts.antennas[0].state == "deployed"

    def test_reads_resource_converters(self) -> None:
        conn = _make_mock_conn()
        state = read_vessel_state(conn)
        assert len(state.parts.resource_converters) == 1
        assert state.parts.resource_converters[0].state == "inactive"

    def test_reads_resource_harvesters(self) -> None:
        conn = _make_mock_conn()
        state = read_vessel_state(conn)
        assert len(state.parts.resource_harvesters) == 1
        assert state.parts.resource_harvesters[0].state == "inactive"

    def test_empty_parts(self) -> None:
        conn = _make_mock_conn()
        conn.space_center.active_vessel.parts.parachutes = []
        conn.space_center.active_vessel.parts.legs = []
        conn.space_center.active_vessel.parts.fairings = []
        state = read_vessel_state(conn)
        assert state.parts.parachutes == ()
        assert state.parts.legs == ()
        assert state.parts.fairings == ()

    def test_resilient_to_missing_parachutes_attr(self) -> None:
        conn = _make_mock_conn()
        del conn.space_center.active_vessel.parts.parachutes
        state = read_vessel_state(conn)
        assert state.parts.parachutes == ()

    def test_resilient_to_missing_legs_attr(self) -> None:
        conn = _make_mock_conn()
        del conn.space_center.active_vessel.parts.legs
        state = read_vessel_state(conn)
        assert state.parts.legs == ()

    def test_resilient_to_missing_fairings_attr(self) -> None:
        conn = _make_mock_conn()
        del conn.space_center.active_vessel.parts.fairings
        state = read_vessel_state(conn)
        assert state.parts.fairings == ()


# ---------------------------------------------------------------------------
# launch_vessel_from_vab
# ---------------------------------------------------------------------------


class TestLaunchVesselFromVab:
    def _make_mock_vessel(self, situation: str) -> SimpleNamespace:
        recovered: list[bool] = []
        return SimpleNamespace(
            situation=situation,
            recover=lambda: recovered.append(True),
            _recovered=recovered,
        )

    def _make_spawn_conn(self, vessels: list[SimpleNamespace]) -> SimpleNamespace:
        launched: list[str] = []
        sc = SimpleNamespace(
            vessels=vessels,
            launch_vessel_from_vab=lambda name: launched.append(name),
            _launched=launched,
        )
        return SimpleNamespace(space_center=sc)

    def test_recovers_prelaunch_vessel_before_spawning(self) -> None:
        pad_vessel = self._make_mock_vessel("VesselSituation.pre_launch")
        conn = self._make_spawn_conn([pad_vessel])
        launch_vessel_from_vab(conn, "fart-1")
        assert pad_vessel._recovered == [True]
        assert conn.space_center._launched == ["fart-1"]

    def test_does_not_recover_flying_vessel(self) -> None:
        flying_vessel = self._make_mock_vessel("VesselSituation.flying")
        conn = self._make_spawn_conn([flying_vessel])
        launch_vessel_from_vab(conn, "fart-1")
        assert flying_vessel._recovered == []
        assert conn.space_center._launched == ["fart-1"]

    def test_recovers_only_prelaunch_among_multiple_vessels(self) -> None:
        pad_vessel = self._make_mock_vessel("VesselSituation.pre_launch")
        orbiting_vessel = self._make_mock_vessel("VesselSituation.orbiting")
        conn = self._make_spawn_conn([pad_vessel, orbiting_vessel])
        launch_vessel_from_vab(conn, "fart-2")
        assert pad_vessel._recovered == [True]
        assert orbiting_vessel._recovered == []

    def test_spawns_when_no_vessels_present(self) -> None:
        conn = self._make_spawn_conn([])
        launch_vessel_from_vab(conn, "fart-1")
        assert conn.space_center._launched == ["fart-1"]


# ---------------------------------------------------------------------------
# read_vessel_state tests: equatorial nodes (AN/DN)
# ---------------------------------------------------------------------------


def _patch_orbit_for_nodes(
    conn: SimpleNamespace,
    *,
    inclination: float = 0.5,
    argument_of_periapsis: float = 0.0,
    period: float = 2400.0,
    semi_major_axis: float = 675_000.0,
    ut_at_true_anomaly: dict[float, float] | None = None,
    radius_at: dict[float, float] | None = None,
) -> None:
    """Wire AN/DN kRPC fields onto the existing mock orbit.

    Tests that exercise AN/DN reading need ``argument_of_periapsis``,
    ``ut_at_true_anomaly`` and ``radius_at`` on the orbit. The base mock
    omits them so existing tests stay focused; this helper attaches them
    just for the tests that care.
    """
    orbit = conn.space_center.active_vessel.orbit
    orbit.inclination = inclination
    orbit.argument_of_periapsis = argument_of_periapsis
    orbit.period = period
    orbit.semi_major_axis = semi_major_axis

    ut_lookup = ut_at_true_anomaly or {}

    def _ut(nu: float) -> float:
        # Match by closeness; tests pass either the exact ν or a nearby float.
        for key, value in ut_lookup.items():
            if abs(nu - key) < 1e-6:
                return value
        return 0.0

    orbit.ut_at_true_anomaly = _ut

    radius_lookup = radius_at or {}

    def _radius(ut: float) -> float:
        for key, value in radius_lookup.items():
            if abs(ut - key) < 1e-3:
                return value
        return semi_major_axis

    orbit.radius_at = _radius


class TestReadVesselStateEquatorialNodes:
    """Tests for orbit ascending/descending node UTs and speeds."""

    def test_equatorial_orbit_yields_infinite_node_uts(self) -> None:
        conn = _make_mock_conn()
        conn.space_center.active_vessel.orbit.inclination = 0.0
        state = read_vessel_state(conn)
        assert math.isinf(state.orbit_ascending_node_ut)
        assert math.isinf(state.orbit_descending_node_ut)
        assert state.orbit_ascending_node_speed == 0.0
        assert state.orbit_descending_node_speed == 0.0

    def test_inclined_orbit_reads_an_and_dn_ut(self) -> None:
        # ω = π/2: AN is at true anomaly = -π/2 (mod 2π) = 3π/2,
        # DN at π - π/2 = π/2.
        conn = _make_mock_conn()
        _patch_orbit_for_nodes(
            conn,
            inclination=0.5,
            argument_of_periapsis=math.pi / 2.0,
            ut_at_true_anomaly={3.0 * math.pi / 2.0: 1_001_200.0, math.pi / 2.0: 1_000_400.0},
            radius_at={1_001_200.0: 680_000.0, 1_000_400.0: 670_000.0},
        )
        state = read_vessel_state(conn)
        assert state.orbit_ascending_node_ut == 1_001_200.0
        assert state.orbit_descending_node_ut == 1_000_400.0
        # vis-viva at AN: sqrt(mu * (2/r - 1/a)); mu and sma from the mock fixture.
        expected_an_speed = math.sqrt(3.5316e12 * (2.0 / 680_000.0 - 1.0 / 675_000.0))
        expected_dn_speed = math.sqrt(3.5316e12 * (2.0 / 670_000.0 - 1.0 / 675_000.0))
        assert abs(state.orbit_ascending_node_speed - expected_an_speed) < 0.5
        assert abs(state.orbit_descending_node_speed - expected_dn_speed) < 0.5

    def test_node_in_the_past_is_bumped_one_period_forward(self) -> None:
        # kRPC may return a UT slightly before current_ut; the bridge bumps
        # forward by full periods until it is in the future.
        conn = _make_mock_conn()
        current_ut = float(conn.space_center.ut)
        _patch_orbit_for_nodes(
            conn,
            inclination=0.5,
            argument_of_periapsis=0.0,
            period=2400.0,
            ut_at_true_anomaly={0.0: current_ut - 100.0, math.pi: current_ut - 200.0},
            radius_at={current_ut - 100.0 + 2400.0: 700_000.0, current_ut - 200.0 + 2400.0: 700_000.0},
        )
        state = read_vessel_state(conn)
        assert state.orbit_ascending_node_ut == current_ut - 100.0 + 2400.0
        assert state.orbit_descending_node_ut == current_ut - 200.0 + 2400.0

    def test_resilient_when_krpc_lacks_argument_of_periapsis(self) -> None:
        # Base mock has no ``argument_of_periapsis``: the helper must fall
        # back to undefined nodes rather than raising.
        conn = _make_mock_conn()
        state = read_vessel_state(conn)
        assert math.isinf(state.orbit_ascending_node_ut)
        assert math.isinf(state.orbit_descending_node_ut)


# ---------------------------------------------------------------------------
# read_vessel_state tests: impact prediction
# ---------------------------------------------------------------------------


def _patch_body_for_impact(
    conn: SimpleNamespace,
    *,
    altitude_at_position: object,
    latitude_at_position: object,
    longitude_at_position: object,
    surface_height: object = lambda _lat, _lon: 0.0,
    rotational_period: float = math.inf,
) -> None:
    """Attach the body-side queries the impact predictor uses.

    ``rotational_period`` defaults to infinity (a non-rotating body) so
    tests that only care about other aspects of the prediction don't have
    to reason about the rotation correction.
    """
    body = conn.space_center.active_vessel.orbit.body
    body.altitude_at_position = altitude_at_position
    body.latitude_at_position = latitude_at_position
    body.longitude_at_position = longitude_at_position
    body.surface_height = surface_height
    body.rotational_period = rotational_period


class TestReadVesselStateImpactPrediction:
    """Tests for State.predicted_impact populated by the bridge."""

    def test_returns_none_when_periapsis_above_terrain(self) -> None:
        # The mock orbit has periapsis = 70 km, well above the 10 km cheap-
        # reject threshold. No impact expected.
        conn = _make_mock_conn()
        state = read_vessel_state(conn)
        assert state.predicted_impact is None

    def test_returns_none_when_orbit_has_no_period(self) -> None:
        conn = _make_mock_conn()
        conn.space_center.active_vessel.orbit.periapsis_altitude = -1000.0
        conn.space_center.active_vessel.orbit.period = 0.0  # parabolic/hyperbolic
        state = read_vessel_state(conn)
        assert state.predicted_impact is None

    def test_returns_prediction_when_periapsis_below_sea_level(self) -> None:
        conn = _make_mock_conn()
        orbit = conn.space_center.active_vessel.orbit
        orbit.periapsis_altitude = -2_000.0
        orbit.period = 1_800.0

        # Simulate altitude descending from +5km at ut=current to -5km at
        # ut=current+900s; lat/lon stay constant for simplicity.
        current_ut = float(conn.space_center.ut)

        def altitude_at_position(pos: tuple[float, float, float], _frame: object) -> float:
            # pos carries the UT we generated, see position_at below.
            ut_local: float = pos[0]
            return 5_000.0 - 10.0 * (ut_local - current_ut)

        orbit.position_at = lambda ut, _frame: (ut, 0.0, 0.0)
        orbit.ut_at_true_anomaly = lambda _nu: current_ut + 900.0  # periapsis, after the crossing

        _patch_body_for_impact(
            conn,
            altitude_at_position=altitude_at_position,
            latitude_at_position=lambda _pos, _frame: -1.5,
            longitude_at_position=lambda _pos, _frame: -71.9,
            surface_height=lambda _lat, _lon: 250.0,
        )

        state = read_vessel_state(conn)
        assert state.predicted_impact is not None
        assert state.predicted_impact.source == "current_orbit"
        # Crossing at ut = current_ut + 500 (altitude = 0).
        assert abs(state.predicted_impact.time_to_ballistic_impact - 500.0) < 1.0
        assert state.predicted_impact.latitude == -1.5
        assert state.predicted_impact.longitude == -71.9
        assert state.predicted_impact.altitude_terrain == 250.0

    def test_uses_post_node_orbit_when_future_node_exists(self) -> None:
        conn = _make_mock_conn()
        current_ut = float(conn.space_center.ut)
        post_orbit = SimpleNamespace(
            apoapsis_altitude=80_000.0,
            periapsis_altitude=-1_000.0,  # drops below sea level
            eccentricity=0.05,
            inclination=0.5,
            period=1_800.0,
            semi_major_axis=670_000.0,
            position_at=lambda ut, _frame: (ut, 0.0, 0.0),
            ut_at_true_anomaly=lambda _nu, _peri=current_ut + 960.0: _peri,  # periapsis half a period after the node
        )
        node = _make_mock_krpc_node(ut=current_ut + 60.0)
        node.orbit = post_orbit
        conn.space_center.active_vessel.control.nodes = [node]

        def altitude_at_position(pos: tuple[float, float, float], _frame: object) -> float:
            ut_local: float = pos[0]
            # Above sea level until ut = node.ut + 300s, then below.
            return (current_ut + 60.0 + 300.0) - ut_local

        _patch_body_for_impact(
            conn,
            altitude_at_position=altitude_at_position,
            latitude_at_position=lambda _pos, _frame: 12.0,
            longitude_at_position=lambda _pos, _frame: 45.0,
        )

        state = read_vessel_state(conn)
        assert state.predicted_impact is not None
        assert state.predicted_impact.source == "next_node_orbit"
        # time_to measured from current_ut; impact at current_ut + 60 + 300.
        assert abs(state.predicted_impact.time_to_ballistic_impact - 360.0) < 1.0

    def test_post_node_orbit_window_capped_at_periapsis(self) -> None:
        # Realistic geometry: a deorbit node sits at apoapsis, so the post-burn
        # orbit is high (apoapsis) at the node, dips below sea level at periapsis
        # half a period later, and returns high one full period later. A
        # full-period search window reads "above sea level" at both ends and
        # misses the periapsis dip, so the window must be capped at periapsis.
        conn = _make_mock_conn()
        current_ut = float(conn.space_center.ut)
        node_ut = current_ut + 60.0
        period = 1_800.0
        periapsis_ut = node_ut + period / 2.0  # apoapsis -> periapsis is half an orbit

        post_orbit = SimpleNamespace(
            apoapsis_altitude=85_000.0,
            periapsis_altitude=-5_000.0,
            eccentricity=0.07,
            inclination=0.1,
            period=period,
            semi_major_axis=640_000.0,
            position_at=lambda ut, _frame: (ut, 0.0, 0.0),
            ut_at_true_anomaly=lambda _nu, _peri=periapsis_ut: _peri,
        )
        node = _make_mock_krpc_node(ut=node_ut, post_orbit=post_orbit)
        conn.space_center.active_vessel.control.nodes = [node]

        # Altitude as an upward parabola in time: -5 km at periapsis (mid-window),
        # +85 km at the node and one full period later. The descending sea-level
        # crossing lies between node_ut and periapsis_ut.
        def altitude_at_position(pos: tuple[float, float, float], _frame: object) -> float:
            ut_local: float = pos[0]
            t = ut_local - periapsis_ut  # 0 at periapsis
            return -5_000.0 + 90_000.0 * (t / (period / 2.0)) ** 2

        _patch_body_for_impact(
            conn,
            altitude_at_position=altitude_at_position,
            latitude_at_position=lambda _pos, _frame: -6.6,
            longitude_at_position=lambda _pos, _frame: -144.0,
        )

        state = read_vessel_state(conn)
        assert state.predicted_impact is not None
        assert state.predicted_impact.source == "next_node_orbit"
        assert state.predicted_impact.latitude == -6.6
        # Crossing solves -5000 + 90000*(t/900)^2 = 0 -> t ~ -212s before periapsis.
        expected_impact_ut = periapsis_ut - 900.0 * math.sqrt(5_000.0 / 90_000.0)
        assert abs(state.predicted_impact.time_to_ballistic_impact - (expected_impact_ut - current_ut)) < 2.0

    def test_longitude_rotated_back_by_body_rotation_during_coast(self) -> None:
        # kRPC's position_at(ut, frame) converts through the frame's rotation
        # at CALL time (ReferenceFrame.PositionFromWorldSpace takes no time),
        # so the raw longitude is where the impact point sits NOW. The body
        # rotates east during the coast to impact, so the true impact
        # longitude lies west by the rotation accrued in between.
        conn = _make_mock_conn()
        current_ut = float(conn.space_center.ut)
        orbit = conn.space_center.active_vessel.orbit
        orbit.periapsis_altitude = -2_000.0
        orbit.period = 1_800.0
        orbit.position_at = lambda ut, _frame: (ut, 0.0, 0.0)
        orbit.ut_at_true_anomaly = lambda _nu: current_ut + 900.0

        def altitude_at_position(pos: tuple[float, float, float], _frame: object) -> float:
            ut_local: float = pos[0]
            return 5_000.0 - 10.0 * (ut_local - current_ut)  # crosses 0 at +500s

        _patch_body_for_impact(
            conn,
            altitude_at_position=altitude_at_position,
            latitude_at_position=lambda _pos, _frame: -1.5,
            longitude_at_position=lambda _pos, _frame: -71.9,
            rotational_period=18_000.0,  # 0.02 deg/s -> 10 deg over the 500s coast
        )

        state = read_vessel_state(conn)
        assert state.predicted_impact is not None
        assert state.predicted_impact.longitude == pytest.approx(-81.9, abs=0.01)
        # Latitude is unaffected: the body rotates about its polar axis.
        assert state.predicted_impact.latitude == -1.5

    def test_longitude_wrapped_to_signed_range(self) -> None:
        conn = _make_mock_conn()
        orbit = conn.space_center.active_vessel.orbit
        orbit.periapsis_altitude = -1_000.0
        orbit.period = 1_800.0
        orbit.position_at = lambda _ut, _frame: (0.0, 0.0, 0.0)
        orbit.ut_at_true_anomaly = lambda _nu, _peri=float(conn.space_center.ut) + 900.0: _peri

        _patch_body_for_impact(
            conn,
            altitude_at_position=lambda _pos, _frame: -1.0,  # already below
            latitude_at_position=lambda _pos, _frame: 0.0,
            longitude_at_position=lambda _pos, _frame: 220.0,  # > 180
        )
        state = read_vessel_state(conn)
        assert state.predicted_impact is not None
        # 220 -> -140
        assert state.predicted_impact.longitude == -140.0

    def test_resilient_when_body_lacks_position_queries(self) -> None:
        # Base mock body lacks altitude_at_position et al. With a low
        # periapsis the helper will try them and must fall back to None.
        conn = _make_mock_conn()
        conn.space_center.active_vessel.orbit.periapsis_altitude = -1_000.0
        state = read_vessel_state(conn)
        assert state.predicted_impact is None


# ---------------------------------------------------------------------------
# Time-warp read/write
# ---------------------------------------------------------------------------


class TestReadTimeWarp:
    """``State.time_warp_rate`` and ``time_warp_rate_max`` mirror kRPC space_center."""

    def test_defaults_to_one_when_krpc_fields_missing(self) -> None:
        conn = _make_mock_conn()
        state = read_vessel_state(conn)
        # Mock space_center has no warp_rate / maximum_rails_warp_factor.
        assert state.time_warp_rate == 1.0
        assert state.time_warp_rate_max == 1.0

    def test_reads_current_rate(self) -> None:
        conn = _make_mock_conn()
        conn.space_center.warp_rate = 100.0
        state = read_vessel_state(conn)
        assert state.time_warp_rate == 100.0

    def test_max_rate_follows_maximum_rails_warp_factor(self) -> None:
        conn = _make_mock_conn()
        conn.space_center.warp_rate = 1.0
        conn.space_center.maximum_rails_warp_factor = 4  # corresponds to 100x
        state = read_vessel_state(conn)
        assert state.time_warp_rate_max == 100.0

    def test_max_rate_caps_at_table_end_for_out_of_range_factor(self) -> None:
        conn = _make_mock_conn()
        conn.space_center.warp_rate = 1.0
        conn.space_center.maximum_rails_warp_factor = 99
        state = read_vessel_state(conn)
        assert state.time_warp_rate_max == 100_000.0


class TestApplyTimeWarp:
    """``commands.time_warp_rate`` writes the chosen factor to kRPC."""

    def _make_warp_conn(self, max_rails: int = 7) -> SimpleNamespace:
        conn = _make_mock_conn()
        conn.space_center.warp_rate = 1.0
        conn.space_center.maximum_rails_warp_factor = max_rails
        conn.space_center.rails_warp_factor = 0
        conn.space_center.physics_warp_factor = 0
        return conn

    def test_target_one_resets_rails_factor_to_zero(self) -> None:
        conn = self._make_warp_conn()
        conn.space_center.rails_warp_factor = 5
        apply_controls(conn, VesselCommands(time_warp_rate=1.0))
        assert conn.space_center.rails_warp_factor == 0

    def test_target_above_threshold_uses_rails(self) -> None:
        conn = self._make_warp_conn()
        apply_controls(conn, VesselCommands(time_warp_rate=1000.0))
        # 1000x is rails factor 5.
        assert conn.space_center.rails_warp_factor == 5

    def test_target_below_threshold_uses_physics(self) -> None:
        conn = self._make_warp_conn()
        apply_controls(conn, VesselCommands(time_warp_rate=3.0))
        # 3x is physics factor 2 (0->1, 1->2, 2->3, 3->4).
        assert conn.space_center.physics_warp_factor == 2

    def test_picks_largest_factor_not_exceeding_target(self) -> None:
        conn = self._make_warp_conn()
        # 73x: largest rails level <= 73 is 50 (factor 3).
        apply_controls(conn, VesselCommands(time_warp_rate=73.0))
        assert conn.space_center.rails_warp_factor == 3

    def test_caps_at_maximum_rails_warp_factor(self) -> None:
        conn = self._make_warp_conn(max_rails=2)  # cap = 10x
        apply_controls(conn, VesselCommands(time_warp_rate=1000.0))
        assert conn.space_center.rails_warp_factor == 2  # 10x, the cap

    def test_resets_physics_factor_when_switching_to_rails(self) -> None:
        conn = self._make_warp_conn()
        conn.space_center.physics_warp_factor = 3
        apply_controls(conn, VesselCommands(time_warp_rate=100.0))
        assert conn.space_center.physics_warp_factor == 0
        assert conn.space_center.rails_warp_factor == 4  # 100x

    def test_resets_rails_factor_when_switching_to_physics(self) -> None:
        conn = self._make_warp_conn()
        conn.space_center.rails_warp_factor = 5
        apply_controls(conn, VesselCommands(time_warp_rate=2.0))
        assert conn.space_center.rails_warp_factor == 0
        assert conn.space_center.physics_warp_factor == 1  # 2x

    def test_none_command_leaves_warp_unchanged(self) -> None:
        conn = self._make_warp_conn()
        conn.space_center.rails_warp_factor = 4
        apply_controls(conn, VesselCommands())  # time_warp_rate is None
        assert conn.space_center.rails_warp_factor == 4
