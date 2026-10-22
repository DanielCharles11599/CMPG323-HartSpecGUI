# test_source_selection_safety.py — FR-01/19: changed-input isolation, not scientific fitting.
"""Headless regression tests for the real source-selection orchestration.

The production invalidation, session store, bridge, spectrum resolver, source
browser helpers and Page 1 script execute from disk. Streamlit rendering/state,
FITS header scanning and the CLC sorter are substituted; this is not a browser
or numerical CLC acceptance test. All filesystem work uses pytest tmp_path.
"""
from __future__ import annotations

import copy
import importlib.util
import sys
import types
from contextlib import nullcontext
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "hartspec_gui" if (ROOT / "hartspec_gui" / "utils").is_dir() else ROOT


class StopRun(BaseException):
    """Model Streamlit navigation/stop, which must not become a CLC error."""


class WidgetState(dict):
    """Detect unsafe reassignment of controls already rendered on this run."""

    def __init__(self):
        super().__init__()
        self.rendered = set()

    def __setitem__(self, key, value):
        if key in self.rendered:
            raise AssertionError(f"Already-rendered widget was reassigned: {key}")
        super().__setitem__(key, value)

    def update(self, *args, **kwargs):
        for key, value in dict(*args, **kwargs).items():
            self[key] = value


class StreamlitFacade(types.ModuleType):
    """Minimal widget facade; the page's control flow itself is not mocked."""

    def __init__(self):
        super().__init__("streamlit")
        self.session_state = WidgetState()
        self.clicked = set()
        self.navigation = None
        self.messages = []

    def begin(self, clicked=()):
        self.session_state.rendered.clear()
        self.clicked = set(clicked)
        self.navigation = None
        self.messages.clear()

    def cache_data(self, **kwargs):
        return lambda function: function

    def set_page_config(self, **kwargs):
        pass

    def markdown(self, text, **kwargs):
        self.messages.append(str(text))

    def write(self, *args, **kwargs):
        pass

    def caption(self, text):
        self.messages.append(str(text))

    def error(self, text):
        self.messages.append(str(text))

    def container(self, **kwargs):
        return nullcontext()

    def expander(self, *args, **kwargs):
        return nullcontext()

    def spinner(self, *args, **kwargs):
        return nullcontext()

    def columns(self, widths):
        return [nullcontext() for _ in range(widths if isinstance(widths, int) else len(widths))]

    def text_input(self, label, *, key, **kwargs):
        self.session_state.setdefault(key, "")
        self.session_state.rendered.add(key)
        return self.session_state[key]

    def selectbox(self, label, *, options, key, **kwargs):
        self.session_state.setdefault(key, options[0])
        assert self.session_state[key] in options
        self.session_state.rendered.add(key)
        return self.session_state[key]

    def button(self, label, *, key, disabled=False, **kwargs):
        return key in self.clicked and not disabled

    def stop(self):
        raise StopRun()

    def switch_page(self, path):
        self.navigation = path
        raise StopRun()


