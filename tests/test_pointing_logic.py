# test_pointing_logic.py — FR-12/13: tests for utils/pointing_logic.py (Page 06 helpers).
# compute_pointing() is tested against the REAL, unmodified clc/Point_cor.py: the wrapper must neither change its
# numbers nor leave anything behind at its hard-coded "../plots/" path.

import os

import numpy as np
import pytest

from utils import pointing_logic as pl


def _spec(position, pointing=1):
    return {"position": position, "pointing": pointing}


def _lookup_from(table):
    return lambda name: table.get(name)


FULL_SCAN = {
    "a_HPN.fits": _spec("HPN"), "a_HPS.fits": _spec("HPS"), "a_HPE.fits": _spec("HPE"),
    "a_HPW.fits": _spec("HPW"), "a_ON1.fits": _spec("ON", 1), "a_OFF1.fits": _spec("OFF", 1),
    "a_ON0.fits": _spec("ON", 0), "a_OFF0.fits": _spec("OFF", 0),
}


def test_find_pointing_scans_picks_the_five_files_and_ignores_science_on_off():
    blocks = {"20260812_0.txt": list(FULL_SCAN)}
    scans = pl.find_pointing_scans(blocks, _lookup_from(FULL_SCAN))
    assert len(scans) == 1
    assert scans[0].files == {"N": "a_HPN.fits", "S": "a_HPS.fits", "E": "a_HPE.fits", "W": "a_HPW.fits",
                              "Centre": "a_ON1.fits"}
    assert scans[0].label == "20260812_0 · scan 1"


def test_find_pointing_scans_splits_two_scans_in_one_block_and_drops_incomplete():
    table = dict(FULL_SCAN)
    second = {f"b_{k}": v for k, v in FULL_SCAN.items()}
    table.update(second)
    del table["b_a_HPW.fits"]  # second scan is missing a direction
    order = list(FULL_SCAN) + [f"b_{k}" for k in FULL_SCAN if f"b_{k}" in table]
    scans = pl.find_pointing_scans({"blk.txt": order}, _lookup_from(table))
    assert [s.number for s in scans] == [1]  # scan 2 incomplete -> dropped


def test_find_pointing_scans_handles_unloaded_files_and_odd_header_text():
    table = {"n.fits": _spec(" hpn "), "s.fits": _spec("HPS"), "e.fits": _spec("HPE"), "w.fits": _spec("HPW"),
             "c.fits": _spec("ON", "1")}
    scans = pl.find_pointing_scans({"b.txt": ["missing.fits", "n.fits", "s.fits", "e.fits", "w.fits", "c.fits"]},
                                   _lookup_from(table))
    assert len(scans) == 1


def test_find_pointing_scans_science_only_on_is_not_a_centre():
    table = {k: v for k, v in FULL_SCAN.items() if k != "a_ON1.fits"}
    assert pl.find_pointing_scans({"b.txt": list(table)}, _lookup_from(table)) == []


def test_peak_helpers():
    vlsr = np.linspace(-10, 10, 21)
    lcp = np.zeros(21)
    rcp = np.zeros(21)
    lcp[15], rcp[15] = 8.0, 6.0
    assert pl.default_peak_index(vlsr, lcp, rcp) == 15
    assert pl.nearest_channel(vlsr, 4.6) == 15
    assert pl.power_at_channel(lcp, rcp, 15) == 7.0
    assert pl.default_peak_index(vlsr, [np.nan] * 3, [np.nan] * 3) == 0


@pytest.fixture
def real_pointcor():
    return pl._import_pointcor()


def test_compute_pointing_symmetric_beam_has_no_offset(tmp_path, real_pointcor):
    cwd_before = os.getcwd()
    result = pl.compute_pointing(
        {"N": 0.9, "S": 0.9, "E": 0.9, "W": 0.9, "Centre": 1.0}, 0.23, "20260812_0", plot_dir=tmp_path / "plots")
    assert abs(result.ns_offset_deg) < 1e-6 and abs(result.ew_offset_deg) < 1e-6
    assert result.correction_factor == pytest.approx(1.0, abs=1e-6)
    assert (tmp_path / "plots" / "Point_Offset_for_20260812.pdf").exists()  # redirected here, not "../plots/"
    assert os.getcwd() == cwd_before
    assert pl._import_pointcor().plt is real_pointcor.plt  # proxy removed again


def test_compute_pointing_matches_pointcor_called_directly(tmp_path, real_pointcor):
    powers = {"N": 0.92, "S": 0.87, "E": 0.90, "W": 0.85, "Centre": 1.0}
    wrapped = pl.compute_pointing(powers, 0.23, "20260812_0", plot_dir=tmp_path)
    real_pointcor.plt = pl._PyplotProxy(real_pointcor.plt, pl._redirected_savefig(real_pointcor.plt, None))
    direct = real_pointcor.pointcor(north=0.92, south=0.87, east=0.90, west=0.85, cen=1.0, hpbw=0.23,
                                    dirname="20260812_0")
    real_pointcor.plt = real_pointcor.plt._real
    assert (wrapped.correction_factor, wrapped.ns_offset_deg, wrapped.ew_offset_deg) == direct  # 6 s.f. requirement
    assert wrapped.ns_offset_deg != 0  # asymmetric beam really produces an offset


def test_compute_pointing_without_plot_dir_writes_nothing(tmp_path, real_pointcor):
    os.chdir(tmp_path)
    pl.compute_pointing({"N": 0.9, "S": 0.8, "E": 0.9, "W": 0.8, "Centre": 1.0}, 0.23, "20260812_0")
    assert list(tmp_path.rglob("*.pdf")) == []


@pytest.mark.parametrize("powers, hpbw", [
    ({"N": 0.9, "S": 0.9, "E": 0.9, "W": 0.9}, 0.23),                        # missing Centre
    ({"N": 0.0, "S": 0.9, "E": 0.9, "W": 0.9, "Centre": 1.0}, 0.23),         # non-positive
    ({"N": float("nan"), "S": 0.9, "E": 0.9, "W": 0.9, "Centre": 1.0}, 0.23),
    ({"N": 0.9, "S": 0.9, "E": 0.9, "W": 0.9, "Centre": 1.0}, 0.0),          # no beam width
])
def test_compute_pointing_rejects_bad_inputs(powers, hpbw):
    with pytest.raises(ValueError):
        pl.compute_pointing(powers, hpbw, "20260812_0")
