"""CommandHistoryWidget - paginated history of VesselCommands sent to the ship."""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import cast

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.message import Message
from textual.widgets import Button, Static

from ksp_mission_control.control.actions.base import (
    ActionStatus,
    AutopilotConfig,
    AutopilotDirection,
    SASMode,
    ScienceAction,
    ScienceCommand,
    SpeedMode,
    VesselCommands,
)
from ksp_mission_control.control.formatting import format_met, resolve_theme_colors

_MAX_HISTORY = 10_000
"""Maximum number of command records to keep. Oldest entries are dropped."""

_STATUS_VARIABLE: dict[ActionStatus, str] = {
    ActionStatus.RUNNING: "accent",
    ActionStatus.SUCCEEDED: "success",
    ActionStatus.FAILED: "error",
}


@dataclass(frozen=True)
class CommandRecord:
    """A single snapshot of commands sent to the vessel."""

    tick_id: int
    action_label: str
    met: float
    commands: VesselCommands
    applied_fields: frozenset[str]
    """Field names that were actually sent (differed from vessel state)."""
    status: ActionStatus | None = None
    message: str = ""


class CommandHistoryWidget(VerticalScroll, can_focus=True):
    """Paginated history of VesselCommands sent to the ship."""

    class TickChanged(Message):
        """Posted when the user requests a different tick via the nav buttons.

        ``tick_id`` is the requested tick, or None to return to live-follow
        mode. The widget does not change its own state in response to a
        button press; it waits for the screen to call ``set_selected_tick``
        as part of the broadcast, keeping all history-aware widgets in sync.
        """

        def __init__(self, tick_id: int | None) -> None:
            super().__init__()
            self.tick_id = tick_id

    DEFAULT_CSS = """
    #command-history-title {
        height: auto;
        padding: 0 0 1 0;
    }
    #command-history-message {
        height: auto;
        padding: 0;
    }
    #command-history-nav {
        height: auto;
        padding: 1 0 0 0;
        dock: bottom;
    }
    #command-history-nav Button {
        min-width: 5;
        width: auto;
        margin: 0 1 0 0;
    }
    #command-history-page {
        content-align: right middle;
        width: 1fr;
        padding: 0 1 0 0;
    }
    """

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._history: list[CommandRecord] = []
        self._index: int = -1
        self._selected_tick: int | None = None
        """Mirror of the screen-level selected tick. None means follow live."""
        self._status_colors: dict[ActionStatus, str] | None = None
        self._accent_color: str | None = None

    @property
    def _following(self) -> bool:
        """True when in live-follow mode (no historical tick pinned)."""
        return self._selected_tick is None

    def compose(self) -> ComposeResult:
        yield Static("[b]Command History[/b]", id="command-history-title")
        yield Static("[dim]No commands yet[/dim]", id="command-history-content")
        yield Static("", id="command-history-message")
        with Horizontal(id="command-history-nav"):
            yield Button("\u25c0\u25c0", id="cmd-first", disabled=True)
            yield Button("\u25c0", id="cmd-prev", disabled=True)
            yield Button("\u25b6", id="cmd-next", disabled=True)
            yield Button("\u25b6\u25b6", id="cmd-last", disabled=True)
            yield Static("", id="command-history-page")

    def record_commands(
        self,
        commands: VesselCommands,
        *,
        applied_fields: frozenset[str],
        action_label: str | None,
        met: float,
        tick_id: int,
        status: ActionStatus | None = None,
        message: str = "",
    ) -> None:
        """Record a command snapshot from the current tick.

        Skips idle ticks where no command field was set (all None).
        Records all ticks where an action set commands, even if every
        field was redundant (filtered by the bridge), so the user can
        see the full command stream.
        """
        # Skip idle ticks (no action running, no commands, no message).
        has_any_command = any((value := getattr(commands, f.name)) is not None and value != () for f in fields(commands))
        if not has_any_command and not message:
            return

        label = action_label or "Manual"
        record = CommandRecord(
            tick_id=tick_id,
            action_label=label,
            met=met,
            commands=commands,
            applied_fields=applied_fields,
            status=status,
            message=message,
        )

        self._history.append(record)
        if len(self._history) > _MAX_HISTORY:
            self._history.pop(0)
            self._index = max(0, self._index - 1)

        if self._following:
            self._index = len(self._history) - 1
        self._render_current()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Translate nav button presses into ``TickChanged`` requests.

        The widget does not change its own ``_index`` here; the screen
        will broadcast the resulting selection back via
        ``set_selected_tick``, keeping all history-aware widgets aligned.
        """
        if event.button.id == "cmd-first":
            self._request_index(0)
        elif event.button.id == "cmd-prev":
            self._request_index(self._index - 1)
        elif event.button.id == "cmd-next":
            self._request_index(self._index + 1)
        elif event.button.id == "cmd-last":
            self.post_message(self.TickChanged(None))

    def _request_index(self, target_index: int) -> None:
        """Post a ``TickChanged`` for the record at *target_index*.

        Lands on the latest record translates to "follow live"
        (``tick_id=None``) so the screen can resume auto-advance.
        """
        if not self._history or not (0 <= target_index < len(self._history)):
            return
        if target_index == len(self._history) - 1:
            self.post_message(self.TickChanged(None))
        else:
            self.post_message(self.TickChanged(self._history[target_index].tick_id))

    def set_selected_tick(self, tick_id: int | None) -> None:
        """Sync the displayed record to the screen-level selected tick.

        When None, snaps to the latest record and resumes follow mode.
        When a tick_id is given, finds the matching record and displays
        it. If no record matches the tick (e.g. the tick had no
        commands), the displayed record is left as-is but the widget
        marks itself as not-following so the next live tick won't snap
        the view forward.
        """
        self._selected_tick = tick_id
        if tick_id is None:
            if self._history:
                self._index = len(self._history) - 1
            self._render_current()
            return
        for index, record in enumerate(self._history):
            if record.tick_id == tick_id:
                self._index = index
                break
        self._render_current()

    def _resolve_colors(self) -> dict[ActionStatus, str]:
        """Resolve theme CSS variables to hex colors, cached after first call."""
        if self._status_colors is None:
            self._status_colors = resolve_theme_colors(self.app, _STATUS_VARIABLE)
        return self._status_colors

    def _resolve_accent(self) -> str:
        """Resolve the accent CSS variable to a hex color, cached after first call."""
        if self._accent_color is None:
            self._accent_color = self.app.get_css_variables().get("accent", "#ffffff")
        return self._accent_color

    def _render_current(self) -> None:
        if not self._history or self._index < 0:
            return
        record = self._history[self._index]
        colors = self._resolve_colors()
        if record.status is not None and record.status in colors:
            color = colors[record.status]
            status_text = f"[bold {color}]{record.status.value}[/bold {color}]"
        else:
            status_text = "[dim]---[/dim]"
        title = f"[b]{record.action_label}[/b]  {status_text}  [dim]{format_met(record.met)}[/dim]"
        self.query_one("#command-history-title", Static).update(title)
        self.query_one("#command-history-content", Static).update(_format_commands(record.commands, record.applied_fields))
        message_text = f"[dim italic]{record.message}[/dim italic]" if record.message else ""
        self.query_one("#command-history-message", Static).update(message_text)
        total = len(self._history)
        page = self._index + 1
        accent_color = self._resolve_accent()
        following_indicator = f"[bold {accent_color}]\u25cf[/bold {accent_color}] " if self._following else ""
        self.query_one("#command-history-page", Static).update(f"{following_indicator}{page}/{total}")
        self.query_one("#cmd-first", Button).disabled = self._index <= 0
        self.query_one("#cmd-prev", Button).disabled = self._index <= 0
        self.query_one("#cmd-next", Button).disabled = self._index >= total - 1
        self.query_one("#cmd-last", Button).disabled = self._following


_TOGGLE_FIELDS: frozenset[str] = frozenset(
    {
        "sas",
        "rcs",
        "gear",
        "legs",
        "lights",
        "brakes",
        "wheels",
        "reaction_wheels",
        "stage_lock",
        "deployable_solar_panels",
        "deployable_antennas",
        "deployable_cargo_bays",
        "deployable_intakes",
        "deployable_parachutes",
        "deployable_radiators",
    }
)

_ANGLE_FIELDS: frozenset[str] = frozenset(
    {
        "autopilot_pitch",
        "autopilot_heading",
        "autopilot_roll",
    }
)

_AXIS_FIELDS: frozenset[str] = frozenset(
    {
        "input_pitch",
        "input_yaw",
        "input_roll",
        "translate_forward",
        "translate_right",
        "translate_up",
        "wheel_throttle",
        "wheel_steering",
    }
)


def _format_direction(direction: AutopilotDirection) -> str:
    """Format an AutopilotDirection as a readable vector + frame."""
    x, y, z = direction.vector
    return f"({x:.2f}, {y:.2f}, {z:.2f}) {direction.reference_frame.display_name}"


def _format_autopilot_config(config: AutopilotConfig) -> str:
    """Format AutopilotConfig as a compact summary."""
    if config == AutopilotConfig.AUTO:
        return "Auto"
    if config.auto_tune:
        peak = config.time_to_peak
        return f"Auto (peak {peak[0]:.1f}s)"
    return "Manual PID"


def format_field_value(name: str, value: object) -> str:
    """Format a command field value with appropriate units."""
    if name == "throttle":
        return f"{float(value) * 100:.0f}%"  # type: ignore[arg-type]
    if name in _ANGLE_FIELDS:
        return f"{float(value):.2f} deg"  # type: ignore[arg-type]
    if name in _AXIS_FIELDS:
        return f"{float(value):+.2f}"  # type: ignore[arg-type]
    if name in _TOGGLE_FIELDS:
        return "ON" if value else "OFF"
    if name == "autopilot":
        return "ENGAGE" if value else "DISENGAGE"
    if name == "sas_mode":
        return cast(SASMode, value).display_name
    if name == "ui_speed_mode":
        return cast(SpeedMode, value).display_name
    if name == "autopilot_direction":
        return _format_direction(cast(AutopilotDirection, value))
    if name == "autopilot_config":
        return _format_autopilot_config(cast(AutopilotConfig, value))
    if name in ("stage", "abort"):
        return "ACTIVATE" if value else "---"
    if name == "all_science":
        return cast(ScienceAction, value).display_name
    if name == "science_commands":
        cmds = cast(tuple[ScienceCommand, ...], value)
        if len(cmds) == 1:
            return f"{cmds[0].action.display_name} experiment #{cmds[0].experiment_index}"
        return f"{len(cmds)} experiment commands"
    return str(value)


def _format_commands(commands: VesselCommands, applied_fields: frozenset[str]) -> str:
    """Format commands with 3 visual states:

    - None: not commanded at all (dim with ---)
    - Has value, not applied: redundant, vessel already had this value (dim with value)
    - Has value, applied: actually sent to vessel (normal)
    """
    lines: list[str] = []
    for field in fields(commands):
        value = getattr(commands, field.name)
        if value is None or value == ():
            continue
        label = field.name.replace("_", " ").title()
        formatted = format_field_value(field.name, value)
        if field.name in applied_fields:
            lines.append(f"{label}: {formatted}")
        else:
            lines.append(f"[dim]{label}: {formatted}[/dim]")

    return "\n".join(lines) if lines else "[dim]No commands[/dim]"
