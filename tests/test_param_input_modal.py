"""Tests for ParamInputModal - parameter collection before action start."""

from __future__ import annotations

from typing import Any, ClassVar

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input

from ksp_mission_control.control.actions.base import (
    Action,
    ActionParam,
    ActionResult,
    ActionStatus,
    VesselCommands,
    VesselState,
)
from ksp_mission_control.control.param_input_modal import ParamInputModal

# ---------------------------------------------------------------------------
# Stub actions for testing
# ---------------------------------------------------------------------------


class SingleParamAction(Action):
    """Action with one optional param (has default)."""

    action_id: ClassVar[str] = "single"
    label: ClassVar[str] = "Single Param"
    description: ClassVar[str] = "Action with one optional param"
    params: ClassVar[list[ActionParam]] = [
        ActionParam(
            param_id="altitude",
            label="Altitude",
            description="Target altitude",
            required=False,
            default=100.0,
            unit="m",
        ),
    ]

    def start(self, param_values: dict[str, Any]) -> None:
        pass

    def tick(self, state: VesselState, controls: VesselCommands, dt: float) -> ActionResult:
        return ActionResult(status=ActionStatus.RUNNING)


class MultiParamAction(Action):
    """Action with multiple params, including a required one."""

    action_id: ClassVar[str] = "multi"
    label: ClassVar[str] = "Multi Param"
    description: ClassVar[str] = "Action with multiple params"
    params: ClassVar[list[ActionParam]] = [
        ActionParam(
            param_id="speed",
            label="Speed",
            description="Target speed",
            required=True,
            unit="m/s",
        ),
        ActionParam(
            param_id="duration",
            label="Duration",
            description="How long to run",
            required=False,
            default=30.0,
            unit="s",
        ),
    ]

    def start(self, param_values: dict[str, Any]) -> None:
        pass

    def tick(self, state: VesselState, controls: VesselCommands, dt: float) -> ActionResult:
        return ActionResult(status=ActionStatus.RUNNING)


class NoParamAction(Action):
    """Action with no params at all."""

    action_id: ClassVar[str] = "noparam"
    label: ClassVar[str] = "No Params"
    description: ClassVar[str] = "Action with no parameters"
    params: ClassVar[list[ActionParam]] = []

    def start(self, param_values: dict[str, Any]) -> None:
        pass

    def tick(self, state: VesselState, controls: VesselCommands, dt: float) -> ActionResult:
        return ActionResult(status=ActionStatus.RUNNING)


# ---------------------------------------------------------------------------
# Test apps
# ---------------------------------------------------------------------------


class SingleParamTestApp(App[None]):
    """Pushes ParamInputModal with a single-param action."""

    def __init__(self) -> None:
        super().__init__()
        self.dismissed_value: dict[str, float] | None = "NOT_SET"  # type: ignore[assignment]

    def compose(self) -> ComposeResult:
        yield from ()

    def on_mount(self) -> None:
        self.push_screen(
            ParamInputModal(SingleParamAction()),
            callback=self._on_dismiss,
        )

    def _on_dismiss(self, result: dict[str, float] | None) -> None:
        self.dismissed_value = result


class MultiParamTestApp(App[None]):
    """Pushes ParamInputModal with a multi-param action."""

    def __init__(self) -> None:
        super().__init__()
        self.dismissed_value: dict[str, float] | None = "NOT_SET"  # type: ignore[assignment]

    def compose(self) -> ComposeResult:
        yield from ()

    def on_mount(self) -> None:
        self.push_screen(
            ParamInputModal(MultiParamAction()),
            callback=self._on_dismiss,
        )

    def _on_dismiss(self, result: dict[str, float] | None) -> None:
        self.dismissed_value = result


class NoParamTestApp(App[None]):
    """Pushes ParamInputModal with a no-param action."""

    def __init__(self) -> None:
        super().__init__()
        self.dismissed_value: dict[str, float] | None = "NOT_SET"  # type: ignore[assignment]

    def compose(self) -> ComposeResult:
        yield from ()

    def on_mount(self) -> None:
        self.push_screen(
            ParamInputModal(NoParamAction()),
            callback=self._on_dismiss,
        )

    def _on_dismiss(self, result: dict[str, float] | None) -> None:
        self.dismissed_value = result


# ---------------------------------------------------------------------------
# Tests: Composition
# ---------------------------------------------------------------------------