@pytest.fixture
def app(monkeypatch, tmp_path):
    """Load actual project modules, with unavailable external interfaces isolated."""
    st = StreamlitFacade()
    utils = types.ModuleType("utils")
    utils.__path__ = [str(APP_ROOT / "utils")]
    env = types.ModuleType("utils.env")
    env.load_dotenv_if_present = lambda: None
    monkeypatch.setitem(sys.modules, "streamlit", st)
    # Page 2 imports components even though this headless flow only calls its
    # load/handoff functions. Isolate that import instead of depending on a
    # real Streamlit module left in sys.modules by another test.
    components = types.ModuleType("streamlit.components")
    components.__path__ = []
    components_v1 = types.ModuleType("streamlit.components.v1")
    components_v1.html = lambda *args, **kwargs: None
    components_v1.iframe = lambda *args, **kwargs: None
    components.v1, st.components = components_v1, components
    monkeypatch.setitem(sys.modules, "streamlit.components", components)
    monkeypatch.setitem(sys.modules, "streamlit.components.v1", components_v1)
    monkeypatch.setitem(sys.modules, "utils", utils)
    monkeypatch.setitem(sys.modules, "utils.env", env)
    monkeypatch.setenv("SESSIONS_PATH", str(tmp_path / "sessions"))

    def load(name):
        spec = importlib.util.spec_from_file_location(f"utils.{name}", APP_ROOT / "utils" / f"{name}.py")
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, spec.name, module)
        setattr(utils, name, module)
        spec.loader.exec_module(module)
        return module

    store = load("session_store")
    store.init_session_state()
    invalidation = load("stage_invalidation")
    load("file_loader_logic")  # Step 3: Page 2 now imports the shared eligibility rule.
    bridge = load("baseline_editor_bridge")
    resolver = load("spectrum_resolution")
    load("styles")
    archive = tmp_path / "archive"
    archive.mkdir()
    ingest = types.ModuleType("utils.fits_ingest")
    ingest.get_archive_root = lambda: archive
    ingest.QUARANTINE_DIRNAME = "Flagged"
    monkeypatch.setitem(sys.modules, "utils.fits_ingest", ingest)
    utils.fits_ingest = ingest
    astropy = types.ModuleType("astropy")
    astropy.__path__ = []
    io = types.ModuleType("astropy.io")
    io.fits = types.ModuleType("astropy.io.fits")
    astropy.io = io
    monkeypatch.setitem(sys.modules, "astropy", astropy)
    monkeypatch.setitem(sys.modules, "astropy.io", io)
    monkeypatch.setitem(sys.modules, "astropy.io.fits", io.fits)
    source = load("source_browser_logic")
    sidebar = types.ModuleType("utils.sidebar")
    sidebar.render_sidebar = lambda current_stage: None
    utils.sidebar = sidebar
    monkeypatch.setitem(sys.modules, "utils.sidebar", sidebar)
    return types.SimpleNamespace(
        st=st, state=st.session_state, store=store, invalidate=invalidation,
        bridge=bridge, resolver=resolver, source=source, archive=archive, tmp_path=tmp_path,
    )


def spectrum(value=100.0):
    """Small deterministic marker arrays, not astronomical reference spectra."""
    return {"Vlsr": [0.0, 1.0], "LCP": [value, value + 1], "RCP": [value + 2, value + 3]}


def selection(app, source="A", names=("a1.fits", "a2.fits"), frequency=1420.405):
    """Produce the same JSON-safe input fields that Page 1 writes."""
    return {
        "selected_files": list(names),
        "fits_file_paths": [str(app.archive / name) for name in names],
        "archive_root": str(app.archive),
        "source_name": source,
        "frequency_mhz": frequency,
        "earliest_observation_date": "2026-08-12",
        "observation_blocks": {"block.txt": list(names)},
        "discarded_files": [],
        "file_check_workspace": str(app.store.SESSIONS_DIR / "old-a" / "workspace" / source / "1420.405"),
        "file_check_error": None,
    }


def seed_old(app):
    """A completed observation with all known downstream state present."""
    state = app.state
    state.update({
        "session_id": "old-a",
        "pipeline_data": {
            **{key: {"old": key} for key in app.store.STAGE_KEYS},
            "01_source_browser": selection(app),
            "extension_metadata": {"keep": True},
        },
        "completed_stages": set(app.store.STAGE_KEYS),
        "audit_log": [{"ts": "10:20:30", "message": "Observation A processed"}],
        "loaded_spectrum": spectrum(), "loaded_spectra": [spectrum(), spectrum(200)],
        "bandpass_corrected_spectrum": spectrum(), "bandpass_display_result": {"old": True},
        "bandpass_applied_mode": "Position Switch", "bandpass_mode": "Position Switch",
        "baseline_corrected_spectrum": spectrum(), "baseline_editor_seen_event_ids": ["old-event"],
        "calibrated_spectrum": spectrum(900), "latest_fit": {"fit_curve": [900, 901]},
        "map_2d_data": {"data": [[1.0] * 3 for _ in range(3)], "x": [0, 1, 2], "y": [0, 1, 2]},
        "pointing_cached_result": {"old": True}, "calibration_cached_result": {"old": True},
        "spectral_fitting_cached_result": {"old": True}, "export_cached_result": {"old": True},
        "file_loader_ingest_result::a1.fits": {"old": True},
        "file_loader_verify_result::a1.fits": {"old": True},
        "file_loader_load_elapsed_s::a1.fits": 0.5,
        "file_loader_target_filenames": ["a1.fits", "a2.fits"], "file_loader_load_done": True,
        "file_loader_pending_quarantine": "a1.fits", "file_loader_pending_quarantine_all": True,
        "file_loader_quarantined": {"bad.fits"}, "file_loader_quarantine_error": "old failure",
        "file_loader_mapping_mode": "Manual", "file_loader_manual_mapping_global": {"Vlsr": "HDU9:OLD"},
        "manual_map_global_Vlsr": "HDU9:OLD", "file_loader_manual_filenames_input": "a1.fits",
        "fit_type": "Multi-component", "fit_polarization": "RCP",
        "theme": "dark", "authentication_status": True, "username": "observer", "sidebar_open": True,
        "source_browser_fits_dir": str(app.archive), "source_browser_source_name": "A",
        "source_browser_frequency_mhz": 1420.405, "source_browser_filename_search": "",
    })
    app.bridge.write_bridge("old-a", {
        "spectrum_fingerprint": app.bridge.spectrum_fingerprint(spectrum()),
        "flattened_spectrum": spectrum(), "complete": True, "events": [],
    })
    return state


