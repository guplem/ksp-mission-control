"""Tests for ControlPanelWidget step click navigation."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import ListView

from ksp_mission_control.control.actions.base import LogEntry, LogLevel
from ksp_mission_control.control.actions.multi_track_executor import (
    MultiTrackSnapshot,
    TrackSnapshot,
)
from ksp_mission_control.control.actions.plan_executor import PlanSnapshot, StepStatus
from ksp_mission_control.control.widgets.control_panel import ControlPanelWidget


class ControlPanelApp(App[None]):
    """Minimal app for exercising the control panel widget."""

    captured_step_clicks: list[int]

    def __init__(self) -> None:
        super().__init__()
        self.captured_step_clicks = []

    def compose(self) -> ComposeResult:
        yield ControlPanelWidget(id="control-panel")

    def on_control_panel_widget_step_clicked(self, event: ControlPanelWidget.StepClicked) -> None:
        self.captured_step_clicks.append(event.tick_id)


def _single_track_snap(statuses: list[StepStatus]) -> tuple[PlanSnapshot, MultiTrackSnapshot]:
    plan_snap = PlanSnapshot(
        plan_name="test-plan",
        current_step_index=0,
        total_steps=len(statuses),
        step_statuses=tuple(statuses),
        step_action_ids=tuple(["hover"] * len(statuses)),
        step_action_labels=tuple(["Hover"] * len(statuses)),
    )
    multi_snap = MultiTrackSnapshot(tracks=(TrackSnapshot(track_name="test-plan", plan_snapshot=plan_snap),))
    return plan_snap, multi_snap


def _multi_track_snap() -> tuple[PlanSnapshot, MultiTrackSnapshot]:
    main = PlanSnapshot(
        plan_name="main",
        current_step_index=0,
        total_steps=2,
        step_statuses=(StepStatus.RUNNING, StepStatus.PENDING),
        step_action_ids=("hover", "hover"),
        step_action_labels=("Hover", "Hover"),
    )
    side = PlanSnapshot(
        plan_name="side",
        current_step_index=0,
        total_steps=1,
        step_statuses=(StepStatus.RUNNING,),
        step_action_ids=("hover",),
        step_action_labels=("Hover",),
    )
    multi_snap = MultiTrackSnapshot(
        tracks=(
            TrackSnapshot(track_name="main", plan_snapshot=main),
            TrackSnapshot(track_name="side", plan_snapshot=side),
        ),
    )
    return main, multi_snap


class TestRecordLogs:
    """record_logs stores the first ACTION_START tick per (track, step)."""

    @pytest.mark.asyncio
    async def test_records_first_action_start(self) -> None:
        async with ControlPanelApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#control-panel", ControlPanelWidget)
            widget.record_logs(
                [LogEntry(level=LogLevel.ACTION_START, message="started", track_name=None, plan_step=1)],
                tick_id=42,
            )
            assert widget._step_start_ticks == {(None, 1): 42}

    @pytest.mark.asyncio
    async def test_first_start_wins_when_step_repeats(self) -> None:
        async with ControlPanelApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#control-panel", ControlPanelWidget)
            widget.record_logs(
                [LogEntry(level=LogLevel.ACTION_START, message="x", plan_step=1)],
                tick_id=10,
            )
            widget.record_logs(
                [LogEntry(level=LogLevel.ACTION_START, message="x", plan_step=1)],
                tick_id=99,
            )
            assert widget._step_start_ticks[(None, 1)] == 10

    @pytest.mark.asyncio
    async def test_ignores_logs_without_plan_step(self) -> None:
        async with ControlPanelApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#control-panel", ControlPanelWidget)
            widget.record_logs(
                [LogEntry(level=LogLevel.ACTION_START, message="manual")],
                tick_id=5,
            )
            assert widget._step_start_ticks == {}


class TestStepClick:
    """Highlighting a started step posts a StepClicked message."""

    @pytest.mark.asyncio
    async def test_click_started_step_posts_tick(self) -> None:
        async with ControlPanelApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#control-panel", ControlPanelWidget)
            plan_snap, multi_snap = _single_track_snap([StepStatus.SUCCEEDED, StepStatus.RUNNING])
            widget.update_plan(plan_snap, multi_snap=multi_snap)
            widget.record_logs(
                [LogEntry(level=LogLevel.ACTION_START, message="s1", plan_step=1)],
                tick_id=7,
            )
            widget.record_logs(
                [LogEntry(level=LogLevel.ACTION_START, message="s2", plan_step=2)],
                tick_id=15,
            )
            await pilot.pause()

            list_view = pilot.app.query_one("#plan-steps-list", ListView)
            list_view.index = 0  # Step 1 (SUCCEEDED)
            await pilot.pause()
            assert pilot.app.captured_step_clicks == [7]

            list_view.index = 1  # Step 2 (RUNNING)
            await pilot.pause()
            assert pilot.app.captured_step_clicks == [7, 15]

    @pytest.mark.asyncio
    async def test_click_pending_step_is_noop(self) -> None:
        async with ControlPanelApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#control-panel", ControlPanelWidget)
            plan_snap, multi_snap = _single_track_snap([StepStatus.RUNNING, StepStatus.PENDING])
            widget.update_plan(plan_snap, multi_snap=multi_snap)
            widget.record_logs(
                [LogEntry(level=LogLevel.ACTION_START, message="s1", plan_step=1)],
                tick_id=20,
            )
            await pilot.pause()

            list_view = pilot.app.query_one("#plan-steps-list", ListView)
            list_view.index = 1  # Step 2 (PENDING)
            await pilot.pause()
            assert pilot.app.captured_step_clicks == []

    @pytest.mark.asyncio
    async def test_click_step_without_recorded_start_is_noop(self) -> None:
        async with ControlPanelApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#control-panel", ControlPanelWidget)
            plan_snap, multi_snap = _single_track_snap([StepStatus.RUNNING])
            widget.update_plan(plan_snap, multi_snap=multi_snap)
            await pilot.pause()

            list_view = pilot.app.query_one("#plan-steps-list", ListView)
            list_view.index = 0
            await pilot.pause()
            assert pilot.app.captured_step_clicks == []


class TestMultiTrackHeaders:
    """Track headers in multi-track mode are not selectable."""

    @pytest.mark.asyncio
    async def test_header_items_are_disabled(self) -> None:
        async with ControlPanelApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#control-panel", ControlPanelWidget)
            primary, multi_snap = _multi_track_snap()
            widget.update_plan(primary, multi_snap=multi_snap)
            await pilot.pause()

            list_view = pilot.app.query_one("#plan-steps-list", ListView)
            # Items: [main header, main step 1, main step 2, side header, side step 1]
            assert list_view.children[0].disabled is True
            assert list_view.children[1].disabled is False
            assert list_view.children[3].disabled is True

    @pytest.mark.asyncio
    async def test_track_step_uses_track_name(self) -> None:
        async with ControlPanelApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#control-panel", ControlPanelWidget)
            primary, multi_snap = _multi_track_snap()
            widget.update_plan(primary, multi_snap=multi_snap)
            widget.record_logs(
                [LogEntry(level=LogLevel.ACTION_START, message="s", track_name="side", plan_step=1)],
                tick_id=33,
            )
            await pilot.pause()

            list_view = pilot.app.query_one("#plan-steps-list", ListView)
            list_view.index = 4  # side step 1
            await pilot.pause()
            assert pilot.app.captured_step_clicks == [33]


class TestSetFollowing:
    """set_following(True) clears the step selection."""

    @pytest.mark.asyncio
    async def test_set_following_true_clears_selection(self) -> None:
        async with ControlPanelApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#control-panel", ControlPanelWidget)
            plan_snap, multi_snap = _single_track_snap([StepStatus.RUNNING])
            widget.update_plan(plan_snap, multi_snap=multi_snap)
            widget.record_logs(
                [LogEntry(level=LogLevel.ACTION_START, message="s", plan_step=1)],
                tick_id=4,
            )
            await pilot.pause()

            list_view = pilot.app.query_one("#plan-steps-list", ListView)
            list_view.index = 0
            await pilot.pause()
            assert list_view.index == 0

            widget.set_following(False)  # navigation began
            widget.set_following(True)  # user returned to live
            await pilot.pause()
            assert list_view.index is None


class TestStatusUpdatesPreserveSelection:
    """Updating only step statuses does not rebuild the ListView."""

    @pytest.mark.asyncio
    async def test_selection_survives_status_change(self) -> None:
        async with ControlPanelApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#control-panel", ControlPanelWidget)
            running_snap, running_multi = _single_track_snap([StepStatus.RUNNING, StepStatus.PENDING])
            widget.update_plan(running_snap, multi_snap=running_multi)
            widget.record_logs(
                [LogEntry(level=LogLevel.ACTION_START, message="s", plan_step=1)],
                tick_id=12,
            )
            await pilot.pause()

            list_view = pilot.app.query_one("#plan-steps-list", ListView)
            list_view.index = 0
            await pilot.pause()
            assert list_view.index == 0

            done_snap, done_multi = _single_track_snap([StepStatus.SUCCEEDED, StepStatus.RUNNING])
            widget.update_plan(done_snap, multi_snap=done_multi)
            await pilot.pause()
            assert list_view.index == 0
