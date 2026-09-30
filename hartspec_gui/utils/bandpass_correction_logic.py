# bandpass_correction_logic.py — FR-04 Bandpass Correction logic
#
# This module contains the non-visual logic used by
# pages/03_Bandpass_Correction.py.
#
# IMPORTANT PROJECT CONSTRAINT:
# The original scientific modules inside /clc MUST NOT be modified.
#
# In particular:
#
#     clc/Baseline.py
#
# already contains:
#
#     freq_switch(spec1, spec2)
#     pos_switch(spec1, spec2)
#
# The GUI does not modify those functions. Instead, this module reproduces
# the same NumPy array operations in a GUI-safe form.
#
# Why not call clc/Baseline.py directly?
# The original Baseline functions contain matplotlib plotting / savefig
# side effects. Those side effects are suitable for the original CLI program
# but are undesirable inside Streamlit because:
#
#   1. Page 03 uses Plotly for its graph.
#   2. Baseline.py may create matplotlib figures during Streamlit reruns.
#   3. Baseline.py writes PDF plots using relative filesystem paths.
#   4. The scientific clc modules are explicitly off-limits for modification.
#
# Therefore this module keeps the GUI integration separate while preserving
# the original scientific subtraction behaviour.
#
# The data flow is Page 01 selection -> Page 02 loading -> this module -> Page 03 display and Page 04 handoff.
#
# Page 01:
#     user selects FITS files
#
# Page 02:
#     loads the selected FITS files using fits_ingest.py
#     and stores successfully loaded spectrum dictionaries in:
#
#         st.session_state["loaded_spectra"]
#
# Page 03:
#     calls get_corrected_spectrum(mode)
#
# This module:
#     retrieves and validates the two spectra,
#     applies the selected correction,
#     and returns the corrected spectrum to Page 03.
#
# Public helpers accept an optional spectra list so unit tests can run without relying on Streamlit session state.
# The public helpers accept an optional `spectra` argument.
#
# In the real Streamlit application:
#
#     get_corrected_spectrum("Frequency Switch")
#
# automatically reads st.session_state["loaded_spectra"].
#
# In pytest:
#
#     get_corrected_spectrum("Frequency Switch", [spec1, spec2])
#
# lets the tests inject spectra directly without requiring a running
# Streamlit application.


from __future__ import annotations

from typing import Any

import numpy as np
import streamlit as st


# Define the shared spectrum type and the constants Page 03 uses for stage identity and mode selection.

# The CLC loaders return dictionaries containing many metadata fields in
# addition to Vlsr/LCP/RCP, so dict[str, Any] is intentionally used instead
# of restricting every value to np.ndarray.
SpectrumDict = dict[str, Any]


# Key used by utils/session_store.py for Page 03's pipeline summary.
THIS_STAGE_KEY = "03_bandpass_correction"


# These names must match the two selector buttons displayed by Page 03.
MODE_OPTIONS = [
    "Frequency Switch",
    "Position Switch",
]


# Minimum fields required by clc/Baseline.py's correction algorithms.
_REQUIRED_SPECTRUM_KEYS = (
    "Vlsr",
    "LCP",
    "RCP",
)


# These helpers validate the loaded spectra before any scientific subtraction is attempted.

# Validate that one loaded spectrum contains usable Vlsr, LCP, and RCP arrays with matching channel counts.
def _validate_spectrum(
    spec: SpectrumDict,
    number: int,
) -> None:
    """Validate one spectrum before attempting bandpass correction.

    Page 02 can load dictionaries containing many FITS/header fields.
    Page 03 only requires Vlsr, LCP, and RCP for FR-04.

    This helper checks:

    1. The three required fields exist.
    2. Each field can be converted into a NumPy array.
    3. Vlsr, LCP, and RCP have equal lengths.

    Parameters
    ----------
    spec:
        Spectrum dictionary returned by the FITS loader.

    number:
        Human-readable spectrum number (1 or 2), used only in error
        messages.

    Raises
    ------
    ValueError
        If required fields are missing or array lengths are inconsistent.
    """

    missing = [
        key
        for key in _REQUIRED_SPECTRUM_KEYS
        if key not in spec
    ]

    if missing:
        raise ValueError(
            f"Spectrum {number} is missing required field(s): "
            f"{', '.join(missing)}."
        )

    try:
        vlsr = np.asarray(spec["Vlsr"])
        lcp = np.asarray(spec["LCP"])
        rcp = np.asarray(spec["RCP"])
    except Exception as exc:
        raise ValueError(
            f"Spectrum {number} contains invalid spectrum arrays: {exc}"
        ) from exc

    if not (
        len(vlsr)
        == len(lcp)
        == len(rcp)
    ):
        raise ValueError(
            f"Spectrum {number} has inconsistent array lengths: "
            f"Vlsr={len(vlsr)}, "
            f"LCP={len(lcp)}, "
            f"RCP={len(rcp)}."
        )