def resolve(app):
    return app.resolver.resolve_spectrum(
        app.state, read_bridge=app.bridge.read_bridge, fingerprint=app.bridge.spectrum_fingerprint,
    )


def commit(app, payload=None, session_id="new-b"):
    return app.invalidate.commit_source_selection(
        app.state, payload or selection(app, "B", ("b1.fits", "b2.fits")),
        archive_root=app.archive, new_session_id=session_id,
    )


@pytest.mark.parametrize("change", ["source", "frequency", "files", "order", "directory"])
def test_different_processing_inputs_invalidate(app, change):
    seed_old(app)
    proposed = selection(app)
    if change == "source":
        proposed["source_name"] = "B"
    elif change == "frequency":
        proposed["frequency_mhz"] = 6668.519
    elif change == "files":
        proposed = selection(app, names=("a1.fits", "a3.fits"))
    elif change == "order":
        proposed = selection(app, names=("a2.fits", "a1.fits"))
    else:
        proposed["archive_root"] = str(app.tmp_path / "other-archive")
    assert commit(app, proposed)
    assert app.state["session_id"] == "new-b"
    assert app.state["completed_stages"] == {"01_source_browser"}
    assert resolve(app).is_placeholder


def test_clears_every_known_downstream_cache_and_intent(app):
    state = seed_old(app)
    prior_keys = set(state)
    assert commit(app)
    defaults = set(app.invalidate._SOURCE_CONTROL_DEFAULTS)
    for key in prior_keys:
        if key in app.invalidate.SOURCE_DEPENDENT_SESSION_KEYS or key.startswith(
            app.invalidate.SOURCE_DEPENDENT_SESSION_PREFIXES
        ):
            assert key not in state or key in defaults, key
    assert state["file_loader_mapping_mode"] == "Auto"
    assert state["file_loader_manual_filenames_input"] == ""
    assert state["bandpass_mode"] == "Frequency Switch"
    assert state["fit_type"] == "1D Gaussian"
    assert state["fit_polarization"] == "LCP"
    assert set(state["pipeline_data"]) == {"01_source_browser", "extension_metadata"}
    assert "map_2d_data" not in state  # independent assertion, not derived from the registry under test


def test_changed_loaded_input_set_clears_spatial_map_but_preserves_loader_evidence(app):
    """Quarantine/validation changes cannot leave a previous observation's spatial map behind."""
    state = seed_old(app)
    loaded = state["loaded_spectra"]
    loader = state["pipeline_data"]["file_loader"]
    source = state["pipeline_data"]["01_source_browser"]
    app.invalidate.invalidate_loaded_input_dependents(state, new_session_id="new-validated-inputs")
    assert "map_2d_data" not in state
    assert "latest_fit" not in state
    assert "07_spectral_fitting" not in state["pipeline_data"]
    assert state["loaded_spectra"] is loaded
    assert state["pipeline_data"]["file_loader"] is loader
    assert state["pipeline_data"]["01_source_browser"] is source
    assert state["session_id"] == "new-validated-inputs"


def test_invalid_loaded_input_replacement_does_not_clear_spatial_map(app):
    """Replacement-ID validation must precede every cleanup, including the new map key."""
    state = seed_old(app)
    before = copy.deepcopy(state)
    with pytest.raises(ValueError):
        app.invalidate.invalidate_loaded_input_dependents(state, new_session_id="old-a")
    assert state == before


