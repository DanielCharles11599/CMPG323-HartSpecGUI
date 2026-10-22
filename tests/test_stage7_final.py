# test_stage7_final.py — Stage 7 numerical adapters, state/replay, import safety and chart contracts.
"""These tests do not require Streamlit. Optional CLC dependencies are tested separately.

AST extraction below runs the exact supplied Gaussf/fit_max definitions without
importing their unrelated Astropy imports; it is not a replacement CLC algorithm.
"""
from __future__ import annotations

import ast
import copy
import importlib
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest
from scipy.optimize import curve_fit

from utils import fit_figures, fitting_helpers as fh, fitting_state as fs

APP = Path(__file__).resolve().parents[1] / "hartspec_gui"


def original_function(filename, name):
    """Compile only the original numerical function, with exactly its NumPy dependency."""
    path = APP / "clc" / filename
    node = next(n for n in ast.parse(path.read_text()).body if isinstance(n, ast.FunctionDef) and n.name == name)
    namespace = {"np": np}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[name]


@pytest.mark.parametrize("seed", [1, 21, 91])
def test_gaussian_exact_clc_definition_and_full_precision_storage(seed):
    model = original_function("Gaussf.py", "gaussf")
    v = np.linspace(-20, 20, 1024)
    width, p0 = 2.31, [8., -4.]
    y = model(v, width, 8.42, -4.2) + np.random.default_rng(seed).normal(0, .03, v.size)
    direct, covariance = curve_fit(lambda x, *p: model(x, width, *p), v, y, p0=p0)
    result = fh.run_gaussf(v, y, width, *p0, module=SimpleNamespace(gaussf=model))
    np.testing.assert_allclose(result.curve, model(v, width, *direct), rtol=5e-7)
    np.testing.assert_allclose([result.parameters["amplitude"], result.parameters["center"]], direct, rtol=5e-7)
    np.testing.assert_allclose(result.covariance, covariance, rtol=5e-7)
    entry = {}
    fs.save_result(entry, "request", result)
    loaded = json.loads(json.dumps(entry, allow_nan=False))
    assert loaded["result"]["parameters"] == result.parameters
    assert loaded["result"]["parameters"]["hpbw"] == width


@pytest.mark.parametrize("order", [2, 3, 4])
@pytest.mark.parametrize("descending", [False, True])
def test_polynomial_exact_clc_window(order, descending):
    model = original_function("fit_max.py", "fit_max")
    v = np.linspace(-20, 20, 1024)
    if descending:
        v = v[::-1]
    y = 5 - (v + 2) ** 2 / 3
    _, peak, xx, yy = model({"Vlsr": v, "ave_pol": y}, -2., 10, order)
    result = fh.run_fit_max(v, y, -2., 10, order, module=SimpleNamespace(fit_max=model))
    np.testing.assert_allclose(result.curve_x, xx, rtol=5e-7)
    np.testing.assert_allclose(result.curve, yy, rtol=5e-7)
    assert result.parameters["peak_amplitude"] == peak
    assert abs(np.diff(fh.fit_max_window(v, -2, 10))[0]) == pytest.approx(abs(xx[-1] - xx[0]))


def test_2d_direct_import_has_no_cli_side_effects(tmp_path, monkeypatch):
    import matplotlib.pyplot as plt
    monkeypatch.chdir(tmp_path)
    state = np.random.get_state()
    figures = plt.get_fignums()
    module = importlib.import_module("clc.2D_Gauss_fit")
    importlib.reload(module)
    assert not list(tmp_path.iterdir())
    assert plt.get_fignums() == figures
    np.testing.assert_array_equal(state[1], np.random.get_state()[1])
    assert not hasattr(module, "popt")


def test_2d_cli_guard_contains_demo_only():
    tree = ast.parse((APP / "clc/2D_Gauss_fit.py").read_text())
    assert isinstance(tree.body[-1], ast.If)
    assert ast.unparse(tree.body[-1].test) == "__name__ == '__main__'"
    assert any(isinstance(n, ast.FunctionDef) and n.name == "twoD_Gaussian" for n in tree.body)


