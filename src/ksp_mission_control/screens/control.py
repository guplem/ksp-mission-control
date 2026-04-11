"""Control screen - main mission control interface."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Center, Middle
from textual.screen import Screen
from textual.widgets import Footer, Header, Static


class ControlScreen(Screen[None]):
    """Main control room screen for live telemetry and vessel control."""

    CSS_PATH = "../styles/control.tcss"

    BINDINGS = [
        ("escape", "go_back", "Back to Setup"),
        ("q", "app.quit", "Quit"),
    ]

    def __init__(self, demo: bool = False) -> None:
        super().__init__()
        self._demo = demo

    def compose(self) -> ComposeResult:
        yield Header()
        with Middle(), Center():
            mode = "DEMO MODE" if self._demo else "LIVE"
            yield Static(
                f"[b]Control Room[/b] ({mode})\n\ncoming soon...",
                id="control-title",
            )
        yield Footer()

    def action_go_back(self) -> None:
        """Return to the setup screen."""
        self.app.pop_screen()
