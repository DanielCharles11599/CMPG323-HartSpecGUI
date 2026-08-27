# bandpass_correction_logic.py — FR-04: pure/testable logic backing
# pages/03_Bandpass_Correction.py. Kept separate from the Streamlit page script
# (same rationale as utils/source_browser_logic.py's own module docstring):
# importing a pages/*.py file directly executes st.set_page_config()/st.* calls
# at import time and fails outside a running Streamlit app.
#
# Numerical core (freq_switch_correct / pos_switch_correct) reproduces the same
# array operations as clc/Baseline.py's freq_switch() / pos_switch() line-for-
# line (elementwise subtract, then restrict to the np.in1d-derived common-
# velocity channels for the frequency-switch case), so results match the
# original CLI's bandpass-corrected output to the project's 6-significant-
# figure regression bar (see HARTSPEC-Claude Project Prompt.md, "Coding
# standards"). This module deliberately does NOT call clc.Baseline.freq_switch
# / clc.Baseline.pos_switch directly, though:
#
# TODO: confirm against design — clc/Baseline.py's freq_switch() and
# pos_switch() unconditionally call plt.plot(...) / plt.savefig(
# "../plots/Bandpass_Example_*.pdf", ...) as a side effect of doing the
# correction. That's a problem for GUI integration two ways: (a) it creates
# orphaned matplotlib Figures inside the Streamlit process instead of the
# mandated Plotly charts, and (b) it writes to a path relative to the
# process's cwd rather than anywhere in the project's /data/ convention --
# depending on how `streamlit run` is invoked this either raises (no
# "../plots" directory) or silently writes a file to an unexpected location.
# This wasn't listed among the Phase-0 GUI-integration fixes already applied
# to clc/Point_cor.py / clc/load_file.py / clc/Option.py, so per the project
# instructions ("never modify the underlying scientific algorithms" + "ask
# before assuming it's still broken") it isn't safe to assume this is already
# handled elsewhere, and this file doesn't patch clc/Baseline.py to work
# around it. Instead, the same math is reimplemented independently below so
# the GUI keeps working today -- flag this for the team to confirm whether
# clc/Baseline.py should get a Phase-0-style GUI-integration fix (stripping
# the plotting side effect) or whether re-deriving the math here is the
# long-term intended pattern.
#
# TODO: confirm against design — separately, clc/Baseline.py's freq_switch()
# calls np.in1d(), which NumPy removed in 2.0. requirements.txt pins
# numpy>=1.24 with no upper bound, so clc/Baseline.py as currently written
# will raise AttributeError under any NumPy >=2.0 environment -- this looks
# like a real forward-compat bug in clc/, distinct from the plotting-side-
# effect issue above, and is flagged rather than fixed in clc/ itself for the
# same "never modify the underlying scientific algorithms" / "ask" reason.
# This file uses np.isin() (the maintained, behavior-equivalent replacement)
# in its own reimplementation below.

from typing import Dict, Tuple

import numpy as np
import streamlit as st

# Vlsr/LCP/RCP arrays, matching the exact contract clc/Baseline.py's own
# freq_switch()/pos_switch() expect (dict-like with these three keys).
SpectrumDict = Dict[str, np.ndarray]

# This page's own key in utils/session_store.py's `pipeline_data` dict and
# `completed_stages` set -- same "01_source_browser"-style convention as
# utils/source_browser_logic.THIS_STAGE_KEY.
THIS_STAGE_KEY = "03_bandpass_correction"

# Build spec §7 (page 03) names exactly these two modes ("Frequency Switch"
# pill active by default, "Position Switch" pill inactive).
MODE_OPTIONS = ["Frequency Switch", "Position Switch"]

_DEFAULT_N_CHANNELS = 256
_DEFAULT_VLSR_STEP = 0.15  # km/s per channel -- arbitrary but realistic for HI-line work
_DEFAULT_VLSR_START = -20.0
_FREQ_SWITCH_SHIFT_CHANNELS = 24  # channel offset between the two LO throws
    

