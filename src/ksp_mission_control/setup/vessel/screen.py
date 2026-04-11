"""Active vessel detection screen."""

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


class VesselScreen(Screen[None]):
    """Screen explaining vessel requirements and testing detection."""

    CSS_PATH = "style.tcss"

    BINDINGS = [
        ("escape", "go_back", "Back"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()

        with Middle(), Center(), VerticalGroup(id="setup-container"):
            yield Center(Static("Active Vessel Detection", id="setup-title"))
            yield Center(
                Static(
                    "KSP Mission Control needs an active vessel under your control.",
                    id="setup-description",
                )
            )

            yield Static(
                "\n".join(
                    [
                        "Before checking, make sure that:",
                        "",
                        "  1. You are in the Flight view (not the Space Center or main menu).",
                        "  2. The vessel is on the launchpad or in flight.",
                        "  3. You are controlling the vessel (not watching from the Tracking Station).",  # noqa: E501
                        "",
                        "Once you have an active vessel, click the button below to verify.",
                    ]
                ),
                id="instructions",
            )

            yield Button(
                "Check Vessel",
                id="test-btn",
                variant="primary",
            )

            yield Center(Static("", id="setup-status"))

        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "test-btn":
            self._do_test()

    def _do_test(self) -> None:
        self._set_status("Checking for active vessel...")
        self.query_one("#test-btn", Button).disabled = True
        self._run_check()

    @work(thread=True)
    def _run_check(self) -> CheckResult:
        from ksp_mission_control.setup.vessel.check import VesselDetectedCheck

        config_manager = cast(MissionControlApp, self.app).config_manager
        return VesselDetectedCheck(config_manager=config_manager).run()

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
