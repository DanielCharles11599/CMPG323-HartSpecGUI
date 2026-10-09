# test_session_checkpoints.py — FR-19/NFR-10: persistence, recovery, Dash and regression boundaries.
"""Real checkpoint/store/bridge/page logic with isolated files and substituted browser/CLC I/O.

The existing app fixture supplies Streamlit's UI facade and artificial FITS data.
No original-CLC equivalence or end-to-end browser claim is made by this suite.
Text reads and fixture writes explicitly use UTF-8, independent of the Windows code page.
"""
from __future__ import annotations

import ast
import copy
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from test_file_validation_handoff import APP_ROOT, StopRun, app  # noqa: F401 -- pytest fixture
from test_bandpass_merge import seed_pairs


@pytest.fixture
def browser(app):
    """Enable the real URL/checkpoint integration on the existing isolated app fixture."""
    app.ui.query_params = {}
    app.store.init_session_state()
    return app


def records(app):
    """Paths of published parameter envelopes, excluding sidecars and temporary files."""
    token = app.state["checkpoint_token"]
    directory = app.store.checkpoint_store.token_directory(app.store.SESSIONS_DIR, token)
    return sorted(path for path in directory.glob("*.json") if ".baseline_editor." not in path.name)


def ready(app):
    """Run the real merged bandpass page on the verified pair fixtures."""
    seed_pairs(app)
    app.run_bandpass()
    assert app.state.get("checkpoint_path")
    return Path(app.state["checkpoint_path"])


def baseline(app, *, start=0.0, end=1.0, complete=True):
    """Construct an explicitly artificial baseline fixture; no polynomial fit is claimed."""
    corrected = app.state["bandpass_corrected_spectrum"]
    spectrum = {key: np.asarray(value).tolist() for key, value in corrected.items()}
    rows = [{"block": 1, "start": start, "end": end}]
    flattened = {key: list(value) for key, value in spectrum.items()}
    flattened["LCP"] = [float(value) + start for value in flattened["LCP"]]
    return {
        "spectrum": spectrum,
        "spectrum_fingerprint": app.bridge.spectrum_fingerprint(corrected),
        "bandpass_mode": app.state["bandpass_mode"],
        "blocks": rows, "selection_mode": "Manual", "manual_orders": {"LCP": 3, "RCP": 4},
        "selected_orders": {"LCP": 3, "RCP": 4} if complete else None,
        "fit_result": {"provider": "clc", "blocks": rows, "panels": []} if complete else None,
        "flattened_spectrum": flattened if complete else None, "complete": complete,
        "events": [{"id": "baseline-event-1", "ts": "12:00:00", "message": "Fixture flat regions set"}],
        "checkpoint_token": app.state["checkpoint_token"],
    }


def attach_baseline(app):
    """Exercise a real bridge mutation and its Dash-side checkpoint hook."""
    state = baseline(app)
    return app.bridge.update_bridge(app.state["session_id"], lambda target: target.update(state))


def test_empty_browser_has_private_token_but_no_autosave(browser):
    assert len(browser.state["checkpoint_token"]) == 32
    assert browser.ui.query_params[browser.store.RECOVERY_PARAM] == browser.state["checkpoint_token"]
    assert records(browser) == []
    assert browser.store.checkpoint_session() is None


def test_completed_bandpass_writes_actual_pair_mode_and_audit(browser):
    path = ready(browser)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["pipeline_data"]["03_bandpass_correction"]["filename1"] == "a.fits"
    assert data["pipeline_data"]["03_bandpass_correction"]["mode"] == "Frequency Switch"
    assert any("Bandpass correction" in entry["message"] for entry in data["audit_log"])
    assert "bandpass_corrected_spectrum" not in data
    assert "loaded_spectra" not in data
    assert "loaded_spectrum" not in data


def test_ordinary_rerun_and_theme_do_not_append_or_touch_checkpoint(browser):
    path = ready(browser)
    before = (path.read_bytes(), path.stat().st_mtime_ns, records(browser))
    browser.run_bandpass()
    browser.state["theme"] = "dark"
    browser.run_bandpass()
    assert (path.read_bytes(), path.stat().st_mtime_ns, records(browser)) == before


def test_unconfirmed_source_controls_are_not_checkpoint_parameters(browser):
    path = ready(browser)
    browser.state.update(source_browser_source_name="Unconfirmed other source",
                         source_browser_filename_search="draft", source_browser_fits_dir="draft-folder")
    browser.store.checkpoint_session("A browse-only rerun")
    assert records(browser) == [path]
    assert json.loads(path.read_text(encoding="utf-8"))["pipeline_data"]["01_source_browser"]["source_name"] == "A"


