# test_polarization_logic.py — FR-09: formulas, SG validation, non-mutation and CLC parity.
"""Numerical tests need NumPy/SciPy; the full-module import test also needs Astropy.

The source-reference fixture compiles the actual ave_pols/add_pols function
bodies from the deployed Pols.py, avoiding unrelated Astropy/pyplot imports.
That is a source-level regression test, not an end-to-end CLI execution.
"""
from __future__ import annotations

import ast
import copy
import json
import sys
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest
from scipy.signal import savgol_filter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hartspec_gui"))
from utils import polarization_logic as logic  # noqa: E402


@pytest.fixture
def fr09_spectrum():
    """Deterministic unequal polarizations, including negative and noisy channels."""
    x = np.linspace(-20.0, 20.0, 1024)
    rng = np.random.default_rng(908)
    return {
        "Vlsr": x,
        "LCP": 8 * np.exp(-0.5 * ((x + 4) / 0.7) ** 2) + rng.normal(0, 0.3, x.size),
        "RCP": 5 * np.exp(-0.5 * ((x + 3.8) / 0.9) ** 2) + rng.normal(0, 0.2, x.size),
        "object": "test source",
    }


@pytest.fixture
def fr09_pols_reference(monkeypatch):
    """Execute unchanged scientific function bodies, not a copied implementation."""
    source = ROOT / "hartspec_gui" / "clc" / "Pols.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name in ("ave_pols", "add_pols")]
    assert len(functions) == 2, "The CLC polarization contract changed."
    module = ModuleType("fr09_source_reference")
    module.__dict__.update(np=np, savgol_filter=savgol_filter)
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), "exec"), module.__dict__)
    monkeypatch.setattr(logic, "_load_pols", lambda: module)
    return module


