# test_feature_detection.py — FR-08 regression tests for CLC-aligned feature detection.
from __future__ import annotations

import ast
import logging
import sys
import types
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "hartspec_gui"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

# The numerical/figure tests do not launch Streamlit. Provide the minimal module
# surface required by utils.styles and feature_detection_ui at import time.
if "streamlit" not in sys.modules:
    streamlit_stub = types.ModuleType("streamlit")
    streamlit_stub.session_state = {}
    sys.modules["streamlit"] = streamlit_stub

from utils.feature_detection_logic import (  # noqa: E402
    FeatureDetectionError,
    _add_remove_feature,
    detect_features,
    event_rows,
)
from utils.feature_detection_ui import build_feature_figure  # noqa: E402


def _extract_clc_add_remove_feature():
    """Load only the supplied CLC function body, avoiding its plotting/import side effects."""
    path = APP / "clc" / "Stats_manager.py"
    source = ast.parse(path.read_text(encoding="utf-8"))
    fn = next(node for node in source.body if isinstance(node, ast.FunctionDef) and node.name == "Add_Remove_feature")
    module = ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[]))
    namespace = {"np": np, "logging": logging}
    exec(compile(module, str(path), "exec"), namespace)
    return namespace["Add_Remove_feature"]


@pytest.fixture
def spectrum():
    vlsr = np.arange(0.0, 20.0, 1.0)
    lcp = np.full(20, 0.1)
    rcp = np.full(20, 0.1)
    lcp[8:10] = 10.0
    rcp[11:13] = 12.0
    return {"Vlsr": vlsr, "LCP": lcp, "RCP": rcp}


@pytest.fixture
def blocks():
    return [{"block": 1, "start": 1.0, "end": 18.0}]


def test_clc_mask3_contract_from_blocks_file():
    text = (APP / "clc" / "Blocks.py").read_text(encoding="utf-8")
    assert "mask3 = np.ones(len(sp['Vlsr']))" in text
    assert "sp['Vlsr']>=vll" in text and "sp['Vlsr']<=vrl" in text


def test_logic_matches_supplied_clc_add_remove_feature(spectrum, blocks):
    clc = _extract_clc_add_remove_feature()
    vlsr = spectrum["Vlsr"]
    mask = np.ones(vlsr.size, dtype=int)
    mask[(vlsr >= 1.0) & (vlsr <= 18.0)] = 0
    mask3 = np.ones(vlsr.size, dtype=int)
    mask3[(vlsr >= 1.0) & (vlsr <= 18.0)] = 0

    for pol in ("LCP", "RCP"):
        expected_rms, _noise, expected_mask = clc(
            spectrum[pol].copy(), vlsr.copy(), mask.copy(), mask3.copy(), 1.0, 18.0
        )
        actual_rms, actual_mask = _add_remove_feature(
            spectrum[pol].copy(), vlsr.copy(), mask.copy(), mask3.copy(), 1.0, 18.0
        )
        assert actual_rms == pytest.approx(float(expected_rms), rel=1e-12, abs=1e-12)
        np.testing.assert_array_equal(actual_mask, expected_mask)


def test_detect_features_does_not_mutate_inputs(spectrum, blocks):
    before = {key: value.copy() for key, value in spectrum.items()}
    original_blocks = [dict(row) for row in blocks]
    detect_features(spectrum, blocks)
    for key in spectrum:
        np.testing.assert_array_equal(spectrum[key], before[key])
    assert blocks == original_blocks


def test_detects_appeared_channels_by_polarization(spectrum, blocks):
    result = detect_features(spectrum, blocks)
    assert result.detections["LCP"].appeared_indices.size > 0
    assert result.detections["RCP"].appeared_indices.size > 0
    assert all(event.change == "Appeared" for event in result.events)
    assert {event.polarization for event in result.events} == {"LCP", "RCP"}


def test_contiguous_changes_are_grouped(spectrum, blocks):
    rows = event_rows(detect_features(spectrum, blocks))
    lcp = [row for row in rows if row["Polarization"] == "LCP"]
    assert len(lcp) == 1
    assert lcp[0]["Channels"] >= 1
    assert lcp[0]["Start Vlsr (km/s)"] <= lcp[0]["End Vlsr (km/s)"]


def test_no_changes_is_valid_result():
    spectrum = {
        "Vlsr": np.arange(0.0, 10.0),
        "LCP": np.full(10, 0.2),
        "RCP": np.full(10, 0.2),
    }
    result = detect_features(spectrum, [{"start": 1.0, "end": 8.0}])
    assert result.events == ()


@pytest.mark.parametrize("missing", ["Vlsr", "LCP", "RCP"])
def test_missing_arrays_raise(missing, spectrum, blocks):
    bad = dict(spectrum)
    bad.pop(missing)
    with pytest.raises(FeatureDetectionError):
        detect_features(bad, blocks)


def test_inconsistent_lengths_raise(spectrum, blocks):
    bad = dict(spectrum)
    bad["RCP"] = bad["RCP"][:-1]
    with pytest.raises(FeatureDetectionError, match="same number of channels"):
        detect_features(bad, blocks)


def test_descending_velocity_rejected(spectrum, blocks):
    bad = {key: value[::-1] for key, value in spectrum.items()}
    with pytest.raises(FeatureDetectionError, match="ascending velocity grid"):
        detect_features(bad, blocks)