def get_raw_pair(mode: str) -> Tuple[SpectrumDict, SpectrumDict]:
    """Return the two real FITS spectra loaded by Page 02."""

    spectra = st.session_state.get("loaded_spectra", [])

    if len(spectra) < 2:
        raise ValueError(
            "Bandpass correction requires two loaded FITS spectra. "
            "Go back to Page 1, select two FITS files, and load them on Page 2."
        )

    spec1 = spectra[0]
    spec2 = spectra[1]

    required_keys = ("Vlsr", "LCP", "RCP")

    for index, spec in enumerate((spec1, spec2), start=1):
        missing = [key for key in required_keys if key not in spec]

        if missing:
            raise ValueError(
                f"Spectrum {index} is missing required fields: "
                f"{', '.join(missing)}"
            )

    return spec1, spec2

    raise ValueError(f"Unknown bandpass mode: {mode!r}. Expected one of {MODE_OPTIONS}.")

def _synthetic_line(vlsr: np.ndarray, seed: int, amplitude_scale: float) -> Tuple[np.ndarray, np.ndarray]:
    """Deterministic synthetic HI-like Gaussian bump + flat Tsys baseline, for LCP/RCP.

    
    TODO: confirm against design — there's no live FITS-reading pipeline wired
    up yet (that's FR-02/clc/load_file.py, page 02's job); this stands in for
    a loaded+calibrated raw spectrum so page 03's chart isn't empty before
    that integration lands. Same "reproduce known sample data, don't fabricate
    real header data" spirit as utils/source_browser_logic.get_source_groups().

    Args:
        vlsr: Velocity axis (km/s) to evaluate the synthetic line on.
        seed: RNG seed -- kept fixed per raw spectrum so results (and tests)
            are reproducible across reruns.
        amplitude_scale: 1.0 includes the synthetic source line; 0.0 produces
            a line-free reference/off-source spectrum (baseline + noise only).

    Returns:
        (lcp, rcp) arrays the same shape as `vlsr`.
    """
    rng = np.random.default_rng(seed)
    line = amplitude_scale * 2.4 * np.exp(-0.5 * ((vlsr - (-4.2)) / 1.1) ** 2)
    lcp = 45.0 + line + rng.normal(0, 0.04, vlsr.shape)
    rcp = 44.6 + (line * 0.94) + rng.normal(0, 0.04, vlsr.shape)
    return lcp, rcp


