"""Shared formatting utilities for the control module."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from textual.app import App


def format_met(met: float) -> str:
    """Format Mission Elapsed Time as T+MM:SS.t for display."""
    minutes = int(met) // 60
    seconds = met - minutes * 60
    return f"T+{minutes:02d}:{seconds:04.1f}"


def resolve_theme_colors[E: Enum](app: App[object], mapping: dict[E, str]) -> dict[E, str]:
    """Resolve a mapping of enum -> CSS variable name to enum -> hex color.

    Used by widgets that need theme-aware colors in Rich markup,
    where Textual CSS variables like ``$warning`` aren't available.
    """
    css_vars = app.get_css_variables()
    return {key: css_vars.get(var, "#ffffff") for key, var in mapping.items()}
