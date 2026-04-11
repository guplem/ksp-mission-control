"""kRPC setup screen for detecting KSP and installing the kRPC mod."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from textual.app import ComposeResult
from textual.containers import Center, HorizontalGroup, Middle, VerticalGroup
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Static
from textual.worker import Worker, WorkerState

from ksp_mission_control.app import MissionControlApp
from ksp_mission_control.config import ConfigManager
from ksp_mission_control.setup.kRPC_installer.detector import (
    find_ksp_install,
    is_krpc_installed,
    is_valid_ksp_install,
)
from ksp_mission_control.setup.kRPC_installer.manager import (
    KrpcInstallError,
    install_krpc,
    uninstall_krpc,
)


class KrpcSetupScreen(Screen[None]):
    """Screen that guides the user through kRPC mod installation."""

    CSS_PATH = "style.tcss"

    BINDINGS = [
        ("escape", "go_back", "Back"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._ksp_path: Path | None = None
        self._restoring_path: bool = False

    def compose(self) -> ComposeResult:
        yield Header()

        with Middle(), Center(), VerticalGroup(id="setup-container"):
            # Title and description
            yield Center(Static("kRPC Setup", id="setup-title"))
            yield Center(
                Static(
                    "Detect your KSP installation and install the kRPC mod.",
                    id="setup-description",
                )
            )

            # Input for KSP path and detect/validate buttons
            yield Center(
                Static("1. Enter the path to your KSP installation:", classes="step-label")
            )
            yield Input(
                placeholder="KSP installation path...",
                id="ksp-path-input",
            )
            with Center(), HorizontalGroup(classes="button-row"):
                yield Button("Detect KSP", id="detect-btn", variant="primary")
                yield Button(
                    "Validate Path", id="validate-path-btn", variant="success", disabled=True
                )

            # Manage kRPC installation
            yield Center(Static("2. Manage kRPC installation:", classes="step-label"))
            with Center(), HorizontalGroup(classes="button-row"):
                yield Button(
                    "Install kRPC",
                    id="install-btn",
                    variant="success",
                    disabled=True,
                )
                yield Button(
                    "Uninstall kRPC",
                    id="uninstall-btn",
                    variant="error",
                    disabled=True,
                )

            # Status message
            yield Center(Static("", id="setup-status"))

        yield Footer()

    def on_mount(self) -> None:
        config_manager: ConfigManager = cast(MissionControlApp, self.app).config_manager
        stored = config_manager.config.ksp_path
        if stored:
            self._restoring_path = True
            self.query_one("#ksp-path-input", Input).value = stored
            self.call_later(self._validate_ksp_path, Path(stored))

    def on_input_changed(self, event: Input.Changed) -> None:
        """Enable/disable the Validate button based on whether the input has text."""
        has_text = bool(event.value.strip())
        self.query_one("#validate-path-btn", Button).disabled = not has_text
        # Skip invalidation when restoring a saved path during mount
        if self._restoring_path:
            self._restoring_path = False
            return
        # Invalidate previous validation when the path changes
        if self._ksp_path is not None:
            self._ksp_path = None
            self._set_install_enabled(False)
            self._set_uninstall_enabled(False)

    def _set_status(self, message: str) -> None:
        self.query_one("#setup-status", Static).update(message)

    def _set_install_enabled(self, enabled: bool) -> None:
        self.query_one("#install-btn", Button).disabled = not enabled

    def _set_uninstall_enabled(self, enabled: bool) -> None:
        self.query_one("#uninstall-btn", Button).disabled = not enabled

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "detect-btn":
            self._do_detect()
        elif event.button.id == "validate-path-btn":
            self._do_validate_path()
        elif event.button.id == "install-btn":
            self._do_install()
        elif event.button.id == "uninstall-btn":
            self._do_uninstall()

    def _do_detect(self) -> None:
        """Auto-detect KSP installation and populate the input field."""
        result = find_ksp_install()
        if result is None:
            self._set_status("KSP not found. Enter the path manually.")
            return

        self.query_one("#ksp-path-input", Input).value = str(result.path)
        self._set_status(f"KSP detected at {result.path}. Click Validate Path to confirm.")

    def _do_validate_path(self) -> None:
        """Validate a manually entered KSP path."""
        raw = self.query_one("#ksp-path-input", Input).value.strip()
        if not raw:
            self._set_status("Please enter a path.")
            self._set_install_enabled(False)
            self._set_uninstall_enabled(False)
            return
        self._validate_ksp_path(Path(raw))

    def _save_ksp_path(self, path: Path) -> None:
        """Persist the KSP path to the application config."""

        config_manager: ConfigManager = cast(MissionControlApp, self.app).config_manager
        config_manager.config.ksp_path = str(path)
        config_manager.save()

    def _validate_ksp_path(self, path: Path) -> None:
        """Check *path* and update UI state accordingly."""
        if not is_valid_ksp_install(path):
            self._set_status("Not a valid KSP installation. Please check the path and try again.")
            self._set_install_enabled(False)
            self._set_uninstall_enabled(False)
            self._ksp_path = None
            return

        self._ksp_path = path
        self._save_ksp_path(path)
        if is_krpc_installed(path):
            self._set_status("Valid KSP installation. kRPC is already installed.")
            self._set_install_enabled(False)
            self._set_uninstall_enabled(True)
        else:
            self._set_status("Valid KSP installation. Ready to install kRPC.")
            self._set_install_enabled(True)
            self._set_uninstall_enabled(False)

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

    def _do_uninstall(self) -> None:
        """Launch the kRPC uninstallation in a background worker."""
        if self._ksp_path is None:
            return
        self._set_status("Uninstalling kRPC...")
        self._set_uninstall_enabled(False)
        self._run_uninstall(self._ksp_path)

    def _run_uninstall(self, ksp_path: Path) -> None:
        """Run the uninstall in a Textual worker."""

        async def do_uninstall() -> None:
            uninstall_krpc(ksp_path)

        self.run_worker(do_uninstall(), name="krpc-uninstall")

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Handle worker completion for kRPC install/uninstall."""
        if event.worker.name == "krpc-install":
            self._on_install_complete(event)
        elif event.worker.name == "krpc-uninstall":
            self._on_uninstall_complete(event)

    def _on_install_complete(self, event: Worker.StateChanged) -> None:
        if event.state == WorkerState.SUCCESS:
            version = event.worker.result
            self._set_status(f"kRPC {version} installed successfully!")
            self._set_uninstall_enabled(True)
        elif event.state == WorkerState.ERROR:
            error = event.worker.error
            if isinstance(error, KrpcInstallError):
                msg = str(error)
            else:
                msg = f"Unexpected error: {error}"
            self._set_status(f"Installation failed: {msg}")
            self._set_install_enabled(True)

    def _on_uninstall_complete(self, event: Worker.StateChanged) -> None:
        if event.state == WorkerState.SUCCESS:
            self._set_status("kRPC uninstalled successfully.")
            self._set_install_enabled(True)
        elif event.state == WorkerState.ERROR:
            error = event.worker.error
            if isinstance(error, KrpcInstallError):
                msg = str(error)
            else:
                msg = f"Unexpected error: {error}"
            self._set_status(f"Uninstall failed: {msg}")
            self._set_uninstall_enabled(True)

    def action_go_back(self) -> None:
        """Return to the previous screen."""
        self.app.pop_screen()