# Confirm that both spectra have compatible polarization array lengths before element-by-element subtraction.
def _validate_pair_lengths(
    spec1: SpectrumDict,
    spec2: SpectrumDict,
) -> None:
    """Ensure the two spectra can be subtracted element-by-element.

    The original clc/Baseline.py performs direct element-wise subtraction:

        spec1["LCP"] - spec2["LCP"]

    and equivalent subtraction for RCP.

    NumPy therefore requires the two polarization arrays to have compatible
    lengths. For the GUI we reject mismatched channel counts explicitly so
    the user receives a useful message instead of a low-level broadcasting
    exception.

    Parameters
    ----------
    spec1:
        First loaded observation.

    spec2:
        Second loaded observation.

    Raises
    ------
    ValueError
        If the LCP or RCP channel counts differ.
    """

    for key in ("LCP", "RCP"):
        length1 = len(np.asarray(spec1[key]))
        length2 = len(np.asarray(spec2[key]))

        if length1 != length2:
            raise ValueError(
                f"The two spectra have different {key} channel counts "
                f"({length1} vs {length2}) and cannot be "
                "bandpass corrected as a pair."
            )


# Read the spectra that Page 02 placed in session state and choose the pair used by FR-04.

# Retrieve the first two successfully loaded spectra and validate them as the active switching pair.
def get_raw_pair(
    spectra: list[SpectrumDict] | None = None,
) -> tuple[SpectrumDict, SpectrumDict]:
    """Return the two spectra used for bandpass correction.

    Normal application behaviour
    ----------------------------
    Page 02 stores successfully loaded observations in:

        st.session_state["loaded_spectra"]

    Therefore Page 03 normally calls this function without an argument.

    Testing behaviour
    -----------------
    Unit tests may pass a list directly:

        get_raw_pair([spec1, spec2])

    This avoids requiring a Streamlit runtime during pytest.

    Parameters
    ----------
    spectra:
        Optional list containing loaded spectrum dictionaries. When None,
        the list is read from Streamlit session state.

    Returns
    -------
    tuple
        (spec1, spec2)

    Raises
    ------
    ValueError
        If fewer than two spectra are available or either spectrum is
        malformed.
    """

    if spectra is None:
        spectra = st.session_state.get(
            "loaded_spectra",
            [],
        )

    if len(spectra) < 2:
        raise ValueError(
            "Bandpass correction requires two successfully loaded FITS "
            "spectra. Select two compatible FITS files on Page 01 and "
            "load them on Page 02."
        )

    # FR-04 currently operates on the first successfully loaded pair.
    #
    # Page 01/Page 02 may eventually support larger observation sets, but
    # pairing/grouping those sets belongs to the ingestion workflow rather
    # than being invented here.
    spec1 = spectra[0]
    spec2 = spectra[1]

    _validate_spectrum(spec1, 1)
    _validate_spectrum(spec2, 2)

    return spec1, spec2


# Apply the frequency-switch numerical behavior while keeping Streamlit free of the CLC plotting side effects.

