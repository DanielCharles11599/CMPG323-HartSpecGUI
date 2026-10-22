# test_fitting_adapters.py — tests for the clc/ adapters in utils/fitting_helpers.py (FR-14/15/16).
#
# NFR-05 concordance: adapter output must equal DIRECT execution of the clc/ code on reference spectra/maps to 6
# significant figures (rtol=1e-6). These tests need the real clc/ modules (hartspec_gui/clc symlink) and skip if
# they cannot be imported. No Streamlit runtime is needed.

import contextlib
import io
import os
import runpy
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")  # the 2D_Gauss_fit.py demo calls plt.show()

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from scipy.optimize import curve_fit  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hartspec_gui"))

from utils import fitting_helpers as fh  # noqa: E402

V = np.linspace(-20, 20, 1024)  # standard 1024-channel spectrum


def _gauss(x, amp, center, fwhm):
    return amp * np.exp(-0.5 * ((x - center) / (fwhm / 2.3548)) ** 2)


def _line(seed=1, amp=8.42, center=-4.2, fwhm=2.31):
    return _gauss(V, amp, center, fwhm) + np.random.default_rng(seed).normal(0, 0.15, V.size)


def _clc(name):
    return pytest.importorskip(f"clc.{name}")


def _clc_2d_path():
    spec = pytest.importorskip("importlib.util").find_spec("clc.2D_Gauss_fit")
    if spec is None or not spec.origin:
        pytest.skip("clc/2D_Gauss_fit.py not available")
    return spec.origin


def _clc_twoD_gaussian():
    """twoD_Gaussian as produced by genuinely running the clc script (in a scratch dir; it writes a PDF)."""
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                return runpy.run_path(_clc_2d_path())["twoD_Gaussian"]
        finally:
            os.chdir(cwd)


def _value(result, name):
    return float(next(r for r in result.rows if r[0] == name)[1].split()[0])


# ---- FR-14: clc/Gaussf.py -------------------------------------------------------------------------------------
def test_gaussf_adapter_matches_direct_clc_execution_to_6_sig_figs():
    gaussf = _clc("Gaussf").gaussf
    y, hpbw, p0 = _line(), 2.31, [8.0, -4.0]
    popt, pcov = curve_fit(lambda x, *p: gaussf(x, hpbw, *p), V, y, p0=p0)
    result = fh.run_gaussf(V, y, hpbw, p0[0], p0[1], unit="Jy")
    assert result.ok and result.converged and result.curve_x is None
    np.testing.assert_allclose(result.curve, gaussf(V, hpbw, *popt), rtol=1e-6)
    np.testing.assert_allclose(_value(result, "Amplitude"), popt[0], rtol=1e-3)  # display rounds to 4 sig figs
    np.testing.assert_allclose(_value(result, "Center (Vlsr)"), popt[1], rtol=1e-3)
    assert abs(popt[0] - 8.42) < 0.2 and abs(popt[1] - (-4.2)) < 0.05


def test_gaussf_reports_fixed_hpbw_units_and_the_no_offset_note():
    _clc("Gaussf")
    result = fh.run_gaussf(V, _line(), 2.31, 8.0, -4.0, unit="Jy")
    fwhm = next(r for r in result.rows if r[0].startswith("FWHM"))
    assert fwhm[1] == "2.31 km/s" and fwhm[2] == "fixed"
    assert next(r for r in result.rows if r[0] == "Amplitude")[1].endswith(" Jy")
    assert any("no baseline offset" in n for n in result.notes)


def test_gaussf_bad_inputs_are_reported_not_raised():
    _clc("Gaussf")
    y = _line()
    for hpbw, amp, cen in ((0.0, 8, 0), (-1.0, 8, 0), (2.0, np.nan, 0), (2.0, 8, np.inf)):
        assert not fh.run_gaussf(V, y, hpbw, amp, cen).ok
    bad = y.copy()
    bad[3] = np.nan
    assert "NaN" in fh.run_gaussf(V, bad, 2.0, 8, 0).notes[0]
    assert "lengths differ" in fh.run_gaussf(V, y[:-1], 2.0, 8, 0).notes[0]
    assert not fh.run_gaussf(V[:2], y[:2], 2.0, 8, 0).ok


