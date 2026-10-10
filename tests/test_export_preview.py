# test_export_preview.py — FR-18: CLC-aligned RMS/peak preview and Page 08 integration.
from __future__ import annotations

import ast
import copy
import sys
import types
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "hartspec_gui"
sys.path.insert(0, str(APP_ROOT))

from utils import export_preview_logic as logic  # noqa: E402


@pytest.fixture
def spectrum():
    """Baseline-flattened spectrum with enough channels for CLC Savitzky-Golay smoothing."""
    v = np.linspace(-5.0, 5.0, 21)
    lcp = 0.08 * np.sin(v * 1.7) + 1.5 * np.exp(-0.5 * (v / 0.35) ** 2)
    r = 0.06 * np.cos(v * 1.3) + 1.1 * np.exp(-0.5 * ((v - 0.1) / 0.4) ** 2)
    return {"Vlsr": v, "LCP": lcp, "RCP": r}


@pytest.fixture
def blocks():
    return [{"block": 1, "start": -4.0, "end": -2.5}, {"block": 2, "start": 2.5, "end": 4.0}]


def _pipeline(blocks):
    return {
        "04_baseline_editor": {
            "selection_semantics": "flat_baseline_fit_regions_v2",
            "blocks": copy.deepcopy(blocks),
            "fit_provider": "clc",
            "complete": True,
        },
        "05_calibration_dashboard": {
            "pss": {"lcp_window_mean": 2.0, "rcp_window_mean": 3.0},
        },
        "06_pointing_correction": {
            "input_source": "pointing scan: obs · scan 1",
            "correction_factor": 1.2,
        },
    }


def _state(spectrum, blocks):
    return {
        "session_id": "preview-session",
        "pipeline_data": _pipeline(blocks),
        "bandpass_corrected_spectrum": {key: np.asarray(value).copy() for key, value in spectrum.items()},
    }


def _fingerprint(spec):
    return "fingerprint-current"


def _bridge(spectrum, *, fingerprint="fingerprint-current"):
    return {"flattened_spectrum": spectrum, "spectrum_fingerprint": fingerprint}


