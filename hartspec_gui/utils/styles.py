"""Theme tokens, layout constants, and shared CSS/HTML helpers for the HARTSPEC GUI.

This module is the single source of truth for both the light and dark color
palettes, plus small HTML-rendering helpers (badges, panels, the page header
with its pipeline progress bar) that every page in ``pages/`` reuses. Values
below come from ``hartspec_gui_codegen_prompt.md`` sections 4-10.

Streamlit renders as a fluid, reactive HTML flow layout, not an absolute-
position canvas, so the exact pixel x/y coordinates from the Figma-derived
prompt are not dropped in verbatim. Instead:

* Fixed-size tokens (border radii, row heights, font sizes, gaps, padding)
  are applied literally, since these don't depend on viewport width.
* Proportional widths (panel widths, table column widths) are expressed as
  flexbox/column ratios so the layout stays correct at any window size.

This file targets Streamlit 1.32.0. It intentionally avoids the newer
``st-key-`` auto-generated CSS class feature for styling individual widgets,
since that convenience wasn't confirmed present in this pinned version --
selectors below use the older, stable ``data-testid`` attributes instead.
"""

from __future__ import annotations

from typing import Literal
from pathlib import Path
from html import escape

from utils.accessibility import accessible_theme, normalize_font_scale

import streamlit as st

ThemeName = Literal["light", "dark"]
StatusName = Literal["ok", "warning", "error", "info"]

# --------------------------------------------------------------------------
# Layout constants (fixed pixel values -- carry over directly regardless of
# viewport width; see module docstring for how proportional widths differ).
# --------------------------------------------------------------------------
FRAME_WIDTH = 1440
FRAME_HEIGHT = 900
SIDEBAR_WIDTH = 220
CONTENT_GUTTER = 24  # per style guide -- gap between sidebar and content
CONTENT_X = SIDEBAR_WIDTH + CONTENT_GUTTER  # = 244
CONTENT_RIGHT_MARGIN = 24  # per style guide -- gap between content and page right edge
CONTENT_WIDTH = FRAME_WIDTH - CONTENT_X - CONTENT_RIGHT_MARGIN  # = 1172

HEADER_HEIGHT = 64
SECTION_GAP = 16
PANEL_RADIUS = 8
BUTTON_RADIUS = 6
PILL_RADIUS = 16
BADGE_RADIUS = 9
TABLE_ROW_HEIGHT = 28
TABLE_HEADER_HEIGHT = 32

PROGRESS_BAR_WIDTH = 260
PROGRESS_BAR_HEIGHT = 8
PROGRESS_BAR_RADIUS = 4
TOTAL_STAGES = 8

CHART_FONT_FAMILY = "Inter, -apple-system, 'Segoe UI', sans-serif"

# --------------------------------------------------------------------------
# Brand constants -- identical in both themes, never theme these.
# --------------------------------------------------------------------------
ACCENT = "#587BBD"
HARTRAO_DARK_BLUE = "#395790"

LCP_COLOR = "#1F77B4"
RCP_COLOR = "#FF7F0E"

# FR-09 derived traces: shared across panels and identical in both themes.
# TODO: confirm against design — mean/Stokes I tokens were not in the original style guide.
MEAN_COLOR = "#2CA02C"
STOKES_I_COLOR = "#9467BD"

FIT_LINE_COLOR: dict[ThemeName, str] = {
    "light": "#DC2626",
    "dark": "#F87171",
}

PROGRESS_BAR_COLORS = {
    "track": "#E2E8F0",
    "fill": ACCENT,
    "label": "#64748B",
    "caption": "#94A3B8",
}