def test_applied_mapping_saved_but_unsubmitted_form_widgets_excluded(browser):
    ready(browser)
    browser.state.update(file_loader_manual_mapping_global={"Vlsr": "HDU0:SPVLSR"},
                         file_loader_mapping_mode="Manual", manual_map_global_Vlsr="UNSUBMITTED")
    path = browser.store.checkpoint_session("Mapping applied")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["ui_state"]["file_loader_manual_mapping_global"] == {"Vlsr": "HDU0:SPVLSR"}
    assert "UNSUBMITTED" not in path.read_text(encoding="utf-8")


def test_checkpoint_files_are_append_only(browser):
    old = ready(browser)
    original = old.read_bytes()
    browser.store.log_event("Second committed action")
    new = browser.store.checkpoint_session("Another commit")
    assert new != old
    assert old.read_bytes() == original
    assert len(records(browser)) == 2
    assert json.loads(new.read_text(encoding="utf-8"))["checkpoint"]["sequence"] == 2


def test_manual_saves_remain_immutable_and_list_excludes_checkpoints(browser):
    ready(browser)
    first = browser.store.save_session()
    original = first.read_bytes()
    browser.store.log_event("Later manual-save action")
    second = browser.store.save_session()
    assert first != second
    assert first.read_bytes() == original
    assert set(browser.store.list_sessions()) == {first, second}


def test_dash_commits_baseline_without_streamlit_rerun(browser):
    ready(browser)
    written = attach_baseline(browser)
    assert written.get("checkpoint_saved_at")
    assert "04_baseline_editor" not in browser.state["pipeline_data"]
    latest = browser.store.checkpoint_store.latest(browser.store.SESSIONS_DIR, browser.state["checkpoint_token"])
    saved = latest.payload["pipeline_data"]["04_baseline_editor"]
    assert saved["blocks"] == [{"block": 1, "start": 0.0, "end": 1.0}]
    assert saved["selected_orders"] == {"LCP": 3, "RCP": 4}
    assert saved["complete"] is True
    assert latest.bridge["flattened_spectrum"] == baseline(browser)["flattened_spectrum"]
    assert len(latest.payload["baseline_event_ids"]) == 1
    assert "checkpoint_token" not in latest.bridge


def test_dash_repeated_identical_mutation_deduplicates_writes(browser):
    ready(browser)
    attach_baseline(browser)
    before = records(browser)
    browser.bridge.update_bridge(browser.state["session_id"], lambda target: None)
    assert records(browser) == before


def test_global_sync_absorbs_dash_then_can_save_without_conflict(browser):
    ready(browser)
    attach_baseline(browser)
    browser.store.begin_page(7)
    assert browser.state["pipeline_data"]["04_baseline_editor"]["complete"]
    assert browser.state["baseline_corrected_spectrum"]
    count = len(records(browser))
    browser.store.checkpoint_session("Unchanged later page")
    assert "checkpoint_error" not in browser.state
    assert len(records(browser)) == count
    assert [e["message"] for e in browser.state["audit_log"]].count("Fixture flat regions set") == 1


def test_baseline_edit_removes_calibration_fit_export_but_not_pointing(browser):
    ready(browser)
    attach_baseline(browser)
    browser.store.begin_page(5)
    for key in ("05_calibration_dashboard", "06_pointing_correction", "07_spectral_fitting", "08_export_and_session"):
        browser.state["pipeline_data"][key] = {"previous": True}
        browser.state["completed_stages"].add(key)
    browser.state.update(calibrated_spectrum={"old": True}, latest_fit={"old": True}, export_cache={"old": True})
    browser.store.checkpoint_session("Downstream results committed")
    changed = baseline(browser, start=0.2, complete=False)
    changed["events"].append({"id": "change-2", "ts": "12:00:01", "message": "Flat region moved"})
    browser.bridge.update_bridge(browser.state["session_id"], lambda target: target.update(changed))
    browser.store.begin_page(8)
    for key in ("05_calibration_dashboard", "07_spectral_fitting", "08_export_and_session"):
        assert key not in browser.state["pipeline_data"]
        assert key not in browser.state["completed_stages"]
    assert "06_pointing_correction" in browser.state["completed_stages"]
    assert "calibrated_spectrum" not in browser.state
    assert "latest_fit" not in browser.state
    assert "export_cache" not in browser.state
    assert "baseline_corrected_spectrum" not in browser.state


def test_frozen_baseline_is_not_modified_by_later_edit(browser):
    ready(browser)
    attach_baseline(browser)
    core = browser.store.checkpoint_store
    old = core.latest(browser.store.SESSIONS_DIR, browser.state["checkpoint_token"])
    sidecar = old.path.parent / old.payload["baseline_snapshot"]["file"]
    before = (old.path.read_bytes(), sidecar.read_bytes())
    browser.bridge.update_bridge(
        browser.state["session_id"], lambda target: target.update(baseline(browser, start=0.2))
    )
    assert (old.path.read_bytes(), sidecar.read_bytes()) == before
    assert core.read_record(old.path).bridge["blocks"][0]["start"] == 0.0


