# test_observation_log.py — FR-20: read-only review, legacy data, Unicode and Page 08 scope.
"""Standalone tests for the observation-log helpers with a substituted Streamlit UI.

Run with pytest from the repo root; no CLC modules, FITS data or browser are needed.
Tests do not import the other developers' pages or mutate their regression files.
"""
from __future__ import annotations

import ast
import copy
import importlib.util
import json
import sys
import types
from contextlib import nullcontext
from pathlib import Path
from types import MappingProxyType

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "hartspec_gui" if (ROOT / "hartspec_gui" / "utils").is_dir() else ROOT
LOGIC_PATH = APP_ROOT / "utils" / "observation_log_logic.py"
UI_PATH = APP_ROOT / "utils" / "observation_log_ui.py"
PAGE_PATH = APP_ROOT / "pages" / "08_Export_and_Session.py"


def _load_module(name, path):
    """Load only the target file, avoiding side effects from the project's utils package."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


logic = _load_module("_hartspec_fr20_logic_tests", LOGIC_PATH)


@pytest.fixture
def recorded_session():
    """Artificial values following the actual producer keys, not a science reference dataset."""
    return {
        "session_id": "fr20-session",
        "audit_log": [
            {"ts": "23:59:59", "message": "Pair selected — on.fits + off.fits"},
            {"ts": "00:00:01", "message": "Calibration committed — PWV 1.23456789 mm"},
            {"ts": "00:00:02", "message": "Fit saved — Δv and ± error"},
        ],
        "pipeline_data": {
            "01_source_browser": {
                "source_name": "W3(OH)", "frequency_mhz": 1420.405,
                "earliest_observation_date": "2026-08-12", "selected_files": ["on.fits", "off.fits"],
            },
            "file_loader": {
                "eligible_files": ["on.fits", "off.fits"], "quarantined_files": [], "flagged_files": ["bad.fits"],
                "validation_policy": "ingest_and_structural_verification_v1",
            },
            "03_bandpass_correction": {
                "mode": "Position Switch", "filename1": "on.fits", "filename2": "off.fits",
                "position1": "ON", "position2": "OFF", "n_channels": 1024,
                "common_velocity_range_kms": [-5.0, 4.0],
            },
            "04_baseline_editor": {
                "selection_mode": "Manual", "selected_orders": {"LCP": 3, "RCP": 4},
                "blocks": [{"block": 1, "start": -10.0, "end": -5.0}],
                "chi_squared": {"LCP": {3: 0.0}}, "fit_provider": "clc", "complete": True,
                "selection_semantics": "flat_baseline_fit_regions_v2",
            },
            "05_calibration_dashboard": {
                "complete": True,
                "atmospheric": {"pwv": 1.23456789, "elevation": 0.0, "atcor": 1.01, "optical_depth": 0.02},
                "pss": {"lcp_window_mean": 2.0, "rcp_window_mean": 4.0, "window_days": 15},
            },
            "06_pointing_correction": {
                "input_source": "Manual input", "correction_factor": 1.2,
                "ns_offset_deg": -0.01, "ew_offset_deg": 0.0, "hpbw_deg": 0.2,
                "peak_powers": {"N": 2.0, "S": 3.0, "E": 4.0, "W": 5.0, "Centre": 6.0},
            },
            "07_spectral_fitting": {
                "fit_type": "1D Gaussian", "fit_type_requested": "2D Gaussian", "fitted_quantity": "Graph 3",
                "parameters": [{"parameter": "Centre", "value": "-4.2 km/s", "error": "0.03 km/s"}],
                "converged": False, "notes": ["Fallback recorded"], "pss_jy_per_k": 3.0,
                "pointing_correction_factor": 1.2, "intensity_unit": "Jy", "vlsr_range_kms": [-5.0, 4.0],
            },
        },
        "completed_stages": {stage for stage, _ in logic.STAGES[:-1]},
        "theme": "dark",
        "loaded_spectrum": {"object": "DO-NOT-USE-RUNTIME-OBJECT"},
        "source_browser_source_name": "UNCOMMITTED-SOURCE",
        "fit_type": "UNSAVED-PREVIEW",
        "latest_fit": {"fit_curve": [987654321]},
        "checkpoint_token": "PRIVATE-RECOVERY-TOKEN",
    }


def find_parameter(model, field):
    """Look up one row by explicit producer field instead of display order."""
    return next(row for row in model.parameters if row.field == field)


def test_events_preserve_exact_messages_and_original_append_order(recorded_session):
    model = logic.build_observation_log(recorded_session)
    assert [row.number for row in model.events] == [1, 2, 3]
    assert [row.message for row in model.events] == [item["message"] for item in recorded_session["audit_log"]]
    assert [row.timestamp for row in model.events] == ["23:59:59", "00:00:01", "00:00:02"]
    assert not model.warnings


def test_newest_means_reverse_append_order_not_clock_sort(recorded_session):
    events = logic.build_observation_log(recorded_session).events
    assert [row.number for row in logic.filter_events(events, newest_first=True)] == [3, 2, 1]
    assert events[0].timestamp == "23:59:59"


@pytest.mark.parametrize("query,expected", [("calibration", [2]), ("  PAIR  ", [1]), ("ΔV", [3]),
                                          ("00:00:02", [3]), (".*", []), ("", [1, 2, 3])])
def test_event_search_is_literal_unicode_case_insensitive(recorded_session, query, expected):
    model = logic.build_observation_log(recorded_session)
    assert [row.number for row in logic.filter_events(model.events, query)] == expected


def test_duplicate_events_not_deduplicated():
    item = {"ts": "12:00:00", "message": "Same recorded action"}
    model = logic.build_observation_log({"audit_log": [item, item]})
    assert len(model.events) == 2


@pytest.mark.parametrize("raw", [None, []])
def test_empty_audit_is_legible(raw):
    model = logic.build_observation_log({"audit_log": raw})
    assert model.events == ()
    assert "No actions recorded." in logic.build_log_download(model).decode("utf-8")


@pytest.mark.parametrize("raw", ["13:14:15 legacy message", {"ts": "12:00:00", "message": "single record"}, 42])
def test_nonlist_audit_is_retained_with_warning(raw):
    model = logic.build_observation_log({"audit_log": raw})
    assert len(model.events) == 1
    assert any("not a list" in message for message in model.warnings)


def test_legacy_entries_do_not_get_invented_timestamps():
    model = logic.build_observation_log({"audit_log": ["12:00:00 old text", {"message": "No time"}, None]})
    assert all(row.timestamp == "Not recorded" for row in model.events)
    assert model.events[0].message == "12:00:00 old text"
    assert all(row.note for row in model.events)


def test_nontext_event_fields_are_labelled_not_converted_to_epochs():
    model = logic.build_observation_log({"audit_log": [{"ts": 12345, "message": {"legacy": "payload"}}]})
    assert model.events[0].timestamp == "12345"
    assert "not text" in model.events[0].note
    assert "legacy" in model.events[0].message


@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing_message_fields_have_a_note(value):
    model = logic.build_observation_log({"audit_log": [{"ts": "12:00:00", "message": value}]})
    assert model.events[0].message == "Not recorded"
    assert "Message missing" in model.events[0].note


def test_no_missing_date_timezone_or_observer_is_inferred(recorded_session):
    model = logic.build_observation_log(recorded_session)
    assert model.events[0].timestamp == "23:59:59"
    report = logic.build_log_download(model).decode("utf-8")
    assert "Missing dates, time zones and observer identities are not inferred" in report
    assert "2026-08-12 23:59:59" not in report


def test_key_parameters_and_units_follow_the_producer_payload(recorded_session):
    model = logic.build_observation_log(recorded_session)
    expected = {
        "01_source_browser.frequency_mhz": ("1420.405", "MHz"),
        "03_bandpass_correction.filename2": ("off.fits", ""),
        "04_baseline_editor.selected_orders.RCP": ("4", ""),
        "05_calibration_dashboard.atmospheric.pwv": ("1.23456789", "mm"),
        "05_calibration_dashboard.atmospheric.elevation": ("0.0", "deg"),
        "05_calibration_dashboard.pss.lcp_window_mean": ("2.0", "Jy/K"),
        "06_pointing_correction.correction_factor": ("1.2", "factor"),
        "06_pointing_correction.ew_offset_deg": ("0.0", "deg"),
        "07_spectral_fitting.parameters[0].value": ("-4.2 km/s", ""),
        "07_spectral_fitting.parameters[0].error": ("0.03 km/s", ""),
        "07_spectral_fitting.converged": ("false", ""),
    }
    for field, pair in expected.items():
        row = find_parameter(model, field)
        assert (row.value, row.unit) == pair


def test_fit_type_requested_and_used_remain_distinct(recorded_session):
    model = logic.build_observation_log(recorded_session)
    assert find_parameter(model, "07_spectral_fitting.fit_type").value == "1D Gaussian"
    assert find_parameter(model, "07_spectral_fitting.fit_type_requested").value == "2D Gaussian"


def test_missing_value_is_not_filled_from_widgets_or_export_math(recorded_session):
    del recorded_session["pipeline_data"]["01_source_browser"]["source_name"]
    del recorded_session["pipeline_data"]["07_spectral_fitting"]["pss_jy_per_k"]
    model = logic.build_observation_log(recorded_session)
    assert find_parameter(model, "01_source_browser.source_name").value == "Not recorded"
    # Stage 05's means exist, but recomputing their average would invent a saved fit parameter.
    assert find_parameter(model, "07_spectral_fitting.pss_jy_per_k").value == "Not recorded"
    report = logic.build_log_download(model).decode("utf-8")
    for forbidden in ("PRIVATE-RECOVERY-TOKEN", "UNCOMMITTED-SOURCE", "UNSAVED-PREVIEW", "DO-NOT-USE", "987654321"):
        assert forbidden not in report


def test_current_values_do_not_become_historical_event_fields(recorded_session):
    recorded_session["pipeline_data"]["05_calibration_dashboard"]["atmospheric"]["pwv"] = 9.87654321
    model = logic.build_observation_log(recorded_session)
    assert "1.23456789" in model.events[1].message
    assert "9.87654321" not in str(model.events)
    assert find_parameter(model, "05_calibration_dashboard.atmospheric.pwv").value == "9.87654321"


@pytest.mark.parametrize("raw,flag,status", [
    ({"mode": "Frequency Switch"}, True, "Recorded as complete"),
    ({"mode": "Frequency Switch"}, False, "Recorded; stage not marked complete"),
    ({"complete": False}, False, "Recorded; stage incomplete"),
    ({"complete": False}, True, "Conflicting completion markers"),
    ({"complete": True}, False, "Payload complete; stage flag absent"),
    (None, True, "Completion flag only; parameters missing"),
    (None, False, "No parameters recorded"),
])
def test_stage_status_comes_from_actual_recorded_flags(raw, flag, status):
    key = "03_bandpass_correction"
    model = logic.build_observation_log({"pipeline_data": {key: raw}, "completed_stages": [key] if flag else []})
    assert find_parameter(model, f"{key}.mode").status == status


def test_legacy_mock_pointing_is_not_endorsed_as_real(recorded_session):
    recorded_session["pipeline_data"]["06_pointing_correction"]["input_source"] = "MOCK_SCAN_PEAKS"
    model = logic.build_observation_log(recorded_session)
    row = find_parameter(model, "06_pointing_correction.correction_factor")
    assert row.value == "1.2"  # preserve the record, but label it visibly
    assert "MOCK" in row.status
    assert any("MOCK" in warning for warning in model.warnings)


@pytest.mark.parametrize("raw", ["broken", [], 12, None])
def test_malformed_pipeline_is_reported_without_crashing(raw):
    model = logic.build_observation_log({"pipeline_data": raw})
    assert any("pipeline_data" in warning for warning in model.warnings)
    assert all(row.value == "Not recorded" for row in model.parameters)


def test_malformed_stage_is_reported():
    model = logic.build_observation_log({"pipeline_data": {"05_calibration_dashboard": "broken"}})
    assert any("05 Calibration" in warning for warning in model.warnings)


def test_malformed_completion_not_treated_as_a_string_collection(recorded_session):
    recorded_session["completed_stages"] = "03_bandpass_correction"
    model = logic.build_observation_log(recorded_session)
    assert find_parameter(model, "03_bandpass_correction.mode").status == "Recorded; stage not marked complete"
    assert any("completed_stages" in warning for warning in model.warnings)


def test_nested_fit_and_empty_lists_are_preserved(recorded_session):
    model = logic.build_observation_log(recorded_session)
    assert find_parameter(model, "file_loader.quarantined_files").value == "[]"
    assert '"start": -10.0' in find_parameter(model, "04_baseline_editor.blocks").value


@pytest.mark.parametrize("raw", ["legacy fit text", [], None, [{"value": 0.0}], ["legacy component"]])
def test_legacy_fit_parameters_are_safe_to_review(raw):
    model = logic.build_observation_log({"pipeline_data": {"07_spectral_fitting": {"parameters": raw}}})
    rows = [row for row in model.parameters if ".parameters" in row.field]
    assert rows
    assert logic.build_log_download(model)


def test_nonfinite_and_unsupported_values_are_labelled():
    model = logic.build_observation_log({"pipeline_data": {"05_calibration_dashboard": {
        "atmospheric": {"pwv": float("nan"), "elevation": object()},
    }}})
    assert "non-finite" in find_parameter(model, "05_calibration_dashboard.atmospheric.pwv").value
    assert "Unsupported recorded type" in find_parameter(model, "05_calibration_dashboard.atmospheric.elevation").value


def test_cycle_in_legacy_metadata_does_not_recurse_forever():
    blocks = []
    blocks.append(blocks)
    model = logic.build_observation_log({"pipeline_data": {"04_baseline_editor": {"blocks": blocks}}})
    assert "cycle or depth limit" in find_parameter(model, "04_baseline_editor.blocks").value


def test_logic_accepts_read_only_mapping_and_leaves_every_input_unchanged(recorded_session):
    before = copy.deepcopy(recorded_session)
    model = logic.build_observation_log(MappingProxyType(recorded_session))
    logic.filter_events(model.events, "fit", newest_first=True)
    logic.filter_parameters(model.parameters, query="pwv")
    logic.build_log_download(model)
    assert recorded_session == before
    recorded_session["audit_log"][0]["message"] = "Changed externally"
    assert model.events[0].message == before["audit_log"][0]["message"]


def test_no_complete_session_mapping_raises_clear_error():
    with pytest.raises(TypeError, match="session mapping"):
        logic.build_observation_log(None)


def test_parameter_filters_use_exact_stage_and_literal_search(recorded_session):
    model = logic.build_observation_log(recorded_session)
    rows = logic.filter_parameters(model.parameters, stage_key="05_calibration_dashboard", query="PWV")
    assert len(rows) == 1 and rows[0].value == "1.23456789"
    assert not logic.filter_parameters(model.parameters, query=".*")
    assert not logic.filter_parameters(model.parameters, stage_key="not-a-stage")


def test_download_contains_all_rows_despite_view_filters(recorded_session):
    model = logic.build_observation_log(recorded_session)
    expected = logic.build_log_download(model)
    assert len(logic.filter_events(model.events, "fit saved")) == 1
    assert len(logic.filter_parameters(model.parameters, stage_key="06_pointing_correction")) < len(model.parameters)
    assert logic.build_log_download(model) == expected
    text = expected.decode("utf-8")
    assert "CURRENT RECORDED PARAMETERS — NOT EVENT HISTORY" in text
    assert all(json.dumps(row.message, ensure_ascii=False) in text for row in model.events)
    assert "not a session replay file" in text
    assert "earlier reductions carried forward" in text


def test_unicode_download_and_readback_on_windows_safe_path(tmp_path, recorded_session):
    recorded_session["audit_log"].append({"ts": "12:00:00", "message": "‘quoted’ → LCP ± Δv — observer café"})
    report = logic.build_log_download(logic.build_observation_log(recorded_session))
    target = tmp_path / "review.txt"
    target.write_bytes(report)
    assert "‘quoted’ → LCP ± Δv" in target.read_text(encoding="utf-8")


def test_embedded_newlines_cannot_spoof_new_report_records():
    message = 'line1\nCURRENT RECORDED PARAMETERS\t"spoof"\r\n<script>'
    model = logic.build_observation_log({"audit_log": [{"ts": "00:00:00", "message": message}]})
    text = logic.build_log_download(model).decode("utf-8")
    assert json.dumps(message, ensure_ascii=False) in text
    assert message not in text


@pytest.mark.parametrize("session_id", ["../../private/thing", "C:\\secret\\name", "", "💫", "x" * 500])
def test_download_name_is_basename_only(session_id):
    name = logic.download_filename(session_id)
    assert "/" not in name and "\\" not in name and ":" not in name
    assert name.startswith("hartspec_observation_log_") and name.endswith(".txt")
    assert len(name) < 100


class FakeUI(types.ModuleType):
    """Record UI calls and enforce only the documented 1.32 dataframe keyword set."""

    def __init__(self, controls=None):
        super().__init__("streamlit")
        self.controls = controls or {}
        self.messages, self.frames, self.downloads, self.keys = [], [], [], []
        self.session_state = {}  # the helper must not write this directly

    def container(self, **kwargs):
        return nullcontext()

    def columns(self, values):
        return [nullcontext() for _ in values]

    def expander(self, *args, **kwargs):
        return nullcontext()

    def markdown(self, body, **kwargs):
        self.messages.append((str(body), kwargs.get("unsafe_allow_html", False)))

    caption = warning = markdown

    def text_input(self, label, *, key, **kwargs):
        self.keys.append(key)
        return self.controls.get(key, "")

    def selectbox(self, label, options, *, key, **kwargs):
        self.keys.append(key)
        return self.controls.get(key, options[0])

    def dataframe(self, data, *, height, use_container_width, hide_index):
        assert height in (240, 320) and use_container_width and hide_index
        # Execute real Pandas Styler generation; this is not a browser render.
        data.to_html()
        self.frames.append((data.data.copy(deep=True), height))

    def download_button(self, label, data, file_name, mime, type, key):
        self.keys.append(key)
        self.downloads.append((label, data, file_name, mime))
        return self.controls.get(key, False)


@pytest.fixture
def panel(monkeypatch):
    """Import the actual UI helper inside a private package and a fake Streamlit module."""
    package_name = "_hartspec_fr20_ui_tests"
    package = types.ModuleType(package_name)
    package.__path__ = [str(APP_ROOT / "utils")]
    monkeypatch.setitem(sys.modules, package_name, package)
    monkeypatch.setitem(sys.modules, f"{package_name}.observation_log_logic", logic)
    fake = FakeUI()
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    spec = importlib.util.spec_from_file_location(f"{package_name}.observation_log_ui", UI_PATH)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module, fake


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_ui_theme_tables_and_download_do_not_write_session(panel, recorded_session, mode):
    module, ui = panel
    theme = ({"text-body": "#334155", "bg-panel": "#FFFFFF", "bg-panel-alt": "#F8FAFC"} if mode == "light" else
             {"text-body": "#CBD5E1", "bg-panel": "#1E293B", "bg-panel-alt": "#243044"})
    before = copy.deepcopy(recorded_session)
    module.render_observation_log(MappingProxyType(recorded_session), theme=MappingProxyType(theme))
    assert len(ui.frames) == 2 and len(ui.downloads) == 1
    assert ui.frames[0][0]["Entry"].tolist() == [3, 2, 1]
    assert recorded_session == before and ui.session_state == {}
    assert all(key.startswith("export_observation_log_") for key in ui.keys)


def test_ui_filtering_and_download_click_preserve_pipeline_and_full_report(panel, recorded_session):
    module, ui = panel
    ui.controls.update({"export_observation_log_search": "pair",
                        "export_observation_log_stage": "03_bandpass_correction",
                        "export_observation_log_parameter_search": "file 2", "export_observation_log_download": True})
    theme = {"text-body": "#334155", "bg-panel": "#FFFFFF", "bg-panel-alt": "#F8FAFC"}
    before = copy.deepcopy(recorded_session)
    module.render_observation_log(recorded_session, theme=theme)
    assert ui.frames[0][0]["Entry"].tolist() == [1]
    assert "Calibration committed" in ui.downloads[0][1].decode("utf-8")
    assert "05 Calibration Dashboard" in ui.downloads[0][1].decode("utf-8")
    assert recorded_session == before and ui.session_state == {}


def test_empty_ui_and_missing_search_do_not_crash(panel):
    module, ui = panel
    ui.controls["export_observation_log_parameter_search"] = "no matching record"
    module.render_observation_log({}, theme={"text-body": "#334155", "bg-panel": "#FFFFFF", "bg-panel-alt": "#F8FAFC"})
    assert ui.frames == []
    assert any("No actions recorded" in text for text, _ in ui.messages)
    assert len(ui.downloads) == 1


def test_html_content_is_never_injected_through_markdown(panel, recorded_session):
    module, ui = panel
    payload = "<script>alert('not executed')</script>"
    recorded_session["audit_log"][0]["message"] = payload
    recorded_session["pipeline_data"]["01_source_browser"]["source_name"] = payload
    module.render_observation_log(recorded_session,
                                  theme={"text-body": "#334155", "bg-panel": "#FFFFFF", "bg-panel-alt": "#F8FAFC"})
    assert all(payload not in text for text, unsafe in ui.messages if unsafe)
    assert payload in ui.frames[0][0]["Message"].tolist()


def test_new_modules_do_not_call_persistence_or_scientific_apis():
    for path in (LOGIC_PATH, UI_PATH):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        calls = {ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
        prohibited = ("save_session", "checkpoint_session", "log_event", "mark_stage_complete", "write_text",
                      "write_bytes", "read_bridge", "graph3", "open")
        assert not any(call.split(".")[-1] in prohibited for call in calls)
        imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        assert not imported.intersection({"numpy", "scipy", "astropy", "clc"})


def test_page8_uses_new_panel_and_keeps_checkpoint_after_completion_action():
    text = PAGE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(text)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    panel_calls = [node for node in calls if ast.unparse(node.func) == "render_observation_log"]
    assert len(panel_calls) == 1
    assert ast.unparse(panel_calls[0].args[0]) == "st.session_state"
    assert "log_text =" not in text
    assert text.index('"Mark export complete"') < text.rindex("session_store.checkpoint_session(")
    assert '"Export CSV"' in text and '"Export graphs (PDF)"' in text


def test_new_text_reads_are_explicit_utf8_and_sources_parse_as_python311():
    for path in (LOGIC_PATH, UI_PATH, Path(__file__)):
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, feature_version=(3, 11))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in ("read_text", "write_text"):
                    assert any(keyword.arg == "encoding" for keyword in node.keywords)


def test_view_controls_do_not_change_the_real_checkpoint_payload(recorded_session):
    """Execute the unchanged store's payload selector; substitute only its final type-normalising copy."""
    path = APP_ROOT / "utils" / "session_store.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "_session_payload")
    namespace = {"Any": object, "st": types.SimpleNamespace(session_state=recorded_session),
                 "checkpoint_store": types.SimpleNamespace(json_safe=copy.deepcopy)}
    code = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    exec(compile(code, str(path), "exec"), namespace)
    before = namespace["_session_payload"]()
    recorded_session.update({"export_observation_log_search": "PWV",
                             "export_observation_log_order": "Last recorded first",
                             "export_observation_log_stage": "05_calibration_dashboard",
                             "export_observation_log_parameter_search": "elevation",
                             "export_observation_log_download": True})
    assert namespace["_session_payload"]() == before
