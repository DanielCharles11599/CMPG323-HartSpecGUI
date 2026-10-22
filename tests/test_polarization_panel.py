# test_polarization_panel.py — FR-09: headless presentation/state contract tests.
"""Use real Plotly figures and a small Streamlit API double, not a browser.

The separate AppTest file exercises real widgets when Streamlit is installed.
Page 05 tests here mock the missing calibration/session/sidebar collaborators;
they do not claim to validate those collaborators' scientific or disk behavior.
"""
from __future__ import annotations

import ast
import copy
import importlib
import importlib.util
import json
import runpy
import sys
from collections import defaultdict
from pathlib import Path
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest
from scipy.signal import savgol_filter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hartspec_gui"))
from utils import polarization_logic as logic  # noqa: E402
from utils import stage_invalidation  # noqa: E402

STAGE = "05_calibration_dashboard"
PREFIX = "calibration_polarization"
UPSTREAM = {"01_source_browser", "file_loader", "03_bandpass_correction", "04_baseline_editor"}


class StreamlitDouble(ModuleType):
    """Model callback-before-rerun order and capture calls; no real UI rendering."""

    def __init__(self):
        super().__init__("streamlit")
        self.session_state = {"session_id": "test-session", "pipeline_data": {STAGE: {}}, "completed_stages": set()}
        self.messages = defaultdict(list)
        self.widgets = {}
        self.figures = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def container(self, **kwargs):
        return self

    def columns(self, weights):
        return [self for _ in range(weights if isinstance(weights, int) else len(weights))]

    def caption(self, message):
        self.messages["caption"].append(message)

    def markdown(self, message, **kwargs):
        self.messages["markdown"].append(message)

    def info(self, message):
        self.messages["info"].append(message)

    def warning(self, message):
        self.messages["warning"].append(message)

    def error(self, message):
        self.messages["error"].append(message)

    def toggle(self, label, **kwargs):
        self.widgets[kwargs["key"]] = kwargs
        return self.session_state[kwargs["key"]]

    def number_input(self, label, **kwargs):
        self.widgets[kwargs["key"]] = kwargs
        return self.session_state[kwargs["key"]]

    def plotly_chart(self, figure, **kwargs):
        self.figures.append(figure)

    def set_page_config(self, **kwargs):
        pass

    def metric(self, *args, **kwargs):
        pass

    def button(self, *args, **kwargs):
        return False

    def interact(self, key, value):
        """Set a widget value then invoke its registered callback before rerender."""
        assert not self.widgets[key]["disabled"], "Test attempted to edit a disabled control"
        self.session_state[key] = value
        self.widgets[key]["on_change"](*self.widgets[key]["args"])