def test_saved_snapshot_waits_for_revalidation_then_restores_exact_baseline(browser):
    ready(browser)
    attach_baseline(browser)
    browser.store.begin_page(4)
    old = browser.store.checkpoint_store.latest(browser.store.SESSIONS_DIR, browser.state["checkpoint_token"])
    old_id, old_token = browser.state["session_id"], browser.state["checkpoint_token"]
    before = old.path.read_bytes()
    caches = {key: value for key, value in browser.state.items() if key.startswith(
        ("file_loader_ingest_result::", "file_loader_verify_result::")
    )}
    browser.ui.begin()
    browser.ui.begin()
    browser.store.recover_checkpoint(old.path, navigate=False)
    new_id = browser.state["session_id"]
    assert new_id != old_id
    assert browser.state["checkpoint_token"] != old_token
    assert "loaded_spectra" not in browser.state
    assert "bandpass_corrected_spectrum" not in browser.state
    assert browser.bridge.read_bridge(new_id) is None
    assert browser.state["checkpoint_pending_bridge"]["bridge"]["blocks"] == old.bridge["blocks"]
    browser.state.update(caches)
    browser.page._sync_validated_handoff(browser.page._get_target_filenames())
    browser.run_bandpass()
    assert "checkpoint_error" not in browser.state
    assert browser.state["session_id"] == new_id
    assert browser.bridge.read_bridge(new_id)["blocks"] == old.bridge["blocks"]
    assert browser.state["baseline_corrected_spectrum"] == old.bridge["flattened_spectrum"]
    assert not browser.state.get("checkpoint_rebuild_required")
    assert old.path.read_bytes() == before


def test_delayed_old_dash_cannot_change_recovered_checkpoint(browser):
    ready(browser)
    attach_baseline(browser)
    old_id = browser.state["session_id"]
    old_bridge = browser.bridge.read_bridge(old_id)
    old = browser.store.checkpoint_store.latest(browser.store.SESSIONS_DIR, browser.state["checkpoint_token"])
    browser.ui.begin()
    browser.store.recover_checkpoint(old.path, navigate=False)
    current_token = browser.state["checkpoint_token"]
    current = browser.store.checkpoint_store.latest(browser.store.SESSIONS_DIR, current_token)
    before = current.path.read_bytes()
    old_bridge["blocks"] = [{"start": 0.4, "end": 1.0}]
    browser.bridge.update_bridge(old_id, lambda target: target.update(old_bridge))
    after = browser.store.checkpoint_store.latest(browser.store.SESSIONS_DIR, current_token)
    assert after.path == current.path
    assert after.path.read_bytes() == before


def test_refresh_url_recovers_its_own_stream_and_routes_to_loader(browser):
    path = ready(browser)
    token = browser.state["checkpoint_token"]
    browser.ui.begin()
    browser.state.clear()
    browser.ui.query_params = {browser.store.RECOVERY_PARAM: token}
    with pytest.raises(StopRun):
        browser.store.init_session_state()
    assert browser.state["pipeline_data"]["03_bandpass_correction"]["filename1"] == "a.fits"
    assert browser.state["checkpoint_token"] != token
    assert browser.state["checkpoint_notice"].startswith("Checkpoint recovered")
    assert path.exists()


def test_new_browser_without_token_does_not_pick_global_latest(browser):
    ready(browser)
    browser.ui.begin()
    browser.state.clear()
    browser.ui.query_params = {}
    browser.store.init_session_state()
    assert browser.state["pipeline_data"] == {}
    assert records(browser) == []


@pytest.mark.parametrize("token", ["../secret", "x", "A" * 32, "/tmp/sessions", "a" * 31, "b" * 33])
def test_invalid_url_identifier_does_not_read_an_arbitrary_path(browser, token):
    browser.ui.begin()
    browser.state.clear()
    browser.ui.query_params = {browser.store.RECOVERY_PARAM: token}
    browser.store.init_session_state()
    assert browser.state["pipeline_data"] == {}
    assert "Invalid recovery" in browser.state["checkpoint_notice"]
    assert len(browser.state["checkpoint_token"]) == 32


def test_navigation_reemits_recovery_token_after_query_is_cleared(browser):
    ready(browser)
    token = browser.state["checkpoint_token"]
    browser.ui.query_params.clear()
    browser.store.begin_page(3)
    assert browser.ui.query_params[browser.store.RECOVERY_PARAM] == token


def test_reset_detaches_previous_stream_and_writes_empty_checkpoint(browser):
    old = ready(browser)
    token = browser.state["checkpoint_token"]
    browser.ui.begin()
    with pytest.raises(StopRun):
        browser.store.reset_session()
    assert browser.state["checkpoint_token"] != token
    assert browser.state["pipeline_data"] == {}
    assert len(records(browser)) == 1
    assert json.loads(records(browser)[0].read_text(encoding="utf-8"))["pipeline_data"] == {}
    assert old.exists()