def test_source_cleanup_namespaces_match_tested_step1_registry(app):
    """Adding runtime namespaces to Step 1 must also update source-change cleanup."""
    assert set(app.invalidate.SOURCE_DEPENDENT_SESSION_PREFIXES) == (
        set(app.store._REDUCTION_STATE_PREFIXES) - {"source_browser_"}
    )
    assert app.invalidate.SOURCE_DEPENDENT_SESSION_KEYS == app.store._REDUCTION_STATE_KEYS
    assert app.invalidate.SOURCE_DEPENDENT_STAGE_KEYS == app.store.STAGE_KEYS[1:]


def test_preserves_audit_preferences_and_current_browser_controls(app):
    state = seed_old(app)
    keys = (
        "audit_log", "theme", "authentication_status", "username", "sidebar_open",
        "source_browser_fits_dir", "source_browser_source_name", "source_browser_frequency_mhz",
        "source_browser_filename_search",
    )
    expected = {key: state[key] for key in keys}
    state.rendered.update(key for key in keys if key.startswith("source_browser_"))
    assert commit(app)
    for key, value in expected.items():
        assert state[key] is value


@pytest.mark.parametrize("change", ["none", "search", "metadata", "path_spelling", "numeric_spelling", "legacy"])
def test_same_inputs_preserve_all_results_and_original_payload(app, change):
    state = seed_old(app)
    proposed = selection(app)
    if change == "search":
        state["source_browser_filename_search"] = "a"
    elif change == "metadata":
        proposed.update(file_check_workspace="/other/workspace", file_check_error="different", observation_blocks={})
    elif change == "path_spelling":
        proposed["selected_files"] = [str(app.archive / "sub/../a1.fits"), str(app.archive / "./a2.fits")]
    elif change == "numeric_spelling":
        proposed["frequency_mhz"] = "1420.4050"
    elif change == "legacy":
        del state["pipeline_data"]["01_source_browser"]["archive_root"]
    before = copy.deepcopy(state)
    bridge_bytes = app.bridge._bridge_path("old-a").read_bytes()
    original_payload = state["pipeline_data"]["01_source_browser"]
    assert not commit(app, proposed)
    assert state == before
    assert state["pipeline_data"]["01_source_browser"] is original_payload
    assert app.bridge._bridge_path("old-a").read_bytes() == bridge_bytes


def test_legacy_selected_files_only_signature_works(app):
    full = selection(app)
    old = {key: full[key] for key in ("selected_files", "source_name", "frequency_mhz")}
    assert app.invalidate.source_selection_signature(old, app.archive) == (
        app.invalidate.source_selection_signature(full, app.archive)
    )


def test_legacy_paths_only_signature_works(app):
    full = selection(app)
    old = {key: full[key] for key in ("fits_file_paths", "source_name", "frequency_mhz")}
    assert app.invalidate.source_selection_signature(old, app.archive) == (
        app.invalidate.source_selection_signature(full, app.archive)
    )


def test_saved_legacy_paths_detect_relocation_of_relative_filenames(app):
    state = seed_old(app)
    del state["pipeline_data"]["01_source_browser"]["archive_root"]
    proposed = selection(app)
    proposed["archive_root"] = str(app.tmp_path / "different")
    assert app.invalidate.source_selection_changed(state, proposed, app.tmp_path / "different")


@pytest.mark.parametrize("key,value", [
    ("selected_files", []), ("selected_files", "a.fits"), ("selected_files", [None]),
    ("selected_files", [""]), ("selected_files", ["bad\x00.fits"]),
    ("selected_files", ["one.fits"]), ("fits_file_paths", [1, 2]),
    ("source_name", 123), ("frequency_mhz", True), ("frequency_mhz", "nonnumeric"),
    ("frequency_mhz", float("nan")), ("frequency_mhz", float("inf")), ("frequency_mhz", 0),
    ("archive_root", ""), ("archive_root", 123),
])
def test_invalid_new_selection_does_not_mutate_active_reduction(app, key, value):
    state = seed_old(app)
    before = copy.deepcopy(state)
    proposed = selection(app, "B", ("b1.fits", "b2.fits"))
    proposed[key] = value
    if key == "selected_files" and value == []:
        proposed["fits_file_paths"] = []
    with pytest.raises(ValueError):
        commit(app, proposed)
    assert state == before


@pytest.mark.parametrize("session_id", ["old-a", "", "../escape", "old-a.baseline_editor", None])
def test_changed_selection_requires_distinct_safe_id_before_clearing(app, session_id):
    state = seed_old(app)
    before = copy.deepcopy(state)
    with pytest.raises(ValueError):
        commit(app, session_id=session_id)
    assert state == before


