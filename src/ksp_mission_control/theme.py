"""Custom Textual theme for KSP Mission Control."""

from __future__ import annotations

from textual.theme import Theme

mission_control_theme = Theme(
    name="mission-control",
    primary="#00ff41",
    secondary="#00cc33",
    accent="#33ff77",
    foreground="#00ff41",
    background="#0a0a0a",
    success="#00ff41",
    warning="#ccff00",
    error="#ff3333",
    surface="#0d1a0d",
    panel="#0f260f",
    dark=True,
    variables={
        # Text
        "text": "#00ff41",
        "text-muted": "#005f1a",
        "text-disabled": "#003d10",
        "text-primary": "#00ff41",
        "text-secondary": "#00cc33",
        "text-accent": "#33ff77",
        "text-warning": "#ccff00",
        "text-error": "#ff3333",
        "text-success": "#00ff41",
        # Foreground
        "foreground-muted": "#007a1f",
        "foreground-disabled": "#003d10",
        # Muted backgrounds
        "primary-muted": "#00ff41 20%",
        "secondary-muted": "#00cc33 20%",
        "accent-muted": "#33ff77 20%",
        "warning-muted": "#ccff00 20%",
        "error-muted": "#ff3333 20%",
        "success-muted": "#00ff41 20%",
        # Surface
        "surface-active": "#1a3d1a",
        # Border
        "border": "#00ff41",
        "border-blurred": "#005f1a",
        # Block cursor
        "block-cursor-foreground": "#0a0a0a",
        "block-cursor-background": "#00ff41",
        "block-cursor-text-style": "bold",
        "block-cursor-blurred-foreground": "#0a0a0a",
        "block-cursor-blurred-background": "#005f1a",
        "block-cursor-blurred-text-style": "none",
        "block-hover-background": "#00ff41 15%",
        # Input
        "input-cursor-foreground": "#0a0a0a",
        "input-cursor-background": "#00ff41",
        "input-cursor-text-style": "bold",
        "input-selection-background": "#00ff41 25%",
        # Button
        "button-color-foreground": "#0a0a0a",
        "button-foreground": "#0a0a0a",
        "button-focus-text-style": "bold reverse",
        # Header
        "header-foreground": "#00ff41",
        "header-background": "#ffff",
        # Footer
        "footer-foreground": "#005f1a",
        "footer-background": "#0a0a0a",
        "footer-key-foreground": "#00ff41",
        "footer-key-background": "#0a0a0a",
        "footer-description-foreground": "#005f1a",
        "footer-description-background": "#0a0a0a",
        "footer-item-background": "#0a0a0a",
        # Scrollbar
        "scrollbar": "#005f1a",
        "scrollbar-hover": "#00cc33",
        "scrollbar-active": "#00ff41",
        "scrollbar-background": "#0a0a0a",
        "scrollbar-background-hover": "#0d1a0d",
        "scrollbar-background-active": "#0d1a0d",
        "scrollbar-corner-color": "#0a0a0a",
        # Links
        "link-color": "#33ff77",
        "link-color-hover": "#00ff41",
        "link-background": "transparent",
        "link-background-hover": "#00ff41 15%",
        "link-style": "underline",
        "link-style-hover": "bold underline",
        # Markdown headings
        "markdown-h1-color": "#00ff41",
        "markdown-h1-background": "#0f260f",
        "markdown-h1-text-style": "bold",
        "markdown-h2-color": "#00cc33",
        "markdown-h2-background": "transparent",
        "markdown-h2-text-style": "bold",
        "markdown-h3-color": "#00cc33",
        "markdown-h3-background": "transparent",
        "markdown-h3-text-style": "bold",
        "markdown-h4-color": "#007a1f",
        "markdown-h4-background": "transparent",
        "markdown-h4-text-style": "bold underline",
        "markdown-h5-color": "#007a1f",
        "markdown-h5-background": "transparent",
        "markdown-h5-text-style": "bold",
        "markdown-h6-color": "#005f1a",
        "markdown-h6-background": "transparent",
        "markdown-h6-text-style": "bold",
    },
)