def test_new_pair_retains_old_checkpoints_and_updates_active_url(browser):
    old = ready(browser)
    old_bytes = old.read_bytes()
    token = browser.state["checkpoint_token"]
    browser.run_bandpass(changes={"bandpass_pair_index": 1})
    assert browser.state["checkpoint_token"] == token
    assert old.read_bytes() == old_bytes
    current = json.loads(Path(browser.state["checkpoint_path"]).read_text(encoding="utf-8"))
    assert current["pipeline_data"]["03_bandpass_correction"]["filename1"] == "c.fits"


def test_disk_failure_keeps_old_record_and_current_work_for_retry(browser, monkeypatch):
    path = ready(browser)
    before = path.read_bytes()
    browser.store.log_event("Unsaved current work")
    core = browser.store.checkpoint_store
    original = core._atomic_create
    monkeypatch.setattr(core, "_atomic_create", lambda *args: (_ for _ in ()).throw(OSError("disk full")))
    assert browser.store.checkpoint_session("Changed") is None
    assert "disk full" in browser.state["checkpoint_error"]
    assert path.read_bytes() == before
    assert browser.state["audit_log"][-1]["message"] == "Unsaved current work"
    monkeypatch.setattr(core, "_atomic_create", original)
    assert browser.store.checkpoint_session("Retry") != path
    assert "checkpoint_error" not in browser.state


def test_corrupt_latest_falls_back_only_during_recovery(browser):
    first = ready(browser)
    browser.store.log_event("Another commit")
    second = browser.store.checkpoint_session("Changed")
    second.write_text("{broken", encoding="utf-8")
    core = browser.store.checkpoint_store
    with pytest.raises(core.CheckpointError):
        core.latest(browser.store.SESSIONS_DIR, browser.state["checkpoint_token"])
    record = core.latest(browser.store.SESSIONS_DIR, browser.state["checkpoint_token"], recover=True)
    assert record.path == first
    assert record.warning


def test_no_silent_fallback_when_manual_snapshot_checksum_is_wrong(browser):
    ready(browser)
    attach_baseline(browser)
    browser.store.begin_page(4)
    path = browser.store.save_session()
    data = json.loads(path.read_text(encoding="utf-8"))
    sidecar = path.parent / data["baseline_snapshot"]["file"]
    sidecar.write_text("{}", encoding="utf-8")
    before = copy.deepcopy(dict(browser.state))
    with pytest.raises(ValueError, match="checksum"):
        browser.store.load_session(path, navigate=False)
    assert browser.state["session_id"] == before["session_id"]
    assert browser.state["completed_stages"] == before["completed_stages"]


@pytest.mark.parametrize("name", ["../outside.json", "/tmp/outside.json", "other.json", "..\\outside.json"])
def test_snapshot_reference_cannot_escape_or_read_another_file(browser, name):
    path = ready(browser)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["baseline_snapshot"] = {"file": name, "sha256": "0" * 64}
    bad = browser.store.SESSIONS_DIR / "bad-reference.json"
    bad.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        browser.store.checkpoint_store.read_record(bad)


def test_stale_writer_is_rejected_not_last_writer_wins(browser):
    ready(browser)
    core = browser.store.checkpoint_store
    token = browser.state["checkpoint_token"]
    record = core.latest(browser.store.SESSIONS_DIR, token)
    payload = copy.deepcopy(record.payload)
    payload["audit_log"].append({"ts": "1", "message": "writer A"})
    latest = core.write_checkpoint(browser.store.SESSIONS_DIR, token, payload, None,
                                   reason="A", expected_revision=record.revision)
    payload["audit_log"][-1]["message"] = "writer B"
    with pytest.raises(core.CheckpointConflict):
        core.write_checkpoint(browser.store.SESSIONS_DIR, token, payload, None,
                              reason="B", expected_revision=record.revision)
    assert core.latest(browser.store.SESSIONS_DIR, token).path == latest.path


def test_baseline_to_new_id_transition_accepts_old_dash_advance_without_copying_it(browser):
    ready(browser)
    attach_baseline(browser)  # Streamlit has not acknowledged this revision yet.
    old_id = browser.state["session_id"]
    browser.ui.begin()
    browser.invalidation.invalidate_loaded_input_dependents(browser.state, new_session_id="changed-observation")
    path = browser.store.checkpoint_session("Changed observation")
    assert path is not None
    assert "checkpoint_error" not in browser.state
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["session_id"] != old_id
    assert "04_baseline_editor" not in data["pipeline_data"]
    assert "baseline_snapshot" not in data