def test_non_json_sort_metadata_is_rejected_before_cleanup(app):
    state = seed_old(app)
    before = copy.deepcopy(state)
    proposed = selection(app, "B", ("b1.fits", "b2.fits"))
    proposed["observation_blocks"] = {"block": {"not-a-json-list"}}
    with pytest.raises(ValueError):
        commit(app, proposed)
    assert state == before


def test_committed_metadata_does_not_alias_callers_mutable_payload(app):
    seed_old(app)
    proposed = selection(app, "B", ("b1.fits", "b2.fits"))
    commit(app, proposed)
    proposed["selected_files"].append("later.fits")
    assert app.state["pipeline_data"]["01_source_browser"]["selected_files"] == ["b1.fits", "b2.fits"]


@pytest.mark.parametrize("old_record", [None, "legacy", {}, {"selected_files": "invalid"}])
def test_missing_or_malformed_old_identity_cannot_keep_old_results(app, old_record):
    seed_old(app)
    app.state["pipeline_data"]["01_source_browser"] = old_record
    assert commit(app)
    assert resolve(app).is_placeholder


def test_unconfirmed_old_identity_cannot_keep_derived_state(app):
    seed_old(app)
    app.state["completed_stages"].discard("01_source_browser")
    assert commit(app, selection(app))
    assert app.state["completed_stages"] == {"01_source_browser"}


@pytest.mark.parametrize("key,value", [("pipeline_data", []), ("completed_stages", [])])
def test_invalid_live_state_is_rejected_without_partial_cleanup(app, key, value):
    seed_old(app)
    app.state[key] = value
    before = copy.deepcopy(app.state)
    with pytest.raises(ValueError):
        commit(app)
    assert app.state == before


def test_baseline_only_invalidation_still_preserves_pointing_and_inputs(app):
    state = seed_old(app)
    pointing = state["pipeline_data"]["06_pointing_correction"]
    spatial_map = state["map_2d_data"]
    app.invalidate.invalidate_baseline_dependents(state)
    assert state["map_2d_data"] is spatial_map  # an independent spatial map is not a 1D-baseline dependency
    assert "06_pointing_correction" in state["completed_stages"]
    assert state["pipeline_data"]["06_pointing_correction"] is pointing
    assert state["pointing_cached_result"] == {"old": True}
    assert state["loaded_spectra"]
    assert state["bandpass_corrected_spectrum"]
    assert "calibrated_spectrum" not in state
    assert "latest_fit" not in state
    assert state["session_id"] == "old-a"


def test_cleanup_is_idempotent_on_empty_and_partial_state(app):
    for state in ({}, {"pipeline_data": {}, "completed_stages": set()}):
        app.invalidate.invalidate_source_dependents(state)
        before = copy.deepcopy(state)
        app.invalidate.invalidate_source_dependents(state)
        assert state == before
    app.invalidate.invalidate_baseline_dependents({})


def test_old_bridge_cannot_resurface_even_with_no_new_bandpass_and_a_late_write(app):
    seed_old(app)
    assert resolve(app).is_calibrated
    commit(app)
    assert app.bridge.read_bridge("old-a")["flattened_spectrum"] == spectrum()
    assert app.bridge.read_bridge("new-b") is None
    # Model a callback already running in the previous iframe after the switch.
    app.bridge.update_bridge("old-a", lambda data: data.update(flattened_spectrum=spectrum(700)))
    assert resolve(app).is_placeholder
    app.state["loaded_spectra"] = [spectrum(2)]
    assert resolve(app).source_key == app.resolver.SOURCE_RAW
    assert resolve(app).channels["LCP"].tolist() == [2, 3]


def test_identical_numeric_bandpass_from_a_new_observation_does_not_restore_old_blocks(app):
    seed_old(app)
    commit(app)
    app.state["bandpass_corrected_spectrum"] = spectrum()  # same numbers, different observation
    fresh = app.bridge.initialize_bridge("new-b", spectrum(), "dark", "Frequency Switch")
    assert fresh["blocks"] == []
    assert fresh["flattened_spectrum"] is None
    assert not fresh["complete"]
    assert app.bridge.read_bridge("old-a")["complete"]