def test_gaussf_missing_clc_module_is_reported_not_raised():
    class Empty:
        pass

    result = fh.run_gaussf(V, _line(), 2.0, 8.0, -4.0, module=Empty())
    assert not result.ok and "Gaussf.py could not be loaded" in result.notes[0]


def test_gaussf_non_convergence_is_reported_not_raised():
    class Broken:
        @staticmethod
        def gaussf(x, hp, *p):
            raise RuntimeError("boom")

    result = fh.run_gaussf(V, _line(), 2.0, 8.0, -4.0, module=Broken())
    assert not result.ok and result.curve is None and "did not converge" in result.notes[0]


def test_default_gaussian_guess_finds_the_line():
    amp, center, hpbw = fh.default_gaussian_guess(V, _line())
    assert abs(center - (-4.2)) < 0.3 and amp > 6.0 and 1.5 < hpbw < 3.5
    assert fh.estimate_fwhm(V, np.zeros(V.size)) == 4.0  # nothing to measure -> documented fallback
    assert fh.estimate_fwhm(V[:2], np.zeros(2)) == 4.0


# ---- FR-15: clc/fit_max.py ----------------------------------------------------------------------------------
def test_fit_max_adapter_matches_direct_clc_execution_to_6_sig_figs():
    fit_max = _clc("fit_max").fit_max
    y = _line()
    with contextlib.redirect_stdout(io.StringIO()):
        chans, peak_amp, fit_x, fit = fit_max({"Vlsr": V, "ave_pol": y}, -4.2, 12, 3)
    result = fh.run_fit_max(V, y, -4.2, 12, 3, unit="Jy")
    assert result.ok and result.converged
    np.testing.assert_allclose(result.curve, fit, rtol=1e-6)
    np.testing.assert_allclose(result.curve_x, fit_x, rtol=1e-6)
    np.testing.assert_allclose(_value(result, "Peak amplitude"), peak_amp, rtol=1e-3)
    assert next(r for r in result.rows if r[0] == "Window")[1].endswith("(24 channels)")


def test_fit_max_uses_an_independent_polyfit_of_the_same_channels():
    _clc("fit_max")
    y = _line()
    result = fh.run_fit_max(V, y, -4.2, 15, 2)
    chan = int(np.abs(V + 4.2).argmin())
    idx = np.arange(chan - 15, chan + 15)  # clc window: upper end exclusive
    expected = np.poly1d(np.polyfit(V[idx], y[idx], 2))(result.curve_x)
    np.testing.assert_allclose(result.curve, expected, rtol=1e-6)
    assert abs(result.curve_x[0] - V[idx[0]]) < 1e-12 and abs(result.curve_x[-1] - V[idx[-1]]) < 1e-12


def test_fit_max_orders_two_to_four_work_and_peak_is_near_the_line():
    _clc("fit_max")
    for order in fh.POLYNOMIAL_ORDERS:
        result = fh.run_fit_max(V, _line(), -4.2, 20, order)
        assert result.ok, (order, result.notes)
        assert abs(_value(result, "Peak Vlsr") - (-4.2)) < 0.5


def test_fit_max_window_helper_matches_what_clc_uses():
    chan = int(np.abs(V - 0.0).argmin())
    lo, hi = fh.fit_max_window(V, 0.0, 10)
    assert lo == V[chan - 10] and hi == V[chan + 9]
    assert fh.fit_max_window(V, V[0], 10) is None  # would wrap around the start inside clc
    assert fh.fit_max_window(V, V[-1], 10) is None  # would run past the end
    assert fh.fit_max_window(V, 0.0, 0) is None and fh.fit_max_window(V, np.nan, 5) is None


def test_fit_max_bad_inputs_are_reported_not_raised_and_clc_is_not_called():
    class Spy:
        called = False

        @staticmethod
        def fit_max(*args):
            Spy.called = True
            raise AssertionError("must not be reached")

    y = _line()
    cases = [dict(peak_vel=-4.2, half_width=10, order=7), dict(peak_vel=-4.2, half_width=0, order=2),
             dict(peak_vel=-4.2, half_width=1, order=4), dict(peak_vel=-4.2, half_width=2.5, order=2),
             dict(peak_vel=V[0], half_width=10, order=2), dict(peak_vel=-4.2, half_width=5000, order=2)]
    for kwargs in cases:
        result = fh.run_fit_max(V, y, module=Spy(), **kwargs)
        assert not result.ok and result.notes, kwargs
    assert not Spy.called


