"""Tests for the Setup screen (system readiness checklist)."""

from __future__ import annotations

from typing import ClassVar

import pytest
from textual.app import App, ComposeResult
from textual.screen import Screen
from textual.widgets import ListItem, Static

from ksp_mission_control.setup.checks import CheckResult, SetupCheck
from ksp_mission_control.setup.screen import SetupScreen

# ---------------------------------------------------------------------------
# Fake checks for testing
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


class SetupTestApp(App[None]):
    """Minimal app that pushes the SetupScreen for testing."""

    def __init__(self, checks: list[SetupCheck] | None = None) -> None:
        super().__init__()
        self._checks = checks

    def compose(self) -> ComposeResult:
        yield from ()

    def on_mount(self) -> None:
        self.push_screen(SetupScreen(checks=self._checks))


# ---------------------------------------------------------------------------
# Composition tests
# ---------------------------------------------------------------------------


class TestSetupScreenComposition:
    """Test that the checklist screen composes the expected widgets."""

    @pytest.mark.asyncio
    async def test_screen_mounts(self) -> None:
        checks = _make_checks()
        async with SetupTestApp(checks=checks).run_test() as pilot:
            assert isinstance(pilot.app.screen, SetupScreen)

    @pytest.mark.asyncio
    async def test_has_logo(self) -> None:
        checks = _make_checks()
        async with SetupTestApp(checks=checks).run_test() as pilot:
            await pilot.pause()
            logo = pilot.app.screen.query_one("#logo")
            assert logo is not None

    @pytest.mark.asyncio
    async def test_has_checklist_items(self) -> None:
        checks = _make_checks()
        async with SetupTestApp(checks=checks).run_test() as pilot:
            await pilot.pause()
            assert pilot.app.screen.query_one("#check-krpc", ListItem)
            assert pilot.app.screen.query_one("#check-comms", ListItem)
            assert pilot.app.screen.query_one("#check-vessel", ListItem)


# ---------------------------------------------------------------------------
# Check logic tests
# ---------------------------------------------------------------------------


class TestSetupScreenChecks:
    """Tests for the system check logic."""

    @pytest.mark.asyncio
    async def test_all_fail_when_krpc_not_installed(self) -> None:
        """When kRPC check fails, later checks should not run."""
        checks = _make_checks(krpc=False)
        async with SetupTestApp(checks=checks).run_test() as pilot:
            await pilot.app.workers.wait_for_complete()
            await pilot.pause()
            screen = pilot.app.screen
            assert isinstance(screen, SetupScreen)
            assert screen.all_checks_passed is False
            # Only the first check should have run (sequential short-circuit)
            assert checks[0].run_count >= 1
            assert checks[1].run_count == 0
            assert checks[2].run_count == 0

    @pytest.mark.asyncio
    async def test_stops_at_comms_when_comms_fail(self) -> None:
        """When comms check fails, vessel check should not run."""
        checks = _make_checks(krpc=True, comms=False)
        async with SetupTestApp(checks=checks).run_test() as pilot:
            await pilot.app.workers.wait_for_complete()
            await pilot.pause()
            screen = pilot.app.screen
            assert isinstance(screen, SetupScreen)
            assert screen.all_checks_passed is False
            assert checks[0].run_count >= 1
            assert checks[1].run_count >= 1
            assert checks[2].run_count == 0

    @pytest.mark.asyncio
    async def test_all_checks_pass(self) -> None:
        """When all checks pass, all_checks_passed should be True."""
        checks = _make_checks(krpc=True, comms=True, vessel=True)
        async with SetupTestApp(checks=checks).run_test() as pilot:
            await pilot.app.workers.wait_for_complete()
            await pilot.pause()
            screen = pilot.app.screen
            assert isinstance(screen, SetupScreen)
            assert screen.all_checks_passed is True
            assert all(c.run_count >= 1 for c in checks)

    @pytest.mark.asyncio
    async def test_display_shows_checkmark_on_pass(self) -> None:
        """Passed checks should display [x]."""
        checks = _make_checks(krpc=True, comms=True, vessel=True)
        async with SetupTestApp(checks=checks).run_test() as pilot:
            await pilot.app.workers.wait_for_complete()
            await pilot.pause()
            for check in checks:
                label = pilot.app.screen.query_one(f"#{check.check_id}-label", Static)
                assert "[✓]" in str(label._Static__content)

    @pytest.mark.asyncio
    async def test_display_shows_fail_mark_on_failure(self) -> None:
        """Failed checks should display [!]."""
        checks = _make_checks(krpc=False)
        async with SetupTestApp(checks=checks).run_test() as pilot:
            await pilot.pause()
            label = pilot.app.screen.query_one("#check-krpc-label", Static)
            assert "[ ]" in str(label._Static__content)

    @pytest.mark.asyncio
    async def test_control_room_disabled_when_checks_fail(self) -> None:
        checks = _make_checks(krpc=False)
        async with SetupTestApp(checks=checks).run_test() as pilot:
            await pilot.pause()
            screen = pilot.app.screen
            assert isinstance(screen, SetupScreen)
            assert screen.check_action_control_room() is False

    @pytest.mark.asyncio
    async def test_control_room_enabled_when_all_pass(self) -> None:
        checks = _make_checks(krpc=True, comms=True, vessel=True)
        async with SetupTestApp(checks=checks).run_test() as pilot:
            await pilot.app.workers.wait_for_complete()
            await pilot.pause()
            screen = pilot.app.screen
            assert isinstance(screen, SetupScreen)
            assert screen.check_action_control_room() is True


# ---------------------------------------------------------------------------
# Unit tests for individual checks
# ---------------------------------------------------------------------------


class TestCheckResults:
    """Test the CheckResult and FakeCheck behavior."""

    def test_check_result_passed(self) -> None:
        r = CheckResult(passed=True, message="ok")
        assert r.passed is True
        assert r.message == "ok"

    def test_check_result_failed(self) -> None:
        r = CheckResult(passed=False, message="nope")
        assert r.passed is False

    def test_fake_check_tracks_run_count(self) -> None:
        c = FakeCheck("test", "Test", passed=True)
        assert c.run_count == 0
        c.run()
        assert c.run_count == 1
        c.run()
        assert c.run_count == 2