def test_existing_files_unchanged_and_new_session_save_load_uses_new_bridge(app):
    seed_old(app)
    old_saved = app.store.save_session()
    workspace = Path(app.state["pipeline_data"]["01_source_browser"]["file_check_workspace"])
    workspace.mkdir(parents=True)
    old_block = workspace / "block.txt"
    old_block.write_text("a1.fits\na2.fits\n")
    raw = app.archive / "a1.fits"
    raw.write_bytes(b"raw observation bytes")
    flagged = app.archive / "Flagged" / "bad.fits"
    flagged.parent.mkdir()
    flagged.write_bytes(b"already quarantined")
    paths = [old_saved, app.bridge._bridge_path("old-a"), old_block, raw, flagged]
    before = {path: path.read_bytes() for path in paths}
    commit(app)
    assert before == {path: path.read_bytes() for path in paths}
    new_saved = app.store.save_session()
    assert new_saved.name == "new-b.json" and old_saved.exists()
    app.state["calibrated_spectrum"] = spectrum(500)
    app.store.load_session(new_saved, navigate=False)
    assert app.state["session_id"] == "new-b"
    assert resolve(app).is_placeholder
    app.store.load_session(old_saved, navigate=False)
    assert resolve(app).source_key == app.resolver.SOURCE_BASELINE
    assert resolve(app).channels["LCP"].tolist() == [100, 101]


@pytest.fixture
def browser(app, monkeypatch):
    """Execute the full Page 1 script with fixture headers and the real workspace adapter."""
    tree = app.source.DirectoryNode(name="archive", path=app.archive)
    for name, src, freq in (
        ("a1.fits", "A", 1420.405), ("a2.fits", "A", 1420.405),
        ("b1.fits", "B", 1420.405), ("b2.fits", "B", 1420.405),
        ("b3.fits", "B", 6668.519), ("b4.fits", "B", 6668.519),
    ):
        path = app.archive / name
        path.write_bytes(b"synthetic test bytes; not a real FITS file")
        tree.files.append(app.source.SourceFileEntry(
            path=path, filename=name, size_mb=0.001, status="OK", source_name=src,
            frequency_mhz=freq, observation_date="2026-08-12",
        ))
    monkeypatch.setattr(app.source, "scan_fits_directory_tree", lambda path: tree)
    calls = []
    controls = {"raise": False}

    def clc_sort(observation, frequency, workspace_root):
        work = Path(workspace_root) / observation / frequency
        calls.append(work)
        if controls["raise"]:
            raise ValueError("Fixture sorter failure")
        block = work / "block.txt"
        block.write_text("\n".join(p.name for p in sorted(work.glob("*.fits"))))
        bad = work / "bad.txt"
        bad.write_text("")
        return {"block_files": [str(block)], "bad_data_file": str(bad)}

    monkeypatch.setattr(app.source, "_import_run_file_check", lambda: clc_sort)
    page = APP_ROOT / "pages" / "01_Source_Browser.py"

    def run(clicked=()):
        app.st.begin(clicked)
        namespace = {"__name__": "_source_browser_integration", "__file__": str(page)}
        try:
            exec(compile(page.read_text(encoding="utf-8"), str(page), "exec"), namespace)
        except StopRun:
            pass
        return namespace

    return types.SimpleNamespace(run=run, calls=calls, controls=controls, tree=tree)


def set_source(app, source, frequency=1420.405, search=""):
    app.st.begin()
    app.state.update({
        "source_browser_source_name": source, "source_browser_frequency_mhz": frequency,
        "source_browser_filename_search": search,
    })


def test_page_browsing_other_inputs_without_confirmation_preserves_active_results(app, browser):
    seed_old(app)
    set_source(app, "B")
    before = copy.deepcopy(app.state)
    browser.run()
    assert app.state == before
    assert browser.calls == []
    assert app.st.navigation is None
    assert resolve(app).is_calibrated


def test_page_changed_confirmation_clears_old_results_and_isolates_workspace(app, browser):
    seed_old(app)
    old_workspace = Path(app.state["pipeline_data"]["01_source_browser"]["file_check_workspace"])
    old_workspace.mkdir(parents=True)
    saved_block = old_workspace / "block.txt"
    saved_block.write_text("keep old block")
    old_bridge = app.bridge._bridge_path("old-a").read_bytes()
    audit_event = app.state["audit_log"][0]
    set_source(app, "B")
    browser.run({"load_into_pipeline_btn"})
    new_id = app.state["session_id"]
    assert new_id != "old-a"
    assert app.state["completed_stages"] == {"01_source_browser"}
    assert app.state["pipeline_data"]["01_source_browser"]["selected_files"] == ["b1.fits", "b2.fits"]
    assert app.st.navigation == "pages/02_File_Loader.py"
    assert len(browser.calls) == 1
    assert browser.calls[0].is_relative_to(app.store.SESSIONS_DIR / new_id)
    assert saved_block.read_text() == "keep old block"
    assert app.bridge._bridge_path("old-a").read_bytes() == old_bridge
    assert app.state["audit_log"][0] is audit_event
    assert sum("Source selection committed" in event["message"] for event in app.state["audit_log"]) == 1
    assert resolve(app).is_placeholder