def test_pointing_manual_values_and_mapping_restore_without_auth_restore(browser):
    ready(browser)
    browser.state["pipeline_data"]["06_pointing_correction"] = {
        "input_source": "manual entry", "scan_key": "manual", "hpbw_deg": 0.12,
        "peak_powers": {"N": 1.2, "S": 1.3, "E": 1.4, "W": 1.5, "Centre": 2.0},
    }
    browser.state["file_loader_mapping_mode"] = "Manual"
    browser.state["file_loader_manual_mapping_global"] = {"Vlsr": "HDU0:SPVLSR"}
    path = browser.store.checkpoint_session("Manual pointing committed")
    browser.state["authentication_status"] = True
    browser.ui.begin()
    browser.ui.begin()
    browser.store.recover_checkpoint(path, navigate=False)
    assert browser.state["pointing_manual::N"] == 1.2
    assert browser.state["pointing_manual::hpbw"] == 0.12
    assert browser.state["file_loader_mapping_mode"] == "Manual"
    assert browser.state["file_loader_manual_mapping_global"] == {"Vlsr": "HDU0:SPVLSR"}
    assert browser.state["authentication_status"] is True
    assert "authentication_status" not in json.loads(path.read_text(encoding="utf-8"))


def test_pointing_scan_and_picks_restore_exactly(browser):
    ready(browser)
    browser.state["pipeline_data"]["06_pointing_correction"] = {
        "input_source": "pointing scan: fixture", "scan_key": "scan-B", "hpbw_deg": 0.13,
        "picked_velocities": {"N": -4.5, "S": -4.4, "E": -4.3, "W": -4.2, "Centre": -4.1},
    }
    path = browser.store.checkpoint_session("Scan picks committed")
    browser.ui.begin()
    browser.store.recover_checkpoint(path, navigate=False)
    assert browser.state["pointing_scan_key"] == "scan-B"
    assert browser.state["pointing_pick::scan-B::Centre"] == -4.1
    assert browser.state["pointing_hpbw::scan-B"] == 0.13


def test_manual_save_does_not_overwrite_working_bridge(browser):
    ready(browser)
    attach_baseline(browser)
    sid = browser.state["session_id"]
    path = browser.bridge._bridge_path(sid)
    original = path.read_bytes()
    saved = browser.store.save_session()
    assert path.read_bytes() == original
    assert saved != path
    assert "baseline_snapshot" in json.loads(saved.read_text(encoding="utf-8"))


def test_pending_snapshot_not_activated_for_different_pair_with_equal_output(browser):
    ready(browser)
    attach_baseline(browser)
    record = browser.store.checkpoint_store.latest(browser.store.SESSIONS_DIR, browser.state["checkpoint_token"])
    browser.ui.begin()
    browser.store.recover_checkpoint(record.path, navigate=False)
    target_id = browser.state["session_id"]
    browser.state["session_id"] = "deliberate-new-pair"
    browser.state["bandpass_corrected_spectrum"] = record.bridge["spectrum"]
    browser.store.sync_baseline_state()
    assert target_id != browser.state["session_id"]
    assert "checkpoint_pending_bridge" not in browser.state
    assert browser.bridge.read_bridge(browser.state["session_id"]) is None


def test_core_rejects_false_completion_when_fit_does_not_match_blocks(browser):
    ready(browser)
    document = baseline(browser)
    document["blocks"] = [{"start": 0.2, "end": 1.0}]
    core = browser.store.checkpoint_store
    frozen = core.matching_bridge(browser.store._session_payload(), document)
    assert frozen["fit_result"] is None
    assert frozen["flattened_spectrum"] is None
    assert frozen["complete"] is False


def test_uncorrelated_bridge_does_not_enter_checkpoint(browser):
    ready(browser)
    document = baseline(browser)
    document["spectrum_fingerprint"] = "another-bandpass"
    written = browser.bridge.update_bridge(browser.state["session_id"], lambda target: target.update(document))
    assert "checkpoint_notice" in written
    assert len(records(browser)) == 1


@pytest.mark.parametrize("value", [float("nan"), float("inf"), object()])
def test_bad_parameter_reports_failure_without_overwriting_checkpoint(browser, value):
    path = ready(browser)
    before = path.read_bytes()
    browser.state["pipeline_data"]["bad"] = {"value": value}
    assert browser.store.checkpoint_session("Bad parameter") is None
    assert browser.state["checkpoint_error"]
    assert path.read_bytes() == before


def test_retry_noop_has_same_timestamp(browser):
    path = ready(browser)
    saved = browser.state["checkpoint_saved_at"]
    assert browser.store.checkpoint_session("Retry") == path
    assert browser.state["checkpoint_saved_at"] == saved


def test_new_stages_have_explicit_checkpoint_hooks_after_commit():
    for name in ("01_Source_Browser.py", "02_File_Loader.py", "03_Bandpass_Correction.py", "04_Baseline_Editor.py",
                 "05_Calibration_Dashboard.py", "06_Pointing_Correction.py", "07_Spectral_Fitting.py",
                 "08_Export_and_Session.py"):
        tree = ast.parse((APP_ROOT / "pages" / name).read_text(encoding="utf-8"))
        assert any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                   and node.func.attr == "checkpoint_session" for node in ast.walk(tree)), name
    tree = ast.parse((APP_ROOT / "utils/session_store.py").read_text(encoding="utf-8"))
    marker = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "mark_stage_complete")
    assert "checkpoint_session" not in ast.unparse(marker)


