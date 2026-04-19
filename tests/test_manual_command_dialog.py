"""Tests for ManualCommandDialog - manual one-shot vessel command dialog."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input, Select

from ksp_mission_control.control.actions.base import (
    AutopilotConfig,
    AutopilotDirection,
    ReferenceFrame,
    SASMode,
    SpeedMode,
    VesselCommands,
)
from ksp_mission_control.control.manual_command_dialog import ManualCommandDialog, _parse_tuple3

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
            sel = pilot.app.screen.query_one("#cmd-ui_speed_mode", Select)
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
            pilot.app.screen.query_one("#cmd-deployable_solar_panels", Select)
            pilot.app.screen.query_one("#cmd-deployable_antennas", Select)
            pilot.app.screen.query_one("#cmd-deployable_parachutes", Select)
            pilot.app.screen.query_one("#cmd-deployable_radiators", Select)

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
            sel = pilot.app.screen.query_one("#cmd-ui_speed_mode", Select)
            sel.value = SpeedMode.SURFACE.value
            await pilot.click("#manual-cmd-send-btn")
            await pilot.pause()
            assert isinstance(app.dismissed_value, VesselCommands)
            assert app.dismissed_value.ui_speed_mode == SpeedMode.SURFACE

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
            assert app.dismissed_value.deployable_solar_panels is None

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
            sel = pilot.app.screen.query_one("#cmd-deployable_solar_panels", Select)
            sel.value = "on"
            await pilot.click("#manual-cmd-send-btn")
            await pilot.pause()
            assert isinstance(app.dismissed_value, VesselCommands)
            assert app.dismissed_value.deployable_solar_panels is True


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


# ---------------------------------------------------------------------------
# Tests: _parse_tuple3 helper
# ---------------------------------------------------------------------------


class TestParseTuple3:
    def test_valid_three_values(self) -> None:
        assert _parse_tuple3("1.0, 2.0, 3.0") == (1.0, 2.0, 3.0)

    def test_no_spaces(self) -> None:
        assert _parse_tuple3("1,2,3") == (1.0, 2.0, 3.0)

    def test_extra_spaces(self) -> None:
        assert _parse_tuple3("  1.5 , 2.5 , 3.5  ") == (1.5, 2.5, 3.5)

    def test_two_values_raises(self) -> None:
        with pytest.raises(ValueError, match="3 comma-separated"):
            _parse_tuple3("1.0, 2.0")

    def test_non_numeric_raises(self) -> None:
        with pytest.raises(ValueError):
            _parse_tuple3("a, b, c")


# ---------------------------------------------------------------------------
# Tests: Autopilot Direction (composite field)
# ---------------------------------------------------------------------------


class TestManualCommandDialogAutopilotDirection:
    @pytest.mark.asyncio
    async def test_has_direction_vector_inputs(self) -> None:
        async with ManualCommandTestApp().run_test() as pilot:
            await pilot.pause()
            pilot.app.screen.query_one("#cmd-ap_dir_x", Input)
            pilot.app.screen.query_one("#cmd-ap_dir_y", Input)
            pilot.app.screen.query_one("#cmd-ap_dir_z", Input)

    @pytest.mark.asyncio
    async def test_has_reference_frame_select(self) -> None:
        async with ManualCommandTestApp().run_test() as pilot:
            await pilot.pause()
            pilot.app.screen.query_one("#cmd-ap_dir_frame", Select)

    @pytest.mark.asyncio
    async def test_all_empty_skips_direction(self) -> None:
        app = ManualCommandTestApp()
        async with app.run_test(size=(80, 60)) as pilot:
            await pilot.pause()
            await pilot.click("#manual-cmd-send-btn")
            await pilot.pause()
            assert isinstance(app.dismissed_value, VesselCommands)
            assert app.dismissed_value.autopilot_direction is None

    @pytest.mark.asyncio
    async def test_full_direction_set(self) -> None:
        app = ManualCommandTestApp()
        async with app.run_test(size=(80, 80)) as pilot:
            await pilot.pause()
            pilot.app.screen.query_one("#cmd-ap_dir_x", Input).value = "1.0"
            pilot.app.screen.query_one("#cmd-ap_dir_y", Input).value = "0.0"
            pilot.app.screen.query_one("#cmd-ap_dir_z", Input).value = "0.0"
            pilot.app.screen.query_one("#cmd-ap_dir_frame", Select).value = ReferenceFrame.VESSEL_ORBITAL.value
            await pilot.click("#manual-cmd-send-btn")
            await pilot.pause()
            assert isinstance(app.dismissed_value, VesselCommands)
            expected = AutopilotDirection(
                vector=(1.0, 0.0, 0.0),
                reference_frame=ReferenceFrame.VESSEL_ORBITAL,
            )
            assert app.dismissed_value.autopilot_direction == expected

    @pytest.mark.asyncio
    async def test_partial_direction_rejects(self) -> None:
        """Setting only some vector fields should show an error."""
        app = ManualCommandTestApp()
        async with app.run_test(size=(80, 80)) as pilot:
            await pilot.pause()
            pilot.app.screen.query_one("#cmd-ap_dir_x", Input).value = "1.0"
            # y and z empty, frame empty
            await pilot.click("#manual-cmd-send-btn")
            await pilot.pause()
            assert isinstance(pilot.app.screen, ManualCommandDialog)
            assert app.dismissed_value == "NOT_SET"  # type: ignore[comparison-overlap]

    @pytest.mark.asyncio
    async def test_non_numeric_vector_rejects(self) -> None:
        app = ManualCommandTestApp()
        async with app.run_test(size=(80, 80)) as pilot:
            await pilot.pause()
            pilot.app.screen.query_one("#cmd-ap_dir_x", Input).value = "abc"
            pilot.app.screen.query_one("#cmd-ap_dir_y", Input).value = "0.0"
            pilot.app.screen.query_one("#cmd-ap_dir_z", Input).value = "0.0"
            pilot.app.screen.query_one("#cmd-ap_dir_frame", Select).value = ReferenceFrame.VESSEL_SURFACE.value
            await pilot.click("#manual-cmd-send-btn")
            await pilot.pause()
            assert isinstance(pilot.app.screen, ManualCommandDialog)
            assert app.dismissed_value == "NOT_SET"  # type: ignore[comparison-overlap]


# ---------------------------------------------------------------------------
# Tests: Autopilot Config (composite field)
# ---------------------------------------------------------------------------


class TestManualCommandDialogAutopilotConfig:
    @pytest.mark.asyncio
    async def test_has_auto_tune_select(self) -> None:
        async with ManualCommandTestApp().run_test() as pilot:
            await pilot.pause()
            pilot.app.screen.query_one("#cmd-ap_cfg_auto_tune", Select)

    @pytest.mark.asyncio
    async def test_has_tuple_inputs(self) -> None:
        async with ManualCommandTestApp().run_test() as pilot:
            await pilot.pause()
            pilot.app.screen.query_one("#cmd-ap_cfg_time_to_peak", Input)
            pilot.app.screen.query_one("#cmd-ap_cfg_overshoot", Input)
            pilot.app.screen.query_one("#cmd-ap_cfg_stopping_time", Input)
            pilot.app.screen.query_one("#cmd-ap_cfg_deceleration_time", Input)
            pilot.app.screen.query_one("#cmd-ap_cfg_attenuation_angle", Input)

    @pytest.mark.asyncio
    async def test_has_roll_threshold_input(self) -> None:
        async with ManualCommandTestApp().run_test() as pilot:
            await pilot.pause()
            pilot.app.screen.query_one("#cmd-ap_cfg_roll_threshold", Input)

    @pytest.mark.asyncio
    async def test_has_pid_inputs(self) -> None:
        async with ManualCommandTestApp().run_test() as pilot:
            await pilot.pause()
            pilot.app.screen.query_one("#cmd-ap_cfg_pitch_pid_gains", Input)
            pilot.app.screen.query_one("#cmd-ap_cfg_yaw_pid_gains", Input)
            pilot.app.screen.query_one("#cmd-ap_cfg_roll_pid_gains", Input)

    @pytest.mark.asyncio
    async def test_all_empty_skips_config(self) -> None:
        app = ManualCommandTestApp()
        async with app.run_test(size=(80, 60)) as pilot:
            await pilot.pause()
            await pilot.click("#manual-cmd-send-btn")
            await pilot.pause()
            assert isinstance(app.dismissed_value, VesselCommands)
            assert app.dismissed_value.autopilot_config is None

    @pytest.mark.asyncio
    async def test_auto_tune_only_builds_config(self) -> None:
        app = ManualCommandTestApp()
        async with app.run_test(size=(80, 80)) as pilot:
            await pilot.pause()
            pilot.app.screen.query_one("#cmd-ap_cfg_auto_tune", Select).value = "off"
            await pilot.click("#manual-cmd-send-btn")
            await pilot.pause()
            assert isinstance(app.dismissed_value, VesselCommands)
            cfg = app.dismissed_value.autopilot_config
            assert isinstance(cfg, AutopilotConfig)
            assert cfg.auto_tune is False

    @pytest.mark.asyncio
    async def test_config_with_tuple_field(self) -> None:
        app = ManualCommandTestApp()
        async with app.run_test(size=(80, 80)) as pilot:
            await pilot.pause()
            pilot.app.screen.query_one("#cmd-ap_cfg_time_to_peak", Input).value = "1.0, 1.0, 1.0"
            await pilot.click("#manual-cmd-send-btn")
            await pilot.pause()
            assert isinstance(app.dismissed_value, VesselCommands)
            cfg = app.dismissed_value.autopilot_config
            assert isinstance(cfg, AutopilotConfig)
            assert cfg.time_to_peak == (1.0, 1.0, 1.0)

    @pytest.mark.asyncio
    async def test_config_with_pid_gains(self) -> None:
        app = ManualCommandTestApp()
        async with app.run_test(size=(80, 80)) as pilot:
            await pilot.pause()
            pilot.app.screen.query_one("#cmd-ap_cfg_auto_tune", Select).value = "off"
            pilot.app.screen.query_one("#cmd-ap_cfg_pitch_pid_gains", Input).value = "2.0, 0.0, 0.5"
            await pilot.click("#manual-cmd-send-btn")
            await pilot.pause()
            assert isinstance(app.dismissed_value, VesselCommands)
            cfg = app.dismissed_value.autopilot_config
            assert isinstance(cfg, AutopilotConfig)
            assert cfg.auto_tune is False
            assert cfg.pitch_pid_gains == (2.0, 0.0, 0.5)

    @pytest.mark.asyncio
    async def test_config_with_roll_threshold(self) -> None:
        app = ManualCommandTestApp()
        async with app.run_test(size=(80, 80)) as pilot:
            await pilot.pause()
            pilot.app.screen.query_one("#cmd-ap_cfg_roll_threshold", Input).value = "10.0"
            await pilot.click("#manual-cmd-send-btn")
            await pilot.pause()
            assert isinstance(app.dismissed_value, VesselCommands)
            cfg = app.dismissed_value.autopilot_config
            assert isinstance(cfg, AutopilotConfig)
            assert cfg.roll_threshold == 10.0

    @pytest.mark.asyncio
    async def test_invalid_tuple_rejects(self) -> None:
        app = ManualCommandTestApp()
        async with app.run_test(size=(80, 80)) as pilot:
            await pilot.pause()
            pilot.app.screen.query_one("#cmd-ap_cfg_time_to_peak", Input).value = "1.0, 2.0"
            await pilot.click("#manual-cmd-send-btn")
            await pilot.pause()
            assert isinstance(pilot.app.screen, ManualCommandDialog)
            assert app.dismissed_value == "NOT_SET"  # type: ignore[comparison-overlap]

    @pytest.mark.asyncio
    async def test_invalid_roll_threshold_rejects(self) -> None:
        app = ManualCommandTestApp()
        async with app.run_test(size=(80, 80)) as pilot:
            await pilot.pause()
            pilot.app.screen.query_one("#cmd-ap_cfg_roll_threshold", Input).value = "abc"
            await pilot.click("#manual-cmd-send-btn")
            await pilot.pause()
            assert isinstance(pilot.app.screen, ManualCommandDialog)
            assert app.dismissed_value == "NOT_SET"  # type: ignore[comparison-overlap]