@pytest.mark.parametrize("seed", [2, 17, 44])
def test_2d_matches_direct_curve_fit(seed):
    model = importlib.import_module("clc.2D_Gauss_fit").twoD_Gaussian
    x, y = np.linspace(-12, 12, 41), np.linspace(-10, 10, 35)
    xx, yy = np.meshgrid(x, y)
    truth = (4, .2, -.8, 3, 1.5, .2, .4)
    z = model((xx, yy), *truth).reshape(xx.shape) + np.random.default_rng(seed).normal(0, .03, xx.shape)
    p0 = [3.5, 0, 0, 2.8, 1.8, 10, .3]
    native = p0.copy()
    native[5] = np.radians(native[5])
    direct, covariance = curve_fit(model, (xx, yy), z.ravel(), p0=native)
    result = fh.run_2d_gauss(x, y, z, p0)
    assert result.ok and result.converged
    np.testing.assert_allclose(result.popt, direct, rtol=5e-7)
    np.testing.assert_allclose(result.pcov, covariance, rtol=5e-7)


def test_synthetic_map_is_deterministic_without_global_rng_side_effects():
    before = np.random.get_state()
    first, second = fh.synthetic_map_2d(), fh.synthetic_map_2d()
    np.testing.assert_array_equal(first.data, second.data)
    np.testing.assert_array_equal(before[1], np.random.get_state()[1])


def test_dashed_spatial_contours_keep_a_plotly_contour_trace():
    m = fh.synthetic_map_2d()
    theme = {"bg-panel": "#FFFFFF", "text-body": "#334155", "text-muted": "#64748B"}
    fig = fit_figures.map_figure(m.data, m.x, m.y, m.data, "K", "arcmin", theme, {},
                                 fit_color="#DC2626", dashed_contours=True)
    assert [t.type for t in fig.data] == ["heatmap", "contour", "scatter"]
    assert fig.data[2].line.dash == "dash" and fig.data[2].line.color == "#DC2626"
    assert len(fig.data[2].x) > 10


@pytest.mark.parametrize("mode", fh.FIT_TYPES)
def test_every_mode_roundtrips_through_stages_fitting(mode):
    pipeline = {}
    stage = fs.ensure_stage(pipeline)
    stage.update(fit_type=mode, fit_type_requested=mode)
    entry = fs.mode_state(stage, mode, "exact-data-hash")
    entry["options"] = {"precise": 1.23456789012345, "p0": list(range(7)), "max_components": 10}
    fs.save_result(entry, "request", {"ok": True, "covariance": np.array([[np.inf, 0], [0, .000123456789]])})
    payload = json.loads(json.dumps(fh.stages_from_pipeline(pipeline), allow_nan=False))
    assert "fitting" in payload and payload["fitting"]["params"] == entry["options"]
    loaded = fh.merge_stages_into_pipeline({}, payload)
    assert loaded == pipeline
    assert loaded is not pipeline
    assert fs.result_is_current(loaded[fs.STAGE_KEY]["modes"][mode], "request")


def test_signature_catches_equal_sum_changed_data_and_sub_six_digit_changes():
    assert fs.signature([1, 2, 3]) != fs.signature([3, 2, 1])
    assert fs.signature([1.00000001]) != fs.signature([1.00000002])
    assert fs.signature([1, 2], context="Jy") != fs.signature([1, 2], context="K")
    assert fs.request_key("x", {"p": 1.000000001}) != fs.request_key("x", {"p": 1.000000002})


def test_failed_request_preserves_previous_model_but_cannot_commit_it():
    entry = {}
    fs.save_result(entry, "old", {"ok": True, "curve": [1, 2]})
    fs.save_failure(entry, "new", "Did not converge")
    assert entry["result"]["curve"] == [1, 2]
    assert not fs.result_is_current(entry, "new")
    fs.save_failure(entry, "old", "Retry failed")
    assert not fs.result_is_current(entry, "old")


def test_changed_data_discards_cached_surface_and_covariance():
    stage = fs.ensure_stage({})
    entry = fs.mode_state(stage, "2D Gaussian", "old-map")
    entry["options"] = {"p0": [1] * 7}
    fs.save_result(entry, "r", {"ok": True, "model": [[1, 2]], "pcov": [[4]]})
    changed = fs.mode_state(stage, "2D Gaussian", "new-map")
    assert "result" not in changed and changed["options"] == {"p0": [1] * 7}


def test_commit_invalidation_drops_export_overlay_and_completion():
    state = {"pipeline_data": {}, "completed_stages": {fs.STAGE_KEY, "08_export_and_session"}, "latest_fit": {}}
    stage = fs.ensure_stage(state["pipeline_data"])
    stage["committed_request"] = "old"
    fs.invalidate_commit(state, stage, "new")
    assert "latest_fit" not in state and state["completed_stages"] == set()


