"""LastCommandWidget - displays the most recent VesselCommands sent to the ship."""

from __future__ import annotations

from dataclasses import fields

from textual.app import ComposeResult
from textual.widgets import Static

from ksp_mission_control.control.actions.base import VesselCommands


class LastCommandWidget(Static):
    """Shows each VesselCommands field, dimming fields that are None."""

    DEFAULT_CSS = """
    #last-command-title {
        padding: 0 0 1 0;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("[b]Last Command[/b]", id="last-command-title")
        yield Static(_format_commands(VesselCommands()), id="last-command-content")

    def update_commands(self, commands: VesselCommands) -> None:
        self.query_one("#last-command-content", Static).update(_format_commands(commands))


def _format_commands(commands: VesselCommands) -> str:
    lines: list[str] = []
    for field in fields(commands):
        value = getattr(commands, field.name)
        label = field.name.replace("_", " ").title()
        if value is None:
            lines.append(f"[dim]{label}: ---[/dim]")
        else:
            lines.append(f"{label}: {value}")
    return "\n".join(lines)