def test_dash_persist_reports_success_and_rejects_transient_old_fit(browser):
    ready(browser)
    attach_baseline(browser)
    source = ast.parse((APP_ROOT / "dash_apps/baseline_editor.py").read_text(encoding="utf-8"))
    func = next(node for node in ast.walk(source) if isinstance(node, ast.FunctionDef) and node.name == "persist")
    func = copy.deepcopy(func)
    func.decorator_list = []
    module = ast.fix_missing_locations(ast.Module(body=[func], type_ignores=[]))
    import utils.baseline_editor_logic as logic
    sentinel = object()
    flatten_calls = []
    ns = dict(no_update=sentinel, normalize_blocks=logic.normalize_blocks, stage_payload=logic.stage_payload,
              rows_equal=logic.rows_equal, append_event=browser.bridge.append_event,
              update_bridge=browser.bridge.update_bridge, CLCBaselineIntegrationUnavailable=RuntimeError)
    ns["flatten_spectrum_for_orders"] = lambda *args: (
        flatten_calls.append(args) or baseline(browser)["flattened_spectrum"]
    )
    exec(compile(module, "persist_callback", "exec"), ns)
    state = browser.bridge.read_bridge(browser.state["session_id"])
    rows = [{"start": 0.3, "end": 1.0}]
    version, message = ns["persist"](rows, "Manual", 3, 4, state["fit_result"], state["selected_orders"], state)
    assert version
    assert "checkpoint saved" in message
    assert flatten_calls == []
    latest = browser.store.checkpoint_store.latest(browser.store.SESSIONS_DIR, browser.state["checkpoint_token"])
    assert latest.payload["pipeline_data"]["04_baseline_editor"]["complete"] is False


def test_atomic_publication_cleans_temporary_files_after_failed_link(browser, monkeypatch):
    core = browser.store.checkpoint_store
    target = browser.store.SESSIONS_DIR / "temporary-test.json"
    monkeypatch.setattr(core.os, "link", lambda *args: (_ for _ in ()).throw(OSError("simulated link failure")))
    with pytest.raises(OSError):
        core._atomic_create(target, b"{}")
    assert not target.exists()
    assert list(target.parent.glob(".hartspec-*.tmp")) == []


def test_writers_do_not_deadlock_bridge_and_checkpoint_locks(browser):
    ready(browser)
    attach_baseline(browser)
    errors = []
    def dash_writer():
        try:
            for _ in range(8):
                browser.bridge.update_bridge(browser.state["session_id"], lambda target: None)
        except Exception as exc:
            errors.append(exc)
    thread = threading.Thread(target=dash_writer, daemon=True)
    thread.start()
    for _ in range(8):
        browser.store.checkpoint_session("Main-thread rerun")
    thread.join(timeout=3)
    assert not thread.is_alive(), "Lock-order deadlock"
    assert not errors
    assert "checkpoint_error" not in browser.state


def test_mode_change_auto_checkpoints_new_mode_without_deleting_old_baseline(browser):
    ready(browser)
    attach_baseline(browser)
    browser.store.begin_page(4)
    old_id = browser.state["session_id"]
    old_bridge = browser.bridge._bridge_path(old_id)
    old_bytes = old_bridge.read_bytes()
    browser.run_bandpass(changes={"bandpass_mode": "Position Switch"})
    assert "checkpoint_error" not in browser.state
    data = json.loads(Path(browser.state["checkpoint_path"]).read_text(encoding="utf-8"))
    assert data["pipeline_data"]["03_bandpass_correction"]["mode"] == "Position Switch"
    assert "04_baseline_editor" not in data["pipeline_data"]
    assert old_bridge.read_bytes() == old_bytes


def test_parameter_only_browser_load_does_not_import_a_newer_live_baseline(browser):
    ready(browser)
    path = browser.store.save_session()  # No baseline yet.
    old_id = browser.state["session_id"]
    attach_baseline(browser)  # This later baseline must not leak into the earlier manual save.
    browser.ui.begin()
    browser.store.load_session(path, navigate=False)
    assert browser.state["session_id"] != old_id
    assert browser.bridge.read_bridge(browser.state["session_id"]) is None
    assert "04_baseline_editor" not in browser.state["pipeline_data"]
    saved = browser.store.checkpoint_session("Loaded earlier manual save")
    assert "baseline_snapshot" not in json.loads(saved.read_text(encoding="utf-8"))


def test_recovery_gates_direct_later_page_without_destroying_saved_parameters(browser):
    path = ready(browser)
    browser.ui.begin()
    browser.store.recover_checkpoint(path, navigate=False)
    previous = copy.deepcopy(browser.state["pipeline_data"])
    with pytest.raises(StopRun):
        browser.store.begin_page(8)
    assert browser.ui.navigation == "pages/02_File_Loader.py"
    assert browser.state["pipeline_data"] == previous