@pytest.mark.parametrize("seed", [0, 1, 17, 92])
def test_default_sg_matches_supplied_clc_to_better_than_six_figures(fr09_pols_reference, seed):
    """Test the entire channel array, including the SG edge handling."""
    rng = np.random.default_rng(seed)
    spectrum = {"Vlsr": np.arange(1024.0), "LCP": rng.normal(size=1024), "RCP": rng.normal(size=1024)}
    expected = fr09_pols_reference.add_pols(fr09_pols_reference.ave_pols(copy.deepcopy(spectrum)))
    result = logic.build_polarization_overlay(spectrum, smoothing_enabled=True)
    np.testing.assert_allclose(result.mean, expected["ave_pol"], rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(result.stokes_i, expected["I"], rtol=1e-12, atol=1e-12)


def test_off_is_exact_mean_and_sum(fr09_spectrum, fr09_pols_reference):
    """Off must not secretly invoke add_pols' always-on filter."""
    result = logic.build_polarization_overlay(fr09_spectrum)
    total = fr09_spectrum["LCP"] + fr09_spectrum["RCP"]
    np.testing.assert_array_equal(result.mean, total / 2)
    np.testing.assert_array_equal(result.stokes_i, total)
    assert not result.smoothing_enabled


@pytest.mark.parametrize("window", [5, 9, 11, 31, 1023])
def test_custom_window_is_one_scipy_pass(fr09_spectrum, fr09_pols_reference, window):
    """Custom windows start from the sum, not the already-filtered CLC output."""
    result = logic.build_polarization_overlay(fr09_spectrum, smoothing_enabled=True, window_length=window)
    expected = savgol_filter(fr09_spectrum["LCP"] + fr09_spectrum["RCP"], window, 3, mode="interp")
    np.testing.assert_array_equal(result.stokes_i, expected)
    np.testing.assert_array_equal(result.lcp, fr09_spectrum["LCP"])
    np.testing.assert_array_equal(result.rcp, fr09_spectrum["RCP"])
    np.testing.assert_array_equal(result.mean, (result.lcp + result.rcp) / 2)


def test_default_calls_real_functions_once_and_does_not_double_smooth(fr09_spectrum, fr09_pols_reference, monkeypatch):
    """Spy on the supplied functions and require exactly one call to each."""
    calls = []
    original_mean, original_i = fr09_pols_reference.ave_pols, fr09_pols_reference.add_pols

    def mean(spec):
        calls.append("mean")
        return original_mean(spec)

    def stokes_i(spec):
        calls.append("I")
        return original_i(spec)

    monkeypatch.setattr(fr09_pols_reference, "ave_pols", mean)
    monkeypatch.setattr(fr09_pols_reference, "add_pols", stokes_i)
    result = logic.build_polarization_overlay(fr09_spectrum, smoothing_enabled=True)
    assert calls == ["mean", "I"]
    twice = savgol_filter(result.stokes_i, 7, 3)
    assert not np.allclose(result.stokes_i, twice)


@pytest.mark.parametrize("enabled,window", [(False, 7), (True, 7), (True, 9)])
def test_inputs_and_previous_results_are_not_mutated(fr09_spectrum, fr09_pols_reference, enabled, window):
    """Readonly pipeline arrays and unrelated metadata must survive every path."""
    before = copy.deepcopy(fr09_spectrum)
    for key in logic.ARRAY_KEYS:
        fr09_spectrum[key].flags.writeable = False
    result = logic.build_polarization_overlay(fr09_spectrum, smoothing_enabled=enabled, window_length=window)
    for key in logic.ARRAY_KEYS:
        np.testing.assert_array_equal(fr09_spectrum[key], before[key])
    assert set(fr09_spectrum) == set(before)
    result.lcp[0] = 1234
    result.mean[0] = -1234
    np.testing.assert_array_equal(fr09_spectrum["LCP"], before["LCP"])
    assert fr09_spectrum["object"] == before["object"]


@pytest.mark.parametrize("size", [1, 2, 3, 4])
def test_short_spectrum_is_viewable_with_smoothing_off(fr09_pols_reference, size):
    """A short input must not trigger CLC's seven-channel filter."""
    spectrum = {key: np.arange(size, dtype=float) for key in logic.ARRAY_KEYS}
    result = logic.build_polarization_overlay(spectrum)
    assert len(result.stokes_i) == size
    with pytest.raises(ValueError, match="exceeds"):
        logic.build_polarization_overlay(spectrum, smoothing_enabled=True)


@pytest.mark.parametrize("window", [0, -7, 1, 3, 4, 6, 8, 7.0, True, "7", None])
def test_invalid_windows_rejected(fr09_spectrum, window):
    """Validation happens before CLC import or calculation."""
    with pytest.raises(ValueError, match="window"):
        logic.build_polarization_overlay(fr09_spectrum, smoothing_enabled=True, window_length=window)


def test_oversized_window_rejected(fr09_spectrum):
    with pytest.raises(ValueError, match="exceeds"):
        logic.build_polarization_overlay(fr09_spectrum, smoothing_enabled=True, window_length=1025)


def test_boolean_toggle_is_not_string_coercion(fr09_spectrum):
    with pytest.raises(ValueError, match="boolean"):
        logic.build_polarization_overlay(fr09_spectrum, smoothing_enabled="false")


@pytest.mark.parametrize("bad", [[], [[1, 2]], [1, np.nan], [np.inf, 1], [1j, 2j], ["bad"],
                                 np.ma.array([1., 2.], mask=[False, True])])
def test_bad_arrays_rejected(bad):
    with pytest.raises(ValueError):
        logic.validated_spectrum({"Vlsr": [1, 2], "LCP": bad, "RCP": [1, 2]})


@pytest.mark.parametrize("spectrum", [None, [], {}, {"LCP": [1]}, {"Vlsr": [1], "LCP": [1, 2], "RCP": [1]}])
def test_missing_or_misaligned_inputs_rejected(spectrum):
    with pytest.raises(ValueError):
        logic.validated_spectrum(spectrum)


def test_channel_order_and_velocity_are_never_resampled(fr09_spectrum, fr09_pols_reference):
    for key in logic.ARRAY_KEYS:
        fr09_spectrum[key] = fr09_spectrum[key][::-1]
    result = logic.build_polarization_overlay(fr09_spectrum, smoothing_enabled=True)
    np.testing.assert_array_equal(result.vlsr, fr09_spectrum["Vlsr"])


def test_overflow_is_reported(fr09_pols_reference):
    spectrum = {"Vlsr": np.arange(7.), "LCP": np.full(7, 1.7e308), "RCP": np.full(7, 1.7e308)}
    with pytest.raises(logic.PolarizationIntegrationError, match="calculation failed"):
        logic.build_polarization_overlay(spectrum)


@pytest.mark.parametrize("bad", [[1], [np.nan] * 1024])
def test_bad_clc_output_is_not_plotted(fr09_spectrum, fr09_pols_reference, monkeypatch, bad):
    monkeypatch.setattr(fr09_pols_reference, "ave_pols", lambda spec: {"ave_pol": bad})
    with pytest.raises(logic.PolarizationIntegrationError, match="invalid"):
        logic.build_polarization_overlay(fr09_spectrum)


@pytest.mark.parametrize("key", logic.ARRAY_KEYS)
def test_source_identity_includes_each_array(fr09_spectrum, key):
    before = logic.spectrum_identity(fr09_spectrum)
    fr09_spectrum[key][0] += 0.00001
    assert logic.spectrum_identity(fr09_spectrum) != before


def test_identity_is_independent_of_list_vs_array(fr09_spectrum):
    arrays = {key: fr09_spectrum[key] for key in logic.ARRAY_KEYS}
    lists = {key: value.tolist() for key, value in arrays.items()}
    assert logic.spectrum_identity(arrays) == logic.spectrum_identity(lists)


def test_settings_json_round_trip_and_no_spectral_arrays():
    record = logic.display_record(
        {"smoothing_enabled": True, "window_length": 11}, source_key="baseline", fingerprint="abc", intensity_unit="K",
    )
    loaded = json.loads(json.dumps(record, allow_nan=False))
    settings, notes = logic.restore_display_settings(loaded, 1024)
    assert settings == {"smoothing_enabled": True, "window_length": 11}
    assert not notes
    assert loaded["display_only"] is True
    assert loaded["smoothing_target"] == "Stokes I"
    assert not any(key in loaded for key in ("LCP", "RCP", "Vlsr", "I", "complete"))


@pytest.mark.parametrize("size,window", [(1024, 7), (6, 5), (5, 5), (4, 5), (1, 5)])
def test_default_controls_fit_channel_count(size, window):
    settings, notes = logic.restore_display_settings(None, size)
    assert settings == {"smoothing_enabled": False, "window_length": window}
    assert not notes


@pytest.mark.parametrize("bad", ["bad", {"schema_version": 999}, {"schema_version": 1, "polyorder": 2},
                                 {"schema_version": 1, "polyorder": 3, "window_length": 6},
                                 {"schema_version": 1, "polyorder": 3, "smoothing_enabled": "false"}])
def test_bad_saved_preferences_are_reported_and_not_trusted(bad):
    settings, notes = logic.restore_display_settings(bad, 1024)
    assert notes
    assert not settings["smoothing_enabled"]
    assert settings["window_length"] == 7


def test_restored_window_too_long_is_not_silently_adjusted():
    record = {"schema_version": 1, "polyorder": 3, "window_length": 11, "smoothing_enabled": True}
    settings, notes = logic.restore_display_settings(record, 7)
    assert settings == {"smoothing_enabled": True, "window_length": 7}
    assert "exceeds" in notes[0]
    settings, notes = logic.restore_display_settings(record, 4)
    assert not settings["smoothing_enabled"]
    assert "turned off" in notes[0]


@pytest.mark.parametrize(
    "source,expected",
    [(None, "requires"), ("x = 1", "must expose"),
     ("import nonexistent_fr09_dependency", "Cannot import"),
     ("def broken(:", "Cannot import")],
)
def test_loader_reports_missing_or_broken_clc(tmp_path, monkeypatch, source, expected):
    logic._load_pols.cache_clear()
    monkeypatch.setattr(logic, "CLC_DIR", tmp_path)
    if source is not None:
        (tmp_path / "Pols.py").write_text(source)
    try:
        with pytest.raises(logic.PolarizationIntegrationError, match=expected):
            logic._load_pols()
    finally:
        logic._load_pols.cache_clear()


def test_live_pols_module_import_and_numerical_parity(fr09_spectrum):
    """Separate full-module integration check; never substitute the AST reference."""
    pytest.importorskip("astropy", reason="Full CLC import requires the existing Astropy dependency")
    logic._load_pols.cache_clear()
    try:
        pols = logic._load_pols()
        expected = pols.add_pols(pols.ave_pols(copy.deepcopy(fr09_spectrum)))
        result = logic.build_polarization_overlay(fr09_spectrum, smoothing_enabled=True)
        np.testing.assert_allclose(result.stokes_i, expected["I"], rtol=1e-12, atol=1e-12)
        np.testing.assert_allclose(result.mean, expected["ave_pol"], rtol=1e-12, atol=1e-12)
    finally:
        logic._load_pols.cache_clear()