# Reproduce the CLC frequency-switch subtraction and keep only velocity channels shared by both spectra.
def freq_switch_correct(
    spec1: SpectrumDict,
    spec2: SpectrumDict,
) -> tuple[SpectrumDict, SpectrumDict]:
    """Apply the original HartSpec frequency-switch subtraction.

    This reproduces the numerical behaviour in:

        clc/Baseline.py -> freq_switch()

    without modifying or directly invoking that CLC function.

    Original behaviour
    ------------------
    1. Subtract the two observations in both directions.
    2. Find Vlsr values appearing in both spectra.
    3. Restrict each corrected spectrum to its common velocity channels.
    4. Preserve the rest of the original spectrum dictionary by copying it.

    Parameters
    ----------
    spec1:
        First frequency-switched observation.

    spec2:
        Second frequency-switched observation.

    Returns
    -------
    tuple
        (new_spec1, new_spec2)

    Notes
    -----
    clc/Baseline.py uses np.in1d().

    np.isin() is the maintained NumPy equivalent and is used here because
    newer NumPy versions removed np.in1d().
    """

    _validate_spectrum(spec1, 1)
    _validate_spectrum(spec2, 2)
    _validate_pair_lengths(spec1, spec2)

    vlsr1 = np.asarray(spec1["Vlsr"])
    vlsr2 = np.asarray(spec2["Vlsr"])

    lcp_spec1 = (
        np.asarray(spec1["LCP"])
        - np.asarray(spec2["LCP"])
    )

    lcp_spec2 = (
        np.asarray(spec2["LCP"])
        - np.asarray(spec1["LCP"])
    )

    rcp_spec1 = (
        np.asarray(spec1["RCP"])
        - np.asarray(spec2["RCP"])
    )

    rcp_spec2 = (
        np.asarray(spec2["RCP"])
        - np.asarray(spec1["RCP"])
    )

    # Build one Boolean mask per spectrum so only channels whose Vlsr value also exists in the partner spectrum survive.
    spec1_common = np.isin(
        vlsr1,
        vlsr2,
    )

    spec2_common = np.isin(
        vlsr2,
        vlsr1,
    )

    # Copy each input dictionary before replacing the three science arrays so all FITS
    # metadata remains available downstream.
    new_spec1 = spec1.copy()
    new_spec2 = spec2.copy()

    new_spec1["Vlsr"] = vlsr1[spec1_common]
    new_spec1["LCP"] = lcp_spec1[spec1_common]
    new_spec1["RCP"] = rcp_spec1[spec1_common]

    new_spec2["Vlsr"] = vlsr2[spec2_common]
    new_spec2["LCP"] = lcp_spec2[spec2_common]
    new_spec2["RCP"] = rcp_spec2[spec2_common]

    return new_spec1, new_spec2


# Apply the position-switch numerical behavior using the first spectrum as signal and the second as reference.

# Reproduce the CLC position-switch subtraction while retaining the first spectrum's velocity grid and metadata.
def pos_switch_correct(
    spec1: SpectrumDict,
    spec2: SpectrumDict,
) -> SpectrumDict:
    """Apply the original HartSpec position-switch subtraction.

    This reproduces:

        clc/Baseline.py -> pos_switch()

    The first spectrum represents the signal/on-source observation and the
    second represents the reference/off-source observation.

    Unlike frequency switching, position switching does not search for a
    common Vlsr subset. The original algorithm directly subtracts LCP and
    RCP while retaining spec1's velocity grid.

    Parameters
    ----------
    spec1:
        Signal/on-source observation.

    spec2:
        Reference/off-source observation.

    Returns
    -------
    dict
        Corrected spectrum based on a copy of spec1.
    """

    _validate_spectrum(spec1, 1)
    _validate_spectrum(spec2, 2)
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


# Expose one mode-based correction function so the Streamlit page does not need to know the algorithm details.

# Dispatch to the correct bandpass algorithm based on the explicit mode selected on Page 03.
def get_corrected_spectrum(
    mode: str,
    spectra: list[SpectrumDict] | None = None,
) -> SpectrumDict:
    """Return the corrected spectrum that Page 03 should display.

    Parameters
    ----------
    mode:
        Either "Frequency Switch" or "Position Switch".

    spectra:
        Optional spectra list. Normally omitted by Page 03 so the function
        reads st.session_state["loaded_spectra"]. Tests can supply spectra
        directly.

    Returns
    -------
    dict
        Corrected spectrum containing Vlsr/LCP/RCP plus any metadata copied
        from the first input observation.

    Raises
    ------
    ValueError
        If the mode is unknown or the loaded pair is invalid.
    """

    # Validate the mode before touching session state. This keeps invalid
    # mode errors deterministic and makes the function easier to test.
    if mode not in MODE_OPTIONS:
        raise ValueError(
            f"Unknown bandpass mode: {mode!r}. "
            f"Expected one of {MODE_OPTIONS}."
        )

    spec1, spec2 = get_raw_pair(spectra)

    if mode == "Frequency Switch":
        new_spec1, _new_spec2 = freq_switch_correct(
            spec1,
            spec2,
        )

        # The Page 03 specification displays one LCP/RCP pair rather than
        # both sign-inverted frequency-switch outputs, so the first corrected
        # spectrum is used for the graph.
        return new_spec1

    # The mode has already been validated above, so the only remaining
    # possibility is Position Switch.
    return pos_switch_correct(
        spec1,
        spec2,
    )


