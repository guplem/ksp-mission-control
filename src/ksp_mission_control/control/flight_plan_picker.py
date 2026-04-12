"""FlightPlanPicker - modal for selecting a .plan file."""

from __future__ import annotations

import contextlib
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, ListItem, ListView, Static

from ksp_mission_control.control.actions.flight_plan import FlightPlan, parse_flight_plan

_PLANS_DIR_NAME = "plans"


class FlightPlanPicker(ModalScreen[FlightPlan | None]):
    """Modal dialog for selecting a flight plan from the plans/ directory.

    Lists all .plan files, shows their name and step count.
    Dismisses with the parsed FlightPlan or None on cancel.
    """

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
        color: $text-muted;
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

    def __init__(self, plans_dir: Path | None = None) -> None:
        super().__init__()
        self._plans_dir = plans_dir or Path.cwd() / _PLANS_DIR_NAME
        self._plan_files: list[Path] = []
        self._parsed_plans: dict[str, FlightPlan] = {}
        self._load_plans()

    def _load_plans(self) -> None:
        """Scan the plans directory for .plan files."""
        if not self._plans_dir.is_dir():
            return
        self._plan_files = sorted(self._plans_dir.glob("*.plan"))
        for plan_file in self._plan_files:
            with contextlib.suppress(ValueError):
                self._parsed_plans[plan_file.stem] = parse_flight_plan(plan_file)

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="picker-container"):
            yield Static("[b]Select Flight Plan[/b]", id="picker-title")
            if not self._parsed_plans:
                yield Static(
                    f"No .plan files found in {self._plans_dir}",
                    id="picker-empty",
                )
            with ListView(id="picker-listview"):
                for name, plan in self._parsed_plans.items():
                    step_count = len(plan.steps)
                    step_word = "step" if step_count == 1 else "steps"
                    yield ListItem(
                        Static(f"{name} ({step_count} {step_word})"),
                        id=f"plan-{name}",
                    )
            yield Static("", id="picker-error")
            with Horizontal(id="picker-buttons"):
                yield Button("Cancel", id="picker-cancel-btn", variant="error")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Select and dismiss with the chosen plan."""
        item_id = event.item.id
        if item_id is None:
            return
        plan_name = item_id.removeprefix("plan-")
        plan = self._parsed_plans.get(plan_name)
        if plan is not None:
            self.dismiss(plan)
        else:
            error = self.query_one("#picker-error", Static)
            error.update(f"Failed to load plan: {plan_name}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "picker-cancel-btn":
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
