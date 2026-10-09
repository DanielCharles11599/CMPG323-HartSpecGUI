# test_session_safety.py — FR-19: Load/Reset isolation and non-destructive failures.
"""Headless tests; no FITS files, CLC imports or running Streamlit server needed.

Only Streamlit's session-state facade and the absent environment bootstrap are
substituted. The production session_store module is loaded from disk unchanged.
Fixtures are function-scoped and restore sys.modules, so they do not replace
Streamlit for other tests in the repository.
"""
from __future__ import annotations

import ast
import copy
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "hartspec_gui" if (ROOT / "hartspec_gui" / "utils").is_dir() else ROOT
STORE_PATH = APP_ROOT / "utils" / "session_store.py"


@pytest.fixture
def store(monkeypatch, tmp_path):
    """Import the real store with isolated state and a temporary sessions folder."""
    fake_streamlit = types.ModuleType("streamlit")
    fake_streamlit.session_state = {}
    fake_utils = types.ModuleType("utils")
    fake_utils.__path__ = [str(APP_ROOT / "utils")]
    fake_env = types.ModuleType("utils.env")
    fake_env.load_dotenv_if_present = lambda: None
    fake_utils.env = fake_env
    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)
    monkeypatch.setitem(sys.modules, "utils", fake_utils)
    monkeypatch.setitem(sys.modules, "utils.env", fake_env)
    monkeypatch.setenv("SESSIONS_PATH", str(tmp_path / "sessions"))
    name = "_hartspec_session_safety_under_test"
    spec = importlib.util.spec_from_file_location(name, STORE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    module.init_session_state()
    return module


def _load(store, path):
    """Exercise the production restore logic without triggering a browser page switch."""
    store.load_session(path, navigate=False)


def _reset(store):
    """Exercise the production reset logic without triggering a browser page switch."""
    store.reset_session(navigate=False)


def _saved_payload(session_id="saved-b") -> dict:
    """Representative current-schema parameters, with no computed spectrum arrays."""
    return {
        "session_id": session_id,
        "saved_at": "2026-10-08T12:34:56+00:00",
        "pipeline_data": {
            "01_source_browser": {
                "selected_files": ["target/first.fits", "target/second.fits"],
                "fits_file_paths": ["/archive/target/first.fits", "/archive/target/second.fits"],
                "source_name": "Saved source B",
                "frequency_mhz": 1420.405,
            },
            "03_bandpass_correction": {"mode": "Position Switch"},
            "04_baseline_editor": {
                "blocks": [{"start": -12.4, "end": -9.8}],
                "selected_orders": {"LCP": 3, "RCP": 4},
                "selection_semantics": "flat_baseline_fit_regions_v2",
            },
            "07_spectral_fitting": {
                "fit_type_requested": "Polynomial Peak",
                "fit_type": "1D Gaussian",
                "polarization": "RCP",
                "parameters": [{"parameter": "Center", "value": "-4.20 km/s", "error": "0.03 km/s"}],
            },
        },
        "completed_stages": ["01_source_browser", "file_loader", "03_bandpass_correction"],
        "audit_log": [{"ts": "12:34:56", "message": "Original saved event", "extra": "preserved"}],
    }


def _write_session(store, payload=None, name="saved-b.json") -> Path:
    """Write only a temporary test session; never touch an observation archive."""
    store.SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    path = store.SESSIONS_DIR / name
    path.write_text(json.dumps(payload if payload is not None else _saved_payload()), encoding="utf-8")
    return path


def _old_state(store) -> dict:
    """Seed real current-page state keys, plus unrelated browser/auth state."""
    state = store.st.session_state
    state.update({
        "session_id": "old-a",
        "pipeline_data": {"old_stage": {"value": "old"}},
        "completed_stages": set(store.STAGE_KEYS),
        "audit_log": [{"ts": "01:02:03", "message": "Previous reduction"}],
        "theme": "dark",
        "authentication_status": True,
        "username": "observer",
        "sidebar_expanded": True,
        "unrelated_extension": {"keep": "unchanged"},
        "loaded_spectra": [{"Vlsr": [0.0], "LCP": [999.0], "RCP": [888.0]}],
        "loaded_spectrum": {"Vlsr": [0.0], "LCP": [999.0], "RCP": [888.0]},
        "bandpass_corrected_spectrum": {"old": "bandpass"},
        "baseline_corrected_spectrum": {"old": "baseline"},
        "calibrated_spectrum": {"Vlsr": [0.0], "LCP": [999.0], "RCP": [888.0]},
        "latest_fit": {"spectrum_source": "calibrated", "fit_curve": [777.0]},
        "bandpass_display_result": {"mode": "Frequency Switch"},
        "bandpass_applied_mode": "Frequency Switch",
        "source_browser_source_name": "Previous source A",
        "source_browser_frequency_mhz": 6668.519,
        "source_browser_filename_search": "old.fits",
        "source_browser_fits_dir": "/archive/old-source",
        "source_browser_browse_open": True,
        "source_browser_file_check_error": {"message": "old error"},
        "file_loader_target_filenames": ["old.fits"],
        "file_loader_manual_filenames_input": "old.fits\nother-old.fits",
        "file_loader_load_done": True,
        "file_loader_ingest_result::old.fits": {"ok": True},
        "file_loader_verify_result::old.fits": {"ok": True},
        "file_loader_load_elapsed_s::old.fits": 1.5,
        "file_loader_quarantined": {"old-bad.fits"},
        "file_loader_pending_quarantine": "old-bad.fits",
        "file_loader_pending_quarantine_all": True,
        "file_loader_quarantine_error": "old error",
        "file_loader_manual_mapping_global": {"Vlsr": "HDU9:OLD"},
        "manual_map_global_Vlsr": "HDU9:OLD",
        "file_loader_mapping_mode": "Manual",
        "file_loader_field_search": "old",
        "file_loader_show_only_flagged": True,
        "baseline_editor_seen_event_ids": ["previous-bridge-event"],
        "calibration_cached_result": {"old": True},
        "pointing_cached_result": {"old": True},
        "spectral_fitting_cached_result": {"old": True},
        "export_cached_result": {"old": True},
        "fit_type": "Multi-component",
        "fit_polarization": "LCP",
    })
    return state


@pytest.mark.parametrize("operation", ["load", "reset"])
def test_removes_previous_arrays_caches_and_quarantine_intent(store, operation):
    """A session transition cannot leave a previously computed result in memory."""
    state = _old_state(store)
    if operation == "load":
        _load(store, _write_session(store))
    else:
        _reset(store)
    for key in (
        "loaded_spectrum", "loaded_spectra", "bandpass_corrected_spectrum",
        "baseline_corrected_spectrum", "calibrated_spectrum", "latest_fit",
        "bandpass_display_result", "bandpass_applied_mode", "baseline_editor_seen_event_ids",
        "source_browser_fits_dir", "source_browser_browse_open", "source_browser_file_check_error",
        "file_loader_ingest_result::old.fits", "file_loader_verify_result::old.fits",
        "file_loader_load_elapsed_s::old.fits", "file_loader_load_done",
        "file_loader_target_filenames", "file_loader_quarantined", "file_loader_pending_quarantine",
        "file_loader_pending_quarantine_all", "file_loader_quarantine_error",
        "file_loader_manual_mapping_global", "manual_map_global_Vlsr", "calibration_cached_result",
        "pointing_cached_result", "spectral_fitting_cached_result", "export_cached_result",
    ):
        assert key not in state, key


@pytest.mark.parametrize("operation", ["load", "reset"])
def test_preserves_theme_authentication_and_unrelated_state(store, operation):
    """Do not use a blanket state.clear() that signs out users or resets their theme."""
    state = _old_state(store)
    original = {key: state[key] for key in (
        "theme", "authentication_status", "username", "sidebar_expanded", "unrelated_extension",
    )}
    if operation == "load":
        _load(store, _write_session(store))
    else:
        _reset(store)
    for key, value in original.items():
        assert state[key] is value


def test_load_preserves_saved_parameters_flags_and_audit_exactly(store):
    """Restore the target metadata rather than merge it with the previous reduction."""
    _old_state(store)
    payload = _saved_payload()
    payload["pipeline_data"]["extension_stage"] = {"precision": 1.2345678901234567, "extra": [None, False]}
    payload["completed_stages"].append("extension_stage")
    _load(store, _write_session(store, payload))
    state = store.st.session_state
    assert state["session_id"] == payload["session_id"]
    assert state["pipeline_data"] == payload["pipeline_data"]
    assert state["completed_stages"] == set(payload["completed_stages"])
    assert state["audit_log"] == payload["audit_log"]
    assert "old_stage" not in state["pipeline_data"]


def test_load_seeds_supported_controls_from_target_not_old_session(store):
    """Source, frequency, bandpass and fit selectors use saved choices where known."""
    _old_state(store)
    _load(store, _write_session(store))
    state = store.st.session_state
    assert state["source_browser_source_name"] == "Saved source B"
    assert state["source_browser_frequency_mhz"] == 1420.405
    assert state["bandpass_mode"] == "Position Switch"
    assert state["fit_type"] == "Polynomial Peak"  # requested, not fallback model
    assert state["fit_polarization"] == "RCP"
    assert state["file_loader_mapping_mode"] == "Auto"
    assert state["file_loader_manual_filenames_input"] == ""
    assert state["source_browser_filename_search"] == ""
    assert state["file_loader_field_search"] == ""
    assert state["file_loader_show_only_flagged"] is False


def test_reset_is_empty_with_new_id_and_safe_control_defaults(store):
    """Reset never marks the new reduction complete or restores any old parameter."""
    state = _old_state(store)
    _reset(store)
    assert state["session_id"] != "old-a"
    assert len(state["session_id"]) == 8
    assert state["pipeline_data"] == {}
    assert state["completed_stages"] == set()
    assert state["audit_log"] == []
    assert state["bandpass_mode"] == "Frequency Switch"
    assert state["fit_type"] == "1D Gaussian"
    assert state["fit_polarization"] == "LCP"
    assert state["file_loader_mapping_mode"] == "Auto"
    assert "source_browser_source_name" not in state
    assert "source_browser_frequency_mhz" not in state


def test_loading_same_id_still_discards_derived_memory(store):
    """Reloading an earlier save of the same reduction also requires recomputation."""
    state = _old_state(store)
    _load(store, _write_session(store, _saved_payload("old-a")))
    assert state["session_id"] == "old-a"
    assert "calibrated_spectrum" not in state
    assert "latest_fit" not in state


@pytest.mark.parametrize("operation", ["load", "reset"])
def test_transition_leaves_saved_json_bridge_workspace_and_raw_files_untouched(store, tmp_path, operation):
    """Only in-memory state changes; quarantines are not undone and bridges are not deleted."""
    _old_state(store)
    saved = _write_session(store)
    bridge = store.SESSIONS_DIR / "old-a.baseline_editor.json"
    bridge.write_text('{"events": ["keep this sidecar"]}', encoding="utf-8")
    workspace = store.SESSIONS_DIR / "old-a" / "workspace" / "blocks.txt"
    workspace.parent.mkdir(parents=True)
    workspace.write_text("old.fits\n", encoding="utf-8")
    raw = tmp_path / "fits" / "raw.fits"
    raw.parent.mkdir()
    raw.write_bytes(b"unchanged raw bytes")
    quarantined = raw.parent / "Flagged" / "bad.fits"
    quarantined.parent.mkdir()
    quarantined.write_bytes(b"still quarantined")
    before = {p: p.read_bytes() for p in (saved, bridge, workspace, raw, quarantined)}
    if operation == "load":
        _load(store, saved)
    else:
        _reset(store)
    assert before == {p: p.read_bytes() for p in before}


@pytest.mark.parametrize("missing", ["session_id", "pipeline_data", "completed_stages", "audit_log"])
def test_rejects_missing_envelope_fields_without_mutating_state(store, missing):
    """Malformed session envelopes are not silently replaced with empty dictionaries."""
    state = _old_state(store)
    before = copy.deepcopy(state)
    original_pipeline = state["pipeline_data"]
    payload = _saved_payload()
    del payload[missing]
    with pytest.raises(ValueError):
        _load(store, _write_session(store, payload))
    assert state == before
    assert state["pipeline_data"] is original_pipeline


@pytest.mark.parametrize("payload", [None, [], "not a session", 9, True])
def test_rejects_non_object_json_without_mutating_state(store, payload):
    """Valid JSON is not necessarily a session file."""
    state = _old_state(store)
    before = copy.deepcopy(state)
    path = _write_session(store)
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        _load(store, path)
    assert state == before


@pytest.mark.parametrize("key,value", [
    ("session_id", ""), ("session_id", None), ("session_id", 123),
    ("session_id", "../escape"), ("session_id", "..\\escape"), ("session_id", "/absolute"),
    ("session_id", "abc.baseline_editor"), ("session_id", "abc\u0000def"),
    ("pipeline_data", []), ("pipeline_data", None),
    ("completed_stages", "file_loader"), ("completed_stages", [None]),
    ("completed_stages", [""]), ("completed_stages", [["nested"]]),
    ("audit_log", {}), ("audit_log", ["message"]),
    ("audit_log", [{"ts": "12:00:00"}]), ("audit_log", [{"message": "no time"}]),
    ("audit_log", [{"ts": 123, "message": "bad time"}]),
])
def test_rejects_invalid_envelope_types_and_ids_before_cleanup(store, key, value):
    """Loading a damaged file must not lose the active reduction or create unsafe paths."""
    state = _old_state(store)
    before = copy.deepcopy(state)
    payload = _saved_payload()
    payload[key] = value
    with pytest.raises(ValueError):
        _load(store, _write_session(store, payload))
    assert state == before


def test_rejects_dash_sidecar_as_session(store):
    """A direct caller cannot accidentally load a bridge as an empty reduction."""
    state = _old_state(store)
    before = copy.deepcopy(state)
    bridge = {"session_id": "saved-b", "flattened_spectrum": {}, "events": []}
    with pytest.raises(ValueError):
        _load(store, _write_session(store, bridge, "saved-b.baseline_editor.json"))
    assert state == before


@pytest.mark.parametrize("content", [b"{broken JSON", b"{\xff\xfe}"])
def test_parse_or_encoding_failure_preserves_active_state(store, content):
    """No cleanup occurs until reading, decoding and envelope validation succeed."""
    state = _old_state(store)
    before = copy.deepcopy(state)
    path = _write_session(store)
    path.write_bytes(content)
    with pytest.raises((UnicodeError, ValueError)):
        _load(store, path)
    assert state == before


def test_missing_file_preserves_active_state(store):
    """A removed history file must not damage the current in-memory reduction."""
    state = _old_state(store)
    before = copy.deepcopy(state)
    with pytest.raises(OSError):
        _load(store, store.SESSIONS_DIR / "missing.json")
    assert state == before


def test_accepts_utf8_bom_and_preserves_unicode_audit(store):
    """UTF-8 JSON from an editor remains loadable without changing its audit text."""
    payload = _saved_payload()
    payload["audit_log"][0]["message"] = "Baseline updated — σ / χ²"
    path = _write_session(store)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8-sig")
    _load(store, path)
    assert store.st.session_state["audit_log"] == payload["audit_log"]


def test_existing_save_format_roundtrips_without_new_schema_requirement(store):
    """Existing save_session output remains readable; parameters retain exact float values."""
    state = store.st.session_state
    state["pipeline_data"] = {"03_bandpass_correction": {"mode": "Position Switch", "value": 1.2345678901234567}}
    store.mark_stage_complete("03_bandpass_correction")
    store.log_event("Original parameter selection")
    path = store.save_session()
    expected = json.loads(path.read_text())
    state["calibrated_spectrum"] = {"old": True}
    state["pipeline_data"] = {"other": {}}
    _load(store, path)
    assert state["pipeline_data"] == expected["pipeline_data"]
    assert state["audit_log"] == expected["audit_log"]
    assert state["completed_stages"] == {"03_bandpass_correction"}
    assert "calibrated_spectrum" not in state
    assert store.completed_before(4) == 1


def test_initialise_after_transition_does_not_undo_loaded_values(store):
    """Repeated init/log calls from pages do not silently reintroduce old state."""
    _old_state(store)
    _load(store, _write_session(store))
    store.init_session_state()
    store.log_event("Session loaded")
    assert store.st.session_state["session_id"] == "saved-b"
    assert store.st.session_state["bandpass_mode"] == "Position Switch"
    assert [e["message"] for e in store.st.session_state["audit_log"]] == ["Original saved event", "Session loaded"]


@pytest.mark.parametrize("pipeline_data", [{}, {
    "01_source_browser": None, "03_bandpass_correction": [], "07_spectral_fitting": "legacy-note",
}, {
    "01_source_browser": {"source_name": None, "frequency_mhz": True},
    "03_bandpass_correction": {"mode": "unsupported"},
    "07_spectral_fitting": {"fit_type_requested": "unsupported", "polarization": "unsupported"},
}])
def test_unsupported_control_metadata_keeps_safe_defaults_without_rewriting_payload(store, pipeline_data):
    """Envelope validation is not a silent migration of scientific stage parameters."""
    _old_state(store)
    payload = _saved_payload()
    payload["pipeline_data"] = pipeline_data
    _load(store, _write_session(store, payload))
    assert store.st.session_state["pipeline_data"] == pipeline_data
    assert store.st.session_state["fit_type"] == "1D Gaussian"
    assert store.st.session_state["fit_polarization"] == "LCP"
    assert store.st.session_state["bandpass_mode"] == "Frequency Switch"


def test_older_fitting_summary_without_requested_type_is_supported(store):
    """The earlier saved fit_type field is still a usable control seed."""
    payload = _saved_payload()
    payload["pipeline_data"]["07_spectral_fitting"] = {"fit_type": "Multi-component", "polarization": "LCP"}
    _load(store, _write_session(store, payload))
    assert store.st.session_state["fit_type"] == "Multi-component"


def test_empty_state_reset_and_load_are_supported(store):
    """The public functions work before init on a brand-new browser session."""
    store.st.session_state.clear()
    _reset(store)
    assert store.st.session_state["pipeline_data"] == {}
    store.st.session_state.clear()
    _load(store, _write_session(store))
    assert store.st.session_state["session_id"] == "saved-b"


def test_list_sessions_still_excludes_bridge_sidecars(store):
    """The existing sidecar-exclusion fix is preserved."""
    saved = _write_session(store)
    (store.SESSIONS_DIR / "saved-b.baseline_editor.json").write_text("{}")
    assert store.list_sessions() == [saved]


def test_file_loader_control_does_not_pass_a_competing_value_argument():
    """Static integration check for the small Page 02 widget change."""
    tree = ast.parse((APP_ROOT / "pages" / "02_File_Loader.py").read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        keywords = {kw.arg: kw.value for kw in node.keywords}
        key = keywords.get("key")
        if isinstance(key, ast.Constant) and key.value == "file_loader_manual_filenames_input":
            found.append(node)
            assert "value" not in keywords
    assert len(found) == 1


def test_export_history_load_errors_are_handled_without_duplicate_success_actions():
    """Shared load action owns navigation/logging; history only handles failures."""
    tree = ast.parse((APP_ROOT / "pages" / "08_Export_and_Session.py").read_text(encoding="utf-8"))
    matching_tries = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Try) and any(
            isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "load_session"
            for child in node.body for n in ast.walk(child)
        ):
            matching_tries.append(node)
    assert len(matching_tries) == 1
    node = matching_tries[0]
    assert "ValueError" in ast.unparse(node.handlers[0].type)
    assert "st.error" in ast.unparse(node.handlers[0])
    assert not node.orelse


@pytest.fixture
def resolver(monkeypatch):
    """Load the existing, unchanged spectrum selector for cross-module regression tests."""
    path = APP_ROOT / "utils" / "spectrum_resolution.py"
    name = "_hartspec_session_safety_resolver"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("operation", ["load", "reset"])
def test_resolver_cannot_return_previous_calibration_after_transition(store, resolver, operation):
    """Reproduce the actual hazard: Pages 07/08 prefer calibrated_spectrum unconditionally."""
    state = _old_state(store)
    before = resolver.resolve_spectrum(state, read_bridge=lambda sid: None, fingerprint=lambda spectrum: "unused")
    assert before.source_key == resolver.SOURCE_CALIBRATED
    assert before.channels["LCP"].tolist() == [999.0]

    if operation == "load":
        _load(store, _write_session(store))
    else:
        _reset(store)
    consulted_sessions = []

    def read_bridge(session_id):
        consulted_sessions.append(session_id)
        return None

    after = resolver.resolve_spectrum(state, read_bridge=read_bridge, fingerprint=lambda spectrum: "unused")
    assert after.is_placeholder  # existing Page 08 blocks export in this state
    assert consulted_sessions == [state["session_id"]]
    assert consulted_sessions != ["old-a"]


def test_resolver_can_use_target_session_bridge_not_previous_memory(store, resolver):
    """Keep the existing bridge lookup behaviour; do not delete the target's saved sidecar."""
    state = _old_state(store)
    _load(store, _write_session(store))
    target = {"Vlsr": [0.0, 1.0], "LCP": [1.25, 2.5], "RCP": [1.0, 2.0]}
    seen = []

    def read_bridge(session_id):
        seen.append(session_id)
        assert session_id == "saved-b"
        return {"flattened_spectrum": target, "spectrum_fingerprint": "target"}

    after = resolver.resolve_spectrum(state, read_bridge=read_bridge, fingerprint=lambda spectrum: "target")
    assert after.source_key == resolver.SOURCE_BASELINE
    assert after.channels["LCP"].tolist() == target["LCP"]
    assert seen == ["saved-b"]


def test_resolver_uses_newly_loaded_raw_data_after_transition(store, resolver):
    """After Page 02 reloads the target files, fallback comes from that new data."""
    state = _old_state(store)
    _load(store, _write_session(store))
    target = {"Vlsr": [-1.0, 0.0], "LCP": [2.125, 3.25], "RCP": [2.0, 3.0]}
    state["loaded_spectra"] = [target]
    after = resolver.resolve_spectrum(state, read_bridge=lambda sid: None, fingerprint=lambda spectrum: "target")
    assert after.source_key == resolver.SOURCE_RAW
    assert after.channels["LCP"].tolist() == target["LCP"]



class _PageSwitch(BaseException):
    """Emulate Streamlit stopping the current script when it switches pages."""


@pytest.mark.parametrize("selection,expected_page", [
    (["a.fits", "b.fits"], "pages/02_File_Loader.py"),
    ([], "pages/01_Source_Browser.py"),
    (None, "pages/01_Source_Browser.py"),
    ("a.fits", "pages/01_Source_Browser.py"),
    ([None], "pages/01_Source_Browser.py"),
])
def test_ui_load_routes_before_later_page_can_discard_restored_state(store, selection, expected_page):
    """Do not rerun Page 3/4 with missing raw input and erase the loaded baseline."""
    state = _old_state(store)
    payload = _saved_payload()
    payload["pipeline_data"]["01_source_browser"]["selected_files"] = selection
    path = _write_session(store, payload)
    routes = []

    def switch_page(page):
        routes.append(page)
        raise _PageSwitch()

    store.st.switch_page = switch_page
    with pytest.raises(_PageSwitch):
        store.load_session(path)
    assert routes == [expected_page]
    assert state["pipeline_data"] == payload["pipeline_data"]
    assert state["audit_log"][:-1] == payload["audit_log"]
    assert state["audit_log"][-1]["message"] == "Session loaded — saved-b"
    assert "calibrated_spectrum" not in state


def test_ui_reset_routes_to_source_browser_and_logs_only_new_session_action(store):
    """Reset on a later page must not immediately repopulate that page's results."""
    state = _old_state(store)
    routes = []

    def switch_page(page):
        routes.append(page)
        raise _PageSwitch()

    store.st.switch_page = switch_page
    with pytest.raises(_PageSwitch):
        store.reset_session()
    assert routes == ["pages/01_Source_Browser.py"]
    assert state["pipeline_data"] == {}
    assert state["completed_stages"] == set()
    assert [entry["message"] for entry in state["audit_log"]] == ["Session reset — new reduction started"]
    assert state["theme"] == "dark"


def test_ui_invalid_load_does_not_navigate_or_add_success_log(store):
    """A failed UI load is non-destructive and stays on the user's current page."""
    state = _old_state(store)
    before = copy.deepcopy(state)
    routes = []
    store.st.switch_page = lambda page: routes.append(page)
    path = _write_session(store, {"not": "a session"})
    with pytest.raises(ValueError):
        store.load_session(path)
    assert routes == []
    assert state == before



@pytest.mark.parametrize("pipeline_data", [None, [], "invalid", {
    "07_spectral_fitting": "invalid", "03_bandpass_correction": ["invalid"],
}])
def test_history_description_tolerates_damaged_metadata(pipeline_data):
    """Exercise the actual pure description function without importing the whole UI."""
    tree = ast.parse((APP_ROOT / "pages" / "08_Export_and_Session.py").read_text(encoding="utf-8"))
    function = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_describe_session"
    )
    module = ast.Module(body=[function], type_ignores=[])
    namespace = {"Any": object}
    exec(compile(ast.fix_missing_locations(module), "history_description_under_test", "exec"), namespace)
    result = namespace["_describe_session"]({"session_id": "test", "pipeline_data": pipeline_data})
    assert result == "Session test"
