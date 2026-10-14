# test_pointing_logic.py — FR-12/13: tests for utils/pointing_logic.py (Page 06 helpers).
# compute_pointing() is tested against the REAL, unmodified clc/Point_cor.py: the wrapper must neither change its
# numbers nor leave anything behind at its hard-coded "../plots/" path.
# FR-13 (Go / No-Go): condition A (|NS offset| < 2.5 sigma_NS) and condition B (Stats_manager.Sig_point) -- B is
# tested against the REAL Sig_point function body, extracted from clc/Stats_manager.py (the module itself imports
# load_file / Pols and is not imported here).

import ast
import json
import logging
import os
from pathlib import Path

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


# ---------------------------------------------------------------------------------------------------------------
# FR-12/13: uncertainties, fit curves, failed-fit panels, Go / No-Go
# ---------------------------------------------------------------------------------------------------------------
POWERS = {"N": 0.92, "S": 0.87, "E": 0.90, "W": 0.85, "Centre": 1.0}


def _result(ns=0.01, ew=0.02, sigmas=(0.01, 0.01, 0.001)):
    unc = None if sigmas is None else pl.PointingUncertainties(*sigmas)
    return pl.PointingResult(1.05, ns, ew, 0.23, {r: 1.0 for r in pl.ROLES}, unc)


PASS_SNR = pl.SignalToNoiseCheck(True, True, "Yes", peak_velocity_kms=-4.0)
FAIL_SNR = pl.SignalToNoiseCheck(True, False, "No", reason="Sig_point: none of the five reach 2.5σ.")


def test_go_needs_both_conditions_and_ignores_ew():
    check = pl.evaluate_pointing_check(_result(ns=0.01, ew=0.20), PASS_SNR)  # EW is 20 sigma out: irrelevant
    assert check.verdict == "Go" and check.evaluated and check.reasons == ()
    assert check.ns_ratio == pytest.approx(1.0)


def test_condition_a_boundary_is_strict_and_reason_names_ns():
    check = pl.evaluate_pointing_check(_result(ns=2.5, sigmas=(1.0, 1.0, 0.1)), PASS_SNR)
    assert check.verdict == "No-Go" and check.overridable and "NS offset" in check.reasons[0]


def test_condition_b_failure_is_no_go_even_when_a_passes():
    check = pl.evaluate_pointing_check(_result(), FAIL_SNR)
    assert check.verdict == "No-Go" and check.evaluated and check.overridable
    assert check.reasons == (FAIL_SNR.reason,)


def test_both_conditions_failing_gives_both_reasons():
    check = pl.evaluate_pointing_check(_result(ns=1.0), FAIL_SNR)
    assert len(check.reasons) == 2


@pytest.mark.parametrize("snr", [None, pl.SignalToNoiseCheck(False, False, reason="no baseline regions")])
def test_unevaluated_condition_b_is_no_go_not_go(snr):
    check = pl.evaluate_pointing_check(_result(), snr)
    assert check.verdict == "No-Go" and not check.evaluated and check.overridable


@pytest.mark.parametrize("sigmas", [None, (0.0, 0.01, 0.001), (float("nan"), 0.01, 0.001),
                                    (float("inf"), 0.01, 0.1)])
def test_missing_or_unusable_ns_uncertainty_is_no_go(sigmas):
    check = pl.evaluate_pointing_check(_result(sigmas=sigmas), PASS_SNR)
    assert check.verdict == "No-Go" and not check.evaluated


def test_failed_fit_check_is_not_overridable_and_keeps_panels():
    check = pl.failed_fit_check("boom", ("West", "Centre", "East"))
    assert check.verdict == "No-Go" and not check.overridable and not check.evaluated
    record = pl.check_record(check, None, signature="s", accepted=False)
    assert record["failed_panels"] == ["West", "Centre", "East"] and record["snr_check"] is None
    assert record["correction_factor"] is None


def test_check_record_is_json_safe_and_override_text_only_for_accepted_no_go():
    bad = pl.evaluate_pointing_check(_result(ns=1.0), PASS_SNR)
    kept = pl.check_record(bad, _result(ns=1.0), signature="s", accepted=True,
                           override_note="n", override_justification="j")
    assert json.loads(json.dumps(kept))["overridden"] is True
    assert kept["override_note"] == "n" and kept["override_justification"] == "j"
    assert kept["snr_check"]["sig_point"] == "Yes" and kept["ns_sigma_deg"] == 0.01
    good = pl.evaluate_pointing_check(_result(), PASS_SNR)
    clean = pl.check_record(good, _result(), signature="s", accepted=True, override_note="n")
    assert clean["override_note"] == "" and clean["overridden"] is False
    pending = pl.check_record(bad, _result(ns=1.0), signature="s", accepted=False, override_note="n")
    assert pending["override_note"] == "" and pending["accepted"] is False


