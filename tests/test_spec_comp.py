# test_spec_comp.py — FR-17 / NFR-05 / NFR-08: tests for utils/fitting_helpers.py + its clc/Spec_comp.py wrapper.
#
# Two layers:
#   1. Unit tests (always run): model maths, termination criteria, locked refit, table <-> params, session JSON
#      round-trip, and the wrapper mechanics against a stand-in module (no astropy/specutils needed).
#   2. NFR-05 concordance (runs where astropy + specutils + clc.Spec_comp are importable): the GUI wrapper's components
#      and residual must match a DIRECT, independent execution of clc/Spec_comp.py to >= 6 significant figures.
#      The direct run exec()s the file's own source into a fresh namespace with its own recorder -- it shares no code
#      with the wrapper's namespace patching.
# Spec_comp.py is only read, never modified.
import importlib.util
import json
import math
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import numpy as np
import pandas as pd
import pytest

# make `utils` importable when pytest is run from the repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hartspec_gui"))
from utils import fitting_helpers as fh  # noqa: E402

SIX_SIG_FIG_RTOL = 5e-7  # relative error below this agrees to 6 significant figures
TRUE_COMPS = [(12.4, -5.0, 2.1), (7.0, 3.0, 3.0), (4.0, 10.0, 1.8)]


def assert_six_sig_figs(actual, desired, atol=1e-12):
    """NFR-05 helper: agreement to >= 6 significant figures."""
    np.testing.assert_allclose(actual, desired, rtol=SIX_SIG_FIG_RTOL, atol=atol)


def make_spectrum(seed=0, noise=0.05, n=1024):
    rng = np.random.default_rng(seed)
    v = np.linspace(-30.0, 30.0, n)
    y = sum(fh.gaussian(v, a, c, w) for a, c, w in TRUE_COMPS) + rng.normal(0.0, noise, n)
    return v, y


def params_of(comps, fixed=False):
    return fh.renumber([{"id": "", "amplitude": a, "center": c, "fwhm": w, "fixed": fixed} for a, c, w in comps])


@pytest.fixture
def spectrum():
    return make_spectrum()


# ---------------------------------------------------------------------
# Model maths
# ---------------------------------------------------------------------
def test_gaussian_peak_and_fwhm():
    v = np.linspace(-10, 10, 20001)
    g = fh.gaussian(v, 5.0, 1.5, 2.0)
    assert g.max() == pytest.approx(5.0)
    assert v[np.argmax(g)] == pytest.approx(1.5, abs=1e-3)
    above_half = v[g >= 2.5]
    assert above_half.max() - above_half.min() == pytest.approx(2.0, abs=2e-3)


def test_composite_empty_and_sum():
    v = np.linspace(-5, 5, 11)
    assert np.all(fh.composite(v, []) == 0.0)
    p = params_of([(1.0, 0.0, 2.0), (2.0, 1.0, 1.0)])
    assert_six_sig_figs(fh.composite(v, p), fh.gaussian(v, 1, 0, 2) + fh.gaussian(v, 2, 1, 1))


def test_stats_zero_residual_for_exact_model():
    v = np.linspace(-20, 20, 512)
    p = params_of(TRUE_COMPS[:2])
    y = fh.composite(v, p)
    assert fh.compute_stats(v, y, p)["rms_residual"] == pytest.approx(0.0, abs=1e-12)


def test_estimate_noise_close_to_truth(spectrum):
    _, y = spectrum
    assert fh.estimate_noise(y) == pytest.approx(0.05, rel=0.1)


def test_stats_reduced_chi2_near_one_for_true_model(spectrum):
    v, y = spectrum
    stats = fh.compute_stats(v, y, params_of(TRUE_COMPS))
    assert stats["chi2"] == pytest.approx(1.0, abs=0.25)
    assert stats["rms_residual"] == pytest.approx(0.05, rel=0.1)


# ---------------------------------------------------------------------
# Termination criteria
# ---------------------------------------------------------------------
def test_termination_max_components(spectrum):
    v, y = spectrum
    kept, why = fh.apply_termination(v, y, params_of(TRUE_COMPS), 2, 3.0, 0.0)
    assert len(kept) == 2 and "max_components" in why
    assert [k["id"] for k in kept] == ["Comp 1", "Comp 2"]