def test_fit_max_clc_exception_is_reported_not_raised():
    class Broken:
        @staticmethod
        def fit_max(spec, peak, hw, order):
            raise KeyError("ave_pol")

    result = fh.run_fit_max(V, _line(), -4.2, 10, 2, module=Broken())
    assert not result.ok and "KeyError" in result.notes[0]


def test_fit_max_stdout_banner_is_suppressed():
    _clc("fit_max")
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        fh.run_fit_max(V, _line(), -4.2, 10, 2)
    assert buffer.getvalue() == ""


def test_align_curve_resamples_inside_the_window_and_is_nan_outside():
    curve_x = np.linspace(-6.0, -2.0, 50)
    curve = curve_x ** 2
    aligned = fh.align_curve(V, curve, curve_x)
    inside = (V >= -6.0) & (V <= -2.0)
    assert aligned.shape == V.shape and np.all(np.isnan(aligned[~inside])) and np.all(np.isfinite(aligned[inside]))
    np.testing.assert_allclose(aligned[inside], V[inside] ** 2, atol=2e-3)
    np.testing.assert_allclose(fh.align_curve(V, V), V)  # already aligned -> unchanged
    descending = fh.align_curve(V[::-1], curve, curve_x)  # reversed velocity axes work too
    assert np.isfinite(descending).sum() == inside.sum()


# ---- FR-16: clc/2D_Gauss_fit.py -------------------------------------------------------------------------------
def _map(seed=3, truth=(3.0, 1.5, -2.0, 8.0, 5.0, 0.4, 10.0)):
    model = fh.twoD_gaussian_model(_clc_2d_path())
    x = np.linspace(-30, 30, 61)
    y = np.linspace(-30, 30, 51)
    xx, yy = np.meshgrid(x, y)
    z = model((xx, yy), *truth).reshape(xx.shape) + np.random.default_rng(seed).normal(0, 0.05, xx.shape)
    return x, y, z, truth


def test_2d_adapter_matches_direct_clc_execution_to_6_sig_figs():
    clc_model = _clc_twoD_gaussian()
    x, y, z, truth = _map()
    p0_ui = (2.5, 0.0, 0.0, 6.0, 6.0, 0.0, 9.0)
    xx, yy = np.meshgrid(x, y)
    popt, pcov = curve_fit(clc_model, (xx, yy), z.ravel(), p0=list(p0_ui))
    result = fh.run_2d_gauss(x, y, z, p0_ui)
    assert result.ok and result.converged and result.popt.shape == (7,) and result.pcov.shape == (7, 7)
    np.testing.assert_allclose(result.popt, popt, rtol=1e-6)
    np.testing.assert_allclose(result.pcov, pcov, rtol=1e-6)
    np.testing.assert_allclose(result.model, clc_model((xx, yy), *popt).reshape(z.shape), rtol=1e-6)
    assert abs(popt[1] - 1.5) < 0.1 and abs(popt[2] - (-2.0)) < 0.1  # sanity: injected centre recovered


