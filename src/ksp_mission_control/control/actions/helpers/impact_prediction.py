"""Pure-Python bisection for predicting where a trajectory hits the ground.

Used by the bridge to populate ``State.predicted_impact``. The bridge wires
kRPC orbit/body queries into the two callables this helper accepts; the
helper itself has no kRPC dependency so it is fully unit-testable with
synthetic functions.

The prediction is ballistic: we search for the first universal time at
which the trajectory's altitude above sea level falls to zero. Terrain
height at the resulting lat/lon is reported separately so callers can
account for impacts on mountains or below sea level (oceans).

Atmospheric drag is not modelled. Real impacts land *short* of the ballistic
prediction once the trajectory enters atmosphere. Action layers should
expose a ``drag_bias`` knob to offset the target position rather than
trying to model drag here.
"""

from __future__ import annotations

from collections.abc import Callable

# Bisection iterations. 30 iterations narrow the impact UT to about
# ``period / 2**30`` precision. For a 30-minute orbit that is microseconds,
# orders of magnitude finer than terrain resolution.
_BISECTION_ITERATIONS: int = 30


def find_impact_ut(
    sample_altitude_at: Callable[[float], float],
    start_ut: float,
    end_ut: float,
    iterations: int = _BISECTION_ITERATIONS,
) -> float | None:
    """Return the universal time at which altitude first crosses sea level.

    ``sample_altitude_at(ut)`` must return the trajectory's altitude above
    sea level (in meters) at the given universal time.

    Returns the UT of the crossing, or ``None`` when the trajectory stays
    above sea level for the entire ``[start_ut, end_ut]`` window. When the
    trajectory is already below sea level at ``start_ut`` (e.g. we are
    inside terrain), ``start_ut`` itself is returned.

    The search assumes altitude is monotone-ish across the window: at most
    one descending crossing of sea level. The bridge enforces this by
    capping the window at ``time_to_periapsis``, where the orbit reaches
    its lowest point.
    """
    alt_start = sample_altitude_at(start_ut)
    if alt_start <= 0.0:
        return start_ut

    alt_end = sample_altitude_at(end_ut)
    if alt_end > 0.0:
        # No crossing within the window: trajectory does not impact.
        return None

    lo, hi = start_ut, end_ut
    for _ in range(iterations):
        mid = (lo + hi) / 2.0
        if sample_altitude_at(mid) > 0.0:
            lo = mid
        else:
            hi = mid
    return hi