def test_termination_rms_cutoff_stops_when_residual_is_noise(spectrum):
    v, y = spectrum
    seq = params_of(TRUE_COMPS + [(0.04, 0.0, 1.0)])  # 4th component is pure noise
    # 5 sigma, not the default 3: the max of ~1000 noise channels already reaches ~3.2 sigma
    kept, why = fh.apply_termination(v, y, seq, 10, 5.0, 0.0)
    assert len(kept) == 3 and "sigma_RMS" in why


def test_termination_chi2_threshold_rejects_useless_component(spectrum):
    v, y = spectrum
    seq = params_of(TRUE_COMPS[:2] + [(0.3, 20.0, 1.0)])
    kept, why = fh.apply_termination(v, y, seq, 10, 0.0, 5.0)  # comp 2 helps hugely; comp 3 does not
    assert len(kept) == 2 and "component 3" in why and "chi2" in why


def test_termination_keeps_everything_when_criteria_met(spectrum):
    v, y = spectrum
    kept, _ = fh.apply_termination(v, y, params_of(TRUE_COMPS), 10, 3.0, 0.0)
    assert len(kept) == 3


# ---------------------------------------------------------------------
# Refit with locking
# ---------------------------------------------------------------------
def test_refit_recovers_parameters_and_reports_uncertainties(spectrum):
    v, y = spectrum
    start = params_of([(10.0, -4.5, 2.5), (6.0, 3.3, 2.5), (5.0, 9.5, 2.0)])
    new, uncs, cov = fh.refit_free(v, y, start)
    for p, (a, c, w) in zip(new, TRUE_COMPS):
        assert p["amplitude"] == pytest.approx(a, rel=0.05)
        assert p["center"] == pytest.approx(c, abs=0.1)
        assert p["fwhm"] == pytest.approx(w, rel=0.05)
    assert all(u is not None and u["amplitude_err"] > 0 for u in uncs)
    assert np.asarray(cov).shape == (9, 9)


def test_refit_holds_locked_component_exactly(spectrum):
    v, y = spectrum
    start = params_of([(12.4, -5.0, 2.1), (6.0, 3.3, 2.5)])
    start[0]["fixed"] = True
    new, uncs, cov = fh.refit_free(v, y, start)
    assert (new[0]["amplitude"], new[0]["center"], new[0]["fwhm"]) == (12.4, -5.0, 2.1)
    assert uncs[0] is None and uncs[1] is not None
    assert np.all(np.asarray(cov)[:3, :] == 0.0)


def test_refit_all_locked_or_empty_raises(spectrum):
    v, y = spectrum
    with pytest.raises(fh.FitError):
        fh.refit_free(v, y, [])
    with pytest.raises(fh.FitError):
        fh.refit_free(v, y, params_of(TRUE_COMPS, fixed=True))


def test_refit_infeasible_start_raises_fit_error_not_crash(spectrum):
    v, y = spectrum
    with pytest.raises(fh.FitError):
        fh.refit_free(v, y, params_of([(5.0, 500.0, 2.0)]))  # centre far outside the velocity axis


# ---------------------------------------------------------------------
# Table <-> params
# ---------------------------------------------------------------------
def test_df_roundtrip_preserves_values_and_locks():
    p = params_of([(1.25, -2.5, 3.0), (0.5, 4.0, 1.0)])
    p[1]["fixed"] = True
    back, problems = fh.params_from_df(fh.df_from_params(p))
    assert back == p and problems == []


def test_params_from_df_skips_incomplete_and_invalid_rows():
    df = pd.DataFrame({
        fh.COL_ID: ["Comp 1", None, "Comp 3", "Comp 4"],
        fh.COL_AMP: [1.0, None, 2.0, 3.0],
        fh.COL_CENTER: [0.0, None, 1.0, 2.0],
        fh.COL_FWHM: [2.0, None, -1.0, 1.5],
        fh.COL_LOCK: [False, None, False, None],
    })
    params, problems = fh.params_from_df(df)
    assert [p["id"] for p in params] == ["Comp 1", "Comp 2"]  # renumbered sequentially
    assert params[1]["fixed"] is False  # missing lock cell -> unlocked
    assert len(problems) == 2