def test_signature_id_is_stable_and_input_sensitive():
    assert pl.signature_id(("scan", (1.0, 2.0), 0.23)) == pl.signature_id(("scan", (1.0, 2.0), 0.23))
    assert pl.signature_id(("scan", (1.0, 2.0), 0.23)) != pl.signature_id(("scan", (1.0, 2.5), 0.23))


# ---- condition B: the REAL Stats_manager.Sig_point -----------------------------------------------------------------
def _real_sig_point():
    """The unmodified Sig_point body (its module imports load_file / Pols / itself, so it is extracted)."""
    path = Path(__file__).resolve().parents[1] / "hartspec_gui" / "clc" / "Stats_manager.py"
    func = next(n for n in ast.parse(path.read_text(encoding="utf-8")).body
                if isinstance(n, ast.FunctionDef) and n.name == "Sig_point")
    namespace = {"np": np, "logging": logging}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[func], type_ignores=[])), str(path), "exec"), namespace)
    return namespace["Sig_point"]


V = np.linspace(-20, 20, 1024)
BLOCKS = [{"start": -19.0, "end": -10.0}, {"start": 5.0, "end": 19.0}]


def _synthetic_spectrum(amplitude, grid=None, seed=0):
    grid = V if grid is None else grid
    rng = np.random.default_rng(seed)
    line = amplitude * np.exp(-0.5 * ((grid + 4) / 1.0) ** 2)
    return {"Vlsr": grid, "LCP": line + rng.normal(0, 0.1, grid.size), "RCP": line + rng.normal(0, 0.1, grid.size)}


def _five(amplitude, weak_role=None):
    return {role: _synthetic_spectrum(0.05 if role == weak_role else amplitude, seed=i)
            for i, role in enumerate(pl.ROLES)}


@pytest.mark.parametrize("amplitude,weak,answer,passed", [(5.0, None, "Yes", True), (0.05, None, "No", False),
                                                          (5.0, "N", "", False)])
def test_condition_b_uses_the_real_sig_point(amplitude, weak, answer, passed):
    snr = pl.evaluate_signal_to_noise(_five(amplitude, weak), BLOCKS, -4.0, sig_point=_real_sig_point())
    assert snr.evaluated and snr.sig_point == answer and snr.passed is passed
    assert bool(snr.reason) is (not passed)  # a pass needs no explanation; "No" and mixed ("") both explain
    assert len(snr.panel_snr) == 5 and snr.resampled == ()
    assert all(value > 2.5 for _role, value in snr.panel_snr) is passed if weak is None else True


def test_condition_b_without_baseline_regions_is_not_evaluated():
    snr = pl.evaluate_signal_to_noise(_five(5.0), [], -4.0, sig_point=_real_sig_point())
    assert not snr.evaluated and not snr.passed and "baseline regions" in snr.reason


def test_condition_b_reports_a_sig_point_crash_instead_of_raising():
    def boom(*args):
        raise ValueError("max() arg is an empty sequence")
    snr = pl.evaluate_signal_to_noise(_five(5.0), BLOCKS, -4.0, sig_point=boom)
    assert not snr.evaluated and "could not be run" in snr.reason


# ---- the "five pointing spectra do not share one velocity grid" regression ----------------------------------------
def test_condition_b_interpolates_slightly_shifted_grids_and_says_so():
    spectra = _five(5.0)
    spectra["N"] = _synthetic_spectrum(5.0, V + 0.003, seed=9)  # a separate observation: tiny LSR shift
    snr = pl.evaluate_signal_to_noise(spectra, BLOCKS, -4.0, sig_point=_real_sig_point())
    assert snr.evaluated and snr.passed and snr.sig_point == "Yes"
    assert len(snr.resampled) == 1 and snr.resampled[0].startswith("N (max shift 0.0030")


def test_condition_b_handles_a_different_channel_count():
    spectra = _five(5.0)
    spectra["E"] = _synthetic_spectrum(5.0, np.linspace(-20.5, 20.5, 800), seed=9)
    snr = pl.evaluate_signal_to_noise(spectra, BLOCKS, -4.0, sig_point=_real_sig_point())
    assert snr.evaluated and snr.passed and snr.resampled == ("E (800 vs 1024 channels)",)


def test_condition_b_handles_a_descending_velocity_axis():
    spectra = _five(5.0)
    spectra["W"] = {key: np.asarray(value)[::-1] for key, value in _synthetic_spectrum(5.0, seed=9).items()}
    snr = pl.evaluate_signal_to_noise(spectra, BLOCKS, -4.0, sig_point=_real_sig_point())
    assert snr.evaluated and snr.passed and len(snr.resampled) == 1