def get_placeholder_raw_pair(mode: str) -> Tuple[SpectrumDict, SpectrumDict]:
    """Build the raw (pre-correction) spec1/spec2 pair for the given mode.

    Frequency Switch: spec1/spec2 sit on two Vlsr grids offset by
    `_FREQ_SWITCH_SHIFT_CHANNELS` channels (mimics an LO throw), with only
    spec1 carrying the source line -- the classic freq-switch setup where the
    line falls in-band on one throw and out-of-band on the other.

    Position Switch: spec1 (on-source, has the line) and spec2 (off-source,
    baseline only) share the exact same Vlsr grid, since pos_switch_correct()
    does a direct element-wise subtraction with no common-velocity search.

    Args:
        mode: One of MODE_OPTIONS.

    Returns:
        (spec1, spec2) Spebase_len = _DEFAULT_N_CHANNELS
    base_vlsr = _DEFAULT_VLSR_START + _DEFAULT_VLSR_STEP * np.arange(base_len + _FREQ_SWITCH_SHIFT_CHANNELS)

    if mode == "Frequency Switch":
        vlsr1 = base_vlsr[:base_len]
        vlsr2 = base_vlsr[_FREQ_SWITCH_SHIFT_CHANNELS:_FREQ_SWITCH_SHIFT_CHANNELS + base_len]
        lcp1, rcp1 = _synthetic_line(vlsr1, seed=1, amplitude_scale=1.0)
        lcp2, rcp2 = _synthetic_line(vlsr2, seed=2, amplitude_scale=0.0)  # reference throw: baseline only
        spec1: SpectrumDict = {"Vlsr": vlsr1, "LCP": lcp1, "RCP": rcp1}
        spec2: SpectrumDict = {"Vlsr": vlsr2, "LCP": lcp2, "RCP": rcp2}
        return spec1, spec2

    if mode == "Position Switch":
        vlsr = base_vlsr[:base_len]
        lcp1, rcp1 = _synthetic_line(vlsr, seed=3, amplitude_scale=1.0)
        lcp2, rcp2 = _synthetic_line(vlsr, seed=4, amplitude_scale=0.0)  # off-source: baseline only
        spec1 = {"Vlsr": vlsr, "LCP": lcp1, "RCP": rcp1}
        spec2 = {"Vlsr": vlsr, "LCP": lcp2, "RCP": rcp2}
        return spec1, spec2

    raise ValueError(f"Unknown bandpass mode: {mode!r}. Expected one of {MODE_OPTIONS}.")ctrumDicts.

    Raises:
        ValueError: If `mode` isn't a recognized value.
    """
    base_len = _DEFAULT_N_CHANNELS
    base_vlsr = _DEFAULT_VLSR_START + _DEFAULT_VLSR_STEP * np.arange(base_len + _FREQ_SWITCH_SHIFT_CHANNELS)

    if mode == "Frequency Switch":
        vlsr1 = base_vlsr[:base_len]
        vlsr2 = base_vlsr[_FREQ_SWITCH_SHIFT_CHANNELS:_FREQ_SWITCH_SHIFT_CHANNELS + base_len]
        lcp1, rcp1 = _synthetic_line(vlsr1, seed=1, amplitude_scale=1.0)
        lcp2, rcp2 = _synthetic_line(vlsr2, seed=2, amplitude_scale=0.0)  # reference throw: baseline only
        spec1: SpectrumDict = {"Vlsr": vlsr1, "LCP": lcp1, "RCP": rcp1}
        spec2: SpectrumDict = {"Vlsr": vlsr2, "LCP": lcp2, "RCP": rcp2}
        return spec1, spec2

    if mode == "Position Switch":
        vlsr = base_vlsr[:base_len]
        lcp1, rcp1 = _synthetic_line(vlsr, seed=3, amplitude_scale=1.0)
        lcp2, rcp2 = _synthetic_line(vlsr, seed=4, amplitude_scale=0.0)  # off-source: baseline only
        spec1 = {"Vlsr": vlsr, "LCP": lcp1, "RCP": rcp1}
        spec2 = {"Vlsr": vlsr, "LCP": lcp2, "RCP": rcp2}
        return spec1, spec2

    raise ValueError(f"Unknown bandpass mode: {mode!r}. Expected one of {MODE_OPTIONS}.")


