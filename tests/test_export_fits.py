# test_export_fits.py — FR-18: unit tests for utils.export_logic.build_export_fits (FITS export on Page 08).
"""Round-trip the FITS builder through astropy and check it carries the same numbers as the CSV."""
import io

import numpy as np
import pytest

from utils import export_logic

fits = pytest.importorskip("astropy.io.fits")

N = 64
VLSR = np.linspace(-20.0, 20.0, N)
LCP = np.sin(VLSR / 5.0) + 1.234567891
RCP = np.cos(VLSR / 7.0) + 2.345678912
AVERAGE = (LCP + RCP) / 2
CALIBRATED = AVERAGE * 3.1
FIT = CALIBRATED * 0.99
METADATA = {
    "source_name": "W3(OH)",
    "observation_date": "2026-08-12T14:03:12",
    "mjd": 61264.58556,
    "decimal_year": 2026.61,
    "spectrum_source": "baseline",
    "pss_used_jy_per_k": 12.5,
    "pointing_correction_factor": "",  # blank -> skipped
    "calibrated_formula": "[(LCP + RCP) × PSS] + Pointing Correction — long text goes to COMMENT cards",
    "fit_type": "1D Gaussian",
    "fit_Amplitude": 8.42,
    "fit_Amplitude_error": float("nan"),  # not representable in a header -> skipped
}


def _build(**overrides):
    kwargs = dict(vlsr=VLSR, lcp=LCP, rcp=RCP, average=AVERAGE, unit="K", calibrated=CALIBRATED, fit_curve=FIT,
                  metadata=METADATA)
    kwargs.update(overrides)
    return export_logic.build_export_fits(**kwargs)


def _open(data: bytes):
    return fits.open(io.BytesIO(data))


def test_ascii_helper_replaces_non_ascii():
    assert export_logic._ascii("(LCP + RCP) × PSS — x") == "(LCP + RCP) x PSS - x"
    assert "\n" not in export_logic._ascii("a\nb")


def test_fits_value_skips_blank_and_non_finite():
    assert export_logic._fits_value(float("nan")) == ""
    assert export_logic._fits_value(None) == ""
    assert export_logic._fits_value(np.float64(1.5)) == 1.5
    assert export_logic._fits_value(True) is True


def test_structure_and_columns():
    with _open(_build()) as hdul:
        assert [hdu.name for hdu in hdul] == ["PRIMARY", "SPECTRUM"]
        assert hdul["SPECTRUM"].columns.names == ["VLSR", "LCP", "RCP", "AVERAGE", "CALIBRATED", "FIT"]
        assert hdul["SPECTRUM"].columns["VLSR"].unit == "km/s"
        assert hdul["SPECTRUM"].columns["LCP"].unit == "K"


def test_values_round_trip_exactly():
    # float64 columns: well inside the 6-significant-figure regression requirement.
    with _open(_build()) as hdul:
        data = hdul["SPECTRUM"].data
        np.testing.assert_array_equal(data["VLSR"], VLSR)
        np.testing.assert_array_equal(data["LCP"], LCP)
        np.testing.assert_array_equal(data["RCP"], RCP)
        np.testing.assert_array_equal(data["AVERAGE"], AVERAGE)
        np.testing.assert_array_equal(data["CALIBRATED"], CALIBRATED)
        np.testing.assert_array_equal(data["FIT"], FIT)


@pytest.mark.parametrize("overrides, missing", [
    ({"calibrated": None, "fit_curve": None}, {"CALIBRATED", "FIT"}),
    ({"fit_curve": None}, {"FIT"}),
    ({"fit_curve": FIT[:-1]}, {"FIT"}),          # wrong length is dropped, as in the CSV
    ({"calibrated": CALIBRATED[:-1]}, {"CALIBRATED"}),
])
def test_optional_columns_omitted(overrides, missing):
    with _open(_build(**overrides)) as hdul:
        assert missing.isdisjoint(hdul["SPECTRUM"].columns.names)
        assert {"VLSR", "LCP", "RCP", "AVERAGE"} <= set(hdul["SPECTRUM"].columns.names)


def test_metadata_in_both_headers():
    with _open(_build()) as hdul:
        for header in (hdul[0].header, hdul["SPECTRUM"].header):
            assert header["OBJECT"] == "W3(OH)"
            assert header["DATE-OBS"] == "2026-08-12T14:03:12"
            assert header["MJD-OBS"] == pytest.approx(61264.58556)
            assert header["HIERARCH PSS_USED_JY_PER_K"] == 12.5
            assert header["HIERARCH FIT_TYPE"] == "1D Gaussian"
            assert header["HIERARCH FIT_AMPLITUDE"] == 8.42
            assert "HIERARCH POINTING_CORRECTION_FACTOR" not in header  # blank skipped
            assert "HIERARCH FIT_AMPLITUDE_ERROR" not in header          # NaN skipped
            assert any("calibrated_formula" in str(c) for c in header["COMMENT"])


def test_empty_metadata_still_valid():
    with _open(_build(metadata={})) as hdul:
        assert hdul[0].header["ORIGIN"] == "HARTSPEC"
        assert len(hdul["SPECTRUM"].data) == N


def test_output_is_deterministic():
    assert _build() == _build()


PIPELINE = {
    "03_bandpass_correction": {"mode": "Frequency Switch"},
    "04_baseline_editor": {
        "blocks": [{"start": -12.4, "end": -9.8}, {"start": 4.1, "end": 7.6}],
        "polynomial_order": 3,
        "huge_array": list(range(500)),  # array-sized: must be skipped
    },
    "05_calibration_dashboard": {"pss": {"lcp_window_mean": 11.9, "rcp_window_mean": 12.4}, "pwv": 4.5},
    "not_a_stage_dict": 5,
}


def test_traceability_collects_session_and_stage_parameters():
    values, notes = export_logic.build_fits_traceability("sess-001", PIPELINE)
    assert values["session_id"] == "sess-001"
    assert values["S03_mode"] == "Frequency Switch"
    assert values["S04_polynomial_order"] == 3
    assert values["S05_pss_lcp_window_mean"] == 11.9
    assert values["S05_pwv"] == 4.5
    assert any("S04_blocks [1]" in n and "start=-12.4" in n for n in notes)
    assert any("S04_blocks [2]" in n and "end=7.6" in n for n in notes)
    assert not any("huge_array" in n for n in notes) and not any("huge_array" in k for k in values)


def test_traceability_handles_missing_data():
    assert export_logic.build_fits_traceability(None, None) == ({}, [])
    assert export_logic.build_fits_traceability("", {"01": "not a mapping"}) == ({}, [])


def test_traceability_written_to_headers():
    values, notes = export_logic.build_fits_traceability("sess-001", PIPELINE)
    with _open(_build(traceability=values, trace_notes=notes)) as hdul:
        header = hdul[0].header
        assert header["HIERARCH SESSION_ID"] == "sess-001"
        assert header["HIERARCH S04_POLYNOMIAL_ORDER"] == 3
        assert header["HIERARCH S03_MODE"] == "Frequency Switch"
        assert any("S04_blocks [1]" in str(c) for c in header["COMMENT"])