@pytest.mark.parametrize("mapping", [{"LCP/RCP": "bad"}, {"LCP/RCP": ["one"]}, {"Vlsr": ["bad"]}])
def test_invalid_extra_mapping_is_rejected_before_changing_session(browser, mapping):
    path = ready(browser)
    data = json.loads(path.read_text(encoding="utf-8"))
    data.pop("checkpoint")
    data["ui_state"] = {"file_loader_manual_mapping_global": mapping}
    bad = browser.store.SESSIONS_DIR / "bad-mapping.json"
    bad.write_text(json.dumps(data), encoding="utf-8")
    old_id = browser.state["session_id"]
    with pytest.raises(ValueError, match="mapping"):
        browser.store.load_session(bad, navigate=False)
    assert browser.state["session_id"] == old_id


def test_sidebar_renders_live_status_and_recovery_selector(browser, monkeypatch):
    import importlib.util
    from contextlib import nullcontext
    ready(browser)
    browser.ui.begin()
    browser.ui.sidebar = nullcontext()
    path = APP_ROOT / "utils/sidebar.py"
    spec = importlib.util.spec_from_file_location("_checkpoint_sidebar_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.render_sidebar(3)
    assert any("Stage 3 of 8" in message and "Last checkpoint" in message for message in browser.ui.messages)
    assert "session_checkpoint_choice" in browser.state
    assert browser.state["checkpoint_status_placeholder"] is browser.ui
    selected_stream = browser.state["session_checkpoint_choice"]
    browser.store.log_event("One more action")
    browser.store.checkpoint_session("New revision")
    browser.ui.begin()
    browser.ui.sidebar = nullcontext()
    module.render_sidebar(3)
    assert browser.state["session_checkpoint_choice"] == selected_stream


def _extract_function(path, name, namespace):
    """Execute an actual page function while injecting unavailable scientific boundaries."""
    source = ast.parse(path.read_text(encoding="utf-8"))
    node = next(node for node in ast.walk(source) if isinstance(node, ast.FunctionDef) and node.name == name)
    node = copy.deepcopy(node)
    node.decorator_list = []
    code = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    exec(compile(code, str(path), "exec"), namespace)
    return namespace[name]


def test_pointing_page_checkpoints_actual_manual_commit_payload(browser):
    ready(browser)
    browser.ui.begin()
    import utils.styles as styles
    powers = {"N": 1.1, "S": 1.2, "E": 1.3, "W": 1.4, "Centre": 2.0}
    result = SimpleNamespace(ns_offset_deg=0.01, ew_offset_deg=0.02, correction_factor=1.2,
                             hpbw_deg=0.1, powers=powers)
    namespace = {
        "st": browser.ui, "session_store": browser.store, "styles": styles,
        "sidebar": SimpleNamespace(render_sidebar=lambda **kwargs: None),
        "CURRENT_STAGE": 6, "PAGE_STAGE_KEY": "06_pointing_correction",
        "LOGGED_SIGNATURE_KEY": "pointing_logged_signature",
        "NEXT_PAGE": "pages/07_Spectral_Fitting.py", "DIRECTIONS": list(powers),
        "_loaded_spectra_by_basename": lambda: {}, "_find_scans": lambda spectra: [],
        "_render_manual_entry": lambda: (powers, 0.1), "render_offset_table": lambda *args: None,
        "_render_pointing_product_graph": lambda *args: None,
        "_compute": lambda *args: {"result": result, "signature": "fixture-signature", "error": None},
    }
    _extract_function(APP_ROOT / "pages/06_Pointing_Correction.py", "main", namespace)()
    data = json.loads(Path(browser.state["checkpoint_path"]).read_text(encoding="utf-8"))
    saved = data["pipeline_data"]["06_pointing_correction"]
    assert saved["peak_powers"] == powers
    assert saved["input_source"] == "manual entry"
    assert saved["scan_key"] == "manual"
    assert "06_pointing_correction" in data["completed_stages"]
    assert any("Pointing correction computed" in e["message"] for e in data["audit_log"])


def test_fit_commit_records_parameters_and_log_before_checkpoint(browser):
    ready(browser)
    browser.ui.begin()
    source = ast.parse((APP_ROOT / "pages/07_Spectral_Fitting.py").read_text(encoding="utf-8"))
    summary = next(node for node in source.body if isinstance(node, ast.FunctionDef) and node.name == "_stage_summary")
    save = next(node for node in source.body if isinstance(node, ast.If) and ast.unparse(node.test) == "save_clicked")
    result = SimpleNamespace(fit_type_used="1D Gaussian", fit_type_requested="1D Gaussian", rows=[("peak", "2", "0.1")],
                             converged=True, notes=[], curve=np.asarray([1., 2.]))
    namespace = dict(Any=object, st=browser.ui, session_store=browser.store, save_clicked=True,
                     THIS_STAGE_KEY="07_spectral_fitting", result=result, source_key="fixture", g3_unit="Jy",
                     pss=SimpleNamespace(value=2.0), pointing_factor=1.2, vlsr=np.asarray([0., 1.]),
                     resolved=SimpleNamespace(source_key="baseline"),
                     fitting_inputs=SimpleNamespace(GRAPH3_FORMULA="fixture-formula"))
    code = ast.fix_missing_locations(ast.Module(body=[summary, save], type_ignores=[]))
    exec(compile(code, "actual_fit_commit", "exec"), namespace)
    data = json.loads(Path(browser.state["checkpoint_path"]).read_text(encoding="utf-8"))
    assert data["pipeline_data"]["07_spectral_fitting"]["pss_jy_per_k"] == 2.0
    assert data["pipeline_data"]["07_spectral_fitting"]["parameters"][0]["parameter"] == "peak"
    assert data["audit_log"][-1]["message"].startswith("Spectral fit committed")
    assert "latest_fit" not in data  # Runtime curves require recomputation, not a fake recovered result.


def test_export_complete_records_completion_before_checkpoint(browser):
    ready(browser)
    browser.ui.begin()
    source = ast.parse((APP_ROOT / "pages/08_Export_and_Session.py").read_text(encoding="utf-8"))
    block = next(node for node in source.body if isinstance(node, ast.If)
                 and "Mark export complete" in ast.unparse(node.test))
    hook = source.body[-1]
    namespace = dict(st=browser.ui, session_store=browser.store, export_blocked=False,
                     THIS_STAGE_KEY="08_export_and_session", vlsr=np.asarray([0., 1.]),
                     resolved=SimpleNamespace(source_key="baseline"), unit="K")
    old = browser.ui.button
    browser.ui.button = lambda *args, **kwargs: True
    try:
        exec(compile(ast.fix_missing_locations(ast.Module(body=[block, hook], type_ignores=[])),
                     "actual_export_commit", "exec"), namespace)
    finally:
        browser.ui.button = old
    data = json.loads(Path(browser.state["checkpoint_path"]).read_text(encoding="utf-8"))
    assert "08_export_and_session" in data["completed_stages"]
    assert data["audit_log"][-1]["message"] == "Export stage marked complete"


def test_global_sync_rejects_current_bandpass_that_no_longer_matches_saved_fingerprint(browser):
    ready(browser)
    attach_baseline(browser)
    browser.store.begin_page(4)
    browser.state["pipeline_data"]["05_calibration_dashboard"] = {"complete": True}
    browser.state["completed_stages"].add("05_calibration_dashboard")
    browser.state["calibrated_spectrum"] = {"old": True}
    browser.state["bandpass_corrected_spectrum"]["LCP"][0] += 100
    browser.store.begin_page(7)
    assert "04_baseline_editor" not in browser.state["completed_stages"]
    assert "05_calibration_dashboard" not in browser.state["completed_stages"]
    assert "calibrated_spectrum" not in browser.state
    assert "baseline_corrected_spectrum" not in browser.state
    path = browser.store.checkpoint_session("Bad runtime input rejected")
    assert "baseline_snapshot" not in json.loads(path.read_text(encoding="utf-8"))


def test_checkpoint_test_text_io_always_specifies_utf8():
    """Prevent omitted encodings in this module from depending on a developer's locale."""
    source = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    for node in ast.walk(source):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("read_text", "write_text")):
            continue
        encoding = next((kw.value for kw in node.keywords if kw.arg == "encoding"), None)
        assert isinstance(encoding, ast.Constant) and encoding.value in ("utf-8", "utf-8-sig"), (
            f"{node.func.attr} at line {node.lineno} must specify its UTF-8 encoding"
        )


