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
from ksp_mission_control.control.screen import ControlScreen
from ksp_mission_control.control.vessel_spawner import SpawnVesselResult, spawn_vessel_from_craft
from ksp_mission_control.craft import (
    CraftError,
    export_craft_to_project,
    find_active_save_dir,
    find_craft_in_save,
    sanitize_craft_name,
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
                yield Button("Export Craft", id="export-craft-btn", variant="default", disabled=True)
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
        export_btn = self.query_one("#export-craft-btn", Button)
        export_btn.disabled = True
        export_btn.tooltip = None
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
        # so "Export Craft" can use it once all checks pass.
        if check_id == "check-vessel" and result is not None and result.passed:
            vessel_check = next(
                (c for c in self._checks if isinstance(c, VesselDetectedCheck)),
                None,
            )
            if vessel_check is not None and vessel_check.vessel_name:
                self._active_vessel_name = vessel_check.vessel_name

        all_passed = self.all_checks_passed
        self.query_one("#enter-control-room", Button).disabled = not all_passed

        # Export Craft needs both a known vessel name AND a clean checklist.
        export_btn = self.query_one("#export-craft-btn", Button)
        if all_passed and self._active_vessel_name is not None:
            export_btn.disabled = False
            export_btn.tooltip = f"Export '{self._active_vessel_name}' to crafts/"
        else:
            export_btn.disabled = True
            export_btn.tooltip = None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses on the setup screen."""
        if event.button.id == "enter-control-room":
            self.app.push_screen(ControlScreen())
        elif event.button.id == "launch-plan-btn":
            self._do_launch_from_plan()
        elif event.button.id == "export-craft-btn":
            self._do_export_craft()

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
        """Validate the chosen plan, then run the unified vessel spawner."""
        if plan is None:
            return
        # require_craft=True guarantees plan.craft is set, but defensive.
        if plan.craft is None:
            self._set_launch_status("Selected plan has no @craft directive.")
            return

        craft_path = Path.cwd() / "crafts" / f"{plan.craft}.craft"
        if not craft_path.is_file():
            self._set_launch_status(f"Craft file not found: crafts/{plan.craft}.craft")
            return

        self._set_launch_status(f"Spawning {plan.craft}...")
        self.query_one("#launch-plan-btn", Button).disabled = True
        self._spawn_vessel_and_navigate(plan)

    @work(thread=True)
    def _spawn_vessel_and_navigate(self, plan: FlightPlan) -> tuple[SpawnVesselResult, FlightPlan]:
        """Run the shared load + spawn workflow; result handled in on_worker_state_changed."""
        config_manager = cast(MissionControlApp, self.app).config_manager
        ksp_path_str = config_manager.config.ksp_path
        if ksp_path_str is None:
            raise CraftError("KSP install path not configured")
        if plan.craft is None:
            raise CraftError("plan has no craft to spawn")

        result = spawn_vessel_from_craft(
            app=self.app,
            craft_name=plan.craft,
            crafts_dir=Path.cwd() / "crafts",
            ksp_path=Path(ksp_path_str),
            krpc_settings=resolve_krpc_connection(config_manager),
        )
        return result, plan

    def _set_launch_status(self, message: str) -> None:
        self.query_one("#setup-launch-status", Static).update(message)

    # -- Export Craft --

    def _do_export_craft(self) -> None:
        """Re-query the active vessel name, prompt on overwrite, export to crafts/.

        The cached name from check-vessel only gates the button; the actual
        export uses a fresh kRPC query so a vessel rename in KSP since the
        check ran is picked up automatically.
        """
        self.query_one("#export-craft-btn", Button).disabled = True
        self._set_launch_status("Querying active vessel...")
        self._export_craft_worker()

    @work(thread=True)
    def _export_craft_worker(self) -> tuple[str, str] | None:
        """Run the full export flow: query → confirm → copy.

        Returns ``(sanitized, dest_filename)`` on success, ``None`` on cancel.
        """
        import krpc  # noqa: PLC0415

        from ksp_mission_control.control.krpc_bridge import get_active_vessel_name  # noqa: PLC0415
        from ksp_mission_control.control.vessel_spawner import await_modal  # noqa: PLC0415
        from ksp_mission_control.setup.overwrite_craft_dialog import (  # noqa: PLC0415
            OverwriteChoice,
            OverwriteCraftDialog,
        )

        config_manager = cast(MissionControlApp, self.app).config_manager
        ksp_path_str = config_manager.config.ksp_path
        if ksp_path_str is None:
            raise CraftError("KSP install path not configured")

        # Fresh kRPC query for the active vessel name.
        krpc_settings = resolve_krpc_connection(config_manager)
        conn = krpc.connect(
            name="KSP-MC Export Craft",
            address=krpc_settings.address,
            rpc_port=krpc_settings.rpc_port,
            stream_port=krpc_settings.stream_port,
        )
        try:
            active_name = get_active_vessel_name(conn)
        finally:
            import contextlib  # noqa: PLC0415

            with contextlib.suppress(Exception):
                conn.close()

        sanitized = sanitize_craft_name(active_name)
        if not sanitized:
            raise CraftError(f"Vessel name {active_name!r} cannot be sanitized to a filename")

        crafts_dir = Path.cwd() / "crafts"
        dest_path = crafts_dir / f"{sanitized}.craft"

        # Confirm overwrite if a copy already lives in the project.
        if dest_path.is_file():
            choice = await_modal(self.app, OverwriteCraftDialog(sanitized))
            if choice == OverwriteChoice.CANCEL:
                return None

        # Copy from KSP's active save's VAB into crafts/, then put the
        # sanitized name on the clipboard so plans can paste it as @craft.
        save_dir = find_active_save_dir(Path(ksp_path_str))
        craft_source = find_craft_in_save(save_dir, active_name)
        dest = export_craft_to_project(craft_source, crafts_dir)
        self.app.call_from_thread(self.app.copy_to_clipboard, sanitized)
        return sanitized, dest.name

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker.name == "_spawn_vessel_and_navigate":
            if event.state == WorkerState.SUCCESS:
                result, plan = cast(
                    tuple[SpawnVesselResult, FlightPlan],
                    event.worker.result,
                )
                if result == SpawnVesselResult.SPAWNED:
                    self._set_launch_status(f"Spawned {plan.craft}. Entering control room...")
                    self.app.push_screen(ControlScreen(pending_plan=plan))
                else:
                    self._set_launch_status("Spawn cancelled.")
            elif event.state == WorkerState.ERROR:
                error_msg = f"Launch failed: {event.worker.error}"
                self._set_launch_status(error_msg)
                self.notify(error_msg, severity="error", timeout=10)
            if event.state in (WorkerState.SUCCESS, WorkerState.ERROR):
                self.query_one("#launch-plan-btn", Button).disabled = not self._comms_passed
        elif event.worker.name == "_export_craft_worker":
            if event.state == WorkerState.SUCCESS:
                payload = cast("tuple[str, str] | None", event.worker.result)
                if payload is None:
                    self._set_launch_status("Export cancelled.")
                else:
                    sanitized, dest_name = payload
                    self._set_launch_status(f"Exported {sanitized} ({dest_name}). Name copied to clipboard.")
            elif event.state == WorkerState.ERROR:
                error_msg = f"Export failed: {event.worker.error}"
                self._set_launch_status(error_msg)
                self.notify(error_msg, severity="error", timeout=10)
            if event.state in (WorkerState.SUCCESS, WorkerState.ERROR):
                self.query_one("#export-craft-btn", Button).disabled = self._active_vessel_name is None or not self.all_checks_passed
