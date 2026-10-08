# test_export_logic.py — FR-18: tests for utils/export_logic.py (CSV with everything; PDF with graphs only).

import io

import numpy as np
import pandas as pd
import pytest

from utils import export_logic as ex
from utils.fitting_inputs import PssValue

VLSR = np.linspace(-5, 5, 6)
LCP = np.arange(6, dtype=float)
RCP = LCP * 2
AVG = (LCP + RCP) / 2
PSS = PssValue(value=3.0, lcp_mean=2.0, rcp_mean=4.0, frequency="66685", window_days=15)
FIT = {"fit_type": "1D Gaussian", "parameters": [{"parameter": "Center (Vlsr)", "value": "-4.20 km/s",
                                                  "error": "0.03 km/s"}]}


def _meta(**over):
    args = dict(spectrum={"object": "G328.24-0.55", "date": "2023-03-08T02:12:56", "restfreq": 6668519000.0},
                spectrum_source="baseline", intensity_unit="K", pss=PSS, pointing_factor=1.05, fit_summary=FIT)
    args.update(over)
    return ex.build_metadata(**args)


def _read(csv_bytes):
    return pd.read_csv(io.BytesIO(csv_bytes))


def test_csv_has_both_polarisations_average_calibrated_and_fit():
    cal = (LCP + RCP) * 3.0 + 1.05
    data = ex.build_export_csv(vlsr=VLSR, lcp=LCP, rcp=RCP, average=AVG, unit="K", calibrated=cal,
                               fit_curve=cal * 0.9, metadata=_meta())
    frame = _read(data)
    assert list(frame.columns[:6]) == ["Vlsr_kms", "LCP_K", "RCP_K", "Average_LCP_RCP_K", "Calibrated_Jy", "Fit_Jy"]
    assert len(frame) == 6
    assert frame["RCP_K"].tolist() == RCP.tolist()  # RCP is exported, not just LCP
    assert frame["source_name"].nunique() == 1 and frame["source_name"][0] == "G328.24-0.55"
    assert frame["pss_used_jy_per_k"][0] == 3.0 and frame["pointing_correction_factor"][0] == 1.05
    assert frame["fit_Center_Vlsr"][0] == "-4.20 km/s" and frame["fit_Center_Vlsr_error"][0] == "0.03 km/s"


def test_csv_omits_calibrated_and_fit_when_unavailable_or_wrong_length():
    meta = _meta(pss=None, pointing_factor=None, fit_summary=None)
    frame = _read(ex.build_export_csv(vlsr=VLSR, lcp=LCP, rcp=RCP, average=AVG, unit="K", calibrated=None,
                                      fit_curve=np.zeros(3), metadata=meta))
    assert "Calibrated_Jy" not in frame.columns and "Fit_Jy" not in frame.columns
    assert frame["pss_used_jy_per_k"].isna().all() and frame["fit_type"].isna().all()  # blank, columns still present


def test_metadata_mjd_and_decimal_year_when_astropy_available():
    pytest.importorskip("astropy")
    meta = _meta()
    assert meta["mjd"] == pytest.approx(60011.09231, abs=1e-4)
    assert meta["decimal_year"] == pytest.approx(2023.1811, abs=1e-3)


def test_metadata_bad_date_never_blocks_export():
    meta = _meta(spectrum={"object": "x", "date": "not a date"})
    assert meta["mjd"] == "" and meta["decimal_year"] == ""


def _graphs(n):
    return [ex.GraphSpec(title=f"Graph {i}", y_label="K", traces=[ex.GraphTrace("a", VLSR, LCP, "#1F77B4"),
                                                                  ex.GraphTrace("fit", VLSR, RCP, "#DC2626", True)],
                         hline=2.0 if i == 0 else None, hline_label="Overall mean" if i == 0 else "")
            for i in range(n)]


@pytest.mark.parametrize("n", [1, 5, 6])
def test_pdf_is_a_valid_pdf(n):
    pytest.importorskip("matplotlib")
    data = ex.build_graphs_pdf(_graphs(n), title="HARTSPEC test")
    assert data.startswith(b"%PDF") and data.rstrip().endswith(b"%%EOF")


def test_pdf_requires_at_least_one_graph():
    pytest.importorskip("matplotlib")
    with pytest.raises(ValueError):
        ex.build_graphs_pdf([])