# --------------------------------------------------------------------------
# Theme token tables (prompt section 4). Keys are identical across both
# themes on purpose -- pages should never need an if/else on theme name.
# --------------------------------------------------------------------------
THEMES: dict[ThemeName, dict[str, str]] = {
    "light": {
        "bg-primary": "#FFFFFF",
        "bg-sidebar": "#395790",
        "bg-panel": "#FFFFFF",
        "bg-panel-alt": "#F8FAFC",
        "border-default": "#CBD5E1",
        "border-subtle": "#E2E8F0",
        "accent": ACCENT,
        "text-heading": "#0F172A",
        "text-body": "#334155",
        "text-muted": "#64748B",
        "text-faint": "#94A3B8",
        "sidebar-text-active": "#FFFFFF",
        "sidebar-text-inactive": "#B7C3DA",
        "sidebar-btn-bg": "#334155",
        "sidebar-btn-border": "#475569",
        "table-header-bg": "#395790",
        "table-header-text": "#F1F5F9",
    },
    "dark": {
        # Note: dark-mode bg-primary intentionally equals light-mode
        # bg-sidebar (#395790) -- that's the design, not a bug. Because of
        # this, dark-mode panels/tables MUST keep their own bg-panel fill
        # and border-subtle outline -- without it a table header blends
        # into the page background.
        "bg-primary": "#395790",
        # Sidebar uses the same #395790 as light mode per explicit request --
        # this overrides the style guide's original dark-mode-only sidebar
        # color (#16233D). Flagging the divergence here since it's a
        # deliberate deviation from that doc, not an oversight.
        "bg-sidebar": "#16233D",
        "bg-panel": "#1E293B",
        "bg-panel-alt": "#243044",
        "border-default": "#334155",
        "border-subtle": "#2B3A52",
        "accent": ACCENT,
        "text-heading": "#F1F5F9",
        "text-body": "#CBD5E1",
        "text-muted": "#94A3B8",
        "text-faint": "#64748B",
        "sidebar-text-active": "#FFFFFF",
        "sidebar-text-inactive": "#7F92B5",
        "sidebar-btn-bg": "#233450",
        "sidebar-btn-border": "#3A4C6E",
        # User-approved header-only override: retain the original panel and row fills.
        "table-header-bg": "#111827",
        "table-header-text": "#F1F5F9",
    },
}

STATUS_BADGES: dict[ThemeName, dict[StatusName, tuple[str, str]]] = {
    "light": {
        "ok": ("#DCFCE7", "#166534"),
        "warning": ("#FEF9C3", "#854D0E"),
        "error": ("#FEE2E2", "#991B1B"),
        "info": ("#DBEAFE", "#1E40AF"),
    },
    "dark": {
        "ok": ("#14532D", "#86EFAC"),
        "warning": ("#78350F", "#FDE68A"),
        "error": ("#7F1D1D", "#FCA5A5"),
        "info": ("#1E3A5F", "#93C5FD"),
    },
}


def get_theme_name() -> ThemeName:
    """Return the active theme name, defaulting to ``"light"`` on first run."""
    name = st.session_state.get("theme", "light")
    if name not in ("light", "dark"):
        name = "light"
    st.session_state["theme"] = name
    return name


def get_theme() -> dict[str, str]:
    """Return the token dict for the currently active theme."""
    return accessible_theme(THEMES[get_theme_name()])


def get_status_badges() -> dict[StatusName, tuple[str, str]]:
    """Return the (fill, text) badge color pairs for the active theme."""
    return STATUS_BADGES[get_theme_name()]


def get_fit_line_color() -> str:
    """Return the dashed fit-overlay color for the active theme (see §4)."""
    return FIT_LINE_COLOR[get_theme_name()]