def test_condition_b_identical_grids_are_never_resampled():
    spectra = _five(5.0)
    spectra["S"] = _synthetic_spectrum(5.0, V.copy(), seed=9)  # equal values, different array object
    assert pl.evaluate_signal_to_noise(spectra, BLOCKS, -4.0, sig_point=_real_sig_point()).resampled == ()


def test_condition_b_does_not_alter_the_callers_spectra():
    spectra = _five(5.0)
    spectra["N"] = _synthetic_spectrum(5.0, V + 0.003, seed=9)
    before = {role: (np.array(s["Vlsr"]), np.array(s["LCP"]), np.array(s["RCP"])) for role, s in spectra.items()}
    pl.evaluate_signal_to_noise(spectra, BLOCKS, -4.0, sig_point=_real_sig_point())
    for role, (vlsr, lcp, rcp) in before.items():
        np.testing.assert_array_equal(spectra[role]["Vlsr"], vlsr)
        np.testing.assert_array_equal(spectra[role]["LCP"], lcp)
        np.testing.assert_array_equal(spectra[role]["RCP"], rcp)


def test_condition_b_uses_only_the_channels_every_spectrum_covers():
    spectra = _five(5.0)
    spectra["S"] = _synthetic_spectrum(5.0, np.linspace(-19.5, 20.5, 1024), seed=9)  # misses the low edge
    snr = pl.evaluate_signal_to_noise(spectra, BLOCKS, -4.0, sig_point=_real_sig_point())
    assert snr.evaluated and snr.passed and len(snr.resampled) == 1
    assert snr.resampled[0].startswith("S (max shift") and "left out of the noise" in snr.resampled[0]


def test_condition_b_partial_coverage_does_not_change_the_peak_to_noise_result():
    shifted = _five(5.0)
    shifted["S"] = _synthetic_spectrum(5.0, V + 3.0, seed=9)  # 3 km/s offset: about 75 channels uncovered at one end
    snr = pl.evaluate_signal_to_noise(shifted, BLOCKS, -4.0, sig_point=_real_sig_point())
    assert snr.evaluated and snr.sig_point in ("Yes", "No") and len(snr.panel_snr) == 5
    assert "left out of the noise" in snr.resampled[0]


def test_condition_b_spectrum_missing_the_peak_velocity_is_not_evaluated():
    spectra = _five(5.0)
    spectra["S"] = _synthetic_spectrum(5.0, np.linspace(0.0, 20.0, 600), seed=9)  # never reaches -4 km/s
    snr = pl.evaluate_signal_to_noise(spectra, BLOCKS, -4.0, sig_point=_real_sig_point())
    assert not snr.evaluated and "does not reach the peak velocity" in snr.reason


def test_condition_b_without_any_commonly_covered_baseline_channel_is_not_evaluated():
    spectra = _five(5.0)
    spectra["S"] = _synthetic_spectrum(5.0, np.linspace(-9.0, 4.0, 300), seed=9)  # covers the peak, no baseline
    snr = pl.evaluate_signal_to_noise(spectra, BLOCKS, -4.0, sig_point=_real_sig_point())
    assert not snr.evaluated and "No baseline channel" in snr.reason


def test_condition_b_repeated_velocities_are_not_a_usable_axis():
    spectra = _five(5.0)
    spectra["N"] = {"Vlsr": np.full(1024, 1.0), "LCP": np.zeros(1024), "RCP": np.zeros(1024)}
    snr = pl.evaluate_signal_to_noise(spectra, BLOCKS, -4.0, sig_point=_real_sig_point())
    assert not snr.evaluated and "repeated" in snr.reason


def test_condition_b_record_lists_resampled_spectra():
    spectra = _five(5.0)
    spectra["N"] = _synthetic_spectrum(5.0, V + 0.003, seed=9)
    snr = pl.evaluate_signal_to_noise(spectra, BLOCKS, -4.0, sig_point=_real_sig_point())
    record = pl.check_record(pl.evaluate_pointing_check(_result(), snr), _result(), signature="s", accepted=False)
    assert json.loads(json.dumps(record))["snr_check"]["resampled"] == list(snr.resampled)


# ---- FR-12: fit uncertainties / curves from the REAL Point_cor.py -----------------------------------------------
def test_measured_points_follow_pointcors_axis_order():
    m = pl.measured_points({"N": 1, "S": 2, "E": 3, "W": 4, "Centre": 5}, 0.2)
    assert m["North-South"]["y"] == [2.0, 5.0, 1.0] and m["East-West"]["y"] == [4.0, 5.0, 3.0]
    assert m["North-South"]["x"] == [-0.1, 0.0, 0.1]
    assert m["North-South"]["panels"] == ("South", "Centre", "North")


