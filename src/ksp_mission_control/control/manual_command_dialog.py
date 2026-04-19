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
    AutopilotConfig,
    AutopilotDirection,
    ReferenceFrame,
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
            _CommandField("ui_speed_mode", "Speed Mode", _FieldKind.SPEED_MODE),
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
            _CommandField("deployable_solar_panels", "Solar Panels", _FieldKind.BOOL),
            _CommandField("deployable_antennas", "Antennas", _FieldKind.BOOL),
            _CommandField("deployable_cargo_bays", "Cargo Bays", _FieldKind.BOOL),
            _CommandField("deployable_intakes", "Intakes", _FieldKind.BOOL),
            _CommandField("deployable_parachutes", "Parachutes", _FieldKind.BOOL),
            _CommandField("deployable_radiators", "Radiators", _FieldKind.BOOL),
        ],
    ),
]

_BOOL_OPTIONS: list[tuple[str, str]] = [("ON", "on"), ("OFF", "off")]

_SAS_MODE_OPTIONS: list[tuple[str, str]] = [(mode.display_name, mode.value) for mode in SASMode]

_SPEED_MODE_OPTIONS: list[tuple[str, str]] = [(mode.display_name, mode.value) for mode in SpeedMode]

_REF_FRAME_OPTIONS: list[tuple[str, str]] = [(frame.display_name, frame.value) for frame in ReferenceFrame]

# AutopilotConfig tuple fields: (widget_id_suffix, label, default_value)
_AP_CFG_TUPLE_FIELDS: list[tuple[str, str, tuple[float, float, float]]] = [
    ("time_to_peak", "Time to Peak", (3.0, 3.0, 3.0)),
    ("overshoot", "Overshoot", (0.01, 0.01, 0.01)),
    ("stopping_time", "Stopping Time", (0.5, 0.5, 0.5)),
    ("deceleration_time", "Decel Time", (5.0, 5.0, 5.0)),
    ("attenuation_angle", "Atten Angle", (1.0, 1.0, 1.0)),
]

_AP_CFG_PID_FIELDS: list[tuple[str, str]] = [
    ("pitch_pid_gains", "Pitch PID"),
    ("yaw_pid_gains", "Yaw PID"),
    ("roll_pid_gains", "Roll PID"),
]


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _parse_tuple3(raw: str) -> tuple[float, float, float]:
    """Parse a comma-separated string into a 3-float tuple.

    Raises ValueError if the format is invalid.
    """
    parts = [p.strip() for p in raw.split(",")]
    if len(parts) != 3:
        msg = "expected 3 comma-separated values"
        raise ValueError(msg)
    return (float(parts[0]), float(parts[1]), float(parts[2]))


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------


