"""ParamInputModal - collects action parameter values before starting."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static, Switch

from ksp_mission_control.control.actions.base import Action, ParamType


class ParamInputModal(ModalScreen[dict[str, float | int | bool | str] | None]):
    """Modal dialog for editing an action's parameters before execution.

    Renders one Input per ActionParam, pre-fills defaults, validates on
    submit, and dismisses with the final param dict (or None on cancel).
    """

    AUTO_FOCUS = ""

    DEFAULT_CSS = """
    ParamInputModal {
        align: center middle;
    }

    #modal-container {
        width: 60;
        height: auto;
        max-height: 80%;
        padding: 1 2;
        border: solid $primary;
        background: $surface;
    }

    #modal-title {
        padding: 0 0 1 0;
    }

    #modal-description {
        padding: 0 0 1 0;
        color: $text-muted;
    }

    .param-label {
        padding: 1 0 0 0;
    }

    #modal-error {
        color: $error;
        padding: 1 0 0 0;
    }

    #modal-buttons {
        dock: bottom;
        padding: 1 0 0 0;
        align-horizontal: right;
        height: auto;
        background: $surface;
    }

    #modal-buttons Button {
        margin-left: 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, action: Action) -> None:
        super().__init__()
        self._action = action

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="modal-container"):
            yield Static(f"[b]{self._action.label}[/b]", id="modal-title")
            yield Static(self._action.description, id="modal-description")
            for param in self._action.params:
                label = f"{param.label} ({param.unit})" if param.unit else param.label
                if param.required:
                    label += " *"
                param_label = Static(label, classes="param-label")
                if param.description:
                    param_label.tooltip = param.description
                yield param_label
                if param.param_type == ParamType.BOOL:
                    yield Switch(
                        value=bool(param.default) if param.default is not None else False,
                        id=f"param-{param.param_id}",
                    )
                else:
                    yield Input(
                        value=str(param.default) if param.default is not None else "",
                        placeholder=param.description,
                        id=f"param-{param.param_id}",
                    )
            yield Static("", id="modal-error")
            with Horizontal(id="modal-buttons"):
                yield Button("Confirm", id="confirm-btn", variant="primary")
                yield Button("Cancel", id="cancel-btn", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-btn":
            self._do_confirm()
        elif event.button.id == "cancel-btn":
            self.dismiss(None)

    def _do_confirm(self) -> None:
        """Validate inputs and dismiss with the param dict."""
        error_widget = self.query_one("#modal-error", Static)
        result: dict[str, float | int | bool | str] = {}

        for param in self._action.params:
            if param.param_type == ParamType.BOOL:
                switch = self.query_one(f"#param-{param.param_id}", Switch)
                result[param.param_id] = switch.value
                continue

            inp = self.query_one(f"#param-{param.param_id}", Input)
            raw = inp.value.strip()

            if not raw:
                if param.required:
                    error_widget.update(f"[b]{param.label}[/b] is required")
                    inp.focus()
                    return
                continue

            if param.param_type == ParamType.STR:
                result[param.param_id] = raw
            elif param.param_type == ParamType.INT:
                try:
                    result[param.param_id] = int(raw)
                except ValueError:
                    error_widget.update(f"[b]{param.label}[/b] must be a whole number")
                    inp.focus()
                    return
            else:
                try:
                    result[param.param_id] = float(raw)
                except ValueError:
                    error_widget.update(f"[b]{param.label}[/b] must be a number")
                    inp.focus()
                    return

        self.dismiss(result)

    def action_cancel(self) -> None:
        self.dismiss(None)