@pytest.mark.parametrize("sx,sy,angle_degrees", [(6.0, 6.0, 20.0), (7.0, 4.0, 20.0), (4.0, 7.0, 110.0)])
def test_2d_adapter_angle_is_given_in_degrees_and_reported_in_degrees(monkeypatch, sx, sy, angle_degrees):
    """Check unit conversion explicitly, and compare the ellipse rather than an arbitrary axis ordering."""
    x, y, z, truth = _map()
    initial = np.array([2.5, 0.0, 0.0, sx, sy, angle_degrees, 9.0])
    captured = []

    def measured(model, xy, values, *, p0):
        captured.append(np.array(p0, copy=True))
        return curve_fit(model, xy, values, p0=p0)

    monkeypatch.setattr(fh, "curve_fit", measured)
    result = fh.run_2d_gauss(x, y, z, initial)
    assert result.ok and result.converged
    expected_p0 = initial.copy()
    expected_p0[5] = np.radians(angle_degrees)
    assert len(captured) == 1
    np.testing.assert_array_equal(captured[0], expected_p0)
    assert initial[5] == angle_degrees  # the UI's array must not be mutated
    angle_row = next(r for r in result.rows if r[0] == "Position angle")
    assert angle_row[1] == f"{np.degrees(result.popt[5]):.4g} °"
    assert angle_row[2] == f"{np.degrees(np.sqrt(abs(result.pcov[5, 5]))):.4g} °"

    # (sigma_x, sigma_y, theta) and (sigma_y, sigma_x, theta + pi/2) give
    # the same CLC surface. Only this comparison uses a common major-axis
    # convention; production popt/pcov must stay in the backend's raw order.
    fitted_angle = result.popt[5] + (np.pi / 2 if abs(result.popt[3]) < abs(result.popt[4]) else 0.0)
    true_angle = truth[5] + (np.pi / 2 if abs(truth[3]) < abs(truth[4]) else 0.0)
    angle_error = (fitted_angle - true_angle + np.pi / 2) % np.pi - np.pi / 2
    np.testing.assert_allclose(angle_error, 0.0, rtol=0.0, atol=0.05)  # original angular tolerance
    np.testing.assert_allclose(np.sort(np.abs(result.popt[3:5])), np.sort(np.abs(truth[3:5])), rtol=0.0, atol=0.1)
    xx, yy = np.meshgrid(x, y)
    noiseless = fh.twoD_gaussian_model(_clc_2d_path())((xx, yy), *truth).reshape(z.shape)
    np.testing.assert_allclose(result.model, noiseless, rtol=0.0, atol=0.05)  # fixture noise sigma is 0.05


def test_2d_adapter_preserves_raw_swapped_axes_and_radian_covariance(monkeypatch):
    """Do not reorder parameters or convert covariance just to satisfy a display-angle test."""
    x, y, z, truth = _map()
    backend = np.array(truth)
    backend[3], backend[4] = truth[4], truth[3]
    backend[5] += np.pi / 2 + 2 * np.pi
    covariance = np.diag(np.arange(1.0, 8.0) * 0.001)
    covariance[1, 5] = covariance[5, 1] = 0.0002

    def fixed_result(model, xy, values, *, p0):
        assert p0[5] == pytest.approx(np.radians(20.0), rel=1e-12)
        return backend.copy(), covariance.copy()

    monkeypatch.setattr(fh, "curve_fit", fixed_result)
    result = fh.run_2d_gauss(x, y, z, (2.5, 0.0, 0.0, 6.0, 6.0, 20.0, 9.0))
    assert result.ok and result.converged
    np.testing.assert_array_equal(result.popt, backend)
    np.testing.assert_array_equal(result.pcov, covariance)
    xx, yy = np.meshgrid(x, y)
    expected = fh.twoD_gaussian_model(_clc_2d_path())((xx, yy), *truth).reshape(z.shape)
    np.testing.assert_allclose(result.model, expected, rtol=1e-12, atol=1e-12)


def test_2d_adapter_does_not_execute_the_clc_demo_script():
    _clc_2d_path()
    x, y, z, _ = _map()
    import matplotlib.pyplot as plt

    figures_before = set(plt.get_fignums())
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        try:
            fh._extract_twoD_gaussian.cache_clear()
            assert fh.run_2d_gauss(x, y, z, (2.5, 0.0, 0.0, 6.0, 6.0, 0.0, 9.0)).ok
            assert os.listdir(tmp) == []  # the script would have written 2D_Gauss.pdf
        finally:
            os.chdir(cwd)
    assert set(plt.get_fignums()) == figures_before  # and would have opened figures


def test_2d_covariance_table_is_7x7_and_labelled():
    x, y, z, _ = _map()
    result = fh.run_2d_gauss(x, y, z, (2.5, 0.0, 0.0, 6.0, 6.0, 0.0, 9.0))
    table = fh.covariance_dataframe(result)
    assert table.shape == (7, 7) and list(table.index) == list(fh.COV_LABELS_2D) == list(table.columns)
    np.testing.assert_allclose(table.to_numpy(), table.to_numpy().T, rtol=1e-6)  # covariance is symmetric
    assert fh.covariance_dataframe(fh._failed_2d("x")).empty