def freq_switch_correct(spec1: SpectrumDict, spec2: SpectrumDict) -> Tuple[SpectrumDict, SpectrumDict]:
    """Bandpass-correct a frequency-switched pair.

    Reproduces clc/Baseline.py's freq_switch() array math exactly: subtract
    the reference spectrum from the signal each way (elementwise, by array
    position -- matching the original), then restrict both results to the
    channels whose Vlsr value also appears in the other spectrum's Vlsr array
    (np.in1d common-velocity search), same as the original.

    Args:
        spec1: First observation of the frequency-switched pair.
        spec2: Second observation of the frequency-switched pair.

    Returns:
        (new_spec1, new_spec2) -- bandpass-corrected spectra restricted to
        their shared velocity range, each other's sign-inverse only where
        their restricted index sets happen to coincide (they generally don't,
        since spec1_common and spec2_common are computed from different
        arrays -- see clc/Baseline.py for the same behavior).
    """
    lcp1 = spec1["LCP"] - spec2["LCP"]
    lcp2 = spec2["LCP"] - spec1["LCP"]
    rcp1 = spec1["RCP"] - spec2["RCP"]
    rcp2 = spec2["RCP"] - spec1["RCP"]

    # clc/Baseline.py's own freq_switch() uses np.in1d() here, which was
    # removed in NumPy 2.0 (this project pins numpy>=1.24 with no upper
    # bound, so clc/Baseline.py as currently written will raise
    # AttributeError under any NumPy >=2.0 install -- a real forward-compat
    # bug in clc/, not something to silently work around by pinning NumPy
    # lower here). np.isin() is the maintained, behavior-equivalent
    # replacement and is what's used below.
    spec1_common = np.nonzero(np.isin(spec1["Vlsr"], spec2["Vlsr"]))
    spec2_common = np.nonzero(np.isin(spec2["Vlsr"], spec1["Vlsr"]))

    new_spec1: SpectrumDict = spec1.copy()
    new_spec2: SpectrumDict = spec2.copy()

    new_spec1["Vlsr"] = spec1["Vlsr"][spec1_common]
    new_spec1["LCP"] = lcp1[spec1_common]
    new_spec1["RCP"] = rcp1[spec1_common]

    new_spec2["Vlsr"] = spec2["Vlsr"][spec2_common]
    new_spec2["LCP"] = lcp2[spec2_common]
    new_spec2["RCP"] = rcp2[spec2_common]

    return new_spec1, new_spec2


def pos_switch_correct(spec1: SpectrumDict, spec2: SpectrumDict) -> SpectrumDict:
    """Bandpass-correct a position-switched pair.

    Reproduces clc/Baseline.py's pos_switch() array math exactly: on-source
    minus off-source, elementwise, on the shared Vlsr grid -- no common-
    channel search (position switching assumes both observations already
    share one grid).

    Args:
        spec1: On-source observation of the position-switched pair.
        spec2: Off-source observation of the position-switched pair.

    Returns:
        The bandpass-corrected spectrum, on spec1's original Vlsr grid.
    """
    new_spec: SpectrumDict = spec1.copy()
    new_spec["LCP"] = spec1["LCP"] - spec2["LCP"]
    new_spec["RCP"] = spec1["RCP"] - spec2["RCP"]
    return new_spec


def get_corrected_spectrum(mode: str) -> SpectrumDict:
    """Return the single displayed bandpass-corrected spectrum for `mode`.

    Frequency Switch produces two corrected spectra (new_spec1/new_spec2,
    from freq_switch_correct); the build spec's chart panel shows one LCP/RCP
    trace pair, not two pairs, so `new_spec1` -- the one carrying spec1's
    original sign convention -- is what's displayed. Position Switch only
    ever produces one spectrum.

    Args:
        mode: One of MODE_OPTIONS.

    Returns:
        The corrected SpectrumDict to plot.

    Raises:
        ValueError: If `mode` isn't a recognized value.
    """
    spec1, spec2 = get_raw_pair(mode)

    if mode == "Frequency Switch":
        new_spec1, _new_spec2 = freq_switch_correct(spec1, spec2)
        return new_spec1

    if mode == "Position Switch":
        return pos_switch_correct(spec1, spec2)

    raise ValueError(f"Unknown bandpass mode: {mode!r}. Expected one of {MODE_OPTIONS}.")


def stage_summary(mode: str, corrected: SpectrumDict) -> Dict[str, object]:
    """Build the small dict stored in session_store's pipeline_data for this stage.

    Keeps only cheap-to-serialize summary fields (this is written straight
    into the session's JSON file per the project's "no database" architecture)
    rather than the full spectrum arrays.

    Args:
        mode: The mode the spectrum was corrected under.
        corrected: The corrected SpectrumDict returned by get_corrected_spectrum().

    Returns:
        A JSON-serializable summary dict.
    """
    has_data = corrected["Vlsr"].size > 0
    return {
        "mode": mode,
        "n_channels": int(corrected["Vlsr"].size),
        "vlsr_range_kms": (
            [float(corrected["Vlsr"].min()), float(corrected["Vlsr"].max())] if has_data else []
        ),
    }
