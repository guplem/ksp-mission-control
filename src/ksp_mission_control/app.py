"""KSP Mission Control - Terminal mission control for Kerbal Space Program."""

from textual.app import App


class MissionControlApp(App[None]):
    """Main application for KSP Mission Control."""

    TITLE = "KSP Mission Control"
    CSS = """
    Screen {
        background: #0a0a0a;
        color: #00ff41;
    }
    """


def main() -> None:
    """Entry point for the ksp-mc command."""
    app = MissionControlApp()
    app.run()
