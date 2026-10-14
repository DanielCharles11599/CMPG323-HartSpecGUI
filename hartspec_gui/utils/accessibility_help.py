# accessibility_help.py — FR-22/NFR-11: local, read-only accessibility manual links.
"""Share help content without passing private recovery tokens to a new tab."""
from __future__ import annotations

from collections.abc import Mapping
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from utils.accessibility import normalize_font_scale

HELP_ROUTE = "Keyboard_Help"
HELP_FILE = Path(__file__).resolve().parents[1] / "help" / "keyboard_accessibility.md"


def help_preferences(query: Mapping[str, Any]) -> tuple[str, int]:
    """Read only the two display preferences, rejecting malformed query values."""
    theme = query.get("display_theme", "light")
    theme = theme if isinstance(theme, str) and theme in ("light", "dark") else "light"
    raw = query.get("display_font_scale", 100)
    try:
        scale = int(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError, OverflowError):
        scale = 100
    return theme, normalize_font_scale(scale)


def help_link_html(theme: str, font_scale: int, *, base_path: str = "") -> str:
    """Build a native new-tab link using only allowlisted display preferences.

    base_path is the optional Streamlit server.baseUrlPath, not the current URL.
    No reduction identifiers, filenames or session query parameters are copied.
    """
    theme = theme if theme in ("light", "dark") else "light"
    parts = base_path.strip("/").split("/") if isinstance(base_path, str) else []
    if any(part in (".", "..") for part in parts):
        parts = []
    prefix = "/".join(quote(part, safe="") for part in parts if part)
    route = f"/{prefix}/{HELP_ROUTE}" if prefix else f"/{HELP_ROUTE}"
    query = urlencode({"display_theme": theme, "display_font_scale": normalize_font_scale(font_scale)})
    href = escape(f"{route}?{query}", quote=True)
    return (
        f'<a class="hs-help-link" href="{href}" target="_blank" rel="noopener noreferrer" '
        'aria-label="Keyboard and accessibility help (opens in a new tab)">'
        'Keyboard and accessibility help</a>'
    )


def read_help_text() -> str:
    """Read the bundled manual chapter; never access scientific data or sessions."""
    return HELP_FILE.read_text(encoding="utf-8")