class TestParamInputModalComposition:
    @pytest.mark.asyncio
    async def test_screen_mounts(self) -> None:
        async with SingleParamTestApp().run_test() as pilot:
            assert isinstance(pilot.app.screen, ParamInputModal)

    @pytest.mark.asyncio
    async def test_shows_action_label(self) -> None:
        async with SingleParamTestApp().run_test() as pilot:
            await pilot.pause()
            title = pilot.app.screen.query_one("#modal-title")
            assert "Single Param" in str(title._Static__content)

    @pytest.mark.asyncio
    async def test_has_input_for_each_param(self) -> None:
        async with SingleParamTestApp().run_test() as pilot:
            await pilot.pause()
            inp = pilot.app.screen.query_one("#param-altitude", Input)
            assert inp is not None

    @pytest.mark.asyncio
    async def test_multi_param_has_all_inputs(self) -> None:
        async with MultiParamTestApp().run_test() as pilot:
            await pilot.pause()
            speed = pilot.app.screen.query_one("#param-speed", Input)
            duration = pilot.app.screen.query_one("#param-duration", Input)
            assert speed is not None
            assert duration is not None

    @pytest.mark.asyncio
    async def test_prefills_default_values(self) -> None:
        async with SingleParamTestApp().run_test() as pilot:
            await pilot.pause()
            inp = pilot.app.screen.query_one("#param-altitude", Input)
            assert inp.value == "100.0"

    @pytest.mark.asyncio
    async def test_required_param_no_default_is_empty(self) -> None:
        async with MultiParamTestApp().run_test() as pilot:
            await pilot.pause()
            speed = pilot.app.screen.query_one("#param-speed", Input)
            assert speed.value == ""

    @pytest.mark.asyncio
    async def test_optional_param_prefilled(self) -> None:
        async with MultiParamTestApp().run_test() as pilot:
            await pilot.pause()
            duration = pilot.app.screen.query_one("#param-duration", Input)
            assert duration.value == "30.0"

    @pytest.mark.asyncio
    async def test_shows_unit_in_label(self) -> None:
        async with SingleParamTestApp().run_test() as pilot:
            await pilot.pause()
            # The label for altitude should contain the unit "m"
            labels = pilot.app.screen.query(".param-label")
            found = any("m" in str(label._Static__content) for label in labels)
            assert found

    @pytest.mark.asyncio
    async def test_has_confirm_button(self) -> None:
        async with SingleParamTestApp().run_test() as pilot:
            await pilot.pause()
            btn = pilot.app.screen.query_one("#confirm-btn")
            assert btn is not None

    @pytest.mark.asyncio
    async def test_has_cancel_button(self) -> None:
        async with SingleParamTestApp().run_test() as pilot:
            await pilot.pause()
            btn = pilot.app.screen.query_one("#cancel-btn")
            assert btn is not None

    @pytest.mark.asyncio
    async def test_no_params_shows_no_inputs(self) -> None:
        async with NoParamTestApp().run_test() as pilot:
            await pilot.pause()
            inputs = pilot.app.screen.query(Input)
            assert len(inputs) == 0


# ---------------------------------------------------------------------------
# Tests: Submit flow
# ---------------------------------------------------------------------------


class TestParamInputModalSubmit:
    @pytest.mark.asyncio
    async def test_confirm_dismisses_with_param_values(self) -> None:
        app = SingleParamTestApp()
        async with app.run_test(size=(80, 40)) as pilot:
            await pilot.pause()
            await pilot.click("#confirm-btn")
            await pilot.pause()
            assert app.dismissed_value == {"altitude": 100.0}

    @pytest.mark.asyncio
    async def test_confirm_with_edited_value(self) -> None:
        app = SingleParamTestApp()
        async with app.run_test(size=(80, 40)) as pilot:
            await pilot.pause()
            inp = pilot.app.screen.query_one("#param-altitude", Input)
            inp.value = "250.5"
            await pilot.click("#confirm-btn")
            await pilot.pause()
            assert app.dismissed_value == {"altitude": 250.5}

    @pytest.mark.asyncio
    async def test_confirm_multi_param(self) -> None:
        app = MultiParamTestApp()
        async with app.run_test(size=(80, 40)) as pilot:
            await pilot.pause()
            speed_inp = pilot.app.screen.query_one("#param-speed", Input)
            speed_inp.value = "15.0"
            await pilot.pause()
            await pilot.click("#confirm-btn")
            await pilot.pause()
            assert app.dismissed_value == {"speed": 15.0, "duration": 30.0}

    @pytest.mark.asyncio
    async def test_confirm_no_params_dismisses_empty_dict(self) -> None:
        app = NoParamTestApp()
        async with app.run_test(size=(80, 40)) as pilot:
            await pilot.pause()
            await pilot.click("#confirm-btn")
            await pilot.pause()
            assert app.dismissed_value == {}

    @pytest.mark.asyncio
    async def test_confirm_rejects_empty_required_param(self) -> None:
        """Required param left empty should not dismiss the modal."""
        app = MultiParamTestApp()
        async with app.run_test(size=(80, 40)) as pilot:
            await pilot.pause()
            # speed is required, leave it empty
            await pilot.click("#confirm-btn")
            await pilot.pause()
            # Modal should still be active (not dismissed)
            assert isinstance(pilot.app.screen, ParamInputModal)
            assert app.dismissed_value == "NOT_SET"  # type: ignore[comparison-overlap]

    @pytest.mark.asyncio
    async def test_confirm_rejects_non_numeric_value(self) -> None:
        """Non-numeric input should not dismiss the modal."""
        app = SingleParamTestApp()
        async with app.run_test(size=(80, 40)) as pilot:
            await pilot.pause()
            inp = pilot.app.screen.query_one("#param-altitude", Input)
            inp.value = "abc"
            await pilot.click("#confirm-btn")
            await pilot.pause()
            assert isinstance(pilot.app.screen, ParamInputModal)
            assert app.dismissed_value == "NOT_SET"  # type: ignore[comparison-overlap]


# ---------------------------------------------------------------------------
# Tests: Cancel flow
# ---------------------------------------------------------------------------


class TestParamInputModalCancel:
    @pytest.mark.asyncio
    async def test_cancel_button_dismisses_with_none(self) -> None:
        app = SingleParamTestApp()
        async with app.run_test(size=(80, 40)) as pilot:
            await pilot.pause()
            await pilot.click("#cancel-btn")
            await pilot.pause()
            assert app.dismissed_value is None

    @pytest.mark.asyncio
    async def test_escape_dismisses_with_none(self) -> None:
        app = SingleParamTestApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert app.dismissed_value is None
