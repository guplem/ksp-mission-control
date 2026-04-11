"""Demo data provider that generates fake telemetry for the debug view."""

from __future__ import annotations

import random


def generate_demo_telemetry(tick: int) -> str:
    """Return a formatted telemetry string with randomized demo values."""
    t = tick
    lines = [
        "[b]Debug View (DEMO)[/b]",
        "",
        "Vessel:          Demo Craft",
        "Situation:       flying",
        f"MET:             {t * 0.5:.1f}s",
        "",
        "--- Flight ---",
        f"Altitude (sea):  {75000 + random.randint(-500, 500)} m",
        f"Altitude (srf):  {74800 + random.randint(-500, 500)} m",
        f"Speed (orbit):   {2200 + random.randint(-10, 10):.1f} m/s",
        f"Speed (surface): {2180 + random.randint(-10, 10):.1f} m/s",
        f"Vertical speed:  {random.randint(-5, 5):.1f} m/s",
        f"Latitude:        {random.uniform(-90, 90):.4f}",
        f"Longitude:       {random.uniform(-180, 180):.4f}",
        "",
        "--- Orbit ---",
        "Body:            Kerbin",
        f"Apoapsis:        {80000 + random.randint(-100, 100)} m",
        f"Periapsis:       {70000 + random.randint(-100, 100)} m",
        "Inclination:     0.50 deg",
        "Eccentricity:    0.0071",
        "Period:          2400.0 s",
        "",
        "--- Resources ---",
        f"Electric charge: {150.0 - t * 0.1:.1f}",
        f"Liquid fuel:     {400.0 - t * 0.5:.1f}",
        f"Oxidizer:        {480.0 - t * 0.6:.1f}",
        f"Mono propellant: {50.0:.1f}",
    ]
    return "\n".join(lines)
