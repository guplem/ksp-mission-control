"""ScienceCommandDialog - send a targeted command to a single science experiment.

Displays experiment details and lets the user pick an action (Run, Reset,
Dump, Transmit). Returns a VesselCommands with a single ScienceCommand
targeting the experiment, or None on cancel.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Select, Static

from ksp_mission_control.control.actions.base import (
    ScienceAction,
    ScienceCommand,
    ScienceExperiment,
    VesselCommands,
)

_ACTION_OPTIONS: list[tuple[str, str]] = [(action.display_name, action.value) for action in ScienceAction]


class ScienceCommandDialog(ModalScreen[VesselCommands | None]):
    """Modal for sending a science command to a specific experiment."""

    AUTO_FOCUS = ""

    DEFAULT_CSS = """
    ScienceCommandDialog {
        align: center middle;
    }

    #science-cmd-container {
        width: 46;
        height: auto;
        padding: 1 2;
        border: solid $primary;
        background: $surface;
    }

    #science-cmd-error {
        color: $error;
    }

    #science-cmd-buttons {
        padding: 1 0 0 0;
        align-horizontal: right;
        height: auto;
    }

    #science-cmd-buttons Button {
        margin-left: 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, experiment: ScienceExperiment) -> None:
        super().__init__()
        self._experiment = experiment

    def compose(self) -> ComposeResult:
        exp = self._experiment
        status = _status_label(exp)
        with Vertical(id="science-cmd-container"):
            yield Static(f"[b]{exp.title}[/b]\n[dim]{exp.part_title}[/dim]\n{status}  |  Sci: {exp.science_value:.1f}/{exp.science_cap:.1f}")
            yield Select[str](
                _ACTION_OPTIONS,
                prompt="Select action...",
                id="science-cmd-action-select",
            )
            yield Static("", id="science-cmd-error")
            with Horizontal(id="science-cmd-buttons"):
                yield Button("Send", id="science-cmd-send-btn", variant="primary")
                yield Button("Cancel", id="science-cmd-cancel-btn", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "science-cmd-send-btn":
            self._do_send()
        elif event.button.id == "science-cmd-cancel-btn":
            self.dismiss(None)

    def _do_send(self) -> None:
        """Validate and dismiss with a VesselCommands containing the science command."""
        select = self.query_one("#science-cmd-action-select", Select)
        error_widget = self.query_one("#science-cmd-error", Static)

        if select.is_blank():
            error_widget.update("Please select an action")
            return

        action = ScienceAction(select.value)
        command = ScienceCommand(experiment_index=self._experiment.index, action=action)
        self.dismiss(VesselCommands(science_commands=(command,)))

    def action_cancel(self) -> None:
        self.dismiss(None)


def _status_label(exp: ScienceExperiment) -> str:
    """Human-readable status for the dialog."""
    if exp.inoperable:
        return "Inoperable"
    if exp.has_data:
        return "Has Data"
    if exp.available:
        return "Available"
    return "Unavailable"