def test_nonfinite_values_rejected(spectrum, blocks):
    bad = {key: value.copy() for key, value in spectrum.items()}
    bad["LCP"][3] = np.nan
    with pytest.raises(FeatureDetectionError, match="NaN or infinite"):
        detect_features(bad, blocks)


def test_empty_blocks_rejected(spectrum):
    with pytest.raises(FeatureDetectionError, match="at least one valid baseline block"):
        detect_features(spectrum, [])


def test_mask3_matches_first_to_last_block_envelope(spectrum):
    blocks = [{"start": 1.0, "end": 3.0}, {"start": 15.0, "end": 18.0}]
    result = detect_features(spectrum, blocks)
    expected = np.ones(20, dtype=int)
    expected[(spectrum["Vlsr"] >= 1.0) & (spectrum["Vlsr"] <= 18.0)] = 0
    np.testing.assert_array_equal(result.mask3, expected)


def test_initial_masks_include_only_selected_flat_blocks(spectrum):
    blocks = [{"start": 1.0, "end": 3.0}, {"start": 15.0, "end": 18.0}]
    result = detect_features(spectrum, blocks)
    expected = np.ones(20, dtype=int)
    expected[(spectrum["Vlsr"] >= 1.0) & (spectrum["Vlsr"] <= 3.0)] = 0
    expected[(spectrum["Vlsr"] >= 15.0) & (spectrum["Vlsr"] <= 18.0)] = 0
    np.testing.assert_array_equal(result.detections["LCP"].initial_mask, expected)


def test_final_rms_is_finite(spectrum, blocks):
    result = detect_features(spectrum, blocks)
    assert np.isfinite(result.detections["LCP"].final_rms)
    assert np.isfinite(result.detections["RCP"].final_rms)


def test_figure_keeps_locked_polarization_colors(spectrum, blocks, monkeypatch):
    import utils.feature_detection_ui as ui
    monkeypatch.setattr(ui.styles, "get_theme_name", lambda: "light")
    result = detect_features(spectrum, blocks)
    theme = {
        "bg-panel": "white", "text-body": "black", "text-muted": "gray",
        "border-subtle": "gray", "accent": "#587BBD",
    }
    figure = build_feature_figure(result, theme)
    assert figure.data[0].line.color == "#1F77B4"
    assert figure.data[1].line.color == "#FF7F0E"


def test_figure_marks_detected_channels(spectrum, blocks, monkeypatch):
    import utils.feature_detection_ui as ui
    monkeypatch.setattr(ui.styles, "get_theme_name", lambda: "light")
    result = detect_features(spectrum, blocks)
    theme = {
        "bg-panel": "white", "text-body": "black", "text-muted": "gray",
        "border-subtle": "gray", "accent": "#587BBD",
    }
    figure = build_feature_figure(result, theme)
    marker_traces = [trace for trace in figure.data[2:] if trace.mode == "markers"]
    assert marker_traces
    assert sum(len(trace.x) for trace in marker_traces) == sum(
        result.detections[pol].appeared_indices.size + result.detections[pol].disappeared_indices.size
        for pol in ("LCP", "RCP")
    )


def test_page04_only_adds_feature_detection_import_and_panel_hook():
    page = (APP / "pages" / "04_Baseline_Editor.py").read_text(encoding="utf-8")
    assert "from utils.feature_detection_ui import render_feature_detection" in page
    assert "Refresh feature detection from editor" in page
    assert "render_feature_detection(" in page
    assert "pages/05_Calibration_Dashboard.py" in page


def test_feature_helpers_do_not_import_streamlit_in_logic():
    text = (APP / "utils" / "feature_detection_logic.py").read_text(encoding="utf-8")
    assert "import streamlit" not in text
    assert "Stats_manager" in text


def test_logic_does_not_write_or_checkpoint():
    tree = ast.parse((APP / "utils" / "feature_detection_logic.py").read_text(encoding="utf-8"))
    names = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "write_text" not in names
    assert "checkpoint_session" not in names


def test_page04_does_not_modify_clc_files():
    # Guard the intended conflict footprint: Page 04 consumes helpers; CLC files stay separate.
    page = (APP / "pages" / "04_Baseline_Editor.py").read_text(encoding="utf-8")
    assert "Stats_manager" not in page
    assert "Blocks" not in page


def test_event_rows_include_detected_amplitude(spectrum, blocks):
    rows = event_rows(detect_features(spectrum, blocks))
    assert rows
    assert all(isinstance(row["Amplitude"], float) for row in rows)


def test_result_arrays_are_copies(spectrum, blocks):
    result = detect_features(spectrum, blocks)
    result.channels["LCP"][0] = 999.0
    assert spectrum["LCP"][0] != 999.0


def test_feature_result_has_same_velocity_length(spectrum, blocks):
    result = detect_features(spectrum, blocks)
    assert len(result.vlsr) == len(spectrum["Vlsr"])


def test_disappeared_grouping_helper_is_supported():
    from utils.feature_detection_logic import _events_for_change
    v = np.arange(5.0)
    a = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
    events = _events_for_change("LCP", "Disappeared", np.array([1, 2]), v, a)
    assert len(events) == 1
    assert events[0].change == "Disappeared"
    assert events[0].channel_count == 2


def test_clc_threshold_literals_are_preserved():
    source = (APP / "utils" / "feature_detection_logic.py").read_text(encoding="utf-8")
    assert "2.5 * initial_rms" in source
    assert "1.2 * initial_rms" in source
