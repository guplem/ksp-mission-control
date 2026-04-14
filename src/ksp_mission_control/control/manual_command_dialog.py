"""ManualCommandDialog - sends one-shot manual commands to the vessel.

Presents all VesselCommands fields organized by category. Each field starts
unset (None = don't change). The user sets only the fields they want, then
clicks Send. Returns a VesselCommands with only the user-set fields.
"""

from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Select, Static

from ksp_mission_control.control.actions.base import (
    SASMode,
    SpeedMode,
    VesselCommands,
)

# ---------------------------------------------------------------------------
# Field descriptors
# ---------------------------------------------------------------------------


class _FieldKind:
    """Discriminators for command field types."""

    FLOAT = "float"
    BOOL = "bool"
    SAS_MODE = "sas_mode"
    SPEED_MODE = "speed_mode"


@dataclass(frozen=True)
class _CommandField:
    """Metadata for one VesselCommands field shown in the dialog."""

    name: str
    label: str
    kind: str
    hint: str = ""


_SECTIONS: list[tuple[str, list[_CommandField]]] = [
    (
        "Throttle & Staging",
        [
            _CommandField("throttle", "Throttle", _FieldKind.FLOAT, "0.0 = off, 1.0 = full"),
            _CommandField("stage", "Stage", _FieldKind.BOOL),
        ],
    ),
    (
        "Rotation Axes",
        [
            _CommandField("input_pitch", "Pitch", _FieldKind.FLOAT, "-1.0 to 1.0"),
            _CommandField("input_yaw", "Yaw", _FieldKind.FLOAT, "-1.0 to 1.0"),
            _CommandField("input_roll", "Roll", _FieldKind.FLOAT, "-1.0 to 1.0"),
        ],
    ),
    (
        "Translation (RCS)",
        [
            _CommandField("translate_forward", "Forward", _FieldKind.FLOAT, "-1.0 to 1.0"),
            _CommandField("translate_right", "Right", _FieldKind.FLOAT, "-1.0 to 1.0"),
            _CommandField("translate_up", "Up", _FieldKind.FLOAT, "-1.0 to 1.0"),
        ],
    ),
    (
        "Autopilot",
        [
            _CommandField("autopilot", "Autopilot", _FieldKind.BOOL),
            _CommandField("autopilot_pitch", "Target Pitch", _FieldKind.FLOAT, "degrees"),
            _CommandField("autopilot_heading", "Target Heading", _FieldKind.FLOAT, "degrees"),
            _CommandField("autopilot_roll", "Target Roll", _FieldKind.FLOAT, "degrees, NaN=disable"),
        ],
    ),
    (
        "Systems",
        [
            _CommandField("sas", "SAS", _FieldKind.BOOL),
            _CommandField("sas_mode", "SAS Mode", _FieldKind.SAS_MODE),
            _CommandField("speed_mode", "Speed Mode", _FieldKind.SPEED_MODE),
            _CommandField("rcs", "RCS", _FieldKind.BOOL),
            _CommandField("gear", "Gear", _FieldKind.BOOL),
            _CommandField("legs", "Legs", _FieldKind.BOOL),
            _CommandField("lights", "Lights", _FieldKind.BOOL),
            _CommandField("brakes", "Brakes", _FieldKind.BOOL),
            _CommandField("wheels", "Wheels", _FieldKind.BOOL),
            _CommandField("abort", "Abort", _FieldKind.BOOL),
        ],
    ),
    (
        "Deployables",
        [
            _CommandField("solar_panels", "Solar Panels", _FieldKind.BOOL),
            _CommandField("antennas", "Antennas", _FieldKind.BOOL),
            _CommandField("cargo_bays", "Cargo Bays", _FieldKind.BOOL),
            _CommandField("intakes", "Intakes", _FieldKind.BOOL),
            _CommandField("parachutes", "Parachutes", _FieldKind.BOOL),
            _CommandField("radiators", "Radiators", _FieldKind.BOOL),
        ],
    ),
]

_BOOL_OPTIONS: list[tuple[str, str]] = [("ON", "on"), ("OFF", "off")]

_SAS_MODE_OPTIONS: list[tuple[str, str]] = [(mode.display_name, mode.value) for mode in SASMode]

_SPEED_MODE_OPTIONS: list[tuple[str, str]] = [(mode.display_name, mode.value) for mode in SpeedMode]


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------


