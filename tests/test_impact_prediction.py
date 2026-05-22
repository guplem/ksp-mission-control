"""Tests for the impact_prediction bisection helper."""

from __future__ import annotations

from ksp_mission_control.control.actions.helpers.impact_prediction import find_impact_ut


class TestFindImpactUt:
    """The helper bisects for the first sea-level crossing in a UT window."""

    def test_returns_start_when_already_below_sea_level(self) -> None:
        # Altitude is already <= 0 at start: bridge interprets this as
        # impact already happened, returns start_ut without bisecting.
        result = find_impact_ut(lambda _ut: -100.0, start_ut=0.0, end_ut=100.0)
        assert result == 0.0

    def test_returns_none_when_no_crossing_in_window(self) -> None:
        # Trajectory stays above sea level the whole window: no impact.
        result = find_impact_ut(lambda _ut: 5000.0, start_ut=0.0, end_ut=100.0)
        assert result is None

    def test_bisects_linear_descent(self) -> None:
        # A linear altitude profile from +1000 at t=0 to -1000 at t=100
        # crosses zero at t=50.
        def altitude(ut: float) -> float:
            return 1000.0 - 20.0 * ut

        result = find_impact_ut(altitude, start_ut=0.0, end_ut=100.0)
        assert result is not None
        assert abs(result - 50.0) < 0.01

    def test_bisects_quadratic_descent(self) -> None:
        # Parabolic descent: altitude = 1_000_000 - (ut - 0)^2 * 100.
        # Crosses zero at ut = 100.
        def altitude(ut: float) -> float:
            return 1_000_000.0 - (ut**2) * 100.0

        result = find_impact_ut(altitude, start_ut=0.0, end_ut=200.0)
        assert result is not None
        assert abs(result - 100.0) < 0.01

    def test_iterations_param_controls_precision(self) -> None:
        # Crossing at ut = 200/3 ≈ 66.67, which the bisection cannot hit
        # exactly with binary midpoints. Verifies more iterations refines the
        # answer.
        def altitude(ut: float) -> float:
            return 200.0 - 3.0 * ut

        coarse = find_impact_ut(altitude, start_ut=0.0, end_ut=100.0, iterations=5)
        fine = find_impact_ut(altitude, start_ut=0.0, end_ut=100.0, iterations=40)
        assert coarse is not None and fine is not None
        target = 200.0 / 3.0
        assert abs(fine - target) < abs(coarse - target)
        assert abs(fine - target) < 1e-6

    def test_returns_upper_bound_when_crossing_exactly_at_end(self) -> None:
        # Edge case: altitude reaches exactly zero at end_ut. The helper
        # treats end_ut <= 0 as "below sea level here", which is correct
        # for impact prediction.
        def altitude(ut: float) -> float:
            return 100.0 - ut

        result = find_impact_ut(altitude, start_ut=0.0, end_ut=100.0)
        assert result is not None
        # Either 100 exactly or very close due to bisection.
        assert abs(result - 100.0) < 1e-3
