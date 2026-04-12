"""Shared formatting utilities for the control module."""

from __future__ import annotations


def format_met(met: float) -> str:
    """Format Mission Elapsed Time as T+MM:SS.t for display."""
    minutes = int(met) // 60
    seconds = met - minutes * 60
    return f"T+{minutes:02d}:{seconds:04.1f}"