# ---------------------------------------------------------------------
# Session JSON (FR-19 / NFR-08)
# ---------------------------------------------------------------------
def test_session_block_roundtrip_is_exact_through_json(spectrum):
    v, y = spectrum
    start = params_of([(10.0, -4.5, 2.5), (6.0, 3.3, 2.5)])
    new, uncs, cov = fh.refit_free(v, y, start)
    block = fh.build_fitting_block(new, uncs, cov, fh.compute_stats(v, y, new))
    reloaded = json.loads(json.dumps(block))  # what /data/sessions/{id}.json does
    assert reloaded["type"] == "multi_component"
    assert set(reloaded["statistics"]) == {"chi2", "rms_residual"}
    assert "residual" not in reloaded and all(len(v_) < 100 for v_ in reloaded.values())  # arrays are not serialised
    restored = fh.restore_from_block(reloaded)
    assert restored == new  # 100 % parameter fidelity: identical floats, ids and lock flags


def test_block_without_uncertainties_and_nan_stats_is_json_safe():
    p = params_of([(1.0, 0.0, 1.0)])
    block = fh.build_fitting_block(p, None, None, {"chi2": float("nan"), "rms_residual": 0.1})
    text = json.dumps(block, allow_nan=False)  # raises if any NaN/inf slipped through
    assert json.loads(text)["statistics"]["chi2"] is None
    assert json.loads(text)["uncertainties"] == [{"amplitude_err": None, "center_err": None, "fwhm_err": None}]


@pytest.mark.parametrize("bad", [
    None,
    {"type": "gaussian_1d", "params": []},
    {"type": "multi_component", "params": [{"amplitude": 1.0, "center": 0.0}]},
    {"type": "multi_component", "params": [{"amplitude": 1.0, "center": 0.0, "fwhm": -2.0}]},
])
def test_restore_from_malformed_block_raises_value_error(bad):
    with pytest.raises(ValueError):
        fh.restore_from_block(bad)


def test_summary_rows_match_other_fit_types_shape():
    p = params_of([(1.0, 2.0, 3.0)])
    rows = fh.summary_rows(p, [{"amplitude_err": 0.1, "center_err": 0.2, "fwhm_err": 0.3}])
    assert rows[0] == {"parameter": "Comp 1 Amplitude", "value": 1.0, "error": 0.1}
    assert [r["parameter"] for r in rows] == ["Comp 1 Amplitude", "Comp 1 Center (Vlsr)", "Comp 1 FWHM"]


# ---------------------------------------------------------------------
# stages.fitting mapping used by utils/session_store.py (spec 6.6)
# ---------------------------------------------------------------------
def _saved_block():
    p = params_of([(12.4, 45.2, 2.1), (5.1, 48.0, 1.8)])
    return fh.build_fitting_block(p, None, None, {"chi2": 1.04, "rms_residual": 0.082})


def test_stages_fitting_is_derived_from_pipeline_data_and_survives_json():
    block = _saved_block()
    pipeline = {fh.FITTING_STAGE_KEY: {"fit_type": "Multi-component", "multi_component": block}}
    payload = json.loads(json.dumps({"pipeline_data": pipeline, "stages": fh.stages_from_pipeline(pipeline)}))
    assert payload["stages"]["fitting"]["type"] == "multi_component"
    assert payload["stages"]["fitting"] == block


def test_stages_empty_when_another_fit_type_is_saved():
    pipeline = {fh.FITTING_STAGE_KEY: {"fit_type": "1D Gaussian"}}
    assert fh.stages_from_pipeline(pipeline) == {}
    assert fh.stages_from_pipeline({}) == {}


def test_load_restores_pipeline_data_from_stages_and_stages_wins_over_stale_copy():
    block = _saved_block()
    stale = dict(block, params=block["params"][:1])
    pipeline = {fh.FITTING_STAGE_KEY: {"fit_type": "Multi-component", "multi_component": stale}}
    fh.merge_stages_into_pipeline(pipeline, {"fitting": block})
    assert fh.restore_from_block(pipeline[fh.FITTING_STAGE_KEY]["multi_component"]) == fh.restore_from_block(block)
    assert len(pipeline[fh.FITTING_STAGE_KEY]["multi_component"]["params"]) == 2


def test_load_with_only_stages_creates_minimal_summary_that_seeds_fit_type():
    pipeline = fh.merge_stages_into_pipeline({}, {"fitting": _saved_block()})
    assert pipeline[fh.FITTING_STAGE_KEY]["fit_type_requested"] == "Multi-component"
    assert pipeline[fh.FITTING_STAGE_KEY]["multi_component"]["type"] == "multi_component"


def test_older_saves_without_stages_load_unchanged():
    pipeline = {"01_source_browser": {"source_name": "W3(OH)"}}
    assert fh.merge_stages_into_pipeline(dict(pipeline), None) == pipeline
    fh.validate_stages(None)  # absent key is valid