def test_legacy_run_fit_remains_callable_with_same_signature():
    v = np.linspace(-10, 10, 200)
    result = fh.run_fit("1D Gaussian", v, fh.gaussian(v, 2, 0, 1))
    assert result.ok


def test_refit_unknown_covariance_is_not_falsely_zero(monkeypatch):
    monkeypatch.setattr(fh, "curve_fit", lambda *a, **k: (np.array([2., 0., 1.]), np.full((3, 3), np.inf)))
    v = np.linspace(-10, 10, 100)
    params = fh.renumber([{"amplitude": 2., "center": 0., "fwhm": 1., "fixed": False}])
    _, errors, covariance = fh.refit_free(v, fh.composite(v, params), params)
    assert errors == [None] and np.isinf(covariance).all()
    assert fs.json_safe(covariance) == [[None] * 3] * 3


def test_auto_can_exceed_legacy_three_component_limit_and_returns_full_covariance():
    v = np.linspace(-25, 25, 1024)
    truth = fh.renumber([dict(amplitude=a, center=c, fwhm=w, fixed=False)
                         for a, c, w in [(10, -15, 1.5), (8, -5, 1.6), (6, 5, 1.7), (4, 15, 1.8)]])
    y = fh.composite(v, truth) + np.random.default_rng(4).normal(0, .03, v.size)
    calls = []

    def seeds(x, residual, *, max_fits):
        calls.append(max_fits)
        peak = float(x[np.argmax(residual)])
        component = min(truth, key=lambda p: abs(p["center"] - peak))
        return [copy.deepcopy(component)]

    output = fh.run_auto_decomposition(v, y, seed_runner=seeds)
    assert len(output["params"]) == 4 and calls == [1] * 4
    assert np.asarray(output["covariance"]).shape == (12, 12)
    assert output["statistics"]["rms_residual"] < .04
    assert len(output["history"]) == 4


def test_auto_noise_cutoff_prevents_any_backend_call():
    v = np.linspace(-20, 20, 1024)
    y = np.random.default_rng(10).normal(0, .1, v.size)

    def forbidden(*args, **kwargs):
        raise AssertionError("Noise should not reach the CLC fitter")

    result = fh.run_auto_decomposition(v, y, seed_runner=forbidden)
    assert not result["params"] and "cutoff" in result["stop_reason"]


def test_auto_preserves_fixed_components():
    v = np.linspace(-20, 20, 1024)
    fixed = dict(amplitude=10., center=-5., fwhm=2., fixed=True, id="Comp 1")
    free = dict(amplitude=5., center=5., fwhm=2., fixed=False, id="Comp 2")
    y = fh.composite(v, [fixed, free]) + np.random.default_rng(4).normal(0, .01, v.size)
    output = fh.run_auto_decomposition(v, y, params=[fixed], seed_runner=lambda *a, **k: [free])
    assert output["params"][0] == fixed
    assert np.all(np.asarray(output["covariance"])[:3] == 0)


@pytest.mark.parametrize("kwargs", [
    {"max_components": 0}, {"max_components": 21}, {"max_components": 1.5},
    {"rms_cutoff": -1}, {"chi2_threshold": np.nan},
])
def test_auto_rejects_invalid_termination_settings(kwargs):
    with pytest.raises(fh.DecompositionError):
        fh.run_auto_decomposition(np.arange(20.), np.ones(20), **kwargs)


def test_recorder_early_stop_and_rng_isolation():
    mod = ModuleType("recording_test")
    mod.np = np
    mod.u = mod.models = mod.Spectrum1D = object()
    model = SimpleNamespace(amplitude=2., mean=0., stddev=1.)
    mod.fit_lines = lambda *a, **k: model
    exec(
        "def Spec_comp(v, y, half_width):\n"
        "    np.random.seed(0)\n    for i in range(3):\n        fit_lines()\n",
        vars(mod),
    )
    before = np.random.get_state()
    original = dict(vars(mod))
    result = fh.run_spec_comp(np.arange(20.), np.ones(20), module=mod, max_fits=1)
    assert len(result) == 1
    assert vars(mod) == original
    np.testing.assert_array_equal(before[1], np.random.get_state()[1])
