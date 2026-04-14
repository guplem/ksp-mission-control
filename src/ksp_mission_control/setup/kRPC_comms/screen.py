"""kRPC server connectivity screen."""

from __future__ import annotations

from typing import cast

from textual import work
from textual.app import ComposeResult
from textual.containers import Center, Middle, VerticalGroup
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static
from textual.worker import Worker, WorkerState

from ksp_mission_control.app import MissionControlApp
from ksp_mission_control.setup.checks import CheckResult


class KrpcCommsScreen(Screen[None]):
    """Screen explaining how to start the kRPC server and testing connectivity."""

    AUTO_FOCUS = ""
    CSS_PATH = "style.tcss"

    BINDINGS = [
        ("escape", "go_back", "Back"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()

        with Middle(), Center(), VerticalGroup(id="setup-container"):
            yield Center(Static("kRPC Server Connection", id="setup-title"))
            yield Center(
                Static(
                    "The kRPC server must be running inside KSP before this tool can connect.",
                    id="setup-description",
                )
            )

            yield Static(
                "\n".join(
                    [
                        "To start the kRPC server:",
                        "",
                        "  1. Open KSP and load a save (main menu is not enough).",
                        "  2. In the Space Center or Flight view, find the kRPC toolbar icon.",
                        "  3. Click 'Add Server' to create a server entry (first time only).",
                        "  4. Click 'Start Server'.",
                        "",
                        "Once the server is running, click the button below to verify.",
                    ]
                ),
                id="instructions",
            )

            yield Button(
                "Test Connection",
                id="test-btn",
                variant="primary",
            )

            yield Center(Static("", id="setup-status"))

        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "test-btn":
            self._do_test()

    def _do_test(self) -> None:
        self._set_status("Testing connection...")
        self.query_one("#test-btn", Button).disabled = True
        self._run_check()

    @work(thread=True)
    def _run_check(self) -> CheckResult:
        from ksp_mission_control.setup.kRPC_comms.check import KrpcCommsCheck

        config_manager = cast(MissionControlApp, self.app).config_manager
        return KrpcCommsCheck(config_manager=config_manager).run()

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker.name != "_run_check":
            return
        if event.state == WorkerState.SUCCESS:
            result = cast(CheckResult, event.worker.result)
            self._set_status(result.message)
        elif event.state == WorkerState.ERROR:
            self._set_status(f"Unexpected error: {event.worker.error}")
        if event.state in (WorkerState.SUCCESS, WorkerState.ERROR):
            self.query_one("#test-btn", Button).disabled = False

    def _set_status(self, message: str) -> None:
        self.query_one("#setup-status", Static).update(message)

    def action_go_back(self) -> None:
        self.app.pop_screen()