def load_module(name, path):
    """Load one test-local copy without replacing a deployed app module."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def panel_context(monkeypatch):
    """Isolate Streamlit only in the tests; compile the real CLC function bodies."""
    fake = StreamlitDouble()
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    package = importlib.import_module("utils")
    styles = load_module("_fr09_test_styles", ROOT / "hartspec_gui/utils/styles.py")
    # FR-22 wraps charts at the rendering boundary; test that adapter separately.
    monkeypatch.setattr(styles, "render_plotly_chart", fake.plotly_chart)
    monkeypatch.setattr(package, "styles", styles, raising=False)
    panel = load_module("_fr09_test_panel", ROOT / "hartspec_gui/utils/polarization_panel.py")
    source = ROOT / "hartspec_gui/clc/Pols.py"
    functions = [node for node in ast.parse(source.read_text()).body
                 if isinstance(node, ast.FunctionDef) and node.name in ("ave_pols", "add_pols")]
    reference = ModuleType("fr09_pols_reference")
    reference.__dict__.update(np=np, savgol_filter=savgol_filter)
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), "exec"), reference.__dict__)
    monkeypatch.setattr(logic, "_load_pols", lambda: reference)
    x = np.linspace(-10., 10., 31)
    spectrum = {"Vlsr": x, "LCP": np.sin(x) + 1, "RCP": np.cos(x) + 2}
    events = []

    def render(spec=spectrum, **kwargs):
        """Render again with the same input unless a test supplies another one."""
        fake.figures.clear()
        fake.messages.clear()
        return panel.render_polarization_panel(
            spec, source_key="baseline", source_label="Baseline input", intensity_unit="K",
            on_change=events.append, **kwargs,
        )

    return SimpleNamespace(st=fake, panel=panel, spectrum=spectrum, render=render, events=events, package=package)


def saved(context):
    """Return the nested metadata without confusing it with a pipeline spectrum."""
    return context.st.session_state["pipeline_data"][STAGE][logic.SETTINGS_KEY]


def test_all_four_traces_and_default_controls(panel_context):
    c = panel_context
    assert c.render()
    assert [trace.name for trace in c.st.figures[0].data] == ["LCP", "RCP", "Mean", "Stokes I"]
    assert not saved(c)["smoothing_enabled"]
    assert saved(c)["window_length"] == 7
    assert c.st.widgets[f"{PREFIX}_window"]["disabled"]
    assert not c.st.session_state["completed_stages"]
    assert len(c.events) == 1


def test_toggle_and_window_callback_persist_without_changing_inputs(panel_context):
    c = panel_context
    original = copy.deepcopy(c.spectrum)
    c.render()
    c.st.interact(f"{PREFIX}_smooth", True)
    c.render()
    assert saved(c)["smoothing_enabled"]
    assert not c.st.widgets[f"{PREFIX}_window"]["disabled"]
    c.st.interact(f"{PREFIX}_window", 11)
    c.render()
    assert saved(c)["window_length"] == 11
    expected = savgol_filter(original["LCP"] + original["RCP"], 11, 3)
    np.testing.assert_array_equal(c.st.figures[0].data[3].y, expected)
    for key in logic.ARRAY_KEYS:
        np.testing.assert_array_equal(c.spectrum[key], original[key])
    c.st.interact(f"{PREFIX}_smooth", False)
    c.render()
    np.testing.assert_array_equal(c.st.figures[0].data[3].y, original["LCP"] + original["RCP"])


def test_unchanged_rerenders_do_not_spam_audit_log(panel_context):
    c = panel_context
    c.render()
    c.render()
    c.render()
    assert len(c.events) == 1


def test_invalid_typed_even_window_keeps_previous_valid_value(panel_context):
    c = panel_context
    c.render()
    c.st.interact(f"{PREFIX}_smooth", True)
    c.render()
    c.st.interact(f"{PREFIX}_window", 6)
    c.render()
    assert saved(c)["window_length"] == 7
    assert "odd" in c.st.messages["error"][0]


def test_preferences_survive_widget_cleanup_and_json_restore(panel_context):
    c = panel_context
    c.render()
    c.st.interact(f"{PREFIX}_smooth", True)
    c.render()
    c.st.interact(f"{PREFIX}_window", 9)
    record = json.loads(json.dumps(c.st.session_state["pipeline_data"]))
    for key in list(c.st.session_state):
        if key.startswith(PREFIX):
            del c.st.session_state[key]
    c.st.session_state["pipeline_data"] = record
    c.render()
    assert c.st.session_state[f"{PREFIX}_smooth"] is True
    assert c.st.session_state[f"{PREFIX}_window"] == 9


def test_same_id_session_load_overrides_stale_widget_values(panel_context):
    c = panel_context
    c.render()
    c.st.session_state[f"{PREFIX}_smooth"] = False
    saved(c).update(smoothing_enabled=True, window_length=13)
    c.render()
    assert c.st.session_state[f"{PREFIX}_smooth"] is True
    assert c.st.session_state[f"{PREFIX}_window"] == 13


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_colors_axes_and_units_follow_shared_style(panel_context, theme):
    c = panel_context
    c.st.session_state["theme"] = theme
    c.render()
    fig = c.st.figures[0]
    assert [trace.line.color for trace in fig.data] == ["#1F77B4", "#FF7F0E", "#2CA02C", "#9467BD"]
    assert fig.layout.paper_bgcolor == c.panel.styles.THEMES[theme]["bg-panel"]
    assert fig.layout.plot_bgcolor == c.panel.styles.THEMES[theme]["bg-panel"]
    assert not fig.layout.xaxis.showgrid and not fig.layout.yaxis.showgrid
    assert fig.layout.yaxis.title.text == "Intensity (K)"
    assert fig.layout.xaxis.title.text == "Vlsr (km/s)"


def test_zoom_revision_changes_only_when_source_changes(panel_context):
    c = panel_context
    c.render()
    revision = c.st.figures[0].layout.uirevision
    c.st.interact(f"{PREFIX}_smooth", True)
    c.render()
    assert c.st.figures[0].layout.uirevision == revision
    c.spectrum["LCP"][0] += 1
    c.render()
    assert c.st.figures[0].layout.uirevision != revision


@pytest.mark.parametrize("size", [1, 4, 5, 6])
def test_short_spectrum_controls_are_valid(panel_context, size):
    c = panel_context
    short = {key: value[:size] for key, value in c.spectrum.items()}
    assert c.render(short)
    assert c.st.widgets[f"{PREFIX}_smooth"]["disabled"] is (size < 5)
    assert c.st.widgets[f"{PREFIX}_window"]["min_value"] <= c.st.widgets[f"{PREFIX}_window"]["max_value"]


def test_missing_input_never_shows_demo_data(panel_context):
    c = panel_context
    assert not c.render(None)
    assert c.st.messages["info"]
    assert not c.st.figures
    assert logic.SETTINGS_KEY not in c.st.session_state["pipeline_data"][STAGE]


def test_malformed_input_has_error_not_partial_overlay(panel_context):
    c = panel_context
    assert not c.render({"Vlsr": [1], "LCP": [1, 2], "RCP": [1]})
    assert c.st.messages["error"]
    assert not c.st.figures


def test_missing_clc_is_reported_in_panel(panel_context, monkeypatch):
    c = panel_context

    def missing():
        raise logic.PolarizationIntegrationError("clc/Pols.py missing")

    monkeypatch.setattr(logic, "_load_pols", missing)
    assert not c.render()
    assert "Pols.py missing" in c.st.messages["error"][0]
    assert not c.st.figures


@pytest.mark.parametrize("change", ["session", "fingerprint", "record"])
def test_stale_callback_cannot_edit_another_input(panel_context, change):
    c = panel_context
    c.render()
    callback = c.st.widgets[f"{PREFIX}_smooth"]
    if change == "session":
        c.st.session_state["session_id"] = "other-session"
    elif change == "fingerprint":
        saved(c)["source_fingerprint"] = "changed"
    else:
        c.st.session_state["pipeline_data"][STAGE].pop(logic.SETTINGS_KEY)
    before = copy.deepcopy(c.st.session_state["pipeline_data"])
    c.st.session_state[f"{PREFIX}_smooth"] = True
    callback["on_change"](*callback["args"])
    assert c.st.session_state["pipeline_data"] == before


def test_existing_baseline_invalidation_removes_view_metadata(panel_context):
    c = panel_context
    c.render()
    c.st.interact(f"{PREFIX}_smooth", True)
    stage_invalidation.invalidate_baseline_dependents(c.st.session_state)
    assert STAGE not in c.st.session_state["pipeline_data"]
    c.render()
    assert not saved(c)["smoothing_enabled"]


@pytest.mark.parametrize("kind", ["source", "loaded"])
def test_existing_input_invalidation_clears_temporary_controls(panel_context, kind):
    c = panel_context
    c.render()
    if kind == "source":
        stage_invalidation.invalidate_source_dependents(c.st.session_state)
    else:
        stage_invalidation.invalidate_loaded_input_dependents(c.st.session_state, new_session_id="next-session")
    assert not any(key.startswith(PREFIX) for key in c.st.session_state)
    assert STAGE not in c.st.session_state["pipeline_data"]


@pytest.fixture
def page05_context(panel_context, monkeypatch):
    """Run the real modified page with named calibration/session API doubles."""
    c = panel_context
    state = c.st.session_state
    state["completed_stages"] = UPSTREAM.copy()
    state["baseline_corrected_spectrum"] = copy.deepcopy(c.spectrum)
    state["loaded_spectrum"] = {"restfreq": 6668518000., "date": "2007-01-01T00:00:00"}
    state["latest_fit"] = {"keep": "unsmoothed fit"}
    checkpoints = []
    sync_calls = []
    session = SimpleNamespace(
        init_session_state=lambda: None,
        sync_baseline_state=lambda: sync_calls.append(True),
        mark_stage_complete=lambda key: state["completed_stages"].add(key),
        log_event=c.events.append,
        checkpoint_session=checkpoints.append,
        completed_count=lambda: len(state["completed_stages"]),
        completed_before=lambda stage: sum(key in state["completed_stages"] for key in UPSTREAM),
    )
    atmos = dict(frequency="66685", pwv=1., elevation=60., azimuth=180., atcor=1.1,
                 nd_lcp=1., nd_rcp=1., optical_depth=0.03)
    series = dict(mjd=[100.], pss=[2.], error=[0.1])
    stats = dict(mean=2., std=None, count=1)

    def fake_calibrate(spectrum, atcor, lcp_pss, rcp_pss, nd_lcp, nd_rcp):
        return {
            "Vlsr": spectrum["Vlsr"].copy(),
            "LCP": spectrum["LCP"] * (nd_lcp * atcor * lcp_pss),
            "RCP": spectrum["RCP"] * (nd_rcp * atcor * rcp_pss),
        }

    calibration = SimpleNamespace(
        get_atmospheric_calibration=lambda spec: atmos.copy(),
        get_pss_history=lambda freq: dict(frequency="66685", lcp=series, rcp=series, source_files={}),
        get_pss_window=lambda date: dict(observation_mjd=100., start_mjd=85., end_mjd=115., days=15),
        get_pss_window_averages=lambda history, window: dict(lcp=2., rcp=2.),
        get_pss_trailing_statistics=lambda history, mjd, days: dict(start_mjd=70., end_mjd=100., lcp=stats, rcp=stats),
        apply_calibration_to_spectrum=fake_calibrate,
    )
    for key, module in (("session_store", session), ("sidebar", SimpleNamespace(render_sidebar=lambda **kw: None)),
                        ("calibration_logic", calibration), ("polarization_panel", c.panel)):
        monkeypatch.setattr(c.package, key, module, raising=False)
        monkeypatch.setitem(sys.modules, f"utils.{key}", module)

    def run():
        c.st.figures.clear()
        c.st.messages.clear()
        return runpy.run_path(str(ROOT / "hartspec_gui/pages/05_Calibration_Dashboard.py"))

    c.run_page, c.calibration, c.checkpoints, c.sync_calls = run, calibration, checkpoints, sync_calls
    return c


def test_page05_uses_calibrated_source_and_preserves_state_on_rerun(page05_context):
    c = page05_context
    c.run_page()
    assert saved(c)["source_key"] == "calibrated"
    assert saved(c)["intensity_unit"] == "Jy"
    original = copy.deepcopy(c.st.session_state["calibrated_spectrum"])
    c.st.interact(f"{PREFIX}_smooth", True)
    c.run_page()
    assert saved(c)["smoothing_enabled"]
    assert c.st.session_state["latest_fit"] == {"keep": "unsmoothed fit"}
    for key in logic.ARRAY_KEYS:
        np.testing.assert_array_equal(c.st.session_state["calibrated_spectrum"][key], original[key])
    assert len(c.sync_calls) == 2
    assert "Polarization display settings recorded" in c.checkpoints
    assert c.st.session_state["completed_stages"] == UPSTREAM | {STAGE}


def test_page05_baseline_fallback_is_explicit_when_calibration_unavailable(page05_context):
    c = page05_context
    c.calibration.get_pss_window_averages = lambda history, window: dict(lcp=None, rcp=None)
    c.run_page()
    assert saved(c)["source_key"] == "baseline"
    assert saved(c)["intensity_unit"] == "K"
    assert STAGE not in c.st.session_state["completed_stages"]


def test_page05_incomplete_upstream_never_uses_orphaned_arrays(page05_context):
    c = page05_context
    c.st.session_state["completed_stages"].discard("03_bandpass_correction")
    c.run_page()
    assert logic.SETTINGS_KEY not in c.st.session_state["pipeline_data"][STAGE]
    assert all([trace.name for trace in fig.data] != ["LCP", "RCP", "Mean", "Stokes I"] for fig in c.st.figures)
    assert c.st.messages["info"]


def test_page05_retains_baseline_view_without_loaded_metadata(page05_context):
    """Missing calibration metadata must not reset valid FR-09 view preferences."""
    c = page05_context
    c.st.session_state.pop('loaded_spectrum', None)
    c.run_page()
    assert saved(c)['source_key'] == 'baseline'
    c.st.interact(f'{PREFIX}_smooth', True)
    c.run_page()
    assert saved(c)['smoothing_enabled'] is True
    c.st.interact(f'{PREFIX}_window', 11)
    c.run_page()
    assert saved(c)['window_length'] == 11
    assert STAGE not in c.st.session_state['completed_stages']


def test_page05_malformed_saved_stage_does_not_crash(page05_context):
    """Session-envelope validation does not validate each stage's nested schema."""
    c = page05_context
    c.st.session_state['pipeline_data'][STAGE] = 'invalid saved stage'
    c.run_page()
    assert saved(c)['source_key'] == 'calibrated'
    assert any('saved' in message.lower() for message in c.st.messages['warning'])


