"""Shared sidebar: logo, pipeline nav, theme toggle, and session controls.

Rendered identically on every page per the code-gen prompt §7 -- call
``render_sidebar`` once, near the top of each page script, right after
``st.set_page_config``. The three session actions (Save / Load / Reset) are
implemented once here rather than being rebuilt per page, as the prompt
requires.
"""

from __future__ import annotations

import streamlit as st

from utils import session_store, styles
from utils.accessibility import FONT_SCALES, normalize_font_scale
from utils.accessibility_help import help_link_html

# (path relative to the app's root script, page label as shown in the nav)
STAGES: list[tuple[str, str]] = [
    ("pages/01_Source_Browser.py", "01  Source Browser"),
    ("pages/02_File_Loader.py", "02  File Loader"),
    ("pages/03_Bandpass_Correction.py", "03  Bandpass Correction"),
    ("pages/04_Baseline_Editor.py", "04  Baseline Block Editor"),
    ("pages/05_Calibration_Dashboard.py", "05  Calibration Dashboard"),
    ("pages/06_Pointing_Correction.py", "06  Pointing Correction"),
    ("pages/07_Spectral_Fitting.py", "07  Spectral Fitting"),
    ("pages/08_Export_and_Session.py", "08  Export & Session"),
]


def _set_theme(name: str) -> None:
    """Commit display-only preferences before rerun; preserve all pipeline outputs."""
    st.session_state["theme"] = name
    session_store.checkpoint_session("Display theme changed", allow_empty=True)


def _set_font_scale() -> None:
    """Copy the temporary widget into a page-independent, checkpointed preference."""
    st.session_state["font_scale"] = normalize_font_scale(st.session_state["_a11y_font_scale"])
    session_store.checkpoint_session("Display font size changed", allow_empty=True)