class ManualCommandDialog(ModalScreen[VesselCommands | None]):
    """Modal for composing and sending a one-shot manual VesselCommands."""

    AUTO_FOCUS = ""

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

            # --- Simple fields (data-driven) ---
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

            # --- Autopilot Direction (composite) ---
            yield Static("[b]--- Autopilot Direction ---[/b]", classes="manual-cmd-section")
            yield Static(
                "[dim]Overrides target pitch/heading. All 3 components + frame required.[/dim]",
                classes="manual-cmd-label",
            )
            for axis_id, axis_label in [("x", "X"), ("y", "Y"), ("z", "Z")]:
                with Horizontal(classes="manual-cmd-field-row"):
                    yield Static(f"Vector {axis_label}", classes="manual-cmd-label")
                    yield Input(
                        placeholder="float",
                        id=f"cmd-ap_dir_{axis_id}",
                        classes="manual-cmd-input",
                    )
            with Horizontal(classes="manual-cmd-field-row"):
                yield Static("Reference Frame", classes="manual-cmd-label")
                yield Select[str](
                    _REF_FRAME_OPTIONS,
                    prompt="---",
                    id="cmd-ap_dir_frame",
                    classes="manual-cmd-select",
                )

            # --- Autopilot Config (composite) ---
            yield Static("[b]--- Autopilot Config ---[/b]", classes="manual-cmd-section")
            yield Static(
                "[dim]Leave all empty to skip. Tuple fields: p, y, r (comma-separated).[/dim]",
                classes="manual-cmd-label",
            )
            with Horizontal(classes="manual-cmd-field-row"):
                yield Static("Auto Tune", classes="manual-cmd-label")
                yield Select[str](
                    _BOOL_OPTIONS,
                    prompt="---",
                    id="cmd-ap_cfg_auto_tune",
                    classes="manual-cmd-select",
                )
            for field_id, field_label, defaults in _AP_CFG_TUPLE_FIELDS:
                default_str = f"{defaults[0]}, {defaults[1]}, {defaults[2]}"
                with Horizontal(classes="manual-cmd-field-row"):
                    yield Static(
                        f"{field_label} [dim](p, y, r)[/dim]",
                        classes="manual-cmd-label",
                    )
                    yield Input(
                        placeholder=default_str,
                        id=f"cmd-ap_cfg_{field_id}",
                        classes="manual-cmd-input",
                    )
            with Horizontal(classes="manual-cmd-field-row"):
                yield Static(
                    "Roll Threshold [dim](degrees)[/dim]",
                    classes="manual-cmd-label",
                )
                yield Input(
                    placeholder="5.0",
                    id="cmd-ap_cfg_roll_threshold",
                    classes="manual-cmd-input",
                )
            for field_id, field_label in _AP_CFG_PID_FIELDS:
                with Horizontal(classes="manual-cmd-field-row"):
                    yield Static(
                        f"{field_label} [dim](Kp, Ki, Kd)[/dim]",
                        classes="manual-cmd-label",
                    )
                    yield Input(
                        placeholder="Kp, Ki, Kd",
                        id=f"cmd-ap_cfg_{field_id}",
                        classes="manual-cmd-input",
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

        # --- Simple fields ---
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

        # --- Autopilot Direction ---
        ap_dir_result = self._collect_autopilot_direction(error_widget)
        if ap_dir_result is _VALIDATION_FAILED:
            return
        if isinstance(ap_dir_result, AutopilotDirection):
            commands.autopilot_direction = ap_dir_result

        # --- Autopilot Config ---
        ap_cfg_result = self._collect_autopilot_config(error_widget)
        if ap_cfg_result is _VALIDATION_FAILED:
            return
        if isinstance(ap_cfg_result, AutopilotConfig):
            commands.autopilot_config = ap_cfg_result

        self.dismiss(commands)

    def _collect_autopilot_direction(self, error_widget: Static) -> AutopilotDirection | None | object:
        """Collect autopilot direction fields.

        Returns:
            AutopilotDirection if all fields are filled.
            None if all fields are empty (skip).
            _VALIDATION_FAILED if partially filled or invalid.
        """
        raw_x = self.query_one("#cmd-ap_dir_x", Input).value.strip()
        raw_y = self.query_one("#cmd-ap_dir_y", Input).value.strip()
        raw_z = self.query_one("#cmd-ap_dir_z", Input).value.strip()
        frame_select = self.query_one("#cmd-ap_dir_frame", Select)
        frame_blank = frame_select.is_blank()

        has_any = bool(raw_x or raw_y or raw_z or not frame_blank)
        has_all = bool(raw_x and raw_y and raw_z and not frame_blank)

        if not has_any:
            return None
        if not has_all:
            error_widget.update("[b]Autopilot Direction[/b]: all 3 vector components + frame required")
            return _VALIDATION_FAILED

        try:
            vec = (float(raw_x), float(raw_y), float(raw_z))
        except ValueError:
            error_widget.update("[b]Autopilot Direction[/b]: vector components must be numbers")
            return _VALIDATION_FAILED

        return AutopilotDirection(vector=vec, reference_frame=ReferenceFrame(frame_select.value))

    def _collect_autopilot_config(self, error_widget: Static) -> AutopilotConfig | None | object:
        """Collect autopilot config fields.

        Returns:
            AutopilotConfig if any field is filled.
            None if all fields are empty (skip).
            _VALIDATION_FAILED if any field is invalid.
        """
        auto_tune_select = self.query_one("#cmd-ap_cfg_auto_tune", Select)
        roll_threshold_raw = self.query_one("#cmd-ap_cfg_roll_threshold", Input).value.strip()

        # Check if any config field has a value
        tuple_raws: dict[str, str] = {}
        for field_id, _label, _defaults in _AP_CFG_TUPLE_FIELDS:
            tuple_raws[field_id] = self.query_one(f"#cmd-ap_cfg_{field_id}", Input).value.strip()

        pid_raws: dict[str, str] = {}
        for field_id, _label in _AP_CFG_PID_FIELDS:
            pid_raws[field_id] = self.query_one(f"#cmd-ap_cfg_{field_id}", Input).value.strip()

        has_any = not auto_tune_select.is_blank() or bool(roll_threshold_raw) or any(tuple_raws.values()) or any(pid_raws.values())
        if not has_any:
            return None

        # Build config with defaults, override with user values
        auto_tune = True
        if not auto_tune_select.is_blank():
            auto_tune = auto_tune_select.value == "on"

        kwargs: dict[str, object] = {"auto_tune": auto_tune}

        # Tuple fields
        for field_id, label, defaults in _AP_CFG_TUPLE_FIELDS:
            raw = tuple_raws[field_id]
            if raw:
                try:
                    kwargs[field_id] = _parse_tuple3(raw)
                except ValueError:
                    error_widget.update(f"[b]{label}[/b]: expected 3 comma-separated numbers")
                    self.query_one(f"#cmd-ap_cfg_{field_id}", Input).focus()
                    return _VALIDATION_FAILED
            else:
                kwargs[field_id] = defaults

        # Roll threshold
        if roll_threshold_raw:
            try:
                kwargs["roll_threshold"] = float(roll_threshold_raw)
            except ValueError:
                error_widget.update("[b]Roll Threshold[/b] must be a number")
                self.query_one("#cmd-ap_cfg_roll_threshold", Input).focus()
                return _VALIDATION_FAILED

        # PID gains (optional)
        for field_id, label in _AP_CFG_PID_FIELDS:
            raw = pid_raws[field_id]
            if raw:
                try:
                    kwargs[field_id] = _parse_tuple3(raw)
                except ValueError:
                    error_widget.update(f"[b]{label}[/b]: expected 3 comma-separated numbers (Kp, Ki, Kd)")
                    self.query_one(f"#cmd-ap_cfg_{field_id}", Input).focus()
                    return _VALIDATION_FAILED

        return AutopilotConfig(**kwargs)  # type: ignore[arg-type]

    def action_cancel(self) -> None:
        self.dismiss(None)


# Sentinel for validation failure (distinct from None which means "skip")
_VALIDATION_FAILED = object()
