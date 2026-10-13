# accessibility.py — FR-22/NFR-11: validated display preferences and contrast helpers.
"""Dependency-free accessibility policy; never read or alter scientific state.

Font sizes are percentages of the existing design, not browser zoom levels.
Unknown/malformed preferences in legacy JSON are ignored, not executed as CSS.
"""
from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from math import isfinite
from typing import Any

FONT_SCALES = (100, 125, 150, 175, 200)
DEFAULT_FONT_SCALE = 100


def normalize_font_scale(value: Any) -> int:
    """Accept only supported finite numeric percentages; otherwise use 100%."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return DEFAULT_FONT_SCALE
    return int(value) if isfinite(value) and value in FONT_SCALES else DEFAULT_FONT_SCALE


def preferences(state: Mapping[str, Any]) -> dict[str, Any]:
    """Return JSON-safe display preferences without including widget or science keys."""
    theme = state.get("theme", "light")
    return {"theme": theme if theme in ("light", "dark") else "light",
            "font_scale": normalize_font_scale(state.get("font_scale", DEFAULT_FONT_SCALE))}


def restore_preferences(state: MutableMapping[str, Any], saved: Any) -> None:
    """Merge supported saved preferences, preserving current values for legacy saves.

    Only valid keys are restored. Missing/invalid font_scale must not unexpectedly
    shrink the text for someone loading an older reduction.
    """
    if not isinstance(saved, Mapping):
        return
    if saved.get("theme") in ("light", "dark"):
        state["theme"] = saved["theme"]
    value = saved.get("font_scale")
    if not isinstance(value, bool) and isinstance(value, (int, float)) and value in FONT_SCALES:
        state["font_scale"] = int(value)


def relative_luminance(hex_color: str) -> float:
    """Compute WCAG relative sRGB luminance for a six-digit #RRGGBB token."""
    if len(hex_color) != 7 or not hex_color.startswith("#"):
        raise ValueError("Expected a #RRGGBB colour")
    channels = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return sum(c * weight for c, weight in zip(linear, (0.2126, 0.7152, 0.0722)))


def contrast_ratio(foreground: str, background: str) -> float:
    """Return an unrounded contrast ratio; callers must not round a failing result up."""
    low, high = sorted((relative_luminance(foreground), relative_luminance(background)))
    return (high + 0.05) / (low + 0.05)


def readable_color(color: str, backgrounds: tuple[str, ...], minimum: float = 4.5) -> str:
    """Keep an approved colour when it passes; otherwise choose black or white.

    The fallback is deliberately explicit, not a silent change to locked brand
    or scientific colours. It is only used for text/control boundary tokens.
    """
    if all(contrast_ratio(color, bg) >= minimum for bg in backgrounds):
        return color
    return max(("#000000", "#FFFFFF"), key=lambda c: min(contrast_ratio(c, bg) for bg in backgrounds))


def accessible_theme(base: Mapping[str, str]) -> dict[str, str]:
    """Derive legible UI text/boundaries without mutating the design-token table.

    TODO: confirm against design — see build spec §3. FR-22 needs readable small
    text on the blue page/sidebar and brand-filled buttons. Brand backgrounds,
    LCP/RCP and fit colours are unchanged; text and interactive boundaries gain
    contrast-safe companion values. See docs/FR22_ACCESSIBILITY.md for ratios.
    """
    theme = dict(base)
    surfaces = (theme["bg-primary"], theme["bg-panel"], theme["bg-panel-alt"])
    for key in ("text-body", "text-heading", "text-muted", "text-faint"):
        theme[key] = readable_color(theme[key], surfaces)
    theme["sidebar-text-inactive"] = readable_color(theme["sidebar-text-inactive"], (theme["bg-sidebar"],))
    theme["text-on-accent"] = readable_color("#FFFFFF", (theme["accent"],))
    theme["control-border"] = readable_color(base["text-muted"], surfaces, 3.0)
    theme["focus-ring"] = "#000000" if relative_luminance(theme["bg-panel"]) > 0.5 else "#FFFFFF"
    return theme


def validate_view_range(start: Any, end: Any) -> tuple[float, float]:
    """Validate a numeric chart viewport, without changing any fit/exclusion ranges."""
    if isinstance(start, bool) or isinstance(end, bool):
        raise ValueError("Enter finite numeric limits with start smaller than end.")
    try:
        lower, upper = float(start), float(end)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("Enter finite numeric limits with start smaller than end.") from exc
    if not isfinite(lower) or not isfinite(upper) or lower >= upper:
        raise ValueError("Enter finite numeric limits with start smaller than end.")
    return lower, upper


def region_options(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Make an independent keyboard selector for the read-only Dash region table."""
    return [{"label": f"Region {i + 1}: {row.get('start', '?')} to {row.get('end', '?')} km/s", "value": i}
            for i, row in enumerate(rows or [])]


def selected_region_index(value: Any, rows: list[dict[str, Any]] | None) -> int:
    """Reject missing/stale indices instead of editing or deleting another region."""
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < len(rows or []):
        raise ValueError("Choose a region in 'Region to edit' first.")
    return value