def _extract_clc_function(path: Path, name: str, namespace: dict):
    """Compile one supplied CLC function without importing its legacy module dependencies."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    node = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == name)
    module = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    exec(compile(module, str(path), "exec"), namespace)
    return namespace[name]


def _clc_reference_functions():
    """Load only the two numerical functions used as references in these tests."""
    import logging
    from scipy.signal import savgol_filter

    stats_fn = _extract_clc_function(
        APP_ROOT / "clc" / "Stats_manager.py", "Add_Remove_feature", {"np": np, "logging": logging}
    )
    pols_fn = _extract_clc_function(
        APP_ROOT / "clc" / "Pols.py", "add_pols", {"np": np, "savgol_filter": savgol_filter}
    )
    return stats_fn, pols_fn


def test_clc_add_remove_feature_matches_supplied_stats_manager(spectrum, blocks):
    clc_add_remove, _pols = _clc_reference_functions()
    v = spectrum["Vlsr"]
    mask, _mask2, vll, vrl = logic.build_clc_masks(v, blocks)
    mask3 = np.ones(v.size, dtype=int)
    mask3[(v >= vll) & (v <= vrl)] = 0

    ours_rms, ours_noise, ours_mask = logic.clc_add_remove_feature(
        spectrum["LCP"], v, mask.copy(), mask3.copy(), vll, vrl
    )
    clc_rms, clc_noise, clc_mask = clc_add_remove(
        spectrum["LCP"].copy(), v.copy(), mask.copy(), mask3.copy(), vll, vrl
    )
    assert ours_rms == pytest.approx(float(clc_rms), rel=0, abs=1e-12)
    np.testing.assert_array_equal(ours_mask, clc_mask)
    np.testing.assert_allclose(ours_noise.filled(np.nan), clc_noise.filled(np.nan), equal_nan=True)


def test_stokes_i_matches_supplied_pols_add_pols(spectrum, blocks):
    _stats, clc_add_pols = _clc_reference_functions()
    result = logic.build_clc_export_preview(
        spectrum, blocks, pss_lcp_jy_per_k=2.0, pss_rcp_jy_per_k=3.0, pointing_factor=1.2
    )
    reference = {"LCP": result.lcp_jy.copy(), "RCP": result.rcp_jy.copy()}
    clc_add_pols(reference)
    np.testing.assert_allclose(result.stokes_i_jy, reference["I"], rtol=0, atol=1e-12)


def test_final_rms_and_peak_match_supplied_rms_stn_numeric_result(spectrum, blocks):
    clc_add_remove, _pols = _clc_reference_functions()

    class _Axis:
        def axhline(self, *args, **kwargs):
            return None

    class _Plot:
        def figure(self, *args, **kwargs):
            return None

        def subplot(self, *args, **kwargs):
            return _Axis()

        def __getattr__(self, _name):
            return lambda *args, **kwargs: None

    rms_stn = _extract_clc_function(
        APP_ROOT / "clc" / "Stats_manager.py",
        "rms_stn",
        {"np": np, "plt": _Plot(), "St": types.SimpleNamespace(Add_Remove_feature=clc_add_remove)},
    )
    result = logic.build_clc_export_preview(
        spectrum, blocks, pss_lcp_jy_per_k=2.0, pss_rcp_jy_per_k=3.0, pointing_factor=1.2
    )
    initial_mask, _mask2, vll, vrl = logic.build_clc_masks(spectrum["Vlsr"], blocks)
    mask3 = np.ones(result.vlsr.size, dtype=int)
    mask3[(result.vlsr >= vll) & (result.vlsr <= vrl)] = 0
    _rms_lcp, _noise, lcp_mask = clc_add_remove(
        spectrum["LCP"].copy(), result.vlsr.copy(), initial_mask.copy(), mask3.copy(), vll, vrl
    )
    clc_rms, clc_peak = rms_stn(
        result.stokes_i_jy.copy(), result.vlsr.copy(), lcp_mask.copy(), mask3.copy(),
        vll, vrl, 0.0, "fixture", "fixture", "fixture",
    )
    assert result.rms_jy == pytest.approx(float(clc_rms), rel=0, abs=1e-12)
    assert result.peak_jy == pytest.approx(float(clc_peak), rel=0, abs=1e-12)


def test_per_polarization_pss_and_pointing_match_hartspec_order(spectrum, blocks):
    result = logic.build_clc_export_preview(
        spectrum, blocks, pss_lcp_jy_per_k=2.0, pss_rcp_jy_per_k=3.0, pointing_factor=1.2
    )
    np.testing.assert_allclose(result.lcp_jy, spectrum["LCP"] * 1.2 * 2.0)
    np.testing.assert_allclose(result.rcp_jy, spectrum["RCP"] * 1.2 * 3.0)


def test_peak_is_maximum_stokes_i_inside_mask3_envelope(spectrum, blocks):
    result = logic.build_clc_export_preview(
        spectrum, blocks, pss_lcp_jy_per_k=2.0, pss_rcp_jy_per_k=3.0, pointing_factor=1.2
    )
    inside = (result.vlsr >= result.vll) & (result.vlsr <= result.vrl)
    expected = float(np.max(result.stokes_i_jy[inside]))
    assert result.peak_jy == pytest.approx(expected)
    peak_indices = np.where(inside & np.isclose(result.stokes_i_jy, expected))[0]
    assert result.peak_velocity_kms == pytest.approx(float(result.vlsr[peak_indices[0]]))


def test_mask_envelope_is_first_start_to_last_end(spectrum, blocks):
    result = logic.build_clc_export_preview(
        spectrum, blocks, pss_lcp_jy_per_k=2.0, pss_rcp_jy_per_k=3.0, pointing_factor=1.2
    )
    assert result.vll == -4.0
    assert result.vrl == 4.0


def test_preview_does_not_mutate_spectrum_or_blocks(spectrum, blocks):
    before = {key: np.asarray(value).copy() for key, value in spectrum.items()}
    before_blocks = copy.deepcopy(blocks)
    logic.build_clc_export_preview(
        spectrum, blocks, pss_lcp_jy_per_k=2.0, pss_rcp_jy_per_k=3.0, pointing_factor=1.2
    )
    for key in before:
        np.testing.assert_array_equal(spectrum[key], before[key])
    assert blocks == before_blocks


@pytest.mark.parametrize("field", ["Vlsr", "LCP", "RCP"])
def test_missing_spectrum_field_is_rejected(spectrum, blocks, field):
    bad = dict(spectrum)
    bad.pop(field)
    with pytest.raises(logic.ExportPreviewUnavailable, match="missing"):
        logic.build_clc_export_preview(
            bad, blocks, pss_lcp_jy_per_k=2.0, pss_rcp_jy_per_k=3.0, pointing_factor=1.2
        )


@pytest.mark.parametrize(
    "kwargs,label",
    [
        ({"pss_lcp_jy_per_k": None, "pss_rcp_jy_per_k": 3.0, "pointing_factor": 1.2}, "LCP PSS"),
        ({"pss_lcp_jy_per_k": 2.0, "pss_rcp_jy_per_k": 0, "pointing_factor": 1.2}, "RCP PSS"),
        ({"pss_lcp_jy_per_k": 2.0, "pss_rcp_jy_per_k": 3.0, "pointing_factor": float("nan")}, "Pointing"),
    ],
)
def test_invalid_calibration_scalar_is_rejected(spectrum, blocks, kwargs, label):
    with pytest.raises(logic.ExportPreviewUnavailable, match=label):
        logic.build_clc_export_preview(spectrum, blocks, **kwargs)


def test_short_spectrum_is_rejected_before_savgol(blocks):
    short = {"Vlsr": np.arange(5.0), "LCP": np.ones(5), "RCP": np.ones(5)}
    with pytest.raises(logic.ExportPreviewUnavailable, match="seven channels"):
        logic.build_clc_export_preview(
            short, [{"start": 0.0, "end": 4.0}],
            pss_lcp_jy_per_k=2.0, pss_rcp_jy_per_k=3.0, pointing_factor=1.2,
        )


def test_descending_velocity_grid_is_rejected(spectrum, blocks):
    bad = {key: np.asarray(value)[::-1] for key, value in spectrum.items()}
    with pytest.raises(logic.ExportPreviewUnavailable, match="ascending"):
        logic.build_clc_export_preview(
            bad, blocks, pss_lcp_jy_per_k=2.0, pss_rcp_jy_per_k=3.0, pointing_factor=1.2
        )


def test_pipeline_preview_uses_committed_page_4_to_6_inputs(spectrum, blocks):
    state = _state(spectrum, blocks)
    result = logic.preview_from_pipeline(
        state, read_bridge=lambda _sid: _bridge(spectrum), fingerprint=_fingerprint
    )
    assert result.available
    assert result.stats.rms_jy > 0


def test_pipeline_preview_rejects_legacy_baseline_semantics(spectrum, blocks):
    state = _state(spectrum, blocks)
    state["pipeline_data"]["04_baseline_editor"].pop("selection_semantics")
    result = logic.preview_from_pipeline(
        state, read_bridge=lambda _sid: _bridge(spectrum), fingerprint=_fingerprint
    )
    assert not result.available
    assert "legacy" in result.reason


def test_pipeline_preview_rejects_mock_pointing(spectrum, blocks):
    state = _state(spectrum, blocks)
    state["pipeline_data"]["06_pointing_correction"]["input_source"] = "MOCK_SCAN_PEAKS"
    result = logic.preview_from_pipeline(
        state, read_bridge=lambda _sid: _bridge(spectrum), fingerprint=_fingerprint
    )
    assert not result.available
    assert "real Page 06" in result.reason


def test_pipeline_preview_rejects_stale_baseline_bridge(spectrum, blocks):
    state = _state(spectrum, blocks)
    result = logic.preview_from_pipeline(
        state, read_bridge=lambda _sid: _bridge(spectrum, fingerprint="old"), fingerprint=_fingerprint
    )
    assert not result.available
    assert "no longer matches" in result.reason


def test_pipeline_preview_does_not_require_runtime_page_08_arrays(spectrum, blocks):
    state = _state(spectrum, blocks)
    state["calibrated_spectrum"] = {"garbage": True}
    state["latest_fit"] = {"fit_curve": [999]}
    result = logic.preview_from_pipeline(
        state, read_bridge=lambda _sid: _bridge(spectrum), fingerprint=_fingerprint
    )
    assert result.available


def test_page08_imports_and_renders_new_preview_once():
    page = (APP_ROOT / "pages" / "08_Export_and_Session.py").read_text(encoding="utf-8")
    tree = ast.parse(page)
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name) and node.func.value.id == "export_preview_ui"
        and node.func.attr == "render_export_preview"
    ]
    assert len(calls) == 1
    assert "export_preview_logic.preview_from_pipeline" in page


def test_page08_existing_observation_log_still_renders_once():
    page = (APP_ROOT / "pages" / "08_Export_and_Session.py").read_text(encoding="utf-8")
    assert page.count("render_observation_log(st.session_state") == 1


def test_page08_existing_csv_and_pdf_export_builders_still_present():
    page = (APP_ROOT / "pages" / "08_Export_and_Session.py").read_text(encoding="utf-8")
    assert "export_logic.build_export_csv(" in page
    assert "export_logic.build_graphs_pdf(" in page
    assert '"Export CSV"' in page
    assert '"Export graphs (PDF)"' in page


def test_new_helpers_do_not_write_session_or_export_files():
    forbidden_attrs = {"checkpoint_session", "save_session", "write_text", "write_bytes"}
    for name in ("export_preview_logic.py", "export_preview_ui.py"):
        path = APP_ROOT / "utils" / name
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name):
                assert node.func.id != "open"
            if isinstance(node.func, ast.Attribute):
                assert node.func.attr not in forbidden_attrs


def test_test_module_text_reads_are_explicit_utf8():
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr == "read_text":
            assert any(keyword.arg == "encoding" and getattr(keyword.value, "value", None) == "utf-8"
                       for keyword in node.keywords)
