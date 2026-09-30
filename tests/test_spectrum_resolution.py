# test_spectrum_resolution.py — unit tests for utils/spectrum_resolution.py (shared by Pages 07 and 08).
#
# The resolver takes the bridge reader and fingerprint function as arguments, so nothing here needs Streamlit,
# the Dash bridge, or files on disk.

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hartspec_gui"))

from utils import spectrum_resolution as sr  # noqa: E402


def _spec(scale=1.0, n=16, start=0.0):
    v = np.linspace(start, start + 10, n)
    return {"Vlsr": v.tolist(), "LCP": (v * scale).tolist(), "RCP": (v * scale * 0.9).tolist()}


def _fp(spectrum):
    """Cheap deterministic stand-in for baseline_editor_bridge.spectrum_fingerprint."""
    return f"fp-{spectrum['Vlsr'][0]}-{len(spectrum['Vlsr'])}"


def _bridge_of(flattened, fingerprint):
    return lambda session_id: {"flattened_spectrum": flattened, "spectrum_fingerprint": fingerprint}


def _no_bridge(session_id):
    return None


def _resolve(state, bridge=_no_bridge, fingerprint=_fp):
    return sr.resolve_spectrum(state, read_bridge=bridge, fingerprint=fingerprint)


def test_calibrated_spectrum_wins_and_is_labelled_in_jy():
    state = {"calibrated_spectrum": _spec(10), "loaded_spectra": [_spec()]}
    resolved = _resolve(state, bridge=_bridge_of(_spec(2), "x"))
    assert resolved.source_key == sr.SOURCE_CALIBRATED and resolved.is_calibrated
    assert resolved.intensity_unit == "Jy" and not resolved.is_placeholder
    assert np.allclose(resolved.channels["LCP"], np.array(_spec(10)["LCP"]))


def test_baseline_bridge_used_when_fingerprint_matches_current_bandpass_spectrum():
    current = _spec(1)
    state = {"session_id": "abc", "bandpass_corrected_spectrum": current, "loaded_spectra": [_spec(7)]}
    resolved = _resolve(state, bridge=_bridge_of(_spec(2), _fp(current)))
    assert resolved.source_key == sr.SOURCE_BASELINE and resolved.intensity_unit == "K"
    assert not resolved.is_calibrated and resolved.notes == ()


def test_stale_bridge_is_rejected_with_a_note_and_falls_through_to_raw():
    # Bridge was built from a different Page 3 spectrum than the current one -> must not be trusted.
    state = {"bandpass_corrected_spectrum": _spec(1, start=0.0), "loaded_spectra": [_spec(7)]}
    resolved = _resolve(state, bridge=_bridge_of(_spec(2), "fp-from-an-older-spectrum"))
    assert resolved.source_key == sr.SOURCE_RAW
    assert any("no longer matches" in n for n in resolved.notes)


def test_bridge_is_accepted_when_there_is_no_current_bandpass_spectrum_to_compare():
    # e.g. straight after a session load: nothing disproves the bridge, so it is not called stale.
    resolved = _resolve({"session_id": "abc"}, bridge=_bridge_of(_spec(2), "whatever"))
    assert resolved.source_key == sr.SOURCE_BASELINE


def test_bridge_is_rejected_when_current_spectrum_cannot_be_fingerprinted():
    def broken_fingerprint(spectrum):
        raise ValueError("cannot hash")

    state = {"bandpass_corrected_spectrum": _spec(1), "loaded_spectra": [_spec(7)]}
    resolved = _resolve(state, bridge=_bridge_of(_spec(2), "x"), fingerprint=broken_fingerprint)
    assert resolved.source_key == sr.SOURCE_RAW


def test_raw_loaded_spectrum_is_used_when_nothing_better_exists():
    resolved = _resolve({"loaded_spectra": [_spec(3)]})
    assert resolved.source_key == sr.SOURCE_RAW and resolved.intensity_unit == "K"


def test_placeholder_is_flagged_deterministic_and_never_calibrated():
    first, second = _resolve({}), _resolve({})
    assert first.is_placeholder and not first.is_calibrated
    assert first.vlsr.size == 1024
    assert np.array_equal(first.channels["LCP"], second.channels["LCP"])
    assert "placeholder" in first.source_label.lower()


def test_malformed_calibrated_spectrum_is_skipped_with_a_note():
    bad = {"Vlsr": [1, 2, 3], "LCP": [1, 2], "RCP": [1, 2, 3]}  # unequal lengths
    resolved = _resolve({"calibrated_spectrum": bad, "loaded_spectra": [_spec()]})
    assert resolved.source_key == sr.SOURCE_RAW
    assert any("calibrated spectrum" in n and "malformed" in n for n in resolved.notes)


def test_missing_keys_and_empty_arrays_are_not_usable():
    assert sr._coerce({"Vlsr": [1, 2], "LCP": [1, 2]}) is None
    assert sr._coerce({"Vlsr": [], "LCP": [], "RCP": []}) is None
    assert sr._coerce("not a mapping") is None
    assert sr._coerce({"Vlsr": ["a"], "LCP": [1], "RCP": [1]}) is None


def test_empty_loaded_spectra_list_falls_to_placeholder():
    assert _resolve({"loaded_spectra": []}).is_placeholder
    assert _resolve({"loaded_spectra": None}).is_placeholder