def test_panel_rejects_malformed_owner_without_overwriting_other_metadata(panel_context):
    """A reusable panel must not silently repair its owning stage's scientific metadata."""
    c = panel_context
    c.st.session_state['pipeline_data'][STAGE] = 'invalid saved stage'
    assert not c.render()
    assert c.st.messages['error']
    assert c.st.session_state['pipeline_data'][STAGE] == 'invalid saved stage'


def test_page05_header_counts_only_preceding_stages(page05_context):
    """Adding FR-09 must not add a ninth stage or count Page 05 as its own predecessor."""
    c = page05_context
    c.run_page()
    assert STAGE in c.st.session_state["completed_stages"]
    header = "\n".join(c.st.messages["markdown"])
    assert "4/8 stages complete" in header


def test_panel_malformed_pipeline_is_reported_without_crashing(panel_context):
    c = panel_context
    c.st.session_state["pipeline_data"] = None
    assert not c.render()
    assert c.st.messages["error"]
    assert c.st.session_state["pipeline_data"] is None


def test_callback_ignores_malformed_pipeline_before_rerun(panel_context):
    c = panel_context
    c.render()
    c.st.session_state["pipeline_data"] = None
    c.st.interact(f"{PREFIX}_smooth", True)
    assert c.st.session_state["pipeline_data"] is None
