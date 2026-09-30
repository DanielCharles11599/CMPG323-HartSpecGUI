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
    session_store.init_session_state()
    theme = styles.get_theme()

    with st.sidebar:
        st.markdown(
            '<div style="padding:24px 24px 12px; font-size:18px; font-weight:700; '
            'color:#FFFFFF;">HARTSPEC</div>',
            unsafe_allow_html=True,
        )

        for idx, (page_path, label) in enumerate(STAGES, start=1):
            if idx == current_stage:
                st.markdown(
                    f'<div style="margin:2px 12px 2px; padding:8px 12px; border-radius:6px; '
                    # font-size intentionally omitted here -- standardizes label size
                    # between the active (filled pill) and inactive (button) nav items
                    f'background-color:{theme["accent"]}; color:#FFFFFF; '
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
            if st.button("☀ Light", key="theme_light", use_container_width=True):
                st.session_state["theme"] = "light"
                st.rerun()
        with col_dark:
            if st.button("🌙 Dark", key="theme_dark", use_container_width=True):
                st.session_state["theme"] = "dark"
                st.rerun()

        st.markdown("<div style='margin-top:16px;'></div>", unsafe_allow_html=True)
        st.caption("SESSION")

        if st.button("Save Session", key="session_save", use_container_width=True):
            saved_path = session_store.save_session()
            st.success(f"Saved: {saved_path.name}")

        with st.expander("Load Session"):
            saved_sessions = session_store.list_sessions()
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
                    session_store.load_session(chosen)
                    st.rerun()

        if st.button("Reset Session", key="session_reset", use_container_width=True):
            session_store.reset_session()
            st.rerun()
