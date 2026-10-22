# test_bandpass_merge.py — merged Page 3 with the supplied, unmodified correction helper.
"""Headless orchestration/numerical regression tests; no CLC-equivalence or browser claim.

The shared fixture executes the actual session store, bridge, eligibility helper,
Plotly figures, bandpass helper and full page. Only UI/FITS-I/O boundaries are substituted.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import types

import numpy as np
import pytest

from test_file_validation_handoff import app, publish, seed_files

# Keep the imported pytest fixture visible to this module while allowing test parameters named ``app``.
_APP_FIXTURE_REFERENCE = app

STAGE = "03_bandpass_correction"
BASELINE = "04_baseline_editor"


def seed_pairs(app, names=("a.fits", "b.fits", "c.fits", "d.fits")):
    """Seed validated observations; channel markers make each pair's result distinctive."""
    seed_files(app, names)
    for index, name in enumerate(names):
        app.state[f"file_loader_ingest_result::{name}"].spectrum.update({
            "pointing": 0, "position": "ON", "LCP": [index ** 2 + 10, index ** 2 + 20],
            "RCP": [index ** 3 + 30, index ** 3 + 40],
        })
    publish(app)
    app.state["completed_stages"].add("file_loader")
    return names


def fake_headers(app, metadata):
    """Read controlled metadata only, without pretending marker files are real FITS."""
    class Headers(list):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def open_header(path):
        if Path(path).name not in metadata:
            raise OSError("Test-only missing header")
        pointing, position = metadata[Path(path).name]
        return Headers([types.SimpleNamespace(header={"SPPOINT": pointing}), types.SimpleNamespace(header={}),
                        types.SimpleNamespace(header={"POSITION": position})])
    app.fits.open = open_header


def downstream(app):
    """Attach a baseline to the actual current bandpass, plus derived cached results."""
    corrected = app.state["bandpass_corrected_spectrum"]
    flattened = {key: np.asarray(value).tolist() for key, value in corrected.items()}
    for key in (BASELINE, "05_calibration_dashboard", "06_pointing_correction", "07_spectral_fitting",
                "08_export_and_session"):
        app.state["pipeline_data"][key] = {"from_old_pair": True}
        app.state["completed_stages"].add(key)
    app.state.update({"baseline_corrected_spectrum": flattened, "calibrated_spectrum": flattened,
                      "latest_fit": {"from_old_pair": True}, "pointing_cached_result": {"from_old_pair": True},
                      "fit_type": "Polynomial Peak", "baseline_editor_seen_event_ids": ["old"],
                      "theme": "dark", "authentication_status": True})
    app.bridge.write_bridge(app.state["session_id"], {
        "spectrum_fingerprint": app.bridge.spectrum_fingerprint(corrected), "flattened_spectrum": flattened,
        "blocks": [{"start": 0.1, "end": 0.7}], "complete": True,
    })


def save_reload(app):
    """Exercise Step 1's real JSON transition; refill the raw per-file caches as Page 2 does."""
    caches = {key: value for key, value in app.state.items() if key.startswith("file_loader_")}
    app.ui.begin()
    path = app.store.save_session()
    app.store.load_session(path, navigate=False)
    app.state.update({key: value for key, value in caches.items() if key.startswith(
        ("file_loader_ingest_result::", "file_loader_verify_result::")
    )})
    return path


def names_used(app):
    return [entry["filename"] for entry in app.calls[-1][1]]


def test_new_pair_auto_applies_with_entry_pair_api(app):
    seed_pairs(app)
    app.run_bandpass()
    assert len(app.calls) == 1
    assert isinstance(app.calls[0][1], tuple)
    assert names_used(app) == ["a.fits", "b.fits"]
    assert app.state["bandpass_applied_mode"] == "Frequency Switch"
    assert STAGE in app.state["completed_stages"]
    assert app.state["bandpass_display_result"]["filename2"] == "b.fits"


def test_ordinary_rerun_and_theme_change_do_not_recompute(app):
    seed_pairs(app)
    app.run_bandpass()
    sid = app.state["session_id"]
    log_count = len(app.state["audit_log"])
    app.run_bandpass(changes={"theme": "dark"})
    app.run_bandpass()
    assert len(app.calls) == 1
    assert app.state["session_id"] == sid
    assert len(app.state["audit_log"]) == log_count


def test_manual_apply_on_first_render_only_computes_once(app):
    seed_pairs(app)
    app.run_bandpass({"apply_bandpass_correction"})
    assert len(app.calls) == 1


def test_reapply_identical_result_retains_baseline_and_id(app):
    seed_pairs(app)
    app.run_bandpass()
    downstream(app)
    sid = app.state["session_id"]
    old_bridge = app.bridge._bridge_path(sid).read_bytes()
    app.run_bandpass({"apply_bandpass_correction"})
    assert len(app.calls) == 2
    assert app.state["session_id"] == sid
    assert BASELINE in app.state["completed_stages"]
    assert app.bridge._bridge_path(sid).read_bytes() == old_bridge


def test_select_another_pair_clears_derived_state_and_auto_applies(app):
    seed_pairs(app)
    app.run_bandpass()
    downstream(app)
    sid = app.state["session_id"]
    app.run_bandpass(changes={"bandpass_pair_index": 1})
    assert names_used(app) == ["c.fits", "d.fits"]
    assert app.state["session_id"] != sid
    assert STAGE in app.state["completed_stages"]
    assert BASELINE not in app.state["completed_stages"]
    assert "06_pointing_correction" not in app.state["completed_stages"]
    assert "calibrated_spectrum" not in app.state
    assert "latest_fit" not in app.state
    assert "pointing_cached_result" not in app.state
    assert app.state["authentication_status"] is True
    assert app.state["theme"] == "dark"


def test_mode_change_uses_same_pair_and_preserves_explicit_override(app):
    seed_pairs(app)
    app.run_bandpass()
    downstream(app)
    app.run_bandpass(changes={"bandpass_mode": "Position Switch"})
    assert len(app.calls) == 2
    assert app.calls[-1][0] == "Position Switch"
    assert names_used(app) == ["a.fits", "b.fits"]
    assert BASELINE not in app.state["completed_stages"]
    app.run_bandpass()
    assert len(app.calls) == 2
    assert app.state["bandpass_mode"] == "Position Switch"


def test_late_old_bridge_write_cannot_restore_identical_arrays_from_old_pair(app):
    seed_pairs(app)
    # Make different inputs with numerically identical corrected output.
    for target, source in (("c.fits", "a.fits"), ("d.fits", "b.fits")):
        app.state[f"file_loader_ingest_result::{target}"].spectrum = copy.deepcopy(
            app.state[f"file_loader_ingest_result::{source}"].spectrum
        )
    app.run_bandpass()
    downstream(app)
    old_id = app.state["session_id"]
    original_bridge = app.bridge.read_bridge(old_id)
    app.run_bandpass(changes={"bandpass_pair_index": 1})
    app.bridge.write_bridge(old_id, original_bridge)
    result = app.resolver.resolve_spectrum(
        app.state,
        read_bridge=app.bridge.read_bridge,
        fingerprint=app.bridge.spectrum_fingerprint,
    )
    assert app.state["session_id"] != old_id
    assert app.bridge.read_bridge(app.state["session_id"]) is None
    assert result.source_key == "raw"


def test_two_polarisation_panels_use_original_axes_and_shared_shading(app):
    seed_pairs(app)
    app.run_bandpass()
    fig = app.ui.figures[0]
    assert [trace.name for trace in fig.data] == ["Before LCP", "After LCP", "Before RCP", "After RCP"]
    assert [trace.xaxis for trace in fig.data] == ["x", "x", "x2", "x2"]
    for trace in fig.data:
        np.testing.assert_array_equal(trace.x, [0, 1])
    assert len(fig.layout.shapes) == 2
    assert fig.layout.xaxis.range == fig.layout.xaxis2.range
    assert fig.layout.shapes[0].x0 == fig.layout.shapes[1].x0 == 0
    assert fig.layout.shapes[0].x1 == fig.layout.shapes[1].x1 == 1


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_both_axes_and_titles_follow_theme(app, theme):
    seed_pairs(app)
    app.state["theme"] = theme
    app.run_bandpass()
    fig = app.ui.figures[0]
    assert fig.layout.xaxis.color == fig.layout.xaxis2.color
    assert fig.layout.yaxis.color == fig.layout.yaxis2.color
    assert fig.layout.xaxis.tickfont.color == fig.layout.xaxis2.tickfont.color
    assert fig.data[0].line.color == fig.data[1].line.color == "#1F77B4"
    assert fig.data[2].line.color == fig.data[3].line.color == "#FF7F0E"
    assert all(annotation.font.color == fig.layout.font.color for annotation in fig.layout.annotations)


def test_observation_directories_do_not_cross_pair(app):
    seed_pairs(app, ("obs1/a.fits", "obs2/b.fits", "obs2/c.fits"))
    app.run_bandpass()
    assert names_used(app) == ["obs2/b.fits", "obs2/c.fits"]


def test_observation_list_order_is_used(app):
    seed_pairs(app)
    (app.archive / "observation_list.txt").write_text("c.fits\nd.fits\na.fits\nb.fits\n")
    app.run_bandpass()
    assert names_used(app) == ["c.fits", "d.fits"]


def test_live_option_reordering_keeps_same_pair_by_identity(app):
    seed_pairs(app)
    app.run_bandpass()
    sid = app.state["session_id"]
    (app.archive / "observation_list.txt").write_text("c.fits\nd.fits\na.fits\nb.fits\n")
    app.run_bandpass()
    assert len(app.calls) == 1
    assert app.state["bandpass_pair_index"] == 1
    assert app.state["session_id"] == sid
    assert app.state["bandpass_display_result"]["filename1"] == "a.fits"


def test_off_on_pair_is_reordered_on_first_and_suggests_position_switch(app):
    seed_pairs(app, ("off.fits", "on.fits"))
    app.state["file_loader_ingest_result::off.fits"].spectrum["position"] = "OFF"
    app.run_bandpass()
    assert names_used(app) == ["on.fits", "off.fits"]
    assert app.calls[-1][0] == "Position Switch"


@pytest.mark.parametrize("exclusion", ["failed", "unverified", "quarantined", "load_failed"])
def test_excluded_member_drops_whole_pair_without_shifting_next_member(app, exclusion):
    seed_pairs(app)
    if exclusion == "failed":
        app.state["file_loader_verify_result::b.fits"].ok = False
    elif exclusion == "unverified":
        app.state.pop("file_loader_verify_result::b.fits")
    elif exclusion == "quarantined":
        app.state["file_loader_quarantined"] = {"b.fits"}
    else:
        app.state["file_loader_ingest_result::b.fits"].ok = False
    app.run_bandpass()
    assert len(app.calls) == 1
    assert names_used(app) == ["c.fits", "d.fits"]
    assert any("not substituted" in message for message in app.ui.messages)


def test_unknown_sp_point_does_not_guess_a_new_pair_in_same_directory(app):
    seed_pairs(app)
    app.state["file_loader_ingest_result::b.fits"].spectrum.pop("pointing")
    fake_headers(app, {})
    app.run_bandpass()
    assert app.calls == []
    assert STAGE not in app.state["completed_stages"]
    assert any("Cannot determine SPPOINT" in message for message in app.ui.messages)


def test_unknown_metadata_in_one_observation_does_not_block_another(app):
    seed_pairs(app, ("obs1/a.fits", "obs1/b.fits", "obs2/c.fits", "obs2/d.fits"))
    app.state["file_loader_ingest_result::obs1/a.fits"].spectrum.pop("pointing")
    fake_headers(app, {})
    app.run_bandpass()
    assert names_used(app) == ["obs2/c.fits", "obs2/d.fits"]


def test_metadata_header_fallback_preserves_older_loader_compatibility(app):
    seed_pairs(app, ("a.fits", "b.fits"))
    for name in ("a.fits", "b.fits"):
        spectrum = app.state[f"file_loader_ingest_result::{name}"].spectrum
        spectrum.pop("pointing")
        spectrum.pop("position")
    fake_headers(app, {"a.fits": (0, "ON"), "b.fits": (0, "OFF")})
    app.run_bandpass()
    assert app.calls[-1][0] == "Position Switch"


def test_unknown_position_requires_explicit_apply_and_does_not_silently_default(app):
    seed_pairs(app, ("a.fits", "b.fits"))
    for name in ("a.fits", "b.fits"):
        app.state[f"file_loader_ingest_result::{name}"].spectrum["position"] = ""
    fake_headers(app, {})
    app.run_bandpass()
    assert app.calls == []
    assert any("POSITION metadata is unavailable" in message for message in app.ui.messages)
    app.run_bandpass({"apply_bandpass_correction"})
    assert len(app.calls) == 1


def test_explicit_radio_change_can_apply_unknown_metadata(app):
    seed_pairs(app, ("a.fits", "b.fits"))
    for name in ("a.fits", "b.fits"):
        app.state[f"file_loader_ingest_result::{name}"].spectrum["position"] = "UNKNOWN"
    app.run_bandpass()
    assert not app.calls
    app.run_bandpass(changes={"bandpass_mode": "Position Switch"})
    assert app.calls[-1][0] == "Position Switch"


def test_no_unverified_loaded_spectra_fallback(app):
    app.state["completed_stages"].update({"01_source_browser", "file_loader"})
    app.state["loaded_spectra"] = [{"Vlsr": [1], "LCP": [2], "RCP": [3], "pointing": 0}] * 2
    app.run_bandpass()
    assert not app.calls
    assert STAGE not in app.state["completed_stages"]


def test_saved_second_pair_and_manual_mode_restore_after_real_load(app):
    seed_pairs(app)
    app.run_bandpass()
    app.run_bandpass(changes={"bandpass_pair_index": 1})
    app.run_bandpass(changes={"bandpass_mode": "Position Switch"})
    expected = copy.deepcopy(app.state["bandpass_corrected_spectrum"])
    downstream(app)
    sid = app.state["session_id"]
    old_bridge = app.bridge._bridge_path(sid).read_bytes()
    save_reload(app)
    app.calls.clear()
    app.run_bandpass()
    assert app.state["bandpass_pair_index"] == 1
    assert app.calls[-1][0] == "Position Switch"
    assert names_used(app) == ["c.fits", "d.fits"]
    assert app.state["session_id"] == sid
    assert BASELINE in app.state["completed_stages"]
    assert app.bridge._bridge_path(sid).read_bytes() == old_bridge
    for key in expected:
        np.testing.assert_array_equal(app.state["bandpass_corrected_spectrum"][key], expected[key])
    assert any("replayed from saved session" in event["message"] for event in app.state["audit_log"])


def test_jc_filename_record_restores_correct_pair_without_overriding_saved_mode(app):
    seed_pairs(app)
    app.state["pipeline_data"][STAGE] = {"mode": "Position Switch", "filename1": "c.fits", "filename2": "d.fits"}
    app.state["completed_stages"].add(STAGE)
    app.run_bandpass()
    assert names_used(app) == ["c.fits", "d.fits"]
    assert app.calls[-1][0] == "Position Switch"


def test_mode_only_legacy_save_can_replay_single_pair(app):
    seed_pairs(app, ("a.fits", "b.fits"))
    app.state["pipeline_data"][STAGE] = {"mode": "Position Switch"}
    app.state["completed_stages"].add(STAGE)
    app.run_bandpass()
    assert len(app.calls) == 1
    assert app.calls[-1][0] == "Position Switch"


def test_mode_only_legacy_save_does_not_guess_among_multiple_pairs(app):
    seed_pairs(app)
    app.state["pipeline_data"][STAGE] = {"mode": "Position Switch"}
    app.state["completed_stages"].add(STAGE)
    app.run_bandpass()
    assert not app.calls
    assert STAGE not in app.state["completed_stages"]
    assert app.state["bandpass_require_apply"]
    app.run_bandpass({"apply_bandpass_correction"}, changes={"bandpass_pair_index": 1})
    assert names_used(app) == ["c.fits", "d.fits"]


def test_missing_saved_pair_requires_confirmation_not_silent_substitution(app):
    seed_pairs(app)
    app.state["pipeline_data"][STAGE] = {"mode": "Position Switch", "filename1": "x.fits", "filename2": "y.fits"}
    app.state["completed_stages"].add(STAGE)
    app.run_bandpass()
    assert not app.calls
    assert "unavailable or ambiguous" in app.state["bandpass_selection_warning"]
    app.run_bandpass({"apply_bandpass_correction"})
    assert names_used(app) == ["a.fits", "b.fits"]


def test_bad_saved_mode_does_not_crash_radio_or_auto_run(app):
    seed_pairs(app)
    app.state["pipeline_data"][STAGE] = {"mode": "not-a-mode", "filename1": "a.fits", "filename2": "b.fits"}
    app.state["completed_stages"].add(STAGE)
    app.run_bandpass()
    assert not app.calls
    assert app.state["bandpass_mode"] in app.adapter.MODE_OPTIONS
    assert "invalid" in app.state["bandpass_selection_warning"]


def test_summary_is_json_safe_and_retains_pair_provenance(app):
    seed_pairs(app)
    app.run_bandpass()
    app.ui.begin()
    summary = json.loads(app.store.save_session().read_text())["pipeline_data"][STAGE]
    assert summary["filename1"] == "a.fits"
    assert summary["filename2"] == "b.fits"
    assert len(summary["pair_paths"]) == 2
    assert len(summary["input_fingerprint"]) == 64
    assert len(summary["corrected_fingerprint"]) == 64
    assert not any(key in summary for key in ("raw_spec1", "corrected", "LCP", "RCP", "Vlsr"))


def test_mutated_loaded_inputs_with_same_names_cannot_reuse_correction(app):
    seed_pairs(app)
    app.run_bandpass()
    downstream(app)
    sid = app.state["session_id"]
    app.state["file_loader_ingest_result::a.fits"].spectrum["LCP"][0] += 12
    app.run_bandpass()
    assert len(app.calls) == 2
    assert app.state["session_id"] != sid
    assert BASELINE not in app.state["completed_stages"]


@pytest.mark.parametrize("key,bad", [
    ("LCP", [np.nan, 2]), ("RCP", [np.inf, 3]), ("Vlsr", [0, np.nan]),
    ("LCP", []), ("Vlsr", 0), ("RCP", [[1, 2]]), ("LCP", ["bad", 2]), ("LCP", [1, 2, 3]),
])
def test_bad_input_arrays_leave_no_completed_output(app, key, bad):
    seed_pairs(app)
    app.run_bandpass()
    downstream(app)
    app.state["file_loader_ingest_result::a.fits"].spectrum[key] = bad
    app.run_bandpass()
    assert STAGE not in app.state["completed_stages"]
    assert "bandpass_corrected_spectrum" not in app.state
    assert "calibrated_spectrum" not in app.state
    assert app.state["bandpass_error"]


def test_no_common_frequency_channels_reports_helper_error_and_does_not_retry_on_rerun(app):
    seed_pairs(app, ("a.fits", "b.fits"))
    app.state["file_loader_ingest_result::b.fits"].spectrum["Vlsr"] = [10, 11]
    app.run_bandpass()
    assert len(app.calls) == 1
    assert "no common velocity channels" in app.state["bandpass_error"]
    app.run_bandpass()
    assert len(app.calls) == 1
    app.run_bandpass({"apply_bandpass_correction"})
    assert len(app.calls) == 2


def test_failed_auto_apply_can_recover_after_mode_change(app):
    seed_pairs(app, ("a.fits", "b.fits"))
    app.state["file_loader_ingest_result::b.fits"].spectrum["Vlsr"] = [10, 11]
    app.run_bandpass()
    assert STAGE not in app.state["completed_stages"]
    app.run_bandpass(changes={"bandpass_mode": "Position Switch"})
    assert STAGE in app.state["completed_stages"]
    assert "bandpass_error" not in app.state
    assert not app.state["bandpass_display_result"]["common_velocity_range_kms"]


@pytest.mark.parametrize("mode", ["Frequency Switch", "Position Switch"])
def test_page_output_exactly_matches_uploaded_helper_without_modifying_inputs(app, mode):
    seed_pairs(app, ("a.fits", "b.fits"))
    before = copy.deepcopy([app.state[f"file_loader_ingest_result::{name}"].spectrum for name in ("a.fits", "b.fits")])
    app.state["pipeline_data"][STAGE] = {"mode": mode, "filename1": "a.fits", "filename2": "b.fits"}
    app.state["completed_stages"].add(STAGE)
    app.run_bandpass()
    pair = app.calls[-1][1]
    reference = app.adapter.build_bandpass_result(mode, pair)["corrected"]
    for key in ("Vlsr", "LCP", "RCP"):
        np.testing.assert_array_equal(app.state["bandpass_corrected_spectrum"][key], reference[key])
    for expected, entry in zip(before, pair):
        assert entry["spectrum"] == expected


def test_stale_corrected_cache_is_recomputed_even_when_both_references_share_mutated_array(app):
    seed_pairs(app)
    app.run_bandpass()
    app.state["bandpass_corrected_spectrum"]["LCP"][0] = 12345
    app.run_bandpass()
    assert len(app.calls) == 2
    assert app.state["bandpass_corrected_spectrum"]["LCP"][0] != 12345


def test_orphaned_calibration_without_saved_bandpass_is_not_preserved(app):
    seed_pairs(app)
    app.state["calibrated_spectrum"] = {"Vlsr": [0, 1], "LCP": [99, 99], "RCP": [99, 99]}
    app.state["completed_stages"].add("05_calibration_dashboard")
    app.run_bandpass()
    assert "calibrated_spectrum" not in app.state
    assert "05_calibration_dashboard" not in app.state["completed_stages"]


def test_continue_navigates_only_after_successful_output(app):
    seed_pairs(app)
    app.run_bandpass({"continue_to_baseline"})
    assert app.ui.navigation == "pages/04_Baseline_Editor.py"


def test_failed_output_does_not_allow_continue(app):
    seed_pairs(app)
    app.state["file_loader_ingest_result::a.fits"].spectrum["LCP"] = [np.nan, 2]
    app.run_bandpass({"continue_to_baseline"})
    assert app.ui.navigation is None


def test_malformed_helper_result_cannot_partially_commit(app, monkeypatch):
    seed_pairs(app)
    app.run_bandpass()
    downstream(app)

    def bad_result(mode, pair):
        return {"mode": mode, "corrected": pair[0]["spectrum"], "raw_spec1": pair[0]["spectrum"],
                "raw_spec2": {"Vlsr": []}, "filename1": pair[0]["filename"], "filename2": pair[1]["filename"]}
    monkeypatch.setattr(app.adapter, "build_bandpass_result", bad_result)
    app.run_bandpass({"apply_bandpass_correction"})
    assert STAGE not in app.state["completed_stages"]
    assert "bandpass_corrected_spectrum" not in app.state
    assert "calibrated_spectrum" not in app.state


def test_wrong_pair_returned_by_helper_is_rejected(app, monkeypatch):
    seed_pairs(app)
    original = app.adapter.build_bandpass_result

    def wrong_pair(mode, pair):
        result = original(mode, pair)
        result["filename1"] = "wrong.fits"
        return result
    monkeypatch.setattr(app.adapter, "build_bandpass_result", wrong_pair)
    app.run_bandpass()
    assert "different pair or mode" in app.state["bandpass_error"]
    assert STAGE not in app.state["completed_stages"]


def test_upstream_guard_removes_stale_results(app):
    seed_pairs(app)
    app.run_bandpass()
    downstream(app)
    app.state["completed_stages"].discard("file_loader")
    app.run_bandpass()
    assert STAGE not in app.state["completed_stages"]
    assert "calibrated_spectrum" not in app.state
    assert not app.ui.figures


def test_text_encoding_is_clean(app):
    seed_pairs(app)
    app.run_bandpass()
    text = " ".join(app.ui.messages)
    assert not any(broken in text for broken in ("ΓÇ", "Γå", "┬", "�"))


@pytest.mark.parametrize("removed", [("bandpass_pair_index",), ("bandpass_mode",),
                                     ("bandpass_pair_index", "bandpass_mode")])
def test_return_after_widget_cleanup_restores_saved_second_pair_without_losing_baseline(app, removed):
    seed_pairs(app)
    app.run_bandpass()
    app.run_bandpass(changes={"bandpass_pair_index": 1})
    app.run_bandpass(changes={"bandpass_mode": "Position Switch"})
    downstream(app)
    sid = app.state["session_id"]
    count = len(app.calls)
    app.ui.begin()
    for key in removed:
        app.state.pop(key)
    app.run_bandpass()
    assert len(app.calls) == count
    assert app.state["bandpass_pair_index"] == 1
    assert app.state["bandpass_mode"] == "Position Switch"
    assert app.state["session_id"] == sid
    assert BASELINE in app.state["completed_stages"]
    assert not app.state["bandpass_replay_pending"]


@pytest.mark.parametrize("bad_index", [-1, 99, True, "oops", None])
def test_invalid_stored_pair_index_is_repaired_before_widget_mounts(app, bad_index):
    seed_pairs(app)
    app.run_bandpass()
    app.ui.begin()
    app.state["bandpass_pair_index"] = bad_index
    app.run_bandpass()
    assert app.state["bandpass_pair_index"] == 0
    assert len(app.calls) == 1


def test_non_object_bridge_is_ignored_and_isolated_instead_of_crashing(app):
    seed_pairs(app)
    sid = app.state["session_id"]
    app.bridge.SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    app.bridge._bridge_path(sid).write_text('["not a bridge object"]')
    app.run_bandpass()
    assert STAGE in app.state["completed_stages"]
    assert app.state["session_id"] != sid
    assert app.bridge._bridge_path(sid).read_text() == '["not a bridge object"]'


def test_guard_then_valid_load_initializes_controls_correctly(app):
    app.run_bandpass()
    seed_pairs(app)
    app.run_bandpass()
    assert STAGE in app.state["completed_stages"]
    assert len(app.calls) == 1


@pytest.mark.parametrize("mode,channels", [("Frequency Switch", 3), ("Position Switch", 4)])
def test_shifted_velocity_grids_keep_uploaded_helpers_exact_channel_selection(app, mode, channels):
    seed_pairs(app, ("a.fits", "b.fits"))
    for i, name in enumerate(("a.fits", "b.fits")):
        app.state[f"file_loader_ingest_result::{name}"].spectrum.update({
            "Vlsr": np.arange(i, 4 + i, dtype=float), "LCP": np.array([10, 11, 13, 12]) + i * 2,
            "RCP": np.array([20, 21, 24, 23]) + i * 3,
        })
    app.state["pipeline_data"][STAGE] = {"mode": mode}
    app.state["completed_stages"].add(STAGE)
    app.run_bandpass()
    assert len(app.state["bandpass_corrected_spectrum"]["Vlsr"]) == channels
    ref = app.adapter.build_bandpass_result(mode, app.calls[-1][1])
    for key in ("Vlsr", "LCP", "RCP"):
        np.testing.assert_array_equal(app.state["bandpass_corrected_spectrum"][key], ref["corrected"][key])
    assert app.state["bandpass_display_result"]["common_velocity_range_kms"] == [1.0, 3.0]


def test_pair_change_preserves_saved_session_bridge_and_raw_files(app):
    seed_pairs(app)
    app.run_bandpass()
    downstream(app)
    app.ui.begin()
    saved = app.store.save_session()
    bridge = app.bridge._bridge_path(app.state["session_id"])
    watched = [saved, bridge] + list(app.archive.glob("*.fits"))
    original = {path: path.read_bytes() for path in watched}
    app.run_bandpass(changes={"bandpass_pair_index": 1})
    assert {path: path.read_bytes() for path in watched} == original


def test_saved_pair_matches_after_dropdown_order_changes_on_load(app):
    seed_pairs(app)
    app.run_bandpass()
    app.run_bandpass(changes={"bandpass_pair_index": 1})
    sid = app.state["session_id"]
    save_reload(app)
    (app.archive / "observation_list.txt").write_text("c.fits\nd.fits\na.fits\nb.fits\n")
    app.calls.clear()
    app.run_bandpass()
    assert app.state["bandpass_pair_index"] == 0
    assert names_used(app) == ["c.fits", "d.fits"]
    assert app.state["session_id"] == sid


def test_quarantined_member_moved_off_disk_keeps_its_pairing_slot(app):
    seed_pairs(app)
    fake_headers(app, {"b.fits": (0, "ON")})
    app.page._quarantine_file("b.fits")
    assert not (app.archive / "b.fits").exists()
    app.run_bandpass()
    assert not any("Cannot determine SPPOINT" in m for m in app.ui.messages)
    assert names_used(app) == ["c.fits", "d.fits"]
    assert any("not substituted" in m for m in app.ui.messages)
