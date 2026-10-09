# test_file_validation_handoff.py — FR-02/03: eligibility, invalidation and exact-pair replay.
"""Execute production handoff/state code and page orchestration headlessly.

Streamlit/CLC/Astropy I/O interfaces are substituted. The uploaded bandpass helper runs unchanged. Quarantine uses the actual
wrapper and temporary files; spectra are marker arrays, not science fixtures.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import sys
import types
from contextlib import nullcontext
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "hartspec_gui" if (ROOT / "hartspec_gui" / "utils").is_dir() else ROOT


class StopRun(BaseException):
    """Navigation/stop must not be swallowed by application error handling."""


class State(dict):
    """Detect writes to already-mounted controls, unlike a plain test dict."""

    def __init__(self):
        super().__init__()
        self.rendered = set()

    def __setitem__(self, key, value):
        if key in self.rendered:
            raise AssertionError(f"Already-mounted widget overwritten: {key}")
        super().__setitem__(key, value)

    def update(self, *args, **kwargs):
        for key, value in dict(*args, **kwargs).items():
            self[key] = value


class UI(types.ModuleType):
    """Widget facade with control-flow semantics; no browser rendering claim."""

    def __init__(self):
        super().__init__("streamlit")
        self.session_state = State()
        self.clicked = set()
        self.messages = []
        self.navigation = None
        self.callbacks = {}
        self.figures = []

    def begin(self, clicked=(), changes=None):
        self.clicked = set(clicked)
        self.session_state.rendered.clear()
        self.messages.clear()
        self.navigation = None
        self.figures.clear()
        for key, value in (changes or {}).items():
            self.session_state[key] = value
        for key in (changes or {}):
            callback = self.callbacks.get(key)
            if callback:
                callback()

    def cache_data(self, **kwargs):
        return lambda function: function

    def set_page_config(self, **kwargs):
        pass

    def markdown(self, value, **kwargs):
        self.messages.append(str(value))

    caption = info = error = warning = success = markdown

    def write(self, *args, **kwargs):
        pass

    def container(self, **kwargs):
        return nullcontext()

    def expander(self, *args, **kwargs):
        return nullcontext()

    def spinner(self, *args, **kwargs):
        return nullcontext()

    def form(self, *args, **kwargs):
        return nullcontext()

    def columns(self, widths):
        return [nullcontext() for _ in range(widths if isinstance(widths, int) else len(widths))]

    def empty(self):
        return self

    def button(self, label, *, key, disabled=False, **kwargs):
        return key in self.clicked and not disabled

    def checkbox(self, label, *, key, **kwargs):
        self.session_state.setdefault(key, False)
        self.session_state.rendered.add(key)
        return self.session_state[key]

    def radio(self, label, options, *, key, on_change=None, **kwargs):
        self.session_state.setdefault(key, options[0])
        self.session_state.rendered.add(key)
        self.callbacks[key] = on_change
        assert self.session_state[key] in options
        return self.session_state[key]

    def selectbox(self, label, options, *, key, on_change=None, **kwargs):
        options = list(options)
        self.session_state.setdefault(key, options[0])
        self.session_state.rendered.add(key)
        self.callbacks[key] = on_change
        assert self.session_state[key] in options
        return self.session_state[key]

    def text_input(self, label, *, key, **kwargs):
        self.session_state.setdefault(key, "")
        self.session_state.rendered.add(key)
        return self.session_state[key]

    text_area = text_input

    def dataframe(self, *args, **kwargs):
        pass

    def plotly_chart(self, figure, **kwargs):
        self.figures.append(figure)

    def switch_page(self, path):
        self.navigation = path
        raise StopRun()

    def stop(self):
        raise StopRun()

    rerun = stop


def spectrum(marker=1):
    """Distinct small spectra for provenance assertions, not numerical validation."""
    return {"Vlsr": [0.0, 1.0], "LCP": [marker, marker + 1], "RCP": [marker + 2, marker + 3]}


@pytest.fixture
def app(monkeypatch, tmp_path):
    """Load actual helpers/pages without a running Streamlit/CLC installation."""
    ui = UI()
    utils = types.ModuleType("utils")
    utils.__path__ = [str(APP_ROOT / "utils")]
    monkeypatch.setitem(sys.modules, "streamlit", ui)
    monkeypatch.setitem(sys.modules, "utils", utils)
    env = types.ModuleType("utils.env")
    env.load_dotenv_if_present = lambda: None
    monkeypatch.setitem(sys.modules, "utils.env", env)
    monkeypatch.setenv("SESSIONS_PATH", str(tmp_path / "sessions"))
    archive = tmp_path / "archive"
    archive.mkdir()
    monkeypatch.setenv("FITS_ARCHIVE_PATH", str(archive))
    fakefits = types.ModuleType("astropy.io.fits")
    fakefits.conf = types.SimpleNamespace(use_memmap=False)
    fakefits.VerifyError = ValueError
    astropy = types.ModuleType("astropy")
    astropy.__path__ = []
    io = types.ModuleType("astropy.io")
    io.fits = fakefits
    astropy.io = io
    for name, value in (("astropy", astropy), ("astropy.io", io), ("astropy.io.fits", fakefits)):
        monkeypatch.setitem(sys.modules, name, value)
    matplotlib = types.ModuleType("matplotlib")
    matplotlib.use = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "matplotlib", matplotlib)
    # The unchanged ingestion wrapper can import without loading real CLC code.
    for name in ("load_file", "load_file2"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))

    def load(name):
        spec = importlib.util.spec_from_file_location(f"utils.{name}", APP_ROOT / "utils" / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, spec.name, module)
        setattr(utils, name, module)
        spec.loader.exec_module(module)
        return module

    store = load("session_store")
    store.init_session_state()
    invalidation = load("stage_invalidation")
    logic = load("file_loader_logic")
    ingest = load("fits_ingest")
    load("source_browser_logic")
    load("styles")
    bridge = load("baseline_editor_bridge")
    resolver = load("spectrum_resolution")
    sidebar = types.ModuleType("utils.sidebar")
    sidebar.render_sidebar = lambda current_stage: None
    utils.sidebar = sidebar
    monkeypatch.setitem(sys.modules, "utils.sidebar", sidebar)

    # Run the provided pair-entry helper, not the pre-merge spectrum-only mock.
    adapter = load("bandpass_correction_logic")
    calls = []
    real_build = adapter.build_bandpass_result

    def build(mode, pair):
        calls.append((mode, pair))
        return real_build(mode, pair)

    monkeypatch.setattr(adapter, "build_bandpass_result", build)

    spec = importlib.util.spec_from_file_location("_validation_loader_page", APP_ROOT / "pages/02_File_Loader.py")
    page = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, page)
    spec.loader.exec_module(page)

    def run_bandpass(clicked=(), changes=None):
        ui.begin(clicked, changes)
        path = APP_ROOT / "pages/03_Bandpass_Correction.py"
        namespace = {"__name__": "_validation_bandpass_page", "__file__": str(path)}
        try:
            exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
        except StopRun:
            pass
        return namespace

    return types.SimpleNamespace(
        ui=ui, state=ui.session_state, store=store, invalidation=invalidation, logic=logic,
        ingest=ingest, page=page, bridge=bridge, resolver=resolver, fits=fakefits, archive=archive,
        run_bandpass=run_bandpass, calls=calls, adapter=adapter,
    )


def seed_files(app, names=("a.fits", "b.fits")):
    app.state["pipeline_data"]["01_source_browser"] = {
        "selected_files": list(names), "source_name": "A", "frequency_mhz": 1420.405,
        "archive_root": str(app.archive),
    }
    app.state["completed_stages"].add("01_source_browser")
    for i, name in enumerate(names):
        (app.archive / name).parent.mkdir(parents=True, exist_ok=True)
        (app.archive / name).write_bytes(f"TEST-ONLY {i}".encode())
        cache_file(app, name, i + 1)
    return names


def cache_file(app, name, marker=1, *, load_ok=True, verify_ok=True):
    app.state[f"file_loader_ingest_result::{name}"] = app.ingest.IngestResult(
        filename=name, path=app.archive / name, ok=load_ok, convention="date", spectrum=spectrum(marker),
        load_errors={} if load_ok else {"date": "Fixture load failed"},
    )
    if verify_ok is not None:
        app.state[f"file_loader_verify_result::{name}"] = app.ingest.VerificationResult(
            name, app.archive / name, verify_ok, [] if verify_ok else ["Fixture structural error"],
        )
    else:
        app.state.pop(f"file_loader_verify_result::{name}", None)


def publish(app, names=None, *, new_id="new-validated-inputs"):
    return app.logic.publish_validated_handoff(
        app.state, names or app.page._get_target_filenames(), app.archive, new_id=lambda: new_id,
    )


def seed_derived(app):
    for key in app.invalidation.LOADED_INPUT_DEPENDENT_STAGE_KEYS:
        app.state["pipeline_data"][key] = {"old": True}
        app.state["completed_stages"].add(key)
    app.state.update({
        "bandpass_corrected_spectrum": spectrum(50), "bandpass_display_result": {"old": True},
        "baseline_corrected_spectrum": spectrum(60), "baseline_editor_seen_event_ids": ["old"],
        "calibrated_spectrum": spectrum(90), "latest_fit": {"old": True},
        "pointing_cached_result": {"old": True}, "calibration_cached_result": {"old": True},
        "export_cached_result": {"old": True}, "spectral_fitting_cached_result": {"old": True},
        "theme": "dark", "authentication_status": True, "username": "observer",
    })
    app.bridge.write_bridge(app.state["session_id"], {
        "flattened_spectrum": spectrum(60), "spectrum_fingerprint": app.bridge.spectrum_fingerprint(spectrum(50)),
        "complete": True, "events": [],
    })


def resolved(app):
    return app.resolver.resolve_spectrum(
        app.state, read_bridge=app.bridge.read_bridge, fingerprint=app.bridge.spectrum_fingerprint,
    )


@pytest.mark.parametrize("load_ok,verify_ok,quarantined,expected", [
    (True, True, False, True), (False, True, False, False), (True, False, False, False),
    (False, False, False, False), (True, None, False, False), (False, None, False, False),
    (True, True, True, False), (True, False, True, False),
])
def test_independent_checks_are_both_required(app, load_ok, verify_ok, quarantined, expected):
    cache_file(app, "a.fits", load_ok=load_ok, verify_ok=verify_ok)
    if quarantined:
        app.state["file_loader_quarantined"] = {"a.fits"}
    assert bool(app.logic.eligible_loaded_entries(app.state, ["a.fits"])) is expected


@pytest.mark.parametrize("bad_spectrum", [None, {}, [], "not a spectrum", {"Vlsr": [0]}])
def test_missing_spectrum_is_not_published(app, bad_spectrum):
    cache_file(app, "a.fits")
    app.state["file_loader_ingest_result::a.fits"].spectrum = bad_spectrum
    assert app.logic.eligible_loaded_entries(app.state, ["a.fits"]) == []


def test_missing_load_cache_fails_closed(app):
    assert app.logic.eligible_loaded_entries(app.state, ["missing.fits"]) == []


def test_no_checksum_keyword_is_not_a_failure(app):
    cache_file(app, "a.fits")
    assert not app.state["file_loader_verify_result::a.fits"].checksum_checked
    assert len(app.logic.eligible_loaded_entries(app.state, ["a.fits"])) == 1


def test_order_and_spectrum_objects_are_preserved(app):
    names = seed_files(app, ("a.fits", "bad.fits", "b.fits"))
    app.state["file_loader_verify_result::bad.fits"].ok = False
    entries = app.logic.eligible_loaded_entries(app.state, names)
    assert [e["filename"] for e in entries] == ["a.fits", "b.fits"]
    assert entries[0]["spectrum"] is app.state["file_loader_ingest_result::a.fits"].spectrum
    assert entries[1]["spectrum"] is app.state["file_loader_ingest_result::b.fits"].spectrum


def test_first_validation_does_not_needlessly_rotate_session(app):
    seed_files(app)
    previous_id = app.state["session_id"]
    result = publish(app)
    assert not result.invalidated
    assert app.state["session_id"] == previous_id
    assert result.eligible_files == ("a.fits", "b.fits")
    assert app.state["loaded_spectrum"] is app.state["loaded_spectra"][0]


def test_unchanged_validation_keeps_progress_and_does_not_call_id_factory(app):
    seed_files(app)
    publish(app)
    seed_derived(app)
    before = copy.deepcopy(app.state)
    result = app.logic.publish_validated_handoff(
        app.state, app.page._get_target_filenames(), app.archive,
        new_id=lambda: pytest.fail("Unchanged input must not reserve a new ID"),
    )
    assert not result.invalidated
    assert app.state == before


def test_changed_eligibility_clears_all_file_dependent_stages_not_loader_evidence(app):
    seed_files(app)
    publish(app)
    seed_derived(app)
    app.state["completed_stages"].add("file_loader")
    app.state["pipeline_data"]["extension"] = {"keep": True}
    app.state["file_loader_manual_mapping_global"] = {"Vlsr": "HDU0:SPVLSR"}
    app.state["manual_map_global_Vlsr"] = "HDU0:SPVLSR"
    app.state["file_loader_verify_result::a.fits"].ok = False
    result = publish(app)
    assert result.invalidated
    assert app.state["completed_stages"] == {"01_source_browser", "file_loader"}
    assert app.state["session_id"] == "new-validated-inputs"
    assert app.state["loaded_spectrum"] is app.state["file_loader_ingest_result::b.fits"].spectrum
    for key in ("bandpass_corrected_spectrum", "baseline_corrected_spectrum", "calibrated_spectrum",
                "latest_fit", "pointing_cached_result", "export_cached_result"):
        assert key not in app.state
    assert app.state["theme"] == "dark"
    assert app.state["authentication_status"] is True
    assert app.state["username"] == "observer"
    assert app.state["pipeline_data"]["extension"] == {"keep": True}
    assert app.state["manual_map_global_Vlsr"] == "HDU0:SPVLSR"
    assert app.state["file_loader_ingest_result::a.fits"].ok
    assert not app.state["file_loader_verify_result::a.fits"].ok
    assert resolved(app).source_key == "raw"


def test_old_bridge_and_late_callback_cannot_resurrect_old_results(app):
    seed_files(app)
    publish(app)
    seed_derived(app)
    old_id = app.state["session_id"]
    app.store.save_session()
    old_session = app.store.SESSIONS_DIR / f"{old_id}.json"
    old_bridge = app.bridge._bridge_path(old_id)
    before = {p: p.read_bytes() for p in (old_session, old_bridge)}
    app.state["file_loader_verify_result::a.fits"].ok = False
    publish(app)
    assert {p: p.read_bytes() for p in before} == before
    app.bridge.write_bridge(old_id, {"flattened_spectrum": spectrum(999), "complete": True})
    assert resolved(app).source_key == "raw"
    assert resolved(app).channels["LCP"].tolist() == [2, 3]


def test_all_invalid_removes_loader_completion_and_raw_fallback(app):
    seed_files(app)
    publish(app)
    seed_derived(app)
    app.state["completed_stages"].add("file_loader")
    for name in app.page._get_target_filenames():
        app.state[f"file_loader_verify_result::{name}"].ok = False
    publish(app)
    assert not app.state["file_loader_load_done"]
    assert app.state["loaded_spectra"] == []
    assert "loaded_spectrum" not in app.state
    assert app.state["completed_stages"] == {"01_source_browser"}
    assert resolved(app).is_placeholder


@pytest.mark.parametrize("legacy_live", [False, True])
def test_legacy_contaminated_handoff_is_invalidated(app, legacy_live):
    seed_files(app)
    if legacy_live:
        app.state["loaded_spectra"] = [
            app.state[f"file_loader_ingest_result::{name}"].spectrum for name in app.page._get_target_filenames()
        ]
    seed_derived(app)
    app.state["file_loader_verify_result::a.fits"].ok = False
    assert publish(app).invalidated
    assert not resolved(app).is_calibrated


@pytest.mark.parametrize("legacy_live", [False, True])
def test_legacy_all_valid_inputs_keep_replay_parameters(app, legacy_live):
    seed_files(app)
    seed_derived(app)
    if legacy_live:
        app.state["loaded_spectra"] = [
            app.state[f"file_loader_ingest_result::{name}"].spectrum for name in app.page._get_target_filenames()
        ]
    old_id = app.state["session_id"]
    assert not publish(app).invalidated
    assert app.state["session_id"] == old_id
    assert "04_baseline_editor" in app.state["pipeline_data"]


def test_saved_signature_survives_load_without_discarding_replay_parameters(app):
    seed_files(app)
    publish(app)
    seed_derived(app)
    saved = app.store.save_session()
    old_id = app.state["session_id"]
    app.store.load_session(saved, navigate=False)
    cache_file(app, "a.fits", 1)
    cache_file(app, "b.fits", 2)
    result = publish(app)
    assert not result.invalidated
    assert app.state["session_id"] == old_id
    assert "04_baseline_editor" in app.state["pipeline_data"]


def test_json_summary_contains_only_metadata_and_actual_classifications(app):
    seed_files(app, ("a.fits", "bad.fits", "moved.fits"))
    app.state["file_loader_verify_result::bad.fits"].ok = False
    app.state["file_loader_quarantined"] = {"moved.fits"}
    publish(app)
    summary = app.state["pipeline_data"]["file_loader"]
    assert summary["eligible_files"] == ["a.fits"]
    assert summary["flagged_files"] == ["bad.fits"]
    assert summary["quarantined_files"] == ["moved.fits"]
    assert "spectrum" not in json.dumps(summary)
    assert json.loads(app.store.save_session().read_text())["pipeline_data"]["file_loader"] == summary


@pytest.mark.parametrize("new_id", ["", "../bad", "same-id", "unsafe.dot", None])
def test_invalid_replacement_id_leaves_active_state_untouched(app, new_id):
    seed_files(app)
    publish(app)
    app.state["session_id"] = "same-id"
    seed_derived(app)
    app.state["file_loader_verify_result::a.fits"].ok = False
    before = copy.deepcopy(app.state)
    with pytest.raises(ValueError, match="session ID"):
        publish(app, new_id=new_id)
    assert app.state == before


def test_reordered_inputs_invalidate_even_with_same_files(app):
    seed_files(app)
    publish(app)
    assert publish(app, ["b.fits", "a.fits"]).invalidated


def test_equivalent_relative_absolute_paths_do_not_reset(app):
    seed_files(app)
    publish(app)
    absolute = [str(app.archive / name) for name in ("a.fits", "b.fits")]
    for name, full in zip(("a.fits", "b.fits"), absolute):
        for prefix in ("file_loader_ingest_result::", "file_loader_verify_result::"):
            app.state[prefix + full] = app.state[prefix + name]
    assert not publish(app, absolute).invalidated


def test_baseline_only_invalidation_still_preserves_pointing(app):
    seed_files(app)
    publish(app)
    seed_derived(app)
    app.invalidation.invalidate_baseline_dependents(app.state)
    assert "06_pointing_correction" in app.state["completed_stages"]
    assert "pointing_cached_result" in app.state


def test_page_loads_all_then_validates_all_and_counts_structural_failure(app, monkeypatch):
    names = seed_files(app, ("a.fits", "bad.fits", "b.fits"))
    events = []
    for name in names:
        app.state.pop(f"file_loader_ingest_result::{name}")
        app.state.pop(f"file_loader_verify_result::{name}")

    def load(path):
        events.append(("load", path.name))
        return app.ingest.IngestResult(path.name, path, True, "date", spectrum(names.index(path.name)), {})

    def verify(path):
        events.append(("verify", path.name))
        return app.ingest.VerificationResult(path.name, path, path.name != "bad.fits", ["test failure"])

    monkeypatch.setattr(app.ingest, "ingest_fits_file", load)
    monkeypatch.setattr(app.ingest, "verify_fits_file", verify)
    app.page._render_load_progress()
    assert events == [(kind, name) for kind in ("load", "verify") for name in names]
    assert len(app.state["loaded_spectra"]) == 2
    assert any("2 Valid (Loaded)" in msg and "1 Flagged" in msg for msg in app.ui.messages)
    rows = app.page._build_validation_rows(list(names))
    assert [row["status"] for row in rows] == ["ok", "error", "ok"]
    app.page._render_load_progress()
    assert len(events) == 6  # no repeat FITS I/O during ordinary reruns or table rendering


def test_page_does_not_verify_a_failed_load(app, monkeypatch):
    seed_files(app, ("bad.fits",))
    app.state["file_loader_ingest_result::bad.fits"].ok = False
    monkeypatch.setattr(app.ingest, "verify_fits_file", lambda path: pytest.fail("Unloaded input should not verify"))
    app.page._render_load_progress()
    assert app.state["loaded_spectra"] == []
    assert not app.state["file_loader_load_done"]


def test_page_no_spectrum_has_consistent_flagged_row(app):
    seed_files(app, ("bad.fits",))
    app.state["file_loader_ingest_result::bad.fits"].spectrum = None
    app.page._render_load_progress()
    assert not app.state["file_loader_load_done"]
    assert app.page._build_validation_rows(["bad.fits"])[0]["status"] == "error"


def test_successful_quarantine_immediately_removes_used_input_and_derived_results(app):
    seed_files(app)
    publish(app)
    seed_derived(app)
    old_id = app.state["session_id"]
    app.page._quarantine_file("a.fits")
    assert not (app.archive / "a.fits").exists()
    assert (app.archive / "Flagged" / "a.fits").is_file()
    assert app.state["session_id"] != old_id
    assert len(app.state["loaded_spectra"]) == 1
    assert "file_loader_ingest_result::a.fits" not in app.state
    assert "calibrated_spectrum" not in app.state
    assert "06_pointing_correction" not in app.state["completed_stages"]
    assert not resolved(app).is_calibrated
    assert any("quarantined" in event["message"] for event in app.state["audit_log"])


def test_quarantining_an_already_excluded_file_keeps_usable_results(app):
    seed_files(app)
    app.state["file_loader_verify_result::a.fits"].ok = False
    publish(app)
    seed_derived(app)
    old_id = app.state["session_id"]
    app.page._quarantine_file("a.fits")
    assert app.state["session_id"] == old_id
    assert resolved(app).is_calibrated
    assert (app.archive / "Flagged" / "a.fits").exists()


def test_failed_quarantine_does_not_claim_move_or_invalidate(app, monkeypatch):
    seed_files(app)
    publish(app)
    seed_derived(app)
    old_id = app.state["session_id"]
    def fail(name):
        raise app.ingest.QuarantineError("Permission denied (fixture)")
    monkeypatch.setattr(app.ingest, "move_to_quarantine", fail)
    app.page._quarantine_file("a.fits")
    assert app.state["session_id"] == old_id
    assert "a.fits" not in app.state.get("file_loader_quarantined", set())
    assert (app.archive / "a.fits").exists()
    assert resolved(app).is_calibrated
    assert "Permission denied" in app.state["file_loader_quarantine_error"]


def test_pending_quarantine_does_not_exclude_or_invalidate(app):
    seed_files(app)
    publish(app)
    seed_derived(app)
    old_id = app.state["session_id"]
    app.page._request_quarantine("a.fits")
    assert not publish(app).invalidated
    assert app.state["session_id"] == old_id
    assert resolved(app).is_calibrated
    assert (app.archive / "a.fits").exists()


def test_all_quarantined_branch_clears_current_raw_fallback(app):
    seed_files(app)
    publish(app)
    seed_derived(app)
    app.state["file_loader_quarantined"] = {"a.fits", "b.fits"}
    app.page._render_load_progress()
    assert app.state["loaded_spectra"] == []
    assert not app.state["file_loader_load_done"]
    assert resolved(app).is_placeholder


def test_loaded_session_restores_quarantine_exclusion_without_reloading_moved_path(app, monkeypatch):
    seed_files(app)
    publish(app)
    app.page._quarantine_file("a.fits")
    saved = app.store.save_session()
    app.store.load_session(saved, navigate=False)
    calls = []
    def load(path):
        calls.append(path.name)
        return app.ingest.IngestResult(path.name, path, True, "date", spectrum(2))
    monkeypatch.setattr(app.ingest, "ingest_fits_file", load)
    monkeypatch.setattr(
        app.ingest, "verify_fits_file", lambda path: app.ingest.VerificationResult(path.name, path, True)
    )
    app.page._render_load_progress()
    assert calls == ["b.fits"]
    assert app.state["file_loader_quarantined"] == {"a.fits"}
    assert app.state["pipeline_data"]["file_loader"]["quarantined_files"] == ["a.fits"]


@pytest.mark.parametrize("saved", [{}, {"file_loader": None}, {"file_loader": {"quarantined_files": "bad"}},
                                  {"file_loader": {"quarantined_files": [None]}}])
def test_malformed_saved_exclusions_do_not_raise_or_move_files(app, saved):
    app.state["pipeline_data"] = saved
    app.logic.restore_saved_quarantine(app.state)
    assert not app.state.get("file_loader_quarantined")


def test_current_runtime_exclusions_take_precedence_over_saved_list(app):
    app.state["file_loader_quarantined"] = {"current.fits"}
    app.state["pipeline_data"]["file_loader"] = {"quarantined_files": ["saved.fits"]}
    app.logic.restore_saved_quarantine(app.state)
    assert app.state["file_loader_quarantined"] == {"current.fits"}


def install_metadata(app):
    """Fake only FITS header reading; pairing logic runs from the real page."""
    def open_headers(path):
        sp_point = 1 if path.name.startswith("pointing") else 0
        headers = [types.SimpleNamespace(header={"SPPOINT": sp_point}), types.SimpleNamespace(header={}),
                   types.SimpleNamespace(header={"POSITION": "ON"})]
        class Headers(list):
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
        return Headers(headers)
    app.fits.open = open_headers


@pytest.mark.parametrize("replay", [False, True])
def test_bandpass_manual_and_replay_use_exact_verified_science_pair(app, replay):
    seed_files(app, ("pointing.fits", "bad.fits", "bad_ref.fits", "a.fits", "b.fits"))
    app.state["file_loader_verify_result::bad.fits"].ok = False
    publish(app)
    app.state["completed_stages"].add("file_loader")
    if replay:
        app.state["completed_stages"].add("03_bandpass_correction")
        app.state["pipeline_data"]["03_bandpass_correction"] = {"mode": "Position Switch"}
    install_metadata(app)
    app.run_bandpass(() if replay else {"apply_bandpass_correction"})
    assert len(app.calls) == 1
    mode, pair = app.calls[0]
    assert mode == ("Position Switch" if replay else "Frequency Switch")
    assert pair[0]["spectrum"] is app.state["file_loader_ingest_result::a.fits"].spectrum
    assert pair[1]["spectrum"] is app.state["file_loader_ingest_result::b.fits"].spectrum
    assert "03_bandpass_correction" in app.state["completed_stages"]


@pytest.mark.parametrize("excluded", ["failed", "missing", "quarantined"])
def test_direct_bandpass_visit_cannot_use_legacy_unverified_cache(app, excluded):
    seed_files(app)
    # Simulate a pre-patch loaded_spectra list still containing both inputs.
    app.state["loaded_spectra"] = [app.state[f"file_loader_ingest_result::{n}"].spectrum for n in ("a.fits", "b.fits")]
    app.state["completed_stages"].update({"file_loader", "03_bandpass_correction"})
    app.state["pipeline_data"]["03_bandpass_correction"] = {"mode": "Frequency Switch"}
    if excluded == "missing":
        app.state.pop("file_loader_verify_result::a.fits")
    elif excluded == "failed":
        app.state["file_loader_verify_result::a.fits"].ok = False
    else:
        app.state["file_loader_quarantined"] = {"a.fits"}
    install_metadata(app)
    app.run_bandpass({"apply_bandpass_correction"})
    assert app.calls == []
    assert "03_bandpass_correction" not in app.state["completed_stages"]
    assert any("at least two successfully loaded FITS spectra" in msg for msg in app.ui.messages)
    assert len(app.state["loaded_spectra"]) == 1


def test_full_loader_page_marks_complete_only_for_validated_input(app, monkeypatch):
    seed_files(app, ("bad.fits",))
    app.state["file_loader_verify_result::bad.fits"].ok = False
    # Header display is unrelated to this test and needs real Astropy headers.
    monkeypatch.setattr(app.page, "_render_header_fields_table", lambda: None)
    app.page.main()
    assert "file_loader" not in app.state["completed_stages"]
    assert app.ui.navigation is None
    assert not app.state["file_loader_load_done"]


def test_full_loader_page_valid_input_and_unchanged_rerun_do_not_reset(app, monkeypatch):
    seed_files(app)
    monkeypatch.setattr(app.page, "_render_header_fields_table", lambda: None)
    app.page.main()
    assert "file_loader" in app.state["completed_stages"]
    seed_derived(app)
    old_id = app.state["session_id"]
    app.ui.begin()
    app.page.main()
    assert app.state["session_id"] == old_id
    assert resolved(app).is_calibrated


def test_direct_bandpass_discards_old_display_even_when_two_alternatives_remain(app):
    seed_files(app, ("bad.fits", "bad_ref.fits", "a.fits", "b.fits"))
    app.state["loaded_spectra"] = [
        app.state[f"file_loader_ingest_result::{name}"].spectrum for name in app.page._get_target_filenames()
    ]
    seed_derived(app)
    old_id = app.state["session_id"]
    app.state["completed_stages"].add("file_loader")
    app.state["pipeline_data"]["03_bandpass_correction"] = {"mode": "Frequency Switch"}
    app.state["bandpass_applied_mode"] = "Frequency Switch"
    app.state["file_loader_verify_result::bad.fits"].ok = False
    install_metadata(app)
    app.run_bandpass()
    assert app.state["session_id"] != old_id
    assert "calibrated_spectrum" not in app.state
    # JC's automatic apply is retained, but it must use the new verified pair.
    assert "03_bandpass_correction" in app.state["completed_stages"]
    assert len(app.calls) == 1
    assert [entry["filename"] for entry in app.calls[0][1]] == ["a.fits", "b.fits"]
    assert app.state["bandpass_display_result"]["filename1"] == "a.fits"
    assert len(app.state["loaded_spectra"]) == 3


def test_cancel_quarantine_from_real_table_preserves_active_reduction(app):
    seed_files(app, ("bad.fits", "a.fits"))
    app.state["file_loader_verify_result::bad.fits"].ok = False
    publish(app)
    seed_derived(app)
    old_id = app.state["session_id"]
    app.page._request_quarantine("bad.fits")
    app.ui.begin({"cancel_quarantine_bad.fits"})
    with pytest.raises(StopRun):
        app.page._render_validation_table()
    assert app.state["file_loader_pending_quarantine"] is None
    assert app.state["session_id"] == old_id
    assert resolved(app).is_calibrated
    assert (app.archive / "bad.fits").exists()
    assert not (app.archive / "Flagged").exists()


def test_bulk_quarantine_confirmation_excludes_files_without_discarding_unaffected_results(app):
    names = seed_files(app, ("bad1.fits", "a.fits", "bad2.fits"))
    for name in (names[0], names[2]):
        app.state[f"file_loader_verify_result::{name}"].ok = False
    publish(app)
    seed_derived(app)
    old_id = app.state["session_id"]
    app.state["file_loader_pending_quarantine_all"] = True
    app.ui.begin({"confirm_quarantine_all"})
    with pytest.raises(StopRun):
        app.page._render_validation_table()
    assert app.state["file_loader_quarantined"] == {"bad1.fits", "bad2.fits"}
    assert app.state["session_id"] == old_id
    assert resolved(app).is_calibrated
    assert (app.archive / "a.fits").exists()
    assert all((app.archive / "Flagged" / name).exists() for name in (names[0], names[2]))
    assert app.state["pipeline_data"]["file_loader"]["eligible_files"] == ["a.fits"]


def test_bulk_quarantine_partial_failure_retains_failed_file_and_reports_failure(app, monkeypatch):
    seed_files(app, ("bad1.fits", "a.fits", "bad2.fits"))
    for name in ("bad1.fits", "bad2.fits"):
        app.state[f"file_loader_verify_result::{name}"].ok = False
    publish(app)
    original_move = app.ingest.move_to_quarantine
    def move(name):
        if name == "bad2.fits":
            raise app.ingest.QuarantineError("Fixture permission failure")
        return original_move(name)
    monkeypatch.setattr(app.ingest, "move_to_quarantine", move)
    app.state["file_loader_pending_quarantine_all"] = True
    app.ui.begin({"confirm_quarantine_all"})
    with pytest.raises(StopRun):
        app.page._render_validation_table()
    assert app.state["file_loader_quarantined"] == {"bad1.fits"}
    assert (app.archive / "bad2.fits").exists()
    assert "1 of 2" in app.state["file_loader_quarantine_error"]
    assert app.state["pipeline_data"]["file_loader"]["flagged_files"] == ["bad2.fits"]


def test_bulk_cancel_does_not_move_files(app):
    seed_files(app, ("bad.fits",))
    app.state["file_loader_verify_result::bad.fits"].ok = False
    app.state["file_loader_pending_quarantine_all"] = True
    app.ui.begin({"cancel_quarantine_all"})
    with pytest.raises(StopRun):
        app.page._render_validation_table()
    assert (app.archive / "bad.fits").exists()
    assert not app.state["file_loader_pending_quarantine_all"]
    assert not app.state.get("file_loader_quarantined")
