"""Setup screen for detecting KSP and installing the kRPC mod."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Center, Horizontal, Middle, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Static
from textual.worker import Worker, WorkerState

from ksp_mission_control.setup.detector import (
    find_ksp_install,
    is_krpc_installed,
    is_valid_ksp_install,
)
from ksp_mission_control.setup.installer import KrpcInstallError, install_krpc


class SetupScreen(Screen[None]):
    """Screen that guides the user through kRPC mod installation."""

    CSS_PATH = "../styles/setup.tcss"

    BINDINGS = [
        ("escape", "go_back", "Back"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._ksp_path: Path | None = None

    def compose(self) -> ComposeResult:
        yield Header()

        with Middle(), Center(), Vertical(id="setup-container"):
            yield Static("kRPC Setup", id="setup-title")
            yield Static(
                "Detect your KSP installation and install the kRPC mod.",
                id="setup-description",
            )
            with Vertical(id="path-row"):
                yield Input(
                    placeholder="KSP installation path...",
                    id="ksp-path-input",
                )
                yield Button("Use Path", id="validate-btn", variant="default")
            with Center():
                with Horizontal(id="button-row"):
                    yield Button("Detect KSP", id="detect-btn", variant="primary")
                    yield Button(
                        "Install kRPC",
                        id="install-btn",
                        variant="success",
                        disabled=True,
                    )
                    yield Button("Back", id="back-btn", variant="default")
            yield Static("", id="setup-status")

        yield Footer()

    def _set_status(self, message: str) -> None:
        self.query_one("#setup-status", Static).update(message)

    def _set_install_enabled(self, enabled: bool) -> None:
        self.query_one("#install-btn", Button).disabled = not enabled

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "detect-btn":
            self._do_detect()
        elif event.button.id == "validate-btn":
            self._do_validate_path()
        elif event.button.id == "install-btn":
            self._do_install()
        elif event.button.id == "back-btn":
            self.action_go_back()

    def _do_detect(self) -> None:
        """Auto-detect KSP installation."""
        result = find_ksp_install()
        if result is None:
            self._set_status("KSP not found. Enter the path manually.")
            self._set_install_enabled(False)
            self._ksp_path = None
            return

        self._ksp_path = result.path
        self.query_one("#ksp-path-input", Input).value = str(result.path)

        if result.has_krpc:
            self._set_status(f"kRPC is already installed at {result.path}")
            self._set_install_enabled(False)
        else:
            self._set_status(f"KSP found at {result.path}. Ready to install kRPC.")
            self._set_install_enabled(True)

    def _do_validate_path(self) -> None:
        """Validate a manually entered KSP path."""
        raw = self.query_one("#ksp-path-input", Input).value.strip()
        if not raw:
            self._set_status("Please enter a path.")
            self._set_install_enabled(False)
            return

        path = Path(raw)
        if not is_valid_ksp_install(path):
            self._set_status(f"Not a valid KSP installation: {path}")
            self._set_install_enabled(False)
            self._ksp_path = None
            return

        self._ksp_path = path
        if is_krpc_installed(path):
            self._set_status(f"kRPC is already installed at {path}")
            self._set_install_enabled(False)
        else:
            self._set_status("Valid KSP installation. Ready to install kRPC.")
            self._set_install_enabled(True)

    def _do_install(self) -> None:
        """Launch the kRPC installation in a background worker."""
        if self._ksp_path is None:
            return
        self._set_status("Downloading and installing kRPC...")
        self._set_install_enabled(False)
        self._run_install(self._ksp_path)

    def _run_install(self, ksp_path: Path) -> None:
        """Run the async install in a Textual worker."""

        async def do_install() -> str:
            return await install_krpc(ksp_path)

        self.run_worker(do_install(), name="krpc-install")

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Handle worker completion for the kRPC install."""
        if event.worker.name != "krpc-install":
            return
        if event.state == WorkerState.SUCCESS:
            version = event.worker.result
            self._set_status(f"kRPC {version} installed successfully!")
        elif event.state == WorkerState.ERROR:
            error = event.worker.error
            if isinstance(error, KrpcInstallError):
                msg = str(error)
            else:
                msg = f"Unexpected error: {error}"
            self._set_status(f"Installation failed: {msg}")

    def action_go_back(self) -> None:
        """Return to the previous screen."""
        self.app.pop_screen()
