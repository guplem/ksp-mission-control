"""Tests for ManualCommandDialog - manual one-shot vessel command dialog."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input, Select

from ksp_mission_control.control.actions.base import SASMode, SpeedMode, VesselCommands
from ksp_mission_control.control.manual_command_dialog import ManualCommandDialog

# ---------------------------------------------------------------------------
# Test app
# ---------------------------------------------------------------------------


class ManualCommandTestApp(App[None]):
    """Pushes ManualCommandDialog for testing."""

    def __init__(self) -> None:
        super().__init__()
        self.dismissed_value: VesselCommands | None = "NOT_SET"  # type: ignore[assignment]

    def compose(self) -> ComposeResult:
        yield from ()

    def on_mount(self) -> None:
        self.push_screen(
            ManualCommandDialog(),
            callback=self._on_dismiss,
        )

    def _on_dismiss(self, result: VesselCommands | None) -> None:
        self.dismissed_value = result


# ---------------------------------------------------------------------------
# Tests: Composition
# ---------------------------------------------------------------------------


class TestManualCommandDialogComposition:
    @pytest.mark.asyncio
    async def test_screen_mounts(self) -> None:
        async with ManualCommandTestApp().run_test() as pilot:
            assert isinstance(pilot.app.screen, ManualCommandDialog)

    @pytest.mark.asyncio
    async def test_has_send_button(self) -> None:
        async with ManualCommandTestApp().run_test() as pilot:
            await pilot.pause()
            btn = pilot.app.screen.query_one("#manual-cmd-send-btn")
            assert btn is not None

    @pytest.mark.asyncio
    async def test_has_cancel_button(self) -> None:
        async with ManualCommandTestApp().run_test() as pilot:
            await pilot.pause()
            btn = pilot.app.screen.query_one("#manual-cmd-cancel-btn")
            assert btn is not None

    @pytest.mark.asyncio
    async def test_has_throttle_input(self) -> None:
        async with ManualCommandTestApp().run_test() as pilot:
            await pilot.pause()
            inp = pilot.app.screen.query_one("#cmd-throttle", Input)
            assert inp is not None

    @pytest.mark.asyncio
    async def test_has_sas_select(self) -> None:
        async with ManualCommandTestApp().run_test() as pilot:
            await pilot.pause()
            sel = pilot.app.screen.query_one("#cmd-sas", Select)
            assert sel is not None

    @pytest.mark.asyncio
    async def test_has_sas_mode_select(self) -> None:
        async with ManualCommandTestApp().run_test() as pilot:
            await pilot.pause()
            sel = pilot.app.screen.query_one("#cmd-sas_mode", Select)
            assert sel is not None

    @pytest.mark.asyncio
    async def test_has_speed_mode_select(self) -> None:
        async with ManualCommandTestApp().run_test() as pilot:
            await pilot.pause()
            sel = pilot.app.screen.query_one("#cmd-speed_mode", Select)
            assert sel is not None

    @pytest.mark.asyncio
    async def test_has_stage_select(self) -> None:
        async with ManualCommandTestApp().run_test() as pilot:
            await pilot.pause()
            sel = pilot.app.screen.query_one("#cmd-stage", Select)
            assert sel is not None

    @pytest.mark.asyncio
    async def test_has_autopilot_fields(self) -> None:
        async with ManualCommandTestApp().run_test() as pilot:
            await pilot.pause()
            pilot.app.screen.query_one("#cmd-autopilot", Select)
            pilot.app.screen.query_one("#cmd-autopilot_pitch", Input)
            pilot.app.screen.query_one("#cmd-autopilot_heading", Input)
            pilot.app.screen.query_one("#cmd-autopilot_roll", Input)

    @pytest.mark.asyncio
    async def test_has_deployable_fields(self) -> None:
        async with ManualCommandTestApp().run_test() as pilot:
            await pilot.pause()
            pilot.app.screen.query_one("#cmd-solar_panels", Select)
            pilot.app.screen.query_one("#cmd-antennas", Select)
            pilot.app.screen.query_one("#cmd-parachutes", Select)
            pilot.app.screen.query_one("#cmd-radiators", Select)

    @pytest.mark.asyncio
    async def test_float_inputs_start_empty(self) -> None:
        async with ManualCommandTestApp().run_test() as pilot:
            await pilot.pause()
            inp = pilot.app.screen.query_one("#cmd-throttle", Input)
            assert inp.value == ""

    @pytest.mark.asyncio
    async def test_bool_selects_start_blank(self) -> None:
        async with ManualCommandTestApp().run_test() as pilot:
            await pilot.pause()
            sel = pilot.app.screen.query_one("#cmd-sas", Select)
            assert sel.is_blank()


# ---------------------------------------------------------------------------
# Tests: Send flow
# ---------------------------------------------------------------------------


class TestManualCommandDialogSend:
    @pytest.mark.asyncio
    async def test_send_with_no_changes_returns_empty_commands(self) -> None:
        """All fields unset should return VesselCommands with all None."""
        app = ManualCommandTestApp()
        async with app.run_test(size=(80, 60)) as pilot:
            await pilot.pause()
            await pilot.click("#manual-cmd-send-btn")
            await pilot.pause()
            assert isinstance(app.dismissed_value, VesselCommands)
            assert app.dismissed_value == VesselCommands()

    @pytest.mark.asyncio
    async def test_send_with_throttle_set(self) -> None:
        app = ManualCommandTestApp()
        async with app.run_test(size=(80, 60)) as pilot:
            await pilot.pause()
            inp = pilot.app.screen.query_one("#cmd-throttle", Input)
            inp.value = "0.75"
            await pilot.click("#manual-cmd-send-btn")
            await pilot.pause()
            assert isinstance(app.dismissed_value, VesselCommands)
            assert app.dismissed_value.throttle == 0.75

    @pytest.mark.asyncio
    async def test_send_with_bool_on(self) -> None:
        app = ManualCommandTestApp()
        async with app.run_test(size=(80, 60)) as pilot:
            await pilot.pause()
            sel = pilot.app.screen.query_one("#cmd-sas", Select)
            sel.value = "on"
            await pilot.click("#manual-cmd-send-btn")
            await pilot.pause()
            assert isinstance(app.dismissed_value, VesselCommands)
            assert app.dismissed_value.sas is True

    @pytest.mark.asyncio
    async def test_send_with_bool_off(self) -> None:
        app = ManualCommandTestApp()
        async with app.run_test(size=(80, 60)) as pilot:
            await pilot.pause()
            sel = pilot.app.screen.query_one("#cmd-rcs", Select)
            sel.value = "off"
            await pilot.click("#manual-cmd-send-btn")
            await pilot.pause()
            assert isinstance(app.dismissed_value, VesselCommands)
            assert app.dismissed_value.rcs is False

    @pytest.mark.asyncio
    async def test_send_with_sas_mode(self) -> None:
        app = ManualCommandTestApp()
        async with app.run_test(size=(80, 60)) as pilot:
            await pilot.pause()
            sel = pilot.app.screen.query_one("#cmd-sas_mode", Select)
            sel.value = SASMode.PROGRADE.value
            await pilot.click("#manual-cmd-send-btn")
            await pilot.pause()
            assert isinstance(app.dismissed_value, VesselCommands)
            assert app.dismissed_value.sas_mode == SASMode.PROGRADE

    @pytest.mark.asyncio
    async def test_send_with_speed_mode(self) -> None:
        app = ManualCommandTestApp()
        async with app.run_test(size=(80, 60)) as pilot:
            await pilot.pause()
            sel = pilot.app.screen.query_one("#cmd-speed_mode", Select)
            sel.value = SpeedMode.SURFACE.value
            await pilot.click("#manual-cmd-send-btn")
            await pilot.pause()
            assert isinstance(app.dismissed_value, VesselCommands)
            assert app.dismissed_value.speed_mode == SpeedMode.SURFACE

    @pytest.mark.asyncio
    async def test_send_with_multiple_fields(self) -> None:
        app = ManualCommandTestApp()
        async with app.run_test(size=(80, 60)) as pilot:
            await pilot.pause()
            # Set throttle
            inp = pilot.app.screen.query_one("#cmd-throttle", Input)
            inp.value = "0.5"
            # Set SAS on
            sel = pilot.app.screen.query_one("#cmd-sas", Select)
            sel.value = "on"
            # Set gear on
            gear_sel = pilot.app.screen.query_one("#cmd-gear", Select)
            gear_sel.value = "on"
            await pilot.click("#manual-cmd-send-btn")
            await pilot.pause()
            assert isinstance(app.dismissed_value, VesselCommands)
            assert app.dismissed_value.throttle == 0.5
            assert app.dismissed_value.sas is True
            assert app.dismissed_value.gear is True
            # Other fields remain None
            assert app.dismissed_value.rcs is None
            assert app.dismissed_value.lights is None

    @pytest.mark.asyncio
    async def test_send_rejects_non_numeric_float(self) -> None:
        app = ManualCommandTestApp()
        async with app.run_test(size=(80, 60)) as pilot:
            await pilot.pause()
            inp = pilot.app.screen.query_one("#cmd-throttle", Input)
            inp.value = "abc"
            await pilot.click("#manual-cmd-send-btn")
            await pilot.pause()
            # Modal should still be active
            assert isinstance(pilot.app.screen, ManualCommandDialog)
            assert app.dismissed_value == "NOT_SET"  # type: ignore[comparison-overlap]

    @pytest.mark.asyncio
    async def test_unset_fields_remain_none(self) -> None:
        """Fields not touched by the user stay None in the result."""
        app = ManualCommandTestApp()
        async with app.run_test(size=(80, 60)) as pilot:
            await pilot.pause()
            inp = pilot.app.screen.query_one("#cmd-throttle", Input)
            inp.value = "1.0"
            await pilot.click("#manual-cmd-send-btn")
            await pilot.pause()
            assert isinstance(app.dismissed_value, VesselCommands)
            assert app.dismissed_value.throttle == 1.0
            assert app.dismissed_value.stage is None
            assert app.dismissed_value.sas is None
            assert app.dismissed_value.input_pitch is None
            assert app.dismissed_value.solar_panels is None

    @pytest.mark.asyncio
    async def test_send_stage_true(self) -> None:
        app = ManualCommandTestApp()
        async with app.run_test(size=(80, 60)) as pilot:
            await pilot.pause()
            sel = pilot.app.screen.query_one("#cmd-stage", Select)
            sel.value = "on"
            await pilot.click("#manual-cmd-send-btn")
            await pilot.pause()
            assert isinstance(app.dismissed_value, VesselCommands)
            assert app.dismissed_value.stage is True

    @pytest.mark.asyncio
    async def test_send_autopilot_pitch(self) -> None:
        app = ManualCommandTestApp()
        async with app.run_test(size=(80, 60)) as pilot:
            await pilot.pause()
            inp = pilot.app.screen.query_one("#cmd-autopilot_pitch", Input)
            inp.value = "45.0"
            await pilot.click("#manual-cmd-send-btn")
            await pilot.pause()
            assert isinstance(app.dismissed_value, VesselCommands)
            assert app.dismissed_value.autopilot_pitch == 45.0

    @pytest.mark.asyncio
    async def test_send_deployable_on(self) -> None:
        app = ManualCommandTestApp()
        async with app.run_test(size=(80, 60)) as pilot:
            await pilot.pause()
            sel = pilot.app.screen.query_one("#cmd-solar_panels", Select)
            sel.value = "on"
            await pilot.click("#manual-cmd-send-btn")
            await pilot.pause()
            assert isinstance(app.dismissed_value, VesselCommands)
            assert app.dismissed_value.solar_panels is True


# ---------------------------------------------------------------------------
# Tests: Cancel flow
# ---------------------------------------------------------------------------


class TestManualCommandDialogCancel:
    @pytest.mark.asyncio
    async def test_cancel_button_dismisses_with_none(self) -> None:
        app = ManualCommandTestApp()
        async with app.run_test(size=(80, 60)) as pilot:
            await pilot.pause()
            await pilot.click("#manual-cmd-cancel-btn")
            await pilot.pause()
            assert app.dismissed_value is None

    @pytest.mark.asyncio
    async def test_escape_dismisses_with_none(self) -> None:
        app = ManualCommandTestApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert app.dismissed_value is None