def test_compute_pointing_returns_uncertainties_curves_and_restores_curve_fit(real_pointcor):
    from scipy.optimize import curve_fit
    result = pl.compute_pointing(POWERS, 0.23, "20260812_0")
    unc = result.uncertainties
    assert unc.ns_sigma_deg > 0 and unc.ew_sigma_deg > 0 and unc.pc_sigma > 0
    assert set(result.fit_curves) == {"North-South", "East-West"}
    for curve in result.fit_curves.values():
        assert len(curve["x"]) == len(curve["y"]) == 100 and np.all(np.isfinite(curve["y"]))
    assert real_pointcor.curve_fit is curve_fit  # the spy is removed again


def test_uncertainty_extraction_does_not_change_pointcors_numbers(real_pointcor):
    wrapped = pl.compute_pointing(POWERS, 0.23, "20260812_0")
    real_pointcor.plt = pl._PyplotProxy(real_pointcor.plt, pl._redirected_savefig(real_pointcor.plt, None))
    direct = real_pointcor.pointcor(north=0.92, south=0.87, east=0.90, west=0.85, cen=1.0, hpbw=0.23,
                                    dirname="20260812_0")
    real_pointcor.plt = real_pointcor.plt._real
    assert (wrapped.correction_factor, wrapped.ns_offset_deg, wrapped.ew_offset_deg) == direct


def test_pc_sigma_matches_first_order_error_propagation(real_pointcor):
    result = pl.compute_pointing(POWERS, 0.23, "20260812_0")
    half = 0.23 / 2
    ns = result.fit_curves["North-South"]["centre"]
    ew = result.fit_curves["East-West"]["centre"]
    unc = result.uncertainties
    spread = np.hypot(ns * unc.ns_sigma_deg, ew * unc.ew_sigma_deg)
    expected = result.correction_factor * (2 * np.log(2) / half ** 2) * spread
    assert unc.pc_sigma == pytest.approx(expected, rel=1e-12)


@pytest.mark.parametrize("failing_call,axis,panels,partial", [
    (1, "North-South", ("South", "Centre", "North"), []),
    (2, "East-West", ("West", "Centre", "East"), ["North-South"]),
])
def test_compute_pointing_names_failed_panels_and_keeps_completed_fits(real_pointcor, monkeypatch,
                                                                       failing_call, axis, panels, partial):
    real, calls = real_pointcor.curve_fit, []

    def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) == failing_call:
            raise RuntimeError("Optimal parameters not found")
        return real(*args, **kwargs)
    monkeypatch.setattr(real_pointcor, "curve_fit", flaky)
    with pytest.raises(pl.PointingFitError) as excinfo:
        pl.compute_pointing(POWERS, 0.23, "x")
    error = excinfo.value
    assert isinstance(error, RuntimeError) and error.axis == axis and error.panels == panels
    assert list(error.partial_curves) == partial and axis in str(error)
    assert real_pointcor.curve_fit is flaky  # restored to what it was, even after a failure


def test_panel_names_map_to_page_roles():
    assert {pl.PANEL_ROLE[name] for _axis, names in pl.FIT_PANELS for name in names} == set(pl.ROLES)


# ---- manual entry: condition B is skipped, not failed ----------------------------------------------------------
def test_manual_entry_skips_condition_b_and_a_alone_decides():
    go = pl.evaluate_pointing_check(_result(), None, snr_required=False)
    assert go.verdict == "Go" and go.evaluated and go.snr_skipped and go.snr is None and go.reasons == ()
    no_go = pl.evaluate_pointing_check(_result(ns=1.0), None, snr_required=False)
    assert no_go.verdict == "No-Go" and len(no_go.reasons) == 1 and "NS offset" in no_go.reasons[0]


def test_skipped_condition_b_ignores_any_snr_that_is_passed_in():
    check = pl.evaluate_pointing_check(_result(), FAIL_SNR, snr_required=False)
    assert check.verdict == "Go" and check.snr is None and check.snr_skipped


def test_condition_b_is_required_by_default_and_recorded_as_such():
    check = pl.evaluate_pointing_check(_result(), PASS_SNR)
    assert not check.snr_skipped
    assert pl.check_record(check, _result(), signature="s", accepted=False)["snr_skipped"] is False
    skipped = pl.evaluate_pointing_check(_result(), None, snr_required=False)
    record = pl.check_record(skipped, _result(), signature="s", accepted=False)
    assert json.loads(json.dumps(record))["snr_skipped"] is True and record["snr_check"] is None


def test_manual_entry_without_a_ns_uncertainty_is_still_no_go():
    check = pl.evaluate_pointing_check(_result(sigmas=None), None, snr_required=False)
    assert check.verdict == "No-Go" and not check.evaluated
    