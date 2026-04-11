"""Tests for the Setup screen (system readiness checklist)."""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, Static

from ksp_mission_control.screens.setup import SetupScreen


class SetupTestApp(App[None]):
    """Minimal app that pushes the SetupScreen for testing."""

    def compose(self) -> ComposeResult:
        yield from ()

    def on_mount(self) -> None:
        self.push_screen(SetupScreen())


class TestSetupScreenComposition:
    """Test that the checklist screen composes the expected widgets."""

    @pytest.mark.asyncio
    async def test_screen_mounts(self) -> None:
        """SetupScreen should mount without errors."""
        with patch(
            "ksp_mission_control.screens.setup.find_ksp_install",
            return_value=None,
        ):
            async with SetupTestApp().run_test() as pilot:
                assert isinstance(pilot.app.screen, SetupScreen)

    @pytest.mark.asyncio
    async def test_has_logo(self) -> None:
        """Should display the ASCII logo."""
        with patch(
            "ksp_mission_control.screens.setup.find_ksp_install",
            return_value=None,
        ):
            async with SetupTestApp().run_test() as pilot:
                await pilot.pause()
                logo = pilot.app.screen.query_one("#logo")
                assert logo is not None

    @pytest.mark.asyncio
    async def test_has_checklist_items(self) -> None:
        """Should have all three checklist items."""
        with patch(
            "ksp_mission_control.screens.setup.find_ksp_install",
            return_value=None,
        ):
            async with SetupTestApp().run_test() as pilot:
                await pilot.pause()
                assert pilot.app.screen.query_one("#check-krpc", Static)
                assert pilot.app.screen.query_one("#check-comms", Static)
                assert pilot.app.screen.query_one("#check-vessel", Static)

    @pytest.mark.asyncio
    async def test_has_krpc_info_button(self) -> None:
        """Should have an info button for kRPC setup."""
        with patch(
            "ksp_mission_control.screens.setup.find_ksp_install",
            return_value=None,
        ):
            async with SetupTestApp().run_test() as pilot:
                await pilot.pause()
                btn = pilot.app.screen.query_one("#krpc-info-btn", Button)
                assert btn is not None


class TestSetupScreenChecks:
    """Tests for the system check logic."""

    @pytest.mark.asyncio
    async def test_krpc_unchecked_when_not_found(self) -> None:
        """kRPC check should be unchecked when not detected."""
        with patch(
            "ksp_mission_control.screens.setup.find_ksp_install",
            return_value=None,
        ):
            async with SetupTestApp().run_test() as pilot:
                await pilot.pause()
                label = pilot.app.screen.query_one("#check-krpc", Static)
                assert "[ ]" in str(label._Static__content)

    @pytest.mark.asyncio
    async def test_krpc_checked_when_installed(self) -> None:
        """kRPC check should be checked when detected as installed."""
        fake_info = Mock()
        fake_info.has_krpc = True

        with patch(
            "ksp_mission_control.screens.setup.find_ksp_install",
            return_value=fake_info,
        ):
            async with SetupTestApp().run_test() as pilot:
                await pilot.pause()
                label = pilot.app.screen.query_one("#check-krpc", Static)
                assert "[x]" in str(label._Static__content)

    @pytest.mark.asyncio
    async def test_krpc_unchecked_when_ksp_found_without_krpc(self) -> None:
        """kRPC check should be unchecked when KSP found but kRPC not installed."""
        fake_info = Mock()
        fake_info.has_krpc = False

        with patch(
            "ksp_mission_control.screens.setup.find_ksp_install",
            return_value=fake_info,
        ):
            async with SetupTestApp().run_test() as pilot:
                await pilot.pause()
                label = pilot.app.screen.query_one("#check-krpc", Static)
                assert "[ ]" in str(label._Static__content)

    @pytest.mark.asyncio
    async def test_control_room_disabled_when_checks_fail(self) -> None:
        """Control Room binding should be disabled when not all checks pass."""
        with patch(
            "ksp_mission_control.screens.setup.find_ksp_install",
            return_value=None,
        ):
            async with SetupTestApp().run_test() as pilot:
                await pilot.pause()
                screen = pilot.app.screen
                assert isinstance(screen, SetupScreen)
                assert screen.check_action_control_room() is False

    @pytest.mark.asyncio
    async def test_all_checks_passed_property(self) -> None:
        """all_checks_passed should only be True when all three flags are set."""
        with patch(
            "ksp_mission_control.screens.setup.find_ksp_install",
            return_value=None,
        ):
            async with SetupTestApp().run_test() as pilot:
                await pilot.pause()
                screen = pilot.app.screen
                assert isinstance(screen, SetupScreen)
                assert screen.all_checks_passed is False

                # Even with kRPC installed, others are still false
                screen._krpc_installed = True
                assert screen.all_checks_passed is False

                screen._comms_ok = True
                screen._vessel_detected = True
                assert screen.all_checks_passed is True