# Build the extra information Page 03 needs for the before/after graph and common-range highlight.

# Calculate the shared velocity extent so Page 03 can highlight it without altering the corrected data.
def common_velocity_range(
    spec1: SpectrumDict,
    spec2: SpectrumDict,
) -> list[float]:
    """Return the shared velocity extent used for the FR-04 highlight.

    Frequency-switch correction ultimately retains velocity values present in
    both observations.  The GUI highlights the extent of those shared values
    without changing the CLC numerical result.  Position-switch pairs are
    expected to share a grid, but the same helper still gives a safe overlap.
    """
    _validate_spectrum(spec1, 1)
    _validate_spectrum(spec2, 2)
    v1 = np.asarray(spec1["Vlsr"], dtype=float).reshape(-1)
    v2 = np.asarray(spec2["Vlsr"], dtype=float).reshape(-1)
    if v1.size == 0 or v2.size == 0:
        return []

    shared = v1[np.isin(v1, v2)]
    if shared.size:
        return [float(np.min(shared)), float(np.max(shared))]

    # No exactly-equal channels.  This is useful diagnostic information for
    # position switching; frequency switching will subsequently yield zero
    # channels and Page 03 will reject the correction.
    lo = max(float(np.min(v1)), float(np.min(v2)))
    hi = min(float(np.max(v1)), float(np.max(v2)))
    return [lo, hi] if lo <= hi else []


# Run one complete FR-04 operation and package the raw inputs, corrected output, and display metadata together.
def build_bandpass_result(
    mode: str,
    spectra: list[SpectrumDict] | None = None,
) -> dict[str, Any]:
    """Run FR-04 once and return everything Page 03 needs to render it.

    This keeps the page from independently re-fetching the pair for its
    before/after plot, ensuring the displayed raw spectra and corrected
    spectrum come from the exact same Page-02 handoff.
    """
    if mode not in MODE_OPTIONS:
        raise ValueError(
            f"Unknown bandpass mode: {mode!r}. Expected one of {MODE_OPTIONS}."
        )
    spec1, spec2 = get_raw_pair(spectra)
    corrected = get_corrected_spectrum(mode, [spec1, spec2])
    return {
        "mode": mode,
        "raw_spec1": spec1,
        "raw_spec2": spec2,
        "corrected": corrected,
        "common_velocity_range_kms": common_velocity_range(spec1, spec2),
    }


# Convert the successful correction into lightweight metadata that can safely be written
# to the session JSON -- the compact JSON-safe summary stored under the Page 03 pipeline
# stage key.
def stage_summary(
    mode: str,
    corrected: SpectrumDict,
) -> dict[str, object]:
    """Build Page 03's small JSON-serializable pipeline summary.

    The full NumPy arrays are deliberately NOT written into pipeline_data.
    Session persistence should contain lightweight metadata rather than
    duplicating large spectrum arrays.

    Parameters
    ----------
    mode:
        Correction mode used.

    corrected:
        Corrected spectrum returned by get_corrected_spectrum().

    Returns
    -------
    dict
        Serializable summary containing mode, channel count, and Vlsr range.
    """

    vlsr = np.asarray(
        corrected["Vlsr"],
    )

    if vlsr.size:
        vlsr_range = [
            float(vlsr.min()),
            float(vlsr.max()),
        ]
    else:
        vlsr_range = []

    return {
        "mode": mode,
        "n_channels": int(vlsr.size),
        "vlsr_range_kms": vlsr_range,
    }
