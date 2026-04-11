"""Tests for CheckRunner - sequential check execution with short-circuit."""

from __future__ import annotations

from typing import ClassVar

from textual.screen import Screen

from ksp_mission_control.setup.check_runner import CheckRunner
from ksp_mission_control.setup.checks import CheckResult, SetupCheck

# ---------------------------------------------------------------------------
# Fake check for testing
# ---------------------------------------------------------------------------


class FakeCheck(SetupCheck):
    """A check whose outcome is predetermined."""

    check_id: ClassVar[str] = ""
    label: ClassVar[str] = ""
    screen: ClassVar[type[Screen] | None] = None

    def __init__(self, check_id: str, label: str, *, passed: bool, message: str = "") -> None:
        self.check_id = check_id  # type: ignore[misc]
        self.label = label  # type: ignore[misc]
        self._passed = passed
        self._message = message
        self.run_count = 0

    def run(self) -> CheckResult:
        self.run_count += 1
        return CheckResult(passed=self._passed, message=self._message)


def _make_checks(
    *,
    krpc: bool = False,
    comms: bool = False,
    vessel: bool = False,
) -> list[FakeCheck]:
    """Create a standard set of fake checks with configurable outcomes."""
    return [
        FakeCheck("check-krpc", "kRPC installed", passed=krpc),
        FakeCheck("check-comms", "kRPC server reachable", passed=comms),
        FakeCheck("check-vessel", "Active vessel detected", passed=vessel),
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCheckRunner:
    """Test the CheckRunner logic independent of any UI."""

    def test_runs_all_checks_when_all_pass(self) -> None:
        checks = _make_checks(krpc=True, comms=True, vessel=True)
        updates: list[tuple[str, str, CheckResult | None, bool]] = []
        runner = CheckRunner(checks=checks, on_update=lambda *args: updates.append(args))

        runner.run_all()

        assert runner.all_passed is True
        assert all(c.run_count == 1 for c in checks)

    def test_short_circuits_on_first_failure(self) -> None:
        checks = _make_checks(krpc=False)
        runner = CheckRunner(checks=checks, on_update=lambda *_: None)

        runner.run_all()

        assert runner.all_passed is False
        assert checks[0].run_count == 1
        assert checks[1].run_count == 0
        assert checks[2].run_count == 0

    def test_short_circuits_on_middle_failure(self) -> None:
        checks = _make_checks(krpc=True, comms=False)
        runner = CheckRunner(checks=checks, on_update=lambda *_: None)

        runner.run_all()

        assert runner.all_passed is False
        assert checks[0].run_count == 1
        assert checks[1].run_count == 1
        assert checks[2].run_count == 0

    def test_calls_update_before_and_after_each_check(self) -> None:
        checks = _make_checks(krpc=True, comms=True, vessel=True)
        updates: list[tuple[str, str, CheckResult | None, bool]] = []
        runner = CheckRunner(checks=checks, on_update=lambda *args: updates.append(args))

        runner.run_all()

        # Each check should produce two callbacks: (running=True), then (result, running=False)
        assert len(updates) == 6
        # First check: before
        assert updates[0] == ("check-krpc", "kRPC installed", None, True)
        # First check: after (passed)
        assert updates[1][0] == "check-krpc"
        assert updates[1][2] is not None
        assert updates[1][2].passed is True
        assert updates[1][3] is False
        # Second check: before
        assert updates[2] == ("check-comms", "kRPC server reachable", None, True)
        # Pattern continues...
        assert updates[4] == ("check-vessel", "Active vessel detected", None, True)

    def test_run_all_resets_previous_results(self) -> None:
        checks = _make_checks(krpc=False)
        runner = CheckRunner(checks=checks, on_update=lambda *_: None)

        runner.run_all()
        assert runner.all_passed is False

        # Now make all checks pass and re-run
        for check in checks:
            check._passed = True  # noqa: SLF001

        runner.run_all()
        assert runner.all_passed is True

    def test_empty_checks_list(self) -> None:
        runner = CheckRunner(checks=[], on_update=lambda *_: None)

        runner.run_all()

        assert runner.all_passed is True