@pytest.mark.parametrize("bad", ["x", [1], {"fitting": "x"}])
def test_validate_stages_rejects_malformed(bad):
    with pytest.raises(ValueError):
        fh.validate_stages(bad)


def test_session_payload_writes_stages_fitting_when_run_in_isolation():
    """Other suites exec session_store._session_payload ALONE (Any, preferences, st, checkpoint_store only).

    It must therefore use no module-level helper, and must agree with fitting_helpers.stages_from_pipeline.
    """
    import ast
    import copy

    path = Path(__file__).resolve().parents[1] / "hartspec_gui" / "utils" / "session_store.py"
    func = next(n for n in ast.parse(path.read_text(encoding="utf-8")).body
                if isinstance(n, ast.FunctionDef) and n.name == "_session_payload")
    block = _saved_block()
    for pipeline in ({fh.FITTING_STAGE_KEY: {"fit_type": "Multi-component", "multi_component": block}},
                     {fh.FITTING_STAGE_KEY: {"fit_type": "1D Gaussian"}}, {}):
        state = {"session_id": "s1", "pipeline_data": pipeline, "completed_stages": set(), "audit_log": []}
        namespace = {"Any": object, "preferences": lambda s: {},
                     "st": SimpleNamespace(session_state=state),
                     "checkpoint_store": SimpleNamespace(json_safe=copy.deepcopy)}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[func], type_ignores=[])), str(path), "exec"), namespace)
        assert namespace["_session_payload"]()["stages"] == fh.stages_from_pipeline(pipeline)


# ---------------------------------------------------------------------
# Wrapper mechanics, against a stand-in for clc/Spec_comp.py (no astropy / specutils required)
# ---------------------------------------------------------------------
class _Q:
    """Minimal Quantity stand-in: has .value like astropy's."""

    def __init__(self, value):
        self.value = value


_FAKE_SOURCE = """
def Spec_comp(Vlsr, Amp, half_width):
    plt.plot(Vlsr, Amp)
    if RAISE_INSIDE:
        raise RuntimeError("Singular matrix")
    for amp, mean, sd in SEEDS:
        fit_lines(None, MODEL(amplitude=_Q(amp), mean=_Q(mean), stddev=_Q(sd)))
"""


def _fake_spec_comp_module(raise_inside=False):
    """Mimics Spec_comp.py's shape: no imports of its own, three fit_lines calls, plt calls, returns nothing.

    The source is exec()'d into the module so the function's globals ARE the module's, exactly as for the real file.
    """
    mod = ModuleType("fake_Spec_comp")
    seeds = [(10.0, -5.0, 0.9), (5.0, 3.0, 1.2), (2.0, 9.0, 0.7)]
    vars(mod).update(np=np, u=object(), models=object(), Spectrum1D=object(), SEEDS=seeds, RAISE_INSIDE=raise_inside,
                     MODEL=SimpleNamespace, _Q=_Q, fit_lines=lambda spectrum, g_init: g_init)  # "fit" returns its start
    exec(_FAKE_SOURCE, vars(mod))
    return mod, seeds


def test_wrapper_records_each_fit_and_converts_stddev_to_fwhm(spectrum):
    mod, seeds = _fake_spec_comp_module()
    out = fh.run_spec_comp(*spectrum, module=mod)
    assert [p["id"] for p in out] == ["Comp 1", "Comp 2", "Comp 3"]
    for p, (amp, mean, sd) in zip(out, seeds):
        assert_six_sig_figs([p["amplitude"], p["center"], p["fwhm"]], [amp, mean, sd * fh.FWHM_PER_SIGMA])
        assert p["fixed"] is False


def test_wrapper_leaves_module_namespace_untouched(spectrum):
    mod, _ = _fake_spec_comp_module()
    original_fit_lines = mod.fit_lines
    fh.run_spec_comp(*spectrum, module=mod)
    assert "plt" not in vars(mod) and mod.fit_lines is original_fit_lines


def test_wrapper_converts_internal_exception_and_restores_namespace(spectrum):
    mod, _ = _fake_spec_comp_module(raise_inside=True)
    original_fit_lines = mod.fit_lines
    with pytest.raises(fh.DecompositionError, match="Singular matrix"):
        fh.run_spec_comp(*spectrum, module=mod)
    assert "plt" not in vars(mod) and mod.fit_lines is original_fit_lines


