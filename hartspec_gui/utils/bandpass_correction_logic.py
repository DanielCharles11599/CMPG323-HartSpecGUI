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

from typing import Any

import numpy as np
import streamlit as st


SpectrumDict = dict[str, Any]

THIS_STAGE_KEY = "03_bandpass_correction"

MODE_OPTIONS = [
    "Frequency Switch",
    "Position Switch",
]

_REQUIRED_SPECTRUM_KEYS = ("Vlsr", "LCP", "RCP")


def _validate_spectrum(spec: SpectrumDict, number: int) -> None:
    """Validate the fields required for bandpass correction."""

    missing = [key for key in _REQUIRED_SPECTRUM_KEYS if key not in spec]

    if missing:
        raise ValueError(
            f"Spectrum {number} is missing required field(s): "
            f"{', '.join(missing)}"
        )

    vlsr = np.asarray(spec["Vlsr"])
    lcp = np.asarray(spec["LCP"])
    rcp = np.asarray(spec["RCP"])

    if not (len(vlsr) == len(lcp) == len(rcp)):
        raise ValueError(
            f"Spectrum {number} has inconsistent array lengths: "
            f"Vlsr={len(vlsr)}, LCP={len(lcp)}, RCP={len(rcp)}."
        )


def get_raw_pair() -> tuple[SpectrumDict, SpectrumDict]:
    """Return the two spectra loaded by Page 02."""

    spectra = st.session_state.get("loaded_spectra", [])

    if len(spectra) < 2:
        raise ValueError(
            "Bandpass correction requires two successfully loaded FITS spectra. "
            "Select two compatible FITS files on Page 01 and load them on Page 02."
        )

    spec1 = spectra[0]
    spec2 = spectra[1]

    _validate_spectrum(spec1, 1)
    _validate_spectrum(spec2, 2)

    return spec1, spec2


def _validate_pair_lengths(
    spec1: SpectrumDict,
    spec2: SpectrumDict,
) -> None:
    """Ensure the two spectra can be subtracted element-by-element."""

    for key in ("LCP", "RCP"):
        if len(spec1[key]) != len(spec2[key]):
            raise ValueError(
                f"The two spectra have different {key} channel counts "
                f"({len(spec1[key])} vs {len(spec2[key])}) and cannot "
                "be bandpass corrected as a pair."
            )


def freq_switch_correct(
    spec1: SpectrumDict,
    spec2: SpectrumDict,
) -> tuple[SpectrumDict, SpectrumDict]:
    """Apply the original HartSpec frequency-switch correction."""

    _validate_pair_lengths(spec1, spec2)

    lcp1 = np.asarray(spec1["LCP"]) - np.asarray(spec2["LCP"])
    lcp2 = np.asarray(spec2["LCP"]) - np.asarray(spec1["LCP"])

    rcp1 = np.asarray(spec1["RCP"]) - np.asarray(spec2["RCP"])
    rcp2 = np.asarray(spec2["RCP"]) - np.asarray(spec1["RCP"])

    vlsr1 = np.asarray(spec1["Vlsr"])
    vlsr2 = np.asarray(spec2["Vlsr"])

    spec1_common = np.isin(vlsr1, vlsr2)
    spec2_common = np.isin(vlsr2, vlsr1)

    new_spec1 = spec1.copy()
    new_spec2 = spec2.copy()

    new_spec1["Vlsr"] = vlsr1[spec1_common]
    new_spec1["LCP"] = lcp1[spec1_common]
    new_spec1["RCP"] = rcp1[spec1_common]

    new_spec2["Vlsr"] = vlsr2[spec2_common]
    new_spec2["LCP"] = lcp2[spec2_common]
    new_spec2["RCP"] = rcp2[spec2_common]

    return new_spec1, new_spec2


def pos_switch_correct(
    spec1: SpectrumDict,
    spec2: SpectrumDict,
) -> SpectrumDict:
    """Apply the original HartSpec position-switch correction."""

    _validate_pair_lengths(spec1, spec2)

    new_spec = spec1.copy()

    new_spec["LCP"] = (
        np.asarray(spec1["LCP"])
        - np.asarray(spec2["LCP"])
    )

    new_spec["RCP"] = (
        np.asarray(spec1["RCP"])
        - np.asarray(spec2["RCP"])
    )

    return new_spec


def get_corrected_spectrum(mode: str) -> SpectrumDict:
    """Return the corrected spectrum displayed by Page 03."""

    spec1, spec2 = get_raw_pair()

    if mode == "Frequency Switch":
        corrected, _ = freq_switch_correct(spec1, spec2)
        return corrected

    if mode == "Position Switch":
        return pos_switch_correct(spec1, spec2)

    raise ValueError(f"Unknown bandpass mode: {mode!r}")


def stage_summary(
    mode: str,
    corrected: SpectrumDict,
) -> dict[str, object]:
    """Return the serializable Page 03 pipeline summary."""

    vlsr = np.asarray(corrected["Vlsr"])

    return {
        "mode": mode,
        "n_channels": int(vlsr.size),
        "vlsr_range_kms": (
            [float(vlsr.min()), float(vlsr.max())]
            if vlsr.size
            else []
        ),
    }