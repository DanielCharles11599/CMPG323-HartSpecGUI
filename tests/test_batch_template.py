# test_batch_template.py — FR-21: saved session compatibility and frozen reference parameters.
"""No FITS/Streamlit required: sessions are representative manual FR-19 JSON saves."""

from __future__ import annotations

import copy
import json

import pytest

from utils import batch_queue, batch_template


def reference() -> dict:
    return {
        "session_id": "abc12345", "completed_stages": [
            "01_source_browser", "file_loader", "03_bandpass_correction", "04_baseline_editor",
            "05_calibration_dashboard", "06_pointing_correction", "07_spectral_fitting",
        ],
        "pipeline_data": {
            "01_source_browser": {"source_name": "W3(OH)", "frequency_mhz": 1420.405},
            "03_bandpass_correction": {"mode": "Frequency Switch"},
            "04_baseline_editor": {"complete": True, "fit_provider": "clc",
                                   "blocks": [{"block": 1, "start": -12.4, "end": -9.8}],
                                   "selected_orders": {"LCP": 3, "RCP": 4}},
            "05_calibration_dashboard": {"atmospheric": {"atcor": 98.1}},
            "06_pointing_correction": {"correction_factor": 80.0,
                                       "peak_velocity_kms": -4.2, "half_width_channels": 5,
                                       "pointing_check": {"accepted": True, "overridden": True}},
            "07_spectral_fitting": {"fit_type_requested": "1D Gaussian", "parameters": [{"value": 999}]},
        },
    }


def save(tmp_path, payload):
    root = tmp_path / "sessions"
    root.mkdir(exist_ok=True)
    path = root / "abc12345.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return root, path


def load(root, path):
    return batch_template.load_template(path, root, source="W3(OH)", frequency=1420.405)


def test_pin_whitelisted_processing_settings_not_results_or_approval(tmp_path):
    source = reference()
    root, path = save(tmp_path, source)
    frozen = load(root, path)
    assert frozen["settings"] == {
        "bandpass_mode": "Frequency Switch", "baseline_blocks": [{"start": -12.4, "end": -9.8}],
        "polynomial_orders": {"LCP": 3, "RCP": 4}, "fit_type": "1D Gaussian",
        "pointing_peak_velocity_kms": -4.2, "pointing_half_width_channels": 5,
    }
    assert "correction_factor" not in json.dumps(frozen)
    assert "accepted" not in json.dumps(frozen)
    before = copy.deepcopy(frozen)
    source["pipeline_data"]["05_calibration_dashboard"]["atmospheric"]["atcor"] = 999
    path.write_text(json.dumps(source), encoding="utf-8")
    assert before == frozen  # saved template is immutable by value
    assert batch_template.signature(frozen) == batch_template.signature(copy.deepcopy(frozen))


@pytest.mark.parametrize("stage,change,expected", [
    ("01_source_browser", {"source_name": "W49"}, "different source"),
    ("01_source_browser", {"frequency_mhz": 6668.0}, "different observing frequency"),
    ("03_bandpass_correction", {"mode": "unknown"}, "bandpass mode"),
    ("04_baseline_editor", {"fit_provider": "mock"}, "CLC-backed"),
    ("04_baseline_editor", {"selected_orders": {"LCP": 2, "RCP": 4}}, "order of 3"),
    ("04_baseline_editor", {"blocks": [{"start": 1.0, "end": 0.0}]}, "inverted"),
    ("07_spectral_fitting", {"fit_type_requested": "2D Gaussian"}, "not validated"),
    ("06_pointing_correction", {"half_width_channels": 0}, "half-width"),
])
def test_incompatible_reference_is_rejected(tmp_path, stage, change, expected):
    payload = reference()
    payload["pipeline_data"][stage].update(change)
    root, path = save(tmp_path, payload)
    with pytest.raises(batch_queue.BatchQueueError, match=expected):
        load(root, path)


def test_reference_requires_stage_commit_not_only_data(tmp_path):
    source = reference()
    source["completed_stages"].remove("04_baseline_editor")
    root, path = save(tmp_path, source)
    with pytest.raises(batch_queue.BatchQueueError, match="after completing"):
        load(root, path)


def test_bad_file_or_path_is_rejected(tmp_path):
    root, path = save(tmp_path, reference())
    outside = tmp_path / "elsewhere.json"
    outside.write_text(path.read_text())
    with pytest.raises(batch_queue.BatchQueueError, match="manual session JSON"):
        load(root, outside)
    (root / "abc12345.baseline_editor.json").write_text(path.read_text())
    with pytest.raises(batch_queue.BatchQueueError, match="manual session JSON"):
        load(root, root / "abc12345.baseline_editor.json")
    path.write_text("not-json")
    with pytest.raises(batch_queue.BatchQueueError, match="invalid"):
        load(root, path)