def plotly_layout_theme(theme: dict[str, str] | None = None) -> dict:
    """Return a complete Plotly ``update_layout`` kwargs dict for the active
    theme, so every chart's background, axis lines, tick labels, axis
    titles, and legend text all stay legible in both light and dark mode.

    ROOT CAUSE this fixes: Plotly's own default template renders tick
    labels, axis titles, and legend text in a fixed color regardless of
    ``paper_bgcolor``/``plot_bgcolor``. A page that only sets those two
    background colors -- or sets a top-level ``font=dict(color=...)`` but
    leaves an axis's own ``tickfont``/``title`` unset -- can end up with
    numbers that are effectively invisible once ``bg-panel`` is dark (or,
    depending on Plotly's default gray, dim in light mode too).
    ``06_Pointing_Correction.py``'s per-panel scan chart was a concrete
    example: it set ``tickfont=dict(size=8)`` with no ``color`` key at
    all, which does NOT inherit the figure's top-level ``layout.font``
    color the way the legend/title text does.

    Usage -- call this FIRST, then layer page-specific settings on top
    (Plotly's ``update_layout`` merges nested dicts rather than replacing
    them outright, so a later ``fig.update_layout(xaxis=dict(title=...))``
    adds to this rather than discarding the color already set here):

        theme = styles.get_theme()
        fig.update_layout(**styles.plotly_layout_theme(theme))
        fig.update_layout(height=320, margin=dict(...))  # page-specific after

    Any additional per-axis property (a custom range, a log scale, an
    explicit ``title`` string) is safe to add afterward the same way --
    only pass the keys you need to change; everything else set here is
    preserved.

    AXIS TITLE FIX (this revision): a page that later sets
    ``xaxis=dict(title="Vlsr (km/s)")`` -- a plain string, the common
    shorthand every page here uses -- causes Plotly to replace the whole
    nested ``title`` object, including any ``font`` set only inside it.
    The dict-level merge that keeps sibling keys (``linecolor``,
    ``tickfont``, etc.) intact does NOT protect a property nested inside
    a compound value that itself gets reassigned wholesale. Fixed by also
    setting axis-level ``color`` here -- a sibling key to ``title``, not
    nested inside it, so a later page-level title-only update can't wipe
    it out. Plotly uses an axis's own ``color`` as the default for its
    line, ticks, AND title text whenever a more specific font color isn't
    set closer to that element, which is exactly the fallback needed here.
    """
    theme = theme or get_theme()
    axis_defaults = dict(
        showgrid=False,
        zeroline=False,
        linecolor=theme["border-subtle"],
        color=theme["text-muted"],
        tickfont=dict(color=theme["text-muted"], family=CHART_FONT_FAMILY, size=10),
        title=dict(font=dict(color=theme["text-muted"], family=CHART_FONT_FAMILY, size=11)),
    )
    return {
        "paper_bgcolor": theme["bg-panel"],
        "plot_bgcolor": theme["bg-panel"],
        "font": dict(family=CHART_FONT_FAMILY, size=11, color=theme["text-body"]),
        "legend": dict(font=dict(color=theme["text-body"], family=CHART_FONT_FAMILY, size=10)),
        "xaxis": dict(**axis_defaults),
        "yaxis": dict(**axis_defaults),
    }


def get_font_scale() -> int:
    """Return the validated percentage, separate from page-owned widget state."""
    return normalize_font_scale(st.session_state.get("font_scale", 100))


def surface_border_colour(theme: dict[str, str], fallback: str = "border-default") -> str:
    """Match dark decorative outlines to the header, preserving each light fallback.

    Does not change the palette's shared border tokens: chart axes, table cell
    separators, input borders and keyboard-focus rings still use those tokens.
    """
    if theme["bg-primary"] == THEMES["dark"]["bg-primary"]:
        return theme["table-header-bg"]
    return theme[fallback]


