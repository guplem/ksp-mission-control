"""FlightPlanPicker - modal for selecting a .plan file."""

from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Static

from ksp_mission_control.control.actions.flight_plan import (
    FlightPlan,
    parse_flight_plan,
)
from ksp_mission_control.control.paste_plan_dialog import PastePlanDialog

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


def format_plan_cell(display_name: str) -> Text:
    """Render a plan display name with the folder prefix dimmed.

    The folder prefix (everything up to and including the last ``/``) is
    rendered with the ``dim`` style so the leaf name stands out. Plans
    with no folder prefix render at full brightness.
    """
    last_slash = display_name.rfind("/")
    if last_slash == -1:
        return Text(display_name)
    folder = display_name[: last_slash + 1]
    leaf = display_name[last_slash + 1 :]
    rendered = Text()
    rendered.append(folder, style="dim")
    rendered.append(leaf)
    return rendered


class FlightPlanPicker(ModalScreen[FlightPlan | None]):
    """Modal dialog for selecting a flight plan from the plans/ directory.

    Shows a two-column table (Plan, Craft). Plans are re-scanned each time
    the dialog opens. Dismisses with the parsed FlightPlan or None on cancel.
    """

    AUTO_FOCUS = ""

    DEFAULT_CSS = """
    FlightPlanPicker {
        align: center middle;
    }

    #picker-container {
        width: 80;
        height: auto;
        max-height: 80%;
        padding: 1 2;
        border: solid $primary;
        background: $surface;
    }

    #picker-title {
        padding: 0 0 1 0;
    }

    #picker-table {
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
        self._plan_names: list[str] = []
        self._highlighted_index: int = -1
        """Row index of the currently highlighted plan (-1 when none)."""

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
            yield DataTable(id="picker-table", cursor_type="row", zebra_stripes=True)
            yield Static("", id="picker-error")
            with Horizontal(id="picker-buttons"):
                yield Button("Paste Plan", id="picker-paste-btn")
                yield Button("Select", id="picker-select-btn", variant="primary")
                yield Button("Cancel", id="picker-cancel-btn", variant="error")

    def on_mount(self) -> None:
        """Re-scan plans from disk each time the dialog opens."""
        table = self.query_one("#picker-table", DataTable)
        table.add_columns("Plan", "Craft")
        self._load_plans()
        self._refresh_list()
        # Hide the DataTable cursor so no plan appears pre-selected. The
        # cursor (and Select button) only activate after explicit user
        # interaction (click or keyboard navigation).
        table.show_cursor = False

    def _refresh_list(self) -> None:
        """Rebuild the table and error display from loaded plans."""
        table = self.query_one("#picker-table", DataTable)
        table.clear()
        self._plan_names = []

        for name, plan in self._parsed_plans.items():
            craft_text = plan.craft if plan.craft else ""
            idx = len(self._plan_names)
            self._plan_names.append(name)
            table.add_row(format_plan_cell(name), craft_text, key=str(idx))

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

        self._highlighted_index = -1
        self._refresh_select_button()

    def _refresh_select_button(self) -> None:
        """Enable Select only when a valid plan row is highlighted."""
        select_btn = self.query_one("#picker-select-btn", Button)
        select_btn.disabled = not (0 <= self._highlighted_index < len(self._plan_names))

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """Track the highlighted row, but only after the cursor has been revealed."""
        try:
            table = self.query_one("#picker-table", DataTable)
        except NoMatches:
            return
        if not table.show_cursor:
            # Cursor is hidden: this fires during mount or while the user
            # has not yet interacted with the table. Ignore it so no plan
            # appears pre-selected.
            return
        self._highlighted_index = event.cursor_row
        self._refresh_select_button()

    def on_click(self, event: events.Click) -> None:
        """Reveal the cursor (and enable Select) when the user clicks the table."""
        if event.widget is None:
            return
        try:
            table = self.query_one("#picker-table", DataTable)
        except NoMatches:
            return
        in_table = event.widget is table or any(ancestor is table for ancestor in event.widget.ancestors_with_self)
        if not in_table or table.show_cursor:
            return
        table.show_cursor = True
        if 0 <= table.cursor_row < len(self._plan_names):
            self._highlighted_index = table.cursor_row
            self._refresh_select_button()

    def on_key(self, event: events.Key) -> None:
        """Reveal the cursor on keyboard navigation while the table is focused."""
        if event.key not in ("up", "down", "home", "end", "pageup", "pagedown"):
            return
        try:
            table = self.query_one("#picker-table", DataTable)
        except NoMatches:
            return
        if not table.has_focus or table.show_cursor:
            return
        table.show_cursor = True
        if 0 <= table.cursor_row < len(self._plan_names):
            self._highlighted_index = table.cursor_row
            self._refresh_select_button()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Dismiss with the double-clicked / Enter-selected plan."""
        key = event.row_key.value
        if key is None:
            return
        try:
            idx = int(key)
        except ValueError:
            return
        self._dismiss_with_plan_at(idx)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "picker-paste-btn":
            self.app.push_screen(PastePlanDialog(), callback=self._on_paste_result)
        elif event.button.id == "picker-select-btn":
            self._dismiss_with_plan_at(self._highlighted_index)
        elif event.button.id == "picker-cancel-btn":
            self.dismiss(None)

    def _dismiss_with_plan_at(self, idx: int) -> None:
        """Dismiss with the plan at *idx* in the visible row order; no-op if out of range."""
        if not (0 <= idx < len(self._plan_names)):
            return
        plan_name = self._plan_names[idx]
        plan = self._parsed_plans.get(plan_name)
        if plan is not None:
            self.dismiss(plan)

    def _on_paste_result(self, plan: FlightPlan | None) -> None:
        """Forward a pasted plan to the picker's caller; stay open on cancel."""
        if plan is not None:
            self.dismiss(plan)

    def action_cancel(self) -> None:
        self.dismiss(None)
