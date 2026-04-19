"""Setup screen with system readiness checklist for KSP Mission Control."""

from __future__ import annotations

from typing import cast

from textual import work
from textual.app import ComposeResult
from textual.containers import Center, Middle, VerticalGroup
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, ListItem, ListView, Static

from ksp_mission_control.app import MissionControlApp
from ksp_mission_control.config import ConfigManager
from ksp_mission_control.control.screen import ControlScreen
from ksp_mission_control.setup.check_runner import CheckRunner
from ksp_mission_control.setup.checks import CheckResult, SetupCheck, get_default_checks
from ksp_mission_control.setup.widgets.welcome_widget import WelcomeWidget


class SetupScreen(Screen[None]):
    """Initial screen showing system readiness checklist."""

    AUTO_FOCUS = ""
    CSS_PATH = "style.tcss"

    BINDINGS = [
        ("escape", "app.quit", "Quit"),
        ("c", "control_room", "Control Room"),
        ("r", "rerun_checks", "Re-run Checks"),
    ]

    def __init__(self, checks: list[SetupCheck] | None = None) -> None:
        super().__init__()
        self._checks: list[SetupCheck] = checks if checks is not None else []
        self._check_runner: CheckRunner | None = None

        if not self._checks:
            config_manager: ConfigManager = cast(MissionControlApp, self.app).config_manager
            self._checks = get_default_checks(config_manager=config_manager)

    @property
    def all_checks_passed(self) -> bool:
        """Return True when every check has passed."""
        if self._check_runner is None:
            return False
        return self._check_runner.all_passed

    def compose(self) -> ComposeResult:
        yield Header()
        with Middle(), Center(), VerticalGroup(id="setup-container"):
            yield WelcomeWidget()
            yield Static("")
            with ListView(id="checklist"):
                for check in self._checks:
                    yield ListItem(
                        Static(f"Preparing {check.check_id}...", id=f"{check.check_id}-label"),
                        id=check.check_id,
                    )
            yield Center(Button("Enter Control Room", id="enter-control-room", variant="primary", disabled=True))
        yield Footer()

    def on_mount(self) -> None:
        """Run checks after initial mount so the UI is responsive and shows progress."""
        self.call_later(self._run_all_checks)

    def on_screen_resume(self) -> None:
        """Re-run checks when returning from a sub-screen."""
        self._run_all_checks()

    def _run_all_checks(self) -> None:
        """Reset state and launch the check worker."""
        # Show all checks as not-started before kicking off the worker thread
        for check in self._checks:
            self._update_check_display(check.check_id, check.label, None, False)
        self._check_runner = CheckRunner(
            checks=self._checks,
            on_update=lambda *args: self.app.call_from_thread(self._update_check_display, *args),
        )
        self._run_checks_worker()

    @work(thread=True)
    def _run_checks_worker(self) -> None:
        """Execute checks in a thread so blocking I/O doesn't freeze the UI."""
        if self._check_runner is not None:
            self._check_runner.run_all()

    def _update_check_display(
        self,
        check_id: str,
        label: str,
        result: CheckResult | None,
        running: bool,
    ) -> None:
        """Update a single checklist item's display text."""
        error_details: str | None = None
        if result is None:  # in progress or not started yet
            mark = "[~]" if running else "[ ]"
        elif result.passed:
            mark = "[✓]"
        else:  # failed
            mark = "[ ]"
            error_details = result.message
        self.query_one(f"#{check_id}-label", Static).update(
            f"{mark} {label}" + (f" ({error_details})" if (error_details is not None and len(error_details) > 0) else "")
        )
        all_passed = self.all_checks_passed
        self.query_one("#enter-control-room", Button).disabled = not all_passed
        if all_passed:
            self.app.push_screen(ControlScreen())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses on the setup screen."""
        if event.button.id == "enter-control-room":
            self.app.push_screen(ControlScreen())

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Navigate to the detail screen for the selected checklist item."""

        check_id = event.item.id
        check = next((c for c in self._checks if c.check_id == check_id), None)

        if check is None:
            self.notify("Selected check not found.", severity="error")
            return

        if check.screen is not None:
            self.app.push_screen(check.screen())

        else:
            self.notify("No setup screen available for this check.", severity="information")

    def check_action_control_room(self) -> bool:
        """Disable 'Control Room' binding until all checks pass."""
        return self.all_checks_passed

    def action_control_room(self) -> None:
        """Launch the control room (requires all checks to pass)."""

        if self.check_action_control_room():
            from ksp_mission_control.control.screen import ControlScreen

            self.app.push_screen(ControlScreen())
        else:
            self.notify("Please fix the failed checks before entering the Control Room.", severity="warning")

    def action_rerun_checks(self) -> None:
        """Manually re-run all system checks."""
        self._run_all_checks()