def test_2d_rows_have_the_seven_named_parameters_with_units():
    x, y, z, _ = _map()
    result = fh.run_2d_gauss(x, y, z, (2.5, 0.0, 0.0, 6.0, 6.0, 0.0, 9.0), unit="K", axis_unit="arcmin")
    assert [r[0] for r in result.rows] == list(fh.PARAM_NAMES_2D)
    assert result.rows[0][1].endswith(" K") and result.rows[1][1].endswith(" arcmin")
    assert any("not re-sorted" in n for n in result.notes)


def test_2d_bad_inputs_are_reported_not_raised():
    x, y, z, _ = _map()
    good = (2.5, 0.0, 0.0, 6.0, 6.0, 0.0, 9.0)
    nan_map = z.copy()
    nan_map[0, 0] = np.nan
    for args in ((x, y, z[:-1], good), (x, y, nan_map, good), (x, y, z, good[:6]),
                 (x, y, z, (2.5, 0, 0, 0.0, 6.0, 0, 9.0)), (x, y, z, (2.5, 0, 0, 6.0, -1.0, 0, 9.0)),
                 (x, y, z, (np.nan,) + good[1:]), (x, y, np.zeros(5), good), ("a", y, z, good)):
        result = fh.run_2d_gauss(*args)
        assert not result.ok and result.notes and result.model is None, args


def test_2d_non_convergence_and_missing_clc_are_reported_not_raised():
    x, y, z, _ = _map()

    def broken(xy, *p):
        raise RuntimeError("maxfev exceeded")

    result = fh.run_2d_gauss(x, y, z, (2.5, 0.0, 0.0, 6.0, 6.0, 0.0, 9.0), model=broken)
    assert not result.ok and "did not converge" in result.notes[0]
    missing = fh.run_2d_gauss(x, y, z, (2.5, 0.0, 0.0, 6.0, 6.0, 0.0, 9.0), source_path="/nonexistent/2D.py")
    assert not missing.ok and "could not be loaded" in missing.notes[0]


def test_2d_loader_rejects_a_source_without_the_model_function():
    with tempfile.TemporaryDirectory() as tmp:
        bad = Path(tmp) / "no_model.py"
        bad.write_text("x = 1\n")
        with pytest.raises(fh.ClcLoadError):
            fh.twoD_gaussian_model(str(bad))


def test_coerce_map_2d_accepts_the_documented_structure_and_rejects_the_rest():
    z = np.ones((4, 5))
    ok = fh.coerce_map_2d({"data": z, "x": np.arange(5), "y": np.arange(4), "unit": "K", "axis_unit": "arcmin"})
    assert ok is not None and ok.data.shape == (4, 5) and ok.unit == "K" and ok.axis_unit == "arcmin"
    assert fh.coerce_map_2d({"data": z, "x": np.arange(5), "y": np.arange(4)}).unit == "map units"
    bad_cases = [None, "map", {"data": z}, {"data": z, "x": np.arange(4), "y": np.arange(4)},  # axes swapped
                 {"data": np.ones(5), "x": np.arange(5), "y": np.arange(1)},
                 {"data": np.ones((2, 2)), "x": np.arange(2), "y": np.arange(2)},  # too small
                 {"data": np.where(np.eye(4, 5) > 0, np.nan, 1.0), "x": np.arange(5), "y": np.arange(4)},
                 {"data": [["a"]], "x": [0], "y": [0]}]
    assert all(fh.coerce_map_2d(case) is None for case in bad_cases)


def test_default_p0_2d_and_synthetic_map_are_usable_starting_points():
    _clc_2d_path()
    synthetic = fh.synthetic_map_2d(source_path=_clc_2d_path())
    assert synthetic.data.shape == (41, 41) and fh.coerce_map_2d(
        {"data": synthetic.data, "x": synthetic.x, "y": synthetic.y}) is not None
    p0 = fh.default_p0_2d(synthetic.x, synthetic.y, synthetic.data)
    assert len(p0) == 7 and p0[3] > 0 and p0[4] > 0 and p0[5] == 0.0
    result = fh.run_2d_gauss(synthetic.x, synthetic.y, synthetic.data, p0)
    assert result.ok
    np.testing.assert_allclose(result.popt[:3], fh.SYNTHETIC_TRUTH_2D[:3], atol=0.2)
    again = fh.synthetic_map_2d(source_path=_clc_2d_path())
    np.testing.assert_allclose(again.data, synthetic.data)  # deterministic
