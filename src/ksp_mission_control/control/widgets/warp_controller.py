"""WarpControllerWidget - user-facing warp rate selector.

Single source of truth for "what warp does the user want right now". The
user picks a rate by clicking one of the rails-warp level buttons. The
selected level highlights so the user can see at a glance what was
requested, separate from the rate KSP actually achieved (which may be
lower under altitude / situation caps).

Posts ``RateSelected`` to the parent screen when the user picks a level.
The screen forwards that to ``ControlSession.set_user_target_warp_rate``,
which both updates the session-level value (read by burn-driven actions
to decide what to restore to) and queues a manual command so KSP receives
the new rate immediately.

The current achieved rate (``State.time_warp_rate``) is shown as a small
text label next to the buttons so the user can see when KSP's cap is
clamping their request below what they asked for.
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Button, Static

_RAILS_WARP_LEVELS: tuple[int, ...] = (1, 5, 10, 50, 100, 1000, 10000, 100000)
"""KSP rails-warp levels exposed in the controller. Matches the constant
in ``helpers/maneuver_node.py`` so the controller and the burn-side
step-down speak the same vocabulary."""


def _format_rate_label(rate: float) -> str:
    """Render a rate as a short button label: 100, 10k, 100k, ..."""
    if rate >= 1000:
        return f"{int(rate / 1000)}k"
    return str(int(rate))


def _format_actual_rate(rate: float) -> str:
    """Render the achieved rate for the small text label next to the buttons."""
    if rate >= 1000:
        return f"{rate / 1000:.0f}k×"
    if rate == int(rate):
        return f"{int(rate)}×"
    return f"{rate:.2f}×"


class WarpControllerWidget(Static):
    """Horizontal strip of warp-rate buttons plus the current achieved rate."""

    DEFAULT_CSS = """
    WarpControllerWidget {
        height: auto;
        padding: 1 1 0 1;
    }

    WarpControllerWidget #warp-controller-title {
        width: auto;
        padding: 0 1 0 0;
        color: $text 60%;
    }

    WarpControllerWidget Horizontal {
        height: auto;
    }

    WarpControllerWidget Button {
        min-width: 5;
        height: 1;
        margin: 0 1 0 0;
        border: none;
        padding: 0 1;
    }

    WarpControllerWidget #warp-actual {
        width: auto;
        padding: 0 0 0 1;
        color: $text 60%;
    }
    """

    class RateSelected(Message):
        """Posted when the user clicks one of the rate buttons."""

        def __init__(self, rate: float) -> None:
            super().__init__()
            self.rate: float = rate

    _target_rate: float
    _actual_rate: float

    _LEVEL_BUTTON_IDS: ClassVar[dict[int, str]] = {level: f"warp-rate-{level}" for level in _RAILS_WARP_LEVELS}

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._target_rate = 1.0
        self._actual_rate = 1.0

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Static("Warp", id="warp-controller-title")
            for level in _RAILS_WARP_LEVELS:
                button = Button(_format_rate_label(float(level)), id=self._LEVEL_BUTTON_IDS[level], compact=True)
                yield button
            yield Static(self._format_actual_label(), id="warp-actual")

    def on_mount(self) -> None:
        """Apply the initial selected-button styling after mount."""
        self._refresh_buttons()

    def update_state(self, target_rate: float, actual_rate: float) -> None:
        """Refresh the highlighted button and the actual-rate label.

        ``target_rate`` is the user's intended rate (drives which button
        looks selected). ``actual_rate`` is what KSP is running at right
        now; shown as a small text label so the user notices KSP-side
        clamping.
        """
        self._target_rate = target_rate
        self._actual_rate = actual_rate
        self._refresh_buttons()
        actual_label = self.query_one("#warp-actual", Static)
        actual_label.update(self._format_actual_label())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        for level, button_id in self._LEVEL_BUTTON_IDS.items():
            if event.button.id == button_id:
                self.post_message(self.RateSelected(float(level)))
                return

    def _refresh_buttons(self) -> None:
        """Mark the button matching ``_target_rate`` as primary; others default.

        Comparison uses the integer level so e.g. KSP's internal physics-warp
        2x or 3x leaves no button highlighted (which is the right behavior:
        the controller is rails-only)."""
        for level, button_id in self._LEVEL_BUTTON_IDS.items():
            try:
                button = self.query_one(f"#{button_id}", Button)
            except Exception:  # noqa: BLE001 - widget not yet mounted on first call
                return
            button.variant = "primary" if float(level) == self._target_rate else "default"

    def _format_actual_label(self) -> str:
        """Build the small ``actual: Xx`` label that flags KSP-side clamping."""
        return f"actual: {_format_actual_rate(self._actual_rate)}"
