
"""HARTSPEC GUI -- multipage entry point.

Streamlit's classic ``pages/`` auto-discovery (the mechanism this project
uses, since ``st.navigation``/``st.Page`` weren't available yet as of the
pinned Streamlit 1.32.0) requires a root script to launch. Run this file:

    streamlit run Home.py

It doesn't render its own UI -- it immediately hands off to Stage 01 so
users always land on the start of the pipeline.
"""

from __future__ import annotations

import streamlit as st

st.switch_page("pages/01_Source_Browser.py")
