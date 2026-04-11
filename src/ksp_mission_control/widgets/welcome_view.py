"""Welcome screen widget shown on app startup."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Static

LOGO = r"""
 _  __  ____  ____    __  __ _         _               ____            _             _       / \   
| |/ / / ___||  _ \  |  \/  (_)___ ___(_) ___  _ __   / ___|___  _ __ | |_ _ __ ___ | |     |   |  
| ' /  \___ \| |_) | | |\/| | / __/ __| |/ _ \| '_ \ | |   / _ \| '_ \| __| '__/ _ \| |     |   |  
| . \   ___) |  __/  | |  | | \__ \__ \ | (_) | | | || |__| (_) | | | | |_| | | (_) | |    /|   |\ 
|_|\_\ |____/|_|     |_|  |_|_|___/___/_|\___/|_| |_| \____\___/|_| |_|\__|_|  \___/|_|   /_|___|_\
                                                                                             /_\   
                                                                                            |___|  
"""  # noqa: E501


class WelcomeView(Static):
    """Welcome screen shown on startup."""

    DEFAULT_CSS = """
    WelcomeView Static {
        text-align: center;
        width: 100%;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(LOGO, id="logo")
        yield Static("v0.1.0", id="version")
        yield Static("")
        yield Static("[b]Terminal Mission Control for Kerbal Space Program[/b]", id="tagline")