class ManualCommandDialog(ModalScreen[VesselCommands | None]):
    """Modal for composing and sending a one-shot manual VesselCommands."""

    DEFAULT_CSS = """
    ManualCommandDialog {
        align: center middle;
    }

    #manual-cmd-container {
        width: 64;
        height: auto;
        max-height: 90%;
        padding: 1 2;
        border: solid $primary;
        background: $surface;
    }

    #manual-cmd-title {
        padding: 0 0 1 0;
    }

    #manual-cmd-description {
        padding: 0 0 1 0;
        color: $text-muted;
    }

    .manual-cmd-section {
        padding: 1 0 0 0;
        color: $accent;
    }

    .manual-cmd-field-row {
        height: auto;
        padding: 0;
    }

    .manual-cmd-label {
        width: 1fr;
        padding: 1 1 0 0;
    }

    .manual-cmd-input {
        width: 2fr;
    }

    .manual-cmd-select {
        width: 2fr;
    }

    #manual-cmd-error {
        color: $error;
        padding: 1 0 0 0;
    }

    #manual-cmd-buttons {
        dock: bottom;
        padding: 1 0 0 0;
        align-horizontal: right;
        height: auto;
        background: $surface;
    }

    #manual-cmd-buttons Button {
        margin-left: 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="manual-cmd-container"):
            yield Static("[b]Manual Command[/b]", id="manual-cmd-title")
            yield Static(
                "Set fields to send. Empty fields are ignored.",
                id="manual-cmd-description",
            )
            for section_name, fields in _SECTIONS:
                yield Static(f"[b]--- {section_name} ---[/b]", classes="manual-cmd-section")
                for field in fields:
                    with Horizontal(classes="manual-cmd-field-row"):
                        label_text = field.label
                        if field.hint:
                            label_text += f" [dim]({field.hint})[/dim]"
                        yield Static(label_text, classes="manual-cmd-label")
                        if field.kind == _FieldKind.FLOAT:
                            yield Input(
                                placeholder=field.hint or field.label,
                                id=f"cmd-{field.name}",
                                classes="manual-cmd-input",
                            )
                        elif field.kind == _FieldKind.BOOL:
                            yield Select[str](
                                _BOOL_OPTIONS,
                                prompt="---",
                                id=f"cmd-{field.name}",
                                classes="manual-cmd-select",
                            )
                        elif field.kind == _FieldKind.SAS_MODE:
                            yield Select[str](
                                _SAS_MODE_OPTIONS,
                                prompt="---",
                                id=f"cmd-{field.name}",
                                classes="manual-cmd-select",
                            )
                        elif field.kind == _FieldKind.SPEED_MODE:
                            yield Select[str](
                                _SPEED_MODE_OPTIONS,
                                prompt="---",
                                id=f"cmd-{field.name}",
                                classes="manual-cmd-select",
                            )
            yield Static("", id="manual-cmd-error")
            with Horizontal(id="manual-cmd-buttons"):
                yield Button("Send", id="manual-cmd-send-btn", variant="primary")
                yield Button("Cancel", id="manual-cmd-cancel-btn", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "manual-cmd-send-btn":
            self._do_send()
        elif event.button.id == "manual-cmd-cancel-btn":
            self.dismiss(None)

    def _do_send(self) -> None:
        """Validate inputs and dismiss with a VesselCommands."""
        error_widget = self.query_one("#manual-cmd-error", Static)
        commands = VesselCommands()

        for _section_name, fields in _SECTIONS:
            for field in fields:
                if field.kind == _FieldKind.FLOAT:
                    inp = self.query_one(f"#cmd-{field.name}", Input)
                    raw = inp.value.strip()
                    if not raw:
                        continue
                    try:
                        value = float(raw)
                    except ValueError:
                        error_widget.update(f"[b]{field.label}[/b] must be a number")
                        inp.focus()
                        return
                    setattr(commands, field.name, value)

                elif field.kind == _FieldKind.BOOL:
                    select = self.query_one(f"#cmd-{field.name}", Select)
                    if select.is_blank():
                        continue
                    setattr(commands, field.name, select.value == "on")

                elif field.kind == _FieldKind.SAS_MODE:
                    select = self.query_one(f"#cmd-{field.name}", Select)
                    if select.is_blank():
                        continue
                    setattr(commands, field.name, SASMode(select.value))

                elif field.kind == _FieldKind.SPEED_MODE:
                    select = self.query_one(f"#cmd-{field.name}", Select)
                    if select.is_blank():
                        continue
                    setattr(commands, field.name, SpeedMode(select.value))

        self.dismiss(commands)

    def action_cancel(self) -> None:
        self.dismiss(None)
