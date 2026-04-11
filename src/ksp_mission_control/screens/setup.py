"""Setup screen with system readiness checklist for KSP Mission Control."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Center, HorizontalGroup, Middle, VerticalGroup
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static

from ksp_mission_control.setup.detector import find_ksp_install
from ksp_mission_control.widgets.welcome_view import WelcomeView


class SetupScreen(Screen[None]):
    """Initial screen showing system readiness checklist."""

    CSS_PATH = "../styles/setup.tcss"

    BINDINGS = [
        ("q", "app.quit", "Quit"),
        ("d", "demo_mode", "Control Room (Demo)"),
        ("c", "control_room", "Control Room"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._krpc_installed: bool = False
        self._comms_ok: bool = False
        self._vessel_detected: bool = False

    @property
    def all_checks_passed(self) -> bool:
        """Return True when all system checks have passed."""
        return self._krpc_installed and self._comms_ok and self._vessel_detected

    def compose(self) -> ComposeResult:
        yield Header()
        with Middle(), Center(), VerticalGroup(id="setup-container"):
            yield WelcomeView()
            yield Static("")
            with HorizontalGroup(classes="checklist-row"):
                yield Static("[ ] kRPC installed", id="check-krpc")
                yield Button("i", id="krpc-info-btn", variant="default")
            yield Static(
                "[ ] Communications with kRPC",
                id="check-comms",
                classes="checklist-item",
            )
            yield Static(
                "[ ] Vessel detected",
                id="check-vessel",
                classes="checklist-item",
            )
        yield Footer()

    def on_mount(self) -> None:
        """Run system checks when the screen first mounts."""
        self._run_checks()

    def on_screen_resume(self) -> None:
        """Re-run checks when returning from a sub-screen."""
        self._run_checks()

    def _run_checks(self) -> None:
        """Run all system checks and update the checklist display."""
        self._check_krpc()
        self._update_checklist()

    def _check_krpc(self) -> None:
        """Check if kRPC is installed in a detected KSP installation."""
        result = find_ksp_install()
        self._krpc_installed = result is not None and result.has_krpc

    def _update_checklist(self) -> None:
        """Update all checklist item labels to reflect current state."""
        krpc_mark = "[x]" if self._krpc_installed else "[ ]"
        comms_mark = "[x]" if self._comms_ok else "[ ]"
        vessel_mark = "[x]" if self._vessel_detected else "[ ]"

        self.query_one("#check-krpc", Static).update(f"{krpc_mark} kRPC installed")
        self.query_one("#check-comms", Static).update(f"{comms_mark} Communications with kRPC")
        self.query_one("#check-vessel", Static).update(f"{vessel_mark} Vessel detected")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle info button presses."""
        if event.button.id == "krpc-info-btn":
            from ksp_mission_control.screens.krpc_setup import KrpcSetupScreen

            self.app.push_screen(KrpcSetupScreen())

    def check_action_control_room(self) -> bool:
        """Disable 'Control Room' binding until all checks pass."""
        return self.all_checks_passed

    def action_demo_mode(self) -> None:
        """Launch the control room in demo mode."""
        from ksp_mission_control.screens.control import ControlScreen

        self.app.push_screen(ControlScreen(demo=True))

    def action_control_room(self) -> None:
        """Launch the control room (requires all checks to pass)."""
        from ksp_mission_control.screens.control import ControlScreen

        self.app.push_screen(ControlScreen(demo=False))
