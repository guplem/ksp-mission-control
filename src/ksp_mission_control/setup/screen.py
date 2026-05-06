"""Setup screen with system readiness checklist for KSP Mission Control."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from textual import work
from textual.app import ComposeResult
from textual.containers import Center, Horizontal, Middle, VerticalGroup
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, ListItem, ListView, Static
from textual.worker import Worker, WorkerState

from ksp_mission_control.app import MissionControlApp
from ksp_mission_control.config import ConfigManager
from ksp_mission_control.control.actions.flight_plan import FlightPlan
from ksp_mission_control.control.craft_loader import CraftLoadResult, load_craft_in_ksp
from ksp_mission_control.control.screen import ControlScreen
from ksp_mission_control.craft import (
    CraftError,
    find_active_save_dir,
    find_craft_in_save,
    sanitize_craft_name,
    save_craft_to_project,
)
from ksp_mission_control.setup.check_runner import CheckRunner
from ksp_mission_control.setup.checks import CheckResult, SetupCheck, get_default_checks
from ksp_mission_control.setup.kRPC_comms.parser import resolve_krpc_connection
from ksp_mission_control.setup.vessel.check import VesselDetectedCheck
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
        self._comms_passed: bool = False
        self._active_vessel_name: str | None = None

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
            with Center(id="setup-buttons"), Horizontal():
                yield Button("Enter Control Room", id="enter-control-room", variant="primary", disabled=True)
                yield Button("Launch from Flight Plan", id="launch-plan-btn", variant="primary", disabled=True)
                yield Button("Save Vessel", id="save-vessel-btn", variant="default", disabled=True)
            yield Center(Static("", id="setup-launch-status"))
        yield Footer()

    def on_mount(self) -> None:
        """Run checks after initial mount so the UI is responsive and shows progress."""
        self.call_later(self._run_all_checks)

    def on_screen_resume(self) -> None:
        """Re-run checks when returning from a sub-screen."""
        self._run_all_checks()

    def _run_all_checks(self) -> None:
        """Reset state and launch the check worker."""
        self._comms_passed = False
        self._active_vessel_name = None
        self.query_one("#launch-plan-btn", Button).disabled = True
        save_btn = self.query_one("#save-vessel-btn", Button)
        save_btn.disabled = True
        save_btn.tooltip = None
        self._set_launch_status("")
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

        # Enable "Launch from Flight Plan" once the kRPC server is reachable.
        if check_id == "check-comms" and result is not None and result.passed:
            self._comms_passed = True
            self.query_one("#launch-plan-btn", Button).disabled = False

        # Cache the active vessel name as soon as the vessel check reports it,
        # so "Save Vessel" can use it once all checks pass.
        if check_id == "check-vessel" and result is not None and result.passed:
            vessel_check = next(
                (c for c in self._checks if isinstance(c, VesselDetectedCheck)),
                None,
            )
            if vessel_check is not None and vessel_check.vessel_name:
                self._active_vessel_name = vessel_check.vessel_name

        all_passed = self.all_checks_passed
        self.query_one("#enter-control-room", Button).disabled = not all_passed

        # Save Vessel needs both a known vessel name AND a clean checklist.
        save_btn = self.query_one("#save-vessel-btn", Button)
        if all_passed and self._active_vessel_name is not None:
            save_btn.disabled = False
            save_btn.tooltip = f"Save '{self._active_vessel_name}' to vessels/"
        else:
            save_btn.disabled = True
            save_btn.tooltip = None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses on the setup screen."""
        if event.button.id == "enter-control-room":
            self.app.push_screen(ControlScreen())
        elif event.button.id == "launch-plan-btn":
            self._do_launch_from_plan()
        elif event.button.id == "save-vessel-btn":
            self._do_save_vessel()

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
            from ksp_mission_control.control.screen import ControlScreen  # noqa: PLC0415

            self.app.push_screen(ControlScreen())
        else:
            self.notify("Please fix the failed checks before entering the Control Room.", severity="warning")

    def action_rerun_checks(self) -> None:
        """Manually re-run all system checks."""
        self._run_all_checks()

    # -- Launch from Flight Plan --

    def _do_launch_from_plan(self) -> None:
        """Open the flight plan picker filtered to plans with @craft."""
        from ksp_mission_control.control.flight_plan_picker import FlightPlanPicker  # noqa: PLC0415

        self.app.push_screen(
            FlightPlanPicker(require_craft=True),
            callback=self._handle_plan_for_launch,
        )

    def _handle_plan_for_launch(self, plan: FlightPlan | None) -> None:
        """Validate the chosen plan, then run the unified craft loader."""
        if plan is None:
            return
        # require_craft=True guarantees plan.craft is set, but defensive.
        if plan.craft is None:
            self._set_launch_status("Selected plan has no @craft directive.")
            return

        craft_path = Path.cwd() / "vessels" / f"{plan.craft}.craft"
        if not craft_path.is_file():
            self._set_launch_status(f"Craft file not found: vessels/{plan.craft}.craft")
            return

        self._set_launch_status(f"Loading {plan.craft}...")
        self.query_one("#launch-plan-btn", Button).disabled = True
        self._load_craft_and_navigate(plan)

    @work(thread=True)
    def _load_craft_and_navigate(self, plan: FlightPlan) -> tuple[CraftLoadResult, FlightPlan]:
        """Run the shared install + launch workflow; result handled in on_worker_state_changed."""
        config_manager = cast(MissionControlApp, self.app).config_manager
        ksp_path_str = config_manager.config.ksp_path
        if ksp_path_str is None:
            raise CraftError("KSP install path not configured")
        if plan.craft is None:
            raise CraftError("plan has no craft to load")

        result = load_craft_in_ksp(
            app=self.app,
            craft_name=plan.craft,
            vessels_dir=Path.cwd() / "vessels",
            ksp_path=Path(ksp_path_str),
            krpc_settings=resolve_krpc_connection(config_manager),
        )
        return result, plan

    def _set_launch_status(self, message: str) -> None:
        self.query_one("#setup-launch-status", Static).update(message)

    # -- Save Vessel --

    def _do_save_vessel(self) -> None:
        """Re-query the live vessel name, prompt on overwrite, save to vessels/.

        The cached name from check-vessel only gates the button; the actual
        save uses a fresh kRPC query so a vessel rename in KSP since the
        check ran is picked up automatically.
        """
        self.query_one("#save-vessel-btn", Button).disabled = True
        self._set_launch_status("Querying active vessel...")
        self._save_vessel_worker()

    @work(thread=True)
    def _save_vessel_worker(self) -> tuple[str, str] | None:
        """Run the full save flow: query → confirm → copy.

        Returns ``(sanitized, dest_filename)`` on success, ``None`` on cancel.
        """
        import krpc  # noqa: PLC0415

        from ksp_mission_control.control.craft_loader import await_modal  # noqa: PLC0415
        from ksp_mission_control.control.krpc_bridge import get_active_vessel_name  # noqa: PLC0415
        from ksp_mission_control.setup.save_vessel_overwrite_dialog import (  # noqa: PLC0415
            OverwriteChoice,
            SaveVesselOverwriteDialog,
        )

        config_manager = cast(MissionControlApp, self.app).config_manager
        ksp_path_str = config_manager.config.ksp_path
        if ksp_path_str is None:
            raise CraftError("KSP install path not configured")

        # Fresh kRPC query for the live vessel name.
        krpc_settings = resolve_krpc_connection(config_manager)
        conn = krpc.connect(
            name="KSP-MC Save Vessel",
            address=krpc_settings.address,
            rpc_port=krpc_settings.rpc_port,
            stream_port=krpc_settings.stream_port,
        )
        try:
            live_name = get_active_vessel_name(conn)
        finally:
            import contextlib  # noqa: PLC0415

            with contextlib.suppress(Exception):
                conn.close()

        sanitized = sanitize_craft_name(live_name)
        if not sanitized:
            raise CraftError(f"Vessel name {live_name!r} cannot be sanitized to a filename")

        vessels_dir = Path.cwd() / "vessels"
        dest_path = vessels_dir / f"{sanitized}.craft"

        # Confirm overwrite if a copy already lives in the project.
        if dest_path.is_file():
            choice = await_modal(self.app, SaveVesselOverwriteDialog(sanitized))
            if choice == OverwriteChoice.CANCEL:
                return None

        # Copy from KSP's active save's VAB into vessels/, then put the
        # sanitized name on the clipboard so plans can paste it as @craft.
        save_dir = find_active_save_dir(Path(ksp_path_str))
        craft_source = find_craft_in_save(save_dir, live_name)
        dest = save_craft_to_project(craft_source, vessels_dir)
        self.app.call_from_thread(self.app.copy_to_clipboard, sanitized)
        return sanitized, dest.name

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker.name == "_load_craft_and_navigate":
            if event.state == WorkerState.SUCCESS:
                result, plan = cast(
                    tuple[CraftLoadResult, FlightPlan],
                    event.worker.result,
                )
                if result == CraftLoadResult.LAUNCHED:
                    self._set_launch_status(f"Loaded {plan.craft}. Entering control room...")
                    self.app.push_screen(ControlScreen(pending_plan=plan))
                else:
                    self._set_launch_status("Craft load cancelled.")
            elif event.state == WorkerState.ERROR:
                error_msg = f"Launch failed: {event.worker.error}"
                self._set_launch_status(error_msg)
                self.notify(error_msg, severity="error", timeout=10)
            if event.state in (WorkerState.SUCCESS, WorkerState.ERROR):
                self.query_one("#launch-plan-btn", Button).disabled = not self._comms_passed
        elif event.worker.name == "_save_vessel_worker":
            if event.state == WorkerState.SUCCESS:
                payload = cast("tuple[str, str] | None", event.worker.result)
                if payload is None:
                    self._set_launch_status("Save cancelled.")
                else:
                    sanitized, dest_name = payload
                    self._set_launch_status(f"Saved {sanitized} ({dest_name}). Name copied to clipboard.")
            elif event.state == WorkerState.ERROR:
                error_msg = f"Save failed: {event.worker.error}"
                self._set_launch_status(error_msg)
                self.notify(error_msg, severity="error", timeout=10)
            if event.state in (WorkerState.SUCCESS, WorkerState.ERROR):
                self.query_one("#save-vessel-btn", Button).disabled = self._active_vessel_name is None or not self.all_checks_passed
