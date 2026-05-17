"""FlightPlanPicker - modal for selecting a .plan file."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, ListItem, ListView, Static

from ksp_mission_control.control.actions.flight_plan import (
    FlightPlan,
    FlightPlanStep,
    ParallelStep,
    parse_flight_plan,
)

_PLANS_DIR_NAME = "plans"
_FOLDER_ENTRYPOINT_STEM = "main"


def compute_plan_display_name(
    plan_file: Path,
    plans_dir: Path,
    folder_visible_counts: dict[Path, int],
) -> str:
    """Return the picker label for a single plan file.

    A plan named ``main.plan`` is collapsed to its parent folder name when
    that folder contains no other visible plans, so e.g.
    ``science/1-low-atmospheric-hop/main`` becomes
    ``science/1-low-atmospheric-hop``. All other plans keep their full
    ``folder/stem`` path.

    ``folder_visible_counts`` maps each parent folder to the number of
    plans the picker would otherwise display from it (hidden plans
    excluded).
    """
    relative = plan_file.relative_to(plans_dir)
    if plan_file.stem == _FOLDER_ENTRYPOINT_STEM and folder_visible_counts.get(plan_file.parent, 0) == 1:
        parent_relative = relative.parent
        if str(parent_relative) == ".":
            return _FOLDER_ENTRYPOINT_STEM
        return str(parent_relative).replace("\\", "/")
    return str(relative.with_suffix("")).replace("\\", "/")


class FlightPlanPicker(ModalScreen[FlightPlan | None]):
    """Modal dialog for selecting a flight plan from the plans/ directory.

    Lists all .plan files, shows their name and step count.
    Plans are re-scanned each time the dialog opens.
    Dismisses with the parsed FlightPlan or None on cancel.
    """

    AUTO_FOCUS = ""

    DEFAULT_CSS = """
    FlightPlanPicker {
        align: center middle;
    }

    #picker-container {
        width: 60;
        height: auto;
        max-height: 80%;
        padding: 1 2;
        border: solid $primary;
        background: $surface;
    }

    #picker-title {
        padding: 0 0 1 0;
    }

    #picker-listview {
        height: auto;
        max-height: 20;
    }

    #picker-error {
        color: $error;
        padding: 1 0 0 0;
    }

    #picker-empty {
        color: $text 60%;
        padding: 1 0;
    }

    #picker-buttons {
        dock: bottom;
        padding: 1 0 0 0;
        align-horizontal: right;
        height: auto;
        background: $surface;
    }

    #picker-buttons Button {
        margin-left: 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, plans_dir: Path | None = None, *, require_craft: bool = False) -> None:
        super().__init__()
        self._plans_dir = plans_dir or Path.cwd() / _PLANS_DIR_NAME
        self._parsed_plans: dict[str, FlightPlan] = {}
        self._parse_errors: dict[str, str] = {}
        self._require_craft = require_craft

    def _load_plans(self) -> None:
        """Scan the plans directory recursively for .plan files.

        Plans marked with ``@hidden`` are dropped from the listing: they can
        still be spawned via ``@parallel`` from another plan, but they are
        not directly selectable from the picker.

        When ``require_craft`` is True, plans without an ``@craft`` directive
        are dropped from the listing entirely.

        Display names are computed via ``compute_plan_display_name``, which
        collapses ``folder/main`` to ``folder`` when ``main`` is the sole
        visible entry-point of its folder.
        """
        self._parsed_plans.clear()
        self._parse_errors.clear()
        if not self._plans_dir.is_dir():
            return

        parsed_by_path: dict[Path, FlightPlan] = {}
        for plan_file in sorted(self._plans_dir.rglob("*.plan")):
            relative = plan_file.relative_to(self._plans_dir)
            fallback_key = str(relative.with_suffix("")).replace("\\", "/")
            try:
                plan = parse_flight_plan(plan_file)
            except ValueError as exc:
                self._parse_errors[fallback_key] = str(exc)
                continue
            if plan.is_hidden:
                continue
            if self._require_craft and plan.craft is None:
                continue
            parsed_by_path[plan_file] = plan

        folder_visible_counts: dict[Path, int] = {}
        for plan_file in parsed_by_path:
            folder_visible_counts[plan_file.parent] = folder_visible_counts.get(plan_file.parent, 0) + 1

        for plan_file, plan in parsed_by_path.items():
            display_name = compute_plan_display_name(plan_file, self._plans_dir, folder_visible_counts)
            self._parsed_plans[display_name] = plan

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="picker-container"):
            yield Static("[b]Select Flight Plan[/b]", id="picker-title")
            yield Static("", id="picker-empty")
            yield ListView(id="picker-listview")
            yield Static("", id="picker-error")
            with Horizontal(id="picker-buttons"):
                yield Button("Cancel", id="picker-cancel-btn", variant="error")

    def on_mount(self) -> None:
        """Re-scan plans from disk each time the dialog opens."""
        self._load_plans()
        self._refresh_list()

    def _refresh_list(self) -> None:
        """Rebuild the list view and error display from loaded plans."""
        listview = self.query_one("#picker-listview", ListView)
        listview.clear()
        self._plan_names: list[str] = []

        for name, plan in self._parsed_plans.items():
            summary_parts: list[str] = []
            action_count = sum(1 for step in plan.steps if isinstance(step, FlightPlanStep))
            parallel_count = sum(1 for step in plan.steps if isinstance(step, ParallelStep))
            if action_count > 0:
                step_word = "step" if action_count == 1 else "steps"
                summary_parts.append(f"{action_count} {step_word}")
            if parallel_count > 0:
                sub_word = "sub-plan" if parallel_count == 1 else "sub-plans"
                summary_parts.append(f"{parallel_count} {sub_word}")
            summary = f" ({', '.join(summary_parts)})" if summary_parts else ""
            craft_suffix = f" — [b]{plan.craft}[/b]" if plan.craft else ""
            idx = len(self._plan_names)
            self._plan_names.append(name)
            listview.append(
                ListItem(
                    Static(f"{name}{summary}{craft_suffix}"),
                    id=f"plan-{idx}",
                )
            )

        empty_widget = self.query_one("#picker-empty", Static)
        if not self._parsed_plans and not self._parse_errors:
            empty_widget.update(f"No .plan files found in {self._plans_dir}")
        else:
            empty_widget.update("")

        error_widget = self.query_one("#picker-error", Static)
        if self._parse_errors:
            error_lines = [f"[b]{name}.plan[/b]: {msg}" for name, msg in self._parse_errors.items()]
            error_widget.update("\n".join(error_lines))
        else:
            error_widget.update("")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Select and dismiss with the chosen plan."""
        item_id = event.item.id
        if item_id is None:
            return
        try:
            idx = int(item_id.removeprefix("plan-"))
        except ValueError:
            return
        if 0 <= idx < len(self._plan_names):
            plan_name = self._plan_names[idx]
            plan = self._parsed_plans.get(plan_name)
            if plan is not None:
                self.dismiss(plan)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "picker-cancel-btn":
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
