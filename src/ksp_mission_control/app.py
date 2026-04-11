"""KSP Mission Control - Terminal mission control for Kerbal Space Program."""

from textual.app import App, ComposeResult
from textual.containers import Center, Middle
from textual.widgets import Footer, Header, Static

LOGO = r"""
 _  __  ____  ____    __  __ _          _              ____            _             _       / \   
| |/ / / ___||  _ \  |  \/  (_) ___ ___(_) ___  _ __  / ___|___  _ __ | |_ _ __ ___ | |     |   |  
| ' /  \___ \| |_) | | |\/| | / __/ __| |/ _ \| '_ \ | |   / _ \| '_ \| __| '__/ _ \| |     |   |  
| . \   ___) |  __/  | |  | | \__ \__ \ | (_) | | | || |__| (_) | | | | |_| | | (_) | |    /|   |\ 
|_|\_\ |____/|_|     |_|  |_|_|___/___/_|\___/|_| |_| \____\___/|_| |_|\__|_|  \___/|_|   /_|___|_\
                                                                                             /_\   
                                                                                            |___|  
"""  # noqa: E501


class WelcomeView(Static):
    """Welcome screen shown on startup."""

    def compose(self) -> ComposeResult:
        yield Static(LOGO, id="logo")
        yield Static("v0.1.0", id="version")
        yield Static("")
        yield Static("[b]Terminal Mission Control for Kerbal Space Program[/b]", id="tagline")


class MissionControlApp(App[None]):
    """Main application for KSP Mission Control."""

    TITLE = "KSP Mission Control"
    CSS_PATH = "styles/app.tcss"
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("d", "demo", "Demo Mode"),
        ("c", "connect", "Connect to KSP"),
        ("s", "setup", "kRPC Setup"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Middle(Center(WelcomeView()))
        yield Footer()

    def action_demo(self) -> None:
        """Launch demo mode (placeholder)."""
        self.notify("Demo mode coming soon...")

    def action_connect(self) -> None:
        """Connect to KSP (placeholder)."""
        self.notify("Connection screen coming soon...")

    def action_setup(self) -> None:
        """Open the kRPC setup screen."""
        from ksp_mission_control.screens.setup import SetupScreen

        self.push_screen(SetupScreen())


def main() -> None:
    """Entry point for the ksp-mc command."""
    app = MissionControlApp()
    app.run()


if __name__ == "__main__":
    """Entry point for `python src/ksp_mission_control/app.py`, used in Textual dev mode."""
    main()
