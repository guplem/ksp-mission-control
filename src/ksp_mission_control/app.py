"""KSP Mission Control - Terminal mission control for Kerbal Space Program."""

from __future__ import annotations

from textual.app import App, ComposeResult

from ksp_mission_control.config import ConfigManager
from ksp_mission_control.theme import mission_control_theme


class MissionControlApp(App[None]):
    """Main application for KSP Mission Control."""

    TITLE = "KSP Mission Control"
    CSS_PATH = "styles/app.tcss"

    def __init__(self) -> None:
        super().__init__()
        self.config_manager = ConfigManager()

    def on_mount(self) -> None:
        self.register_theme(mission_control_theme)
        self.theme = "mission-control"

        from ksp_mission_control.screens.setup import SetupScreen

        self.push_screen(SetupScreen())

    def compose(self) -> ComposeResult:
        yield from ()


def main() -> None:
    """Entry point for the ksp-mc command."""
    app = MissionControlApp()
    app.run()


if __name__ == "__main__":
    """Entry point for `python src/ksp_mission_control/app.py`, used in Textual dev mode."""
    main()
