"""FlightPlanPicker - modal for selecting a .plan file."""

from __future__ import annotations

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

    def __init__(self, plans_dir: Path | None = None) -> None:
        super().__init__()
        self._plans_dir = plans_dir or Path.cwd() / _PLANS_DIR_NAME
        self._parsed_plans: dict[str, FlightPlan] = {}
        self._parse_errors: dict[str, str] = {}

    def _load_plans(self) -> None:
        """Scan the plans directory for .plan files."""
        self._parsed_plans.clear()
        self._parse_errors.clear()
        if not self._plans_dir.is_dir():
            return
        for plan_file in sorted(self._plans_dir.glob("*.plan")):
            try:
                self._parsed_plans[plan_file.stem] = parse_flight_plan(plan_file)
            except ValueError as exc:
                self._parse_errors[plan_file.stem] = str(exc)

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

        for name, plan in self._parsed_plans.items():
            step_count = len(plan.steps)
            step_word = "step" if step_count == 1 else "steps"
            listview.append(
                ListItem(
                    Static(f"{name} ({step_count} {step_word})"),
                    id=f"plan-{name}",
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
        plan_name = item_id.removeprefix("plan-")
        plan = self._parsed_plans.get(plan_name)
        if plan is not None:
            self.dismiss(plan)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "picker-cancel-btn":
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