def render_sidebar(current_stage: int) -> None:
    """Render the sidebar for the page at ``current_stage`` (1-indexed, 1-8).

    The active stage is shown as a filled, non-interactive pill (there's no
    need for it to be clickable -- the user is already on that page); the
    other seven are ``st.button`` + ``st.switch_page`` (NOT ``st.page_link``:
    that command validates its target file at render time, so the sidebar
    would break the moment it lists a stage whose page file doesn't exist
    yet -- ``switch_page`` only checks the target when actually clicked).
    Each of these buttons is preceded by a small ``.hs-nav-marker`` element
    so ``styles.inject_base_css`` can strip its background/border via CSS
    without touching the Save/Load/Reset or theme-toggle buttons below.
    """
    session_store.begin_page(current_stage)
    theme = styles.get_theme()

    with st.sidebar:
        st.markdown('<a class="hs-skip-link" href="#hs-main-content">Skip to page content</a>',
                    unsafe_allow_html=True)
        st.markdown(
            '<div style="padding:24px 24px 12px; font-size:1.125rem; font-weight:700; '
            'color:#FFFFFF;">HARTSPEC</div>',
            unsafe_allow_html=True,
        )

        for idx, (page_path, label) in enumerate(STAGES, start=1):
            if idx == current_stage:
                st.markdown(
                    f'<div class="hs-active-nav" aria-current="page" '
                    f'style="margin:2px 12px 2px; padding:8px 12px; border-radius:6px; '
                    # font-size intentionally omitted here -- standardizes label size
                    # between the active (filled pill) and inactive (button) nav items
                    f'background-color:{theme["accent"]}; color:{theme["text-on-accent"]}; '
                    f'font-weight:600;">{label}</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown('<span class="hs-nav-marker"></span>', unsafe_allow_html=True)
                if st.button(label, key=f"nav_{idx}", use_container_width=True):
                    st.switch_page(page_path)

        st.markdown("<div style='margin-top:20px;'></div>", unsafe_allow_html=True)
        st.caption("THEME")
        col_light, col_dark = st.columns(2)
        with col_light:
            st.button("☀ Light", key="theme_light", use_container_width=True,
                      on_click=_set_theme, args=("light",))
        with col_dark:
            st.button("🌙 Dark", key="theme_dark", use_container_width=True,
                      on_click=_set_theme, args=("dark",))

        st.caption(f"Current theme: {styles.get_theme_name().title()}")
        # The permanent key must not be owned by Streamlit's per-page widget cleanup.
        st.session_state["_a11y_font_scale"] = styles.get_font_scale()
        # Display numeric percentages directly: Streamlit 1.32's AppTest
        # selectbox cannot round-trip format_func labels like "200%" when the
        # stored widget value is the integer 200. Keep the unit in the label.
        st.selectbox("Font size (%)", FONT_SCALES, key="_a11y_font_scale", on_change=_set_font_scale)
        # TODO: confirm against design — see build spec §3. Keep long instructions
        # on a separate manual page; never forward this tab's private recovery token.
        get_option = getattr(st, "get_option", None)
        base_path = get_option("server.baseUrlPath") if callable(get_option) else ""
        st.markdown(
            help_link_html(styles.get_theme_name(), styles.get_font_scale(), base_path=base_path),
            unsafe_allow_html=True,
        )

        st.markdown("<div style='margin-top:16px;'></div>", unsafe_allow_html=True)
        st.caption("SESSION")
        st.session_state["checkpoint_status_placeholder"] = st.empty()
        session_store.render_checkpoint_status()
        if st.session_state.get("checkpoint_notice"):
            st.info(st.session_state.pop("checkpoint_notice"))
        if st.session_state.get("checkpoint_error") and st.button("Retry checkpoint", key="checkpoint_retry"):
            session_store.checkpoint_session("Checkpoint retry", allow_empty=True)

        if st.button("Save Session", key="session_save", use_container_width=True):
            try:
                saved_path = session_store.save_session()
                st.success(f"Saved: {saved_path.name}")
            except (OSError, UnicodeError, ValueError, TypeError) as exc:
                st.error(f"Session not saved: {exc}. Current work remains in memory.")

        with st.expander("Load Session"):
            try:
                saved_sessions = session_store.list_sessions()
            except OSError as exc:
                saved_sessions = []
                st.error(f"Cannot read saved sessions: {exc}")
            if not saved_sessions:
                st.caption("No saved sessions yet.")
            else:
                chosen = st.selectbox(
                    "Choose a session",
                    saved_sessions,
                    format_func=lambda p: p.stem,
                    key="session_load_choice",
                    label_visibility="collapsed",
                )
                if st.button("Load", key="session_load_confirm", use_container_width=True):
                    try:
                        session_store.load_session(chosen)
                    except (OSError, UnicodeError, ValueError) as exc:
                        st.error(f"Could not load session: {exc}")

        # TODO: confirm against design — shared checkpoint recovery complements the three session actions.
        with st.expander("Recover checkpoint"):
            from utils import checkpoint_store
            try:
                checkpoints = checkpoint_store.list_latest(session_store.SESSIONS_DIR)
            except OSError as exc:
                checkpoints = []
                st.error(f"Cannot list checkpoints: {exc}")
            if checkpoints:
                # Preserve the stable recovery stream ID separately from the
                # user-facing labels. Streamlit 1.32's AppTest checks displayed
                # options against the widget state, not format_func's raw value.
                options = {item.path.parent.name: item for item in checkpoints}
                current_stream = st.session_state.get("session_checkpoint_choice")
                if current_stream not in options:
                    current_stream = next(iter(options))

                labels_to_streams = {}
                for stream_id, item in options.items():
                    label = _checkpoint_label(item.payload)
                    if label in labels_to_streams:
                        # Different streams can have identical source/stage/time labels.
                        suffix = 2
                        while f"{label} ({suffix})" in labels_to_streams:
                            suffix += 1
                        label = f"{label} ({suffix})"
                    labels_to_streams[label] = stream_id

                display_key = "session_checkpoint_display_choice"

                def _select_checkpoint() -> None:
                    """Keep the stable stream ID when a user picks a display label."""
                    selected = st.session_state.get(display_key)
                    if selected in labels_to_streams:
                        st.session_state["session_checkpoint_choice"] = labels_to_streams[selected]

                # A revision can change a label or make it collide with another
                # stream's label. On non-selection reruns, the stored ID wins.
                current_label = next(
                    label for label, stream_id in labels_to_streams.items()
                    if stream_id == current_stream
                )
                if st.session_state.get(display_key) != current_label:
                    st.session_state[display_key] = current_label
                chosen_label = st.selectbox(
                    "Checkpoint", list(labels_to_streams), key=display_key,
                    on_change=_select_checkpoint,
                )
                chosen_checkpoint = labels_to_streams[chosen_label]
                st.session_state["session_checkpoint_choice"] = chosen_checkpoint
                if st.button("Recover selected", key="session_checkpoint_recover", use_container_width=True):
                    try:
                        selected = options[chosen_checkpoint]
                        session_store.recover_checkpoint(selected.path, warning=selected.warning)
                    except (OSError, UnicodeError, ValueError) as exc:
                        st.error(f"Could not recover checkpoint: {exc}")
            else:
                st.caption("No automatic checkpoints yet.")
            st.caption("Recovery uses the private identifier in this tab's URL. Keep the address private.")

        if st.button("Reset Session", key="session_reset", use_container_width=True):
            session_store.reset_session()
            st.rerun()


def _checkpoint_label(payload: dict) -> str:
    """Make explicit recovery choices distinguishable without exposing token values."""
    source = payload.get("pipeline_data", {}).get("01_source_browser", {})
    source = source if isinstance(source, dict) else {}
    label = source.get("source_name") or "Unnamed reduction"
    count = len(payload.get("completed_stages", []))
    return f"{label} · {count}/8 stages · {payload.get('saved_at', '')}"
