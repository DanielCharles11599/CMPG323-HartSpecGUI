"""HARTSPEC GUI -- multipage entry point.

Streamlit's classic ``pages/`` auto-discovery (the mechanism this project
uses, since ``st.navigation``/``st.Page`` weren't available yet as of the
pinned Streamlit 1.32.0) requires a root script to launch. Run this file:

    streamlit run Home.py

It doesn't render its own UI -- it immediately hands off to Stage 01 so
users always land on the start of the pipeline.

Loads a local .env file (if present) before anything else, so env-var
overrides like HARTSPEC_FITS_ARCHIVE_ROOT work without setting them in the
shell every session. See .env.example. utils/fits_ingest.py also loads
.env at its own import time, independently -- this call here is defense in
depth for the `streamlit run Home.py` entry point specifically, not the
only place it happens.
"""

from __future__ import annotations

import streamlit as st

from utils.env import load_dotenv_if_present

load_dotenv_if_present()

st.switch_page("pages/01_Source_Browser.py")