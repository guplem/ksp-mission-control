"""Tests for the kRPC Setup screen."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from textual.app import App, ComposeResult

from ksp_mission_control.screens.setup import SetupScreen


class SetupTestApp(App[None]):
    """Minimal app that pushes the SetupScreen for testing."""

    def compose(self) -> ComposeResult:
        yield from ()

    def on_mount(self) -> None:
        self.push_screen(SetupScreen())


class TestSetupScreenComposition:
    """Test that the screen composes the expected widgets."""

    @pytest.mark.asyncio
    async def test_screen_mounts(self) -> None:
        """SetupScreen should mount without errors."""
        async with SetupTestApp().run_test() as pilot:
            assert isinstance(pilot.app.screen, SetupScreen)

    @pytest.mark.asyncio
    async def test_has_detect_button(self) -> None:
        """Should have a 'Detect KSP' button."""
        async with SetupTestApp().run_test() as pilot:
            await pilot.pause()
            button = pilot.app.screen.query_one("#detect-btn")
            assert button is not None

    @pytest.mark.asyncio
    async def test_has_path_input(self) -> None:
        """Should have an input for manual KSP path entry."""
        async with SetupTestApp().run_test() as pilot:
            await pilot.pause()
            inp = pilot.app.screen.query_one("#ksp-path-input")
            assert inp is not None

    @pytest.mark.asyncio
    async def test_has_install_button(self) -> None:
        """Should have an 'Install kRPC' button (initially disabled)."""
        async with SetupTestApp().run_test() as pilot:
            await pilot.pause()
            button = pilot.app.screen.query_one("#install-btn")
            assert button.disabled is True

    @pytest.mark.asyncio
    async def test_has_status_label(self) -> None:
        """Should have a status area for feedback messages."""
        async with SetupTestApp().run_test() as pilot:
            await pilot.pause()
            status = pilot.app.screen.query_one("#setup-status")
            assert status is not None


class TestSetupScreenDetection:
    """Tests for the KSP detection flow."""

    @pytest.mark.asyncio
    async def test_detect_populates_path(self) -> None:
        """Pressing Detect should populate the path input when KSP is found."""
        fake_info = Mock()
        fake_info.path = Path("/fake/ksp")
        fake_info.has_krpc = False

        with patch(
            "ksp_mission_control.screens.setup.find_ksp_install",
            return_value=fake_info,
        ):
            async with SetupTestApp().run_test() as pilot:
                await pilot.pause()
                await pilot.click("#detect-btn")
                await pilot.pause()
                inp = pilot.app.screen.query_one("#ksp-path-input")
                assert inp.value == "/fake/ksp"

    @pytest.mark.asyncio
    async def test_detect_shows_not_found(self) -> None:
        """When KSP is not found, status should report it."""
        with patch(
            "ksp_mission_control.screens.setup.find_ksp_install",
            return_value=None,
        ):
            async with SetupTestApp().run_test() as pilot:
                await pilot.pause()
                await pilot.click("#detect-btn")
                await pilot.pause()
                status = pilot.app.screen.query_one("#setup-status")
                assert "not found" in str(status._Static__content).lower()

    @pytest.mark.asyncio
    async def test_detect_enables_install_when_krpc_missing(self) -> None:
        """Install button should enable when KSP is found but kRPC is not."""
        fake_info = Mock()
        fake_info.path = Path("/fake/ksp")
        fake_info.has_krpc = False

        with patch(
            "ksp_mission_control.screens.setup.find_ksp_install",
            return_value=fake_info,
        ):
            async with SetupTestApp().run_test() as pilot:
                await pilot.pause()
                await pilot.click("#detect-btn")
                await pilot.pause()
                button = pilot.app.screen.query_one("#install-btn")
                assert button.disabled is False

    @pytest.mark.asyncio
    async def test_detect_shows_krpc_already_installed(self) -> None:
        """When kRPC is already present, status should say so."""
        fake_info = Mock()
        fake_info.path = Path("/fake/ksp")
        fake_info.has_krpc = True

        with patch(
            "ksp_mission_control.screens.setup.find_ksp_install",
            return_value=fake_info,
        ):
            async with SetupTestApp().run_test() as pilot:
                await pilot.pause()
                await pilot.click("#detect-btn")
                await pilot.pause()
                status = pilot.app.screen.query_one("#setup-status")
                assert "already installed" in str(status._Static__content).lower()


class TestSetupScreenManualPath:
    """Tests for manual KSP path entry."""

    @pytest.mark.asyncio
    async def test_valid_manual_path_enables_install(self) -> None:
        """Entering a valid KSP path manually should enable install."""
        with (
            patch(
                "ksp_mission_control.screens.setup.is_valid_ksp_install",
                return_value=True,
            ),
            patch(
                "ksp_mission_control.screens.setup.is_krpc_installed",
                return_value=False,
            ),
        ):
            async with SetupTestApp().run_test() as pilot:
                await pilot.pause()
                inp = pilot.app.screen.query_one("#ksp-path-input")
                inp.value = "/some/ksp/path"
                await pilot.click("#validate-btn")
                await pilot.pause()
                button = pilot.app.screen.query_one("#install-btn")
                assert button.disabled is False

    @pytest.mark.asyncio
    async def test_invalid_manual_path_shows_error(self) -> None:
        """Entering an invalid path should show an error."""
        with patch(
            "ksp_mission_control.screens.setup.is_valid_ksp_install",
            return_value=False,
        ):
            async with SetupTestApp().run_test() as pilot:
                await pilot.pause()
                inp = pilot.app.screen.query_one("#ksp-path-input")
                inp.value = "/not/valid"
                await pilot.click("#validate-btn")
                await pilot.pause()
                status = pilot.app.screen.query_one("#setup-status")
                assert "not a valid" in str(status._Static__content).lower()
