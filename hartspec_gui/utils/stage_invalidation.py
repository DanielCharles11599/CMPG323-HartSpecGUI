"""stage_invalidation.py -- clear everything derived from the Page 4 baseline.

Several pages derive their results from the baseline-flattened spectrum:

  05_calibration_dashboard  -> st.session_state["calibrated_spectrum"]
  07_spectral_fitting       -> st.session_state["latest_fit"]
  08_export_and_session     -> export-complete marker

If the spectrum upstream of them changes (bandpass mode changed on Page 3, or
the baseline blocks / polynomial orders were edited on Page 4), those results
are stale. Each page recomputes its own state when *visited*, but Pages 7/8
can be reached directly from the sidebar without revisiting Page 5 -- so
without an explicit invalidation step, a user could fit or export against a
calibrated spectrum computed from a baseline that no longer exists.

Pure functions over a mapping (st.session_state in the app, a plain dict in
tests), so this needs no Streamlit runtime to verify.

Page 06 (Pointing Correction) is deliberately NOT listed: its inputs are the
half-power-point scan readings, not the baseline-flattened spectrum, so a
baseline change does not make its result stale.
"""

from __future__ import annotations

from typing import Any, MutableMapping

BASELINE_DEPENDENT_STAGE_KEYS = (
    "05_calibration_dashboard",
    "07_spectral_fitting",
    "08_export_and_session",
)

BASELINE_DEPENDENT_SESSION_KEYS = (
    "calibrated_spectrum",
    "latest_fit",
)


def invalidate_baseline_dependents(session_state: MutableMapping[str, Any]) -> None:
    """Drop completion flags, saved summaries and derived arrays for every
    stage downstream of the Page 4 baseline.

    Safe to call repeatedly and on a partially-initialised session: missing
    keys are ignored rather than raising.
    """
    completed = session_state.get("completed_stages")
    pipeline_data = session_state.get("pipeline_data")

    for stage_key in BASELINE_DEPENDENT_STAGE_KEYS:
        if completed is not None:
            completed.discard(stage_key)
        if pipeline_data is not None:
            pipeline_data.pop(stage_key, None)

    for key in BASELINE_DEPENDENT_SESSION_KEYS:
        session_state.pop(key, None)