def test_unicode_audit_text_survives_checkpoint_and_manual_save_recovery(browser):
    """Keep Unicode intact in actual saved bytes and both production recovery paths."""
    ready(browser)
    message = 'Observer “Zoë” — σ = 0.2; LCP × RCP → ✓'
    browser.store.log_event(message)
    checkpoint = browser.store.checkpoint_session("Unicode audit regression")
    manual_save = browser.store.save_session()
    original_bytes = {}
    for path in (checkpoint, manual_save):
        raw = path.read_bytes()
        original_bytes[path] = raw
        # The closing curly quote contains a UTF-8 byte undefined in cp1252.
        # This is the specific failure signature reported on Windows.
        with pytest.raises(UnicodeDecodeError):
            raw.decode("cp1252")
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert any(entry["message"] == message for entry in payload["audit_log"])
        record = browser.store.checkpoint_store.read_record(path)
        assert any(entry["message"] == message for entry in record.payload["audit_log"])

    browser.ui.begin()
    browser.store.recover_checkpoint(checkpoint, navigate=False)
    assert any(entry["message"] == message for entry in browser.state["audit_log"])
    browser.ui.begin()
    browser.store.load_session(manual_save, navigate=False)
    assert any(entry["message"] == message for entry in browser.state["audit_log"])
    assert all(path.read_bytes() == raw for path, raw in original_bytes.items())