def test_page_same_inputs_skip_sorting_and_do_not_rewrite_existing_workspace(app, browser):
    seed_old(app)
    old_payload = app.state["pipeline_data"]["01_source_browser"]
    old_result = app.state["calibrated_spectrum"]
    browser.run({"load_into_pipeline_btn"})
    assert browser.calls == []
    assert app.state["session_id"] == "old-a"
    assert app.state["pipeline_data"]["01_source_browser"] is old_payload
    assert app.state["calibrated_spectrum"] is old_result
    assert app.state["completed_stages"] == set(app.store.STAGE_KEYS)
    assert app.st.navigation == "pages/02_File_Loader.py"


def test_page_sort_failure_retains_active_reduction_until_explicit_bypass(app, browser):
    seed_old(app)
    browser.controls["raise"] = True
    set_source(app, "B")
    prior_pipeline = copy.deepcopy(app.state["pipeline_data"])
    browser.run({"load_into_pipeline_btn"})
    pending = app.state["source_browser_file_check_error"]
    assert app.state["session_id"] == "old-a"
    assert app.state["pipeline_data"] == prior_pipeline
    assert resolve(app).is_calibrated
    assert app.st.navigation is None
    assert pending["candidate_session_id"] != "old-a"
    browser.run({"continue_without_sort_btn"})
    assert app.state["session_id"] == pending["candidate_session_id"]
    payload = app.state["pipeline_data"]["01_source_browser"]
    assert "Fixture sorter failure" in payload["file_check_error"]
    assert payload["observation_blocks"] == {}
    assert "source_browser_file_check_error" not in app.state
    assert app.state["completed_stages"] == {"01_source_browser"}
    assert app.st.navigation == "pages/02_File_Loader.py"
    assert resolve(app).is_placeholder


def test_page_pending_bypass_cannot_confirm_a_different_current_selection(app, browser):
    seed_old(app)
    browser.controls["raise"] = True
    set_source(app, "B")
    browser.run({"load_into_pipeline_btn"})
    pending = app.state["source_browser_file_check_error"]
    set_source(app, "B", 6668.519)
    browser.run({"continue_without_sort_btn"})
    assert app.state["session_id"] == "old-a"
    assert resolve(app).is_calibrated
    assert app.state["source_browser_file_check_error"] is pending
    assert app.st.navigation is None


def test_page_empty_filtered_selection_does_not_commit_or_sort(app, browser):
    seed_old(app)
    set_source(app, "B", search="does-not-exist")
    browser.run({"load_into_pipeline_btn", "continue_without_sort_btn"})
    assert app.state["session_id"] == "old-a"
    assert resolve(app).is_calibrated
    assert browser.calls == []


def test_page_workspace_reservation_failure_does_not_change_active_selection(app, browser, monkeypatch):
    seed_old(app)
    set_source(app, "B")
    blocker = app.tmp_path / "not-a-directory"
    blocker.write_text("must survive")
    monkeypatch.setattr(app.store, "SESSIONS_DIR", blocker)
    browser.run({"load_into_pipeline_btn"})
    assert app.state["session_id"] == "old-a"
    assert resolve(app).is_calibrated
    assert browser.calls == []
    assert any("active selection was not changed" in msg for msg in app.st.messages)
    assert blocker.read_text() == "must survive"


def test_page_reservation_skips_existing_ids_files_bridges_and_workspaces(app, browser, monkeypatch):
    seed_old(app)
    namespace = browser.run()
    sessions = app.store.SESSIONS_DIR
    (sessions / "saved123.json").write_text("saved")
    (sessions / "bridge12.baseline_editor.json").write_text("bridge")
    (sessions / "working1").mkdir()
    ids = iter(["old-a", "saved123", "bridge12", "working1", "fresh123"])
    monkeypatch.setattr(namespace["uuid"], "uuid4", lambda: types.SimpleNamespace(hex=next(ids)))
    assert namespace["_reserve_selection_session_id"]() == "fresh123"
    assert (sessions / "fresh123").is_dir()
    assert (sessions / "saved123.json").read_text() == "saved"
    assert (sessions / "bridge12.baseline_editor.json").read_text() == "bridge"


