"""Demo data provider that generates fake vessel state for the control screen."""

from __future__ import annotations

import random

from ksp_mission_control.control.actions.base import VesselState


def generate_demo_vessel_state(tick: int) -> VesselState:
    """Return a VesselState with randomized demo values."""
    t = tick
    return VesselState(
        altitude_sea=75000.0 + random.randint(-500, 500),
        altitude_surface=74800.0 + random.randint(-500, 500),
        vertical_speed=float(random.randint(-5, 5)),
        surface_speed=2180.0 + random.randint(-10, 10),
        orbital_speed=2200.0 + random.randint(-10, 10),
        apoapsis=80000.0 + random.randint(-100, 100),
        periapsis=70000.0 + random.randint(-100, 100),
        met=t * 0.5,
        vessel_name="Demo Craft",
        situation="flying",
        body="Kerbin",
        latitude=random.uniform(-90, 90),
        longitude=random.uniform(-180, 180),
        inclination=0.50,
        eccentricity=0.0071,
        period=2400.0,
        pitch=random.uniform(-5.0, 45.0),
        heading=random.uniform(0.0, 360.0),
        roll=random.uniform(-10.0, 10.0),
        throttle=0.75 if t < 200 else 0.0,
        sas=True,
        rcs=t > 100,
        current_stage=min(t // 50, 4),
        max_stages=5,
        electric_charge=max(0.0, 150.0 - t * 0.1),
        liquid_fuel=max(0.0, 400.0 - t * 0.5),
        oxidizer=max(0.0, 480.0 - t * 0.6),
        mono_propellant=50.0,
    )
