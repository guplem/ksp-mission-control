"""Setup screen with system readiness checklist for KSP Mission Control."""

from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.containers import Center, Middle, VerticalGroup
from textual.screen import Screen
from textual.widgets import Footer, Header, ListItem, ListView, Static

from ksp_mission_control.setup.checks import CheckResult, SetupCheck, get_default_checks
from ksp_mission_control.widgets.welcome_view import WelcomeView


class SetupScreen(Screen[None]):
    """Initial screen showing system readiness checklist."""

    CSS_PATH = "../styles/setup.tcss"

    BINDINGS = [
        ("q", "app.quit", "Quit"),
        ("d", "demo_mode", "Control Room (Demo)"),
        ("c", "control_room", "Control Room"),
        ("r", "rerun_checks", "Re-run Checks"),
    ]

    def __init__(self, checks: list[SetupCheck] | None = None) -> None:
        super().__init__()
        self._checks = checks if checks is not None else get_default_checks()
        self._results: dict[str, CheckResult] = {}

    @property
    def all_checks_passed(self) -> bool:
        """Return True when every check has passed."""
        return len(self._results) == len(self._checks) and all(
            r.passed for r in self._results.values()
        )

    def compose(self) -> ComposeResult:
        yield Header()
        with Middle(), Center(), VerticalGroup(id="setup-container"):
            yield WelcomeView()
            yield Static("")
            with ListView(id="checklist"):
                for check in self._checks:
                    yield ListItem(
                        Static(f"[ ] {check.label}", id=f"{check.check_id}-label"),
                        id=check.check_id,
                    )
        yield Footer()

    def on_mount(self) -> None:
        """Run system checks when the screen first mounts."""
        self._run_all_checks()

    def on_screen_resume(self) -> None:
        """Re-run checks when returning from a sub-screen."""
        self._run_all_checks()

    def _run_all_checks(self) -> None:
        """Reset state and launch the check worker."""
        self._results.clear()
        for check in self._checks:
            self._update_check_display(check.check_id, check.label, None)
        self._run_checks_worker()

    @work(thread=True)
    def _run_checks_worker(self) -> None:
        """Execute each check in a thread so blocking I/O doesn't freeze the UI.

        Checks run sequentially: later checks (comms, vessel) only make
        sense if earlier ones (kRPC installed) have passed.
        """
        for check in self._checks:
            self.app.call_from_thread(
                self._update_check_display,
                check.check_id,
                check.label,
                None,
                running=True,
            )
            result = check.run()
            self._results[check.check_id] = result
            self.app.call_from_thread(
                self._update_check_display, check.check_id, check.label, result
            )
            if not result.passed:
                break

    def _update_check_display(
        self,
        check_id: str,
        label: str,
        result: CheckResult | None,
        *,
        running: bool = False,
    ) -> None:
        """Update a single checklist item's display text."""
        if result is None:
            mark = "[~]" if running else "[ ]"
        elif result.passed:
            mark = "[x]"
        else:
            mark = "[!]"
        self.query_one(f"#{check_id}-label", Static).update(f"{mark} {label}")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Navigate to the detail screen for the selected checklist item."""
        check_id = event.item.id
        if check_id == "check-krpc":
            from ksp_mission_control.screens.krpc_setup import KrpcSetupScreen

            self.app.push_screen(KrpcSetupScreen())
        else:
            self.notify("No setup screen available for this check.", severity="information")

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

    def action_rerun_checks(self) -> None:
        """Manually re-run all system checks."""
        self._run_all_checks()