def test_page_changing_files_of_same_source_preserves_previous_sort_workspace(app, browser):
    """Regression for the real wrapper's rmtree(observation_dir) behaviour."""
    seed_old(app)
    old_workspace = Path(app.state["pipeline_data"]["01_source_browser"]["file_check_workspace"])
    old_workspace.mkdir(parents=True)
    old_block = old_workspace / "block.txt"
    old_block.write_text("a1.fits\na2.fits\n")
    set_source(app, "A", search="a1")
    browser.run({"load_into_pipeline_btn"})
    assert app.state["session_id"] != "old-a"
    assert old_block.read_text() == "a1.fits\na2.fits\n"
    assert app.state["pipeline_data"]["01_source_browser"]["selected_files"] == ["a1.fits"]
    assert len(browser.calls) == 1


def test_paths_only_old_handoff_is_recommitted_not_reused_as_loader_input(app):
    seed_old(app)
    del app.state["pipeline_data"]["01_source_browser"]["selected_files"]
    assert commit(app, selection(app))
    assert app.state["pipeline_data"]["01_source_browser"]["selected_files"] == ["a1.fits", "a2.fits"]
    assert resolve(app).is_placeholder


def test_page_invalid_sort_metadata_is_reported_without_clearing_active_state(app, browser):
    seed_old(app)
    set_source(app, "B")
    namespace = browser.run()
    outcome = app.source.FileCheckOutcome(work_dir=app.tmp_path, blocks={"block": {"invalid-json-set"}})
    namespace["_commit_and_continue"](outcome, None, "new-b")
    assert app.state["session_id"] == "old-a"
    assert resolve(app).is_calibrated
    assert app.st.navigation is None
    assert any("Could not commit the new selection" in msg for msg in app.st.messages)


def test_file_loader_reloads_overlap_after_changed_selection_with_actual_page_functions(app, monkeypatch):
    """Page 2 uses the new handoff and cannot reuse the shared filename's old cached arrays."""
    seed_old(app)
    calls = []
    ingest = sys.modules["utils.fits_ingest"]

    def load(path):
        calls.append(path)
        return types.SimpleNamespace(
            ok=True, convention="fixture", spectrum=spectrum(len(calls)), load_errors={},
        )

    verification_calls = []

    def verify(path):
        verification_calls.append(path)
        return types.SimpleNamespace(ok=True, issues=[])

    monkeypatch.setattr(ingest, "ingest_fits_file", load, raising=False)
    monkeypatch.setattr(ingest, "verify_fits_file", verify, raising=False)
    monkeypatch.setattr(app.st, "empty", lambda: app.st, raising=False)
    path = APP_ROOT / "pages" / "02_File_Loader.py"
    spec = importlib.util.spec_from_file_location("_selection_safety_loader_page", path)
    assert spec and spec.loader
    loader = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, loader)
    spec.loader.exec_module(loader)
    proposed = selection(app, names=("a1.fits", "b2.fits"))
    commit(app, proposed)
    assert loader._get_target_filenames() == ["a1.fits", "b2.fits"]
    loader._render_load_progress()
    assert calls == [app.archive / "a1.fits", app.archive / "b2.fits"]
    assert app.state["loaded_spectra"] == [spectrum(1), spectrum(2)]
    assert app.state["file_loader_load_done"]
    assert resolve(app).source_key == app.resolver.SOURCE_RAW
    assert resolve(app).channels["LCP"].tolist() == [1, 2]
    loader._render_load_progress()
    assert len(calls) == 2  # ordinary reruns still use the new selection's cache
    assert loader._run_real_verify("a1.fits").ok
    assert loader._run_real_verify("a1.fits").ok
    # Step 3 validates every candidate after loading before publishing it;
    # the direct verification calls above must still be cache hits.
    assert verification_calls == [app.archive / "a1.fits", app.archive / "b2.fits"]


def test_non_object_selection_is_rejected(app):
    with pytest.raises(ValueError, match="must be an object"):
        app.invalidate.source_selection_signature(None, app.archive)