@pytest.mark.parametrize("v,y", [
    (np.arange(5.0), np.arange(5.0)),                       # too short
    (np.arange(20.0), np.arange(19.0)),                     # length mismatch
    (np.arange(20.0), np.r_[np.arange(19.0), np.nan]),      # NaN channel
])
def test_wrapper_rejects_bad_input(v, y):
    mod, _ = _fake_spec_comp_module()
    with pytest.raises(fh.DecompositionError):
        fh.run_spec_comp(v, y, module=mod)


# ---------------------------------------------------------------------
# NFR-05: GUI wrapper vs DIRECT execution of the real clc/Spec_comp.py
# ---------------------------------------------------------------------
def _direct_spec_comp(v, y):
    """Run the real Spec_comp.py source in a fresh namespace; return the astropy models it fitted, in order."""
    spec = importlib.util.find_spec("clc.Spec_comp")
    if spec is None or spec.origin is None:
        pytest.skip("clc.Spec_comp is not importable in this environment (clc/ symlink missing).")
    from astropy import units as u
    from astropy.modeling import models
    from specutils import Spectrum1D
    from specutils.fitting import fit_lines

    fitted = []

    def recorder(*args, **kwargs):
        model = fit_lines(*args, **kwargs)
        fitted.append(model)
        return model

    class _Plt:
        def __getattr__(self, name):
            return lambda *a, **k: None

    namespace = {"np": np, "u": u, "models": models, "Spectrum1D": Spectrum1D, "fit_lines": recorder, "plt": _Plt()}
    exec(compile(Path(spec.origin).read_text(), spec.origin, "exec"), namespace)
    namespace["Spec_comp"](v.copy(), y.copy(), 1.0)
    return fitted, u


@pytest.fixture
def real_deps():
    pytest.importorskip("astropy")
    pytest.importorskip("specutils")


def _assert_concordance(v, y):
    """GUI wrapper vs direct Spec_comp.py: components, residual and RMS agree to >= 6 significant figures."""
    fitted, u = _direct_spec_comp(v, y)
    direct_params = np.array([[float(m.amplitude.value), float(m.mean.value),
                               abs(float(m.stddev.value)) * fh.FWHM_PER_SIGMA] for m in fitted])
    direct_model = sum(m(v * u.um).value for m in fitted)  # evaluated by astropy itself, not by fh.gaussian

    gui = fh.run_spec_comp(v, y)
    gui_params = np.array([[p["amplitude"], p["center"], p["fwhm"]] for p in gui])
    assert gui_params.shape == direct_params.shape == (3, 3)
    assert_six_sig_figs(gui_params, direct_params)

    gui_residual = y - fh.composite(v, gui)
    assert_six_sig_figs(gui_residual, y - direct_model, atol=1e-9 * float(np.max(np.abs(y))))
    gui_stats = fh.compute_stats(v, y, gui)
    direct_rms = float(np.sqrt(np.mean((y - direct_model) ** 2)))
    assert gui_stats["rms_residual"] == pytest.approx(direct_rms, rel=SIX_SIG_FIG_RTOL)
    assert math.isfinite(gui_stats["chi2"])


def test_gui_wrapper_matches_direct_spec_comp_to_six_sig_figs(real_deps, spectrum):
    _assert_concordance(*spectrum)


def _reference_spectrum(n):
    """(Vlsr, (LCP + RCP) / 2) of tests/data/ref_spec_0{n}.fits (or /data/fits/) via clc.load_file; skip if absent."""
    name = f"ref_spec_{n:02d}.fits"
    candidates = [Path(__file__).resolve().parent / "data" / name, Path("/data/fits") / name]
    path = next((c for c in candidates if c.exists()), None)
    if path is None:
        pytest.skip(f"{name} not found in tests/data/ or /data/fits/.")
    try:
        from clc.load_file import load_file
    except ImportError:
        pytest.skip("clc.load_file is not importable in this environment (clc/ symlink missing).")
    _header, vlsr, lcp, rcp = load_file(str(path))
    v, y = np.asarray(vlsr, dtype=float), (np.asarray(lcp, dtype=float) + np.asarray(rcp, dtype=float)) / 2.0
    keep = np.isfinite(v) & np.isfinite(y)  # Spec_comp cannot take NaN channels; both runs use the same masked arrays
    return v[keep], y[keep]


@pytest.mark.parametrize("n", [1, 2, 3])
def test_concordance_on_reference_fits_files(real_deps, n):
    """NFR-05 on the real reference spectra (the channel average is used as the decomposition input)."""
    _assert_concordance(*_reference_spectrum(n))