def inject_base_css() -> None:
    """Inject global CSS for the active theme.

    Call near the top of every page script -- after ``st.set_page_config``
    and ``sidebar.render_sidebar``, before any other UI is rendered.
    """
    theme = get_theme()
    # Reset counters only after a chart/table has actually created them. Avoid
    # modifying a source-browsing session just by injecting display CSS.
    for key in ("_a11y_chart_counter", "_a11y_table_counter"):
        if key in st.session_state:
            st.session_state[key] = 0

    st.markdown(
        f"""
        <style>
        /* -- Font -------------------------------------------------------
           Inter must be self-hosted: the intranet server has no internet
           dependency, so this can't point at Google Fonts. Place woff2
           files under `static/fonts/` and add
               [server]
               enableStaticServing = true
           to .streamlit/config.toml (already stubbed in this project's
           config.toml). Falls back to the system sans-serif stack if the
           font files aren't present yet, so the app still renders. */
        @font-face {{
            font-family: 'Inter';
            font-weight: 400;
            src: url('app/static/fonts/Inter-Regular.woff2') format('woff2');
        }}
        @font-face {{
            font-family: 'Inter';
            font-weight: 600;
            src: url('app/static/fonts/Inter-SemiBold.woff2') format('woff2');
        }}
        @font-face {{
            font-family: 'Inter';
            font-weight: 700;
            src: url('app/static/fonts/Inter-Bold.woff2') format('woff2');
        }}

        html, body, [class*="css"] {{
            font-family: 'Inter', -apple-system, 'Segoe UI', sans-serif;
        }}

        /* Hide Streamlit's chrome + default multipage nav -- the custom
           sidebar in utils/sidebar.py replaces the nav entirely. */
        #MainMenu, footer {{ visibility: hidden; }}
        [data-testid="stSidebarNav"] {{ display: none; }}

        .stApp {{
            background-color: {theme['bg-primary']};
        }}

        [data-testid="stSidebar"] {{
            background-color: {theme['bg-sidebar']};
            width: {SIDEBAR_WIDTH}px !important;
            min-width: {SIDEBAR_WIDTH}px !important;
        }}

        /* Set the default on the sidebar, not every descendant: select values,
           SVG icons and emphasized help text must inherit their own control colour. */
        [data-testid="stSidebar"] {{
            color: {theme['sidebar-text-inactive']};
        }}

        /* Inactive nav items -- text only, no background, no border, no
           hover fill. Scoped via the .hs-nav-marker span sidebar.py emits
           immediately before each nav st.button, using the long-stable
           .element-container wrapper class + :has() -- this deliberately
           avoids the newer `st-key-` widget CSS class, which only shipped
           in Streamlit 1.39 and isn't available in this project's pinned
           1.32.0. The active stage is its own filled pill <div>, rendered
           separately in utils/sidebar.py, and is unaffected by this rule. */
        [data-testid="stSidebar"] .element-container:has(.hs-nav-marker) + .element-container button {{
            background: transparent !important;
            border: none !important;
            box-shadow: none !important;
            color: {theme['sidebar-text-inactive']} !important;
            font-size: 0.75rem !important;
            font-weight: 400 !important;
            text-align: left !important;
            justify-content: flex-start !important;
            padding: 8px 12px !important;
        }}
        [data-testid="stSidebar"] .element-container:has(.hs-nav-marker) + .element-container button:hover,
        [data-testid="stSidebar"] .element-container:has(.hs-nav-marker) + .element-container button:focus {{
            background: transparent !important;
            border: none !important;
            box-shadow: none !important;
            color: {theme['sidebar-text-inactive']} !important;
        }}

        .block-container {{
            padding-top: 2rem;
            padding-left: {CONTENT_GUTTER}px;
            padding-right: {CONTENT_RIGHT_MARGIN}px;
            max-width: {CONTENT_WIDTH}px;
        }}

        .hs-title {{
            color: {theme['text-heading']};
            font-weight: 700;
        }}

        .hs-subtitle {{
            color: {theme['text-muted']};
            font-size: 0.8125rem;
        }}

        .hs-eyebrow {{
            color: {theme['text-muted']};
            font-size: 0.625rem;
            font-weight: 600;
            letter-spacing: 0.06em;
            text-transform: uppercase;
            margin-bottom: 6px;
        }}

        .hs-panel {{
            background-color: {theme['bg-panel']};
            border: 1px solid {theme['border-default']};
            border-radius: {PANEL_RADIUS}px;
            padding: 16px;
            margin-bottom: {SECTION_GAP}px;
        }}

        .hs-panel-title {{
            color: {theme['text-body']};
            font-size: 0.65625rem;
            font-weight: 600;
            margin-bottom: 12px;
        }}

        .hs-badge {{
            display: inline-block;
            border-radius: {BADGE_RADIUS}px;
            padding: 3px 10px;
            font-size: 0.625rem;
            font-weight: 600;
            line-height: 1;
            white-space: nowrap;
        }}

        /* Buttons -- Streamlit exposes button "kind" via a stable
           data-testid rather than the newer key-based CSS class. */
        button[data-testid="baseButton-primary"] {{
            background-color: {theme['accent']} !important;
            border: none !important;
            color: {theme['text-on-accent']} !important;
            border-radius: {BUTTON_RADIUS}px !important;
            font-weight: 600 !important;
        }}
        button[data-testid="baseButton-secondary"] {{
            background-color: {theme['bg-panel']} !important;
            border: 1px solid {theme['border-default']} !important;
            color: {theme['text-body']} !important;
            border-radius: {BUTTON_RADIUS}px !important;
            font-weight: 600 !important;
        }}

        [data-testid="stVerticalBlockBorderWrapper"] {{
            border-radius: {PANEL_RADIUS}px !important;
        }}

        /* Native st.radio option text (Page 02's Auto/Manual toggle,
           Page 03's Bandpass mode, Page 07's Fit type, and any future
           st.radio) falls back to Streamlit's own base theme text color
           from .streamlit/config.toml, which is static per server
           instance and doesn't react to st.session_state["theme"] (see
           the Style Guide's §5 note) -- unlike .stButton, which does pick
           up theme tokens correctly. Fixed once here, system-wide. */
        [data-testid="stRadio"] label p,
        [data-testid="stRadio"] [data-testid="stMarkdownContainer"] p {{
            color: {theme['text-body']} !important;
        }}
        /* FR-09 native controls/captions must follow the runtime theme too. */
        [data-testid="stCheckbox"] label p,
        [data-testid="stNumberInput"] label p {{
            color: {theme['text-body']} !important;
        }}
        [data-testid="stCaptionContainer"] p {{
            color: {theme['text-muted']} !important;
        }}
        [data-testid="stNumberInput"] input {{
            color: {theme['text-body']} !important;
            background-color: {theme['bg-panel']} !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )

    # TODO: confirm against design — see build spec §3. Enlarged text and safe
    # contrast intentionally override the original fixed-height small-text rules.
    variables = {
        "root-size": f"{16 * get_font_scale() / 100:g}px",
        "sidebar-width": f"{SIDEBAR_WIDTH * get_font_scale() / 100:g}px",
        "text-body": theme["text-body"], "text-muted": theme["text-muted"],
        "bg-panel": theme["bg-panel"], "bg-panel-alt": theme["bg-panel-alt"],
        "control-border": theme["control-border"], "text-on-accent": theme["text-on-accent"],
        "sidebar-text": theme["sidebar-text-inactive"],
        "focus-ring": theme["focus-ring"], "panel-focus-ring": theme["focus-ring"],
        "text-heading": theme["text-heading"], "bg-primary": theme["bg-primary"],
        "accent": theme["accent"],
        "table-header-bg": theme["table-header-bg"], "table-header-text": theme["table-header-text"],
        "section-header-bg": theme["table-header-bg"] if get_theme_name() == "dark" else "transparent",
        "section-header-text": theme["table-header-text"] if get_theme_name() == "dark" else theme["text-body"],
        "section-header-padding": ".5rem .75rem" if get_theme_name() == "dark" else "0",
    }
    custom = ";".join(f"--hs-{key}:{value}" for key, value in variables.items())
    css = Path(__file__).with_name("accessibility.css").read_text(encoding="utf-8")
    # User-approved decorative outline colour only; light-mode CSS stays unchanged.
    if get_theme_name() == "dark":
        css += "\n" + Path(__file__).with_name("dark_surface_borders.css").read_text(encoding="utf-8")
    st.markdown(f"<style>:root{{{custom}}}\n{css}</style>", unsafe_allow_html=True)


def render_plotly_chart(figure, **kwargs):
    """Render a chart with scalable text and equivalent keyboard view controls."""
    from utils.accessibility_ui import render_plotly_chart as render
    return render(figure, **kwargs)


def render_dataframe(data, **kwargs):
    """Keep the native grid plus an accessible, scalable read-only table view."""
    from utils.accessibility_ui import render_dataframe as render
    return render(data, **kwargs)


def render_badge(label: str, status: StatusName) -> str:
    """Return an HTML ``<span>`` for a status badge in the active theme.

    Always a fill/text color pair -- never a bare colored dot -- per the
    component spec in prompt §8.
    """
    fill, text = get_status_badges()[status]
    return f'<span class="hs-badge" style="background-color:{fill}; color:{text};">{label}</span>'


def render_panel_open(title: str) -> None:
    """Open a themed panel ``<div>``, optionally with a title. Pair with `render_panel_close`."""
    title_html = f'<div class="hs-panel-title">{title}</div>' if title else ""
    st.markdown(f'<div class="hs-panel">{title_html}', unsafe_allow_html=True)


def render_panel_close() -> None:
    """Close a panel opened with `render_panel_open`."""
    st.markdown("</div>", unsafe_allow_html=True)


def render_page_header(title: str, subtitle: str, current_stage: int, completed_stages: int) -> None:
    """Render the shared page header: H1 + subtitle on the left, the
    pipeline progress bar top-right -- matches the layout used across all
    8 dark-mode Figma frames, applied uniformly to every page/theme
    (prompt §8 "Pipeline progress bar" / §10).

    Parameters
    ----------
    title:
        Page H1, e.g. ``"Source Browser"``.
    subtitle:
        FR-reference subtitle line.
    current_stage:
        1-indexed stage number (1-8), shown as "Stage N of 8".
    completed_stages:
        Count of stages strictly before this one that are already
        complete. Used to size the progress fill -- pass
        ``session_store.completed_count()``.
    """
    pct = max(0.0, min(1.0, completed_stages / TOTAL_STAGES))
    fill_width = max(4, round(PROGRESS_BAR_WIDTH * pct))
    colors = dict(PROGRESS_BAR_COLORS, label=get_theme()["text-muted"], caption=get_theme()["text-muted"])
    theme = get_theme()

    st.markdown(
        f"""
        <div class="hs-page-header" style="display:flex; justify-content:space-between; align-items:flex-start;
                    border-bottom:1px solid {theme['border-subtle']};
                    padding-bottom:16px; margin-bottom:{SECTION_GAP}px;">
          <div>
            <h1 id="hs-main-content" tabindex="-1" class="hs-title">{escape(title)}</h1>
            <div class="hs-subtitle">{escape(subtitle)}</div>
          </div>
          <div class="hs-progress" style="width:{PROGRESS_BAR_WIDTH}px; text-align:right; flex-shrink:0;">
            <div style="font-size:0.625rem; font-weight:600; color:{colors['label']};">
                Stage {current_stage} of {TOTAL_STAGES}
            </div>
            <div role="progressbar" aria-label="Pipeline stages complete" aria-valuemin="0"
                 aria-valuemax="8" aria-valuenow="{max(0, min(8, completed_stages))}"
                 style="width:100%; height:{PROGRESS_BAR_HEIGHT}px; border-radius:{PROGRESS_BAR_RADIUS}px;
                        background-color:{colors['track']}; margin:6px 0 4px;">
              <div style="width:{fill_width}px; height:100%; border-radius:{PROGRESS_BAR_RADIUS}px;
                          background-color:{colors['fill']};"></div>
            </div>
            <div style="font-size:0.5625rem; color:{colors['caption']};">
                {completed_stages}/{TOTAL_STAGES} stages complete
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
