# test_batch_processing_ui.py — FR-21: headless pinning, review skip and progress button.
"""Widget control-flow checks with Streamlit replaced by a narrow fake API."""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from contextlib import nullcontext
from pathlib import Path

from test_batch_runner import prepared
from test_batch_template import reference
from utils import batch_queue


class FakeSt(types.ModuleType):
    """Record Streamlit actions without requiring a running Streamlit server."""

    def __init__(self):
        super().__init__("streamlit")
        self.clicked = set()
        self.input_values = {}
        self.messages = []
        self.reruns = 0
        self.session_state = {}

    def expander(self, *args, **kwargs):
        return nullcontext()

    def spinner(self, *args, **kwargs):
        return nullcontext()

    def selectbox(self, label, options, **kwargs):
        chosen = self.input_values.get(kwargs.get("key"))
        return chosen if chosen in options else options[0]

    def checkbox(self, label, *, key, **kwargs):
        return bool(self.input_values.get(key, False))

    def button(self, label, *, key, **kwargs):
        return key in self.clicked

    def text_input(self, label, *, key, **kwargs):
        return self.input_values.get(key, "")

    def text_area(self, label, *, key, **kwargs):
        return self.input_values.get(key, "")

    def rerun(self):
        self.reruns += 1

    def empty(self):
        return self

    def progress(self, value, **kwargs):
        self.messages.append(f"progress {value}")

    def divider(self):
        return None

    def plotly_chart(self, *args, **kwargs):
        self.messages.append("plot chart")

    def download_button(self, *args, **kwargs):
        return False

    def markdown(self, message, **kwargs):
        self.messages.append(message)

    caption = warning = success = info = error = markdown


def app(monkeypatch):
    """Load the actual processing panel after injecting the fake display facade."""
    st = FakeSt()
    monkeypatch.setitem(sys.modules, "streamlit", st)
    path = Path(batch_queue.__file__).with_name("batch_processing_ui.py")
    spec = importlib.util.spec_from_file_location("utils._fr21_processing_ui_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return st, module


def test_pin_valid_manual_save_through_source_browser_controls(tmp_path, monkeypatch):
    """The reference selector must invoke the real whitelist template loader."""
    root, manifest = prepared(tmp_path, count=1)
    # Reconstruct a not-yet-enabled queue, like the Source Browser creates.
    path = root / "batches" / f"{manifest['batch_id']}.json"
    raw = json.loads(path.read_text())
    raw.update(processing_enabled=False, template=None, template_signature=None, template_session_id=None,
               revision=1)
    path.write_text(json.dumps(raw))
    (root / "abc12345.json").write_text(json.dumps(reference()))
    st, ui = app(monkeypatch)
    st.clicked.add(f"fr21_pin_{manifest['batch_id']}")
    ui.render_processing_controls(batch_queue.load_batch(root, manifest["batch_id"]), sessions_root=root)
    pinned = batch_queue.load_batch(root, manifest["batch_id"])
    assert pinned["processing_enabled"] is True
    assert pinned["template_session_id"] == "abc12345"
    assert pinned["template"]["settings"]["pointing_peak_velocity_kms"] == -4.2
    assert st.reruns == 1


def test_unapprovable_review_can_be_skipped_through_ui(tmp_path, monkeypatch):
    """The skip button must stay reachable when there is no approvable plot."""
    root, manifest = prepared(tmp_path, count=1)
    job = manifest["jobs"][0]
    running = batch_queue.update_job_status(root, manifest["batch_id"], job["job_id"], "running",
                                            expected_revision=manifest["revision"])
    held = batch_queue.update_job_status(
        root, manifest["batch_id"], job["job_id"], "needs_review",
        expected_revision=running["revision"], reason="No matching calibration reference",
        review_stage="06_pointing_correction", approvable=False,
    )
    st, ui = app(monkeypatch)
    prefix = f"fr21_{job['job_id']}"
    st.input_values[f"{prefix}_skip_operator"] = "Review Operator"
    st.input_values[f"{prefix}_skip_reason"] = "Pointing reference absent; cannot produce a reliable fit"
    st.clicked.add(f"{prefix}_skip")
    ui.render_processing_controls(held, sessions_root=root)
    latest = batch_queue.load_batch(root, manifest["batch_id"])
    assert latest["jobs"][0]["status"] == "failed"
    assert latest["jobs"][0]["review"]["skipped_by"] == "Review Operator"
    assert st.reruns == 1
    assert any("cannot replace missing" in str(line) for line in st.messages)


def test_run_control_wires_stage_progress_and_refresh(tmp_path, monkeypatch):
    """A run click must call the sequential runner and display stage updates."""
    root, manifest = prepared(tmp_path, count=1)
    st, ui = app(monkeypatch)
    st.clicked.add(f"fr21_run_{manifest['batch_id']}")
    invoked = []

    def runner(root_, batch_, *, on_stage):
        invoked.append((root_, batch_))
        on_stage("04_baseline_editor")
        return manifest

    monkeypatch.setattr(ui.batch_runner, "run_campaign", runner)
    ui.render_processing_controls(manifest, sessions_root=root)
    assert invoked == [(root, manifest["batch_id"])]
    assert any("progress 0.5" in str(message) for message in st.messages)
    assert st.reruns == 1


def test_multi_pair_assignment_ui_requires_explicit_mapping_and_splits(tmp_path, monkeypatch):
    """Streamlit action passes named mapping into the checked queue split operation."""
    from test_batch_observations import complex_observation

    root, manifest, inspect, _ = complex_observation(tmp_path)
    st, ui = app(monkeypatch)
    monkeypatch.setattr(ui.batch_observations, "inspect_observation_job", inspect)
    batch_id = manifest["batch_id"]
    job_id = manifest["jobs"][0]["job_id"]
    st.clicked.add(f"fr21_inspect_{batch_id}")
    ui.render_processing_controls(manifest, sessions_root=root)
    preview = st.session_state[f"fr21_inspection_{batch_id}"]
    assert len(preview["pairs"]) == len(preview["scans"]) == 2

    st.clicked.clear()
    for index, scan in enumerate(preview["scans"], start=1):
        st.input_values[f"fr21_scan_{batch_id}_{job_id}_{index}"] = scan["key"]
    st.input_values[f"fr21_plan_operator_{job_id}"] = "Observer"
    st.input_values[f"fr21_plan_note_{job_id}"] = "Paired by observed scan sequence"
    st.clicked.add(f"fr21_split_{job_id}")
    ui.render_processing_controls(batch_queue.load_batch(root, batch_id), sessions_root=root)
    result = batch_queue.load_batch(root, batch_id)
    assert len(result["jobs"]) == 2
    assert st.reruns == 1
    assert all(job.get("pair_assignment") for job in result["jobs"])


def test_completed_job_replays_via_existing_fr19_loader(tmp_path, monkeypatch):
    """The button hands only the isolated session JSON path to the normal FR-19 loader."""
    from test_batch_runner import output_files
    from utils import batch_queue as queue

    root, manifest = prepared(tmp_path, count=1)
    job = manifest["jobs"][0]
    running = queue.update_job_status(root, manifest["batch_id"], job["job_id"], "running",
                                      expected_revision=manifest["revision"])
    for stage in ("04_baseline_editor", "06_pointing_correction"):
        running = queue.record_automatic_gate_pass(root, manifest["batch_id"], job["job_id"], stage,
                                                   expected_revision=running["revision"],
                                                   evidence="Synthetic unit-test decision")
    filenames = output_files(root, manifest, job)
    finished = queue.update_job_status(root, manifest["batch_id"], job["job_id"], "completed",
                                       expected_revision=running["revision"],
                                       session_id="synthetic_job", output_files=filenames,
                                       stage="08_export_and_session")
    st, ui = app(monkeypatch)
    loaded_paths = []
    module = types.ModuleType("utils.session_store")
    module.load_session = lambda path: loaded_paths.append(path)
    ingest = types.ModuleType("utils.fits_ingest")
    ingest.get_archive_root = lambda: Path(job["archive_root"])
    monkeypatch.setitem(sys.modules, "utils.fits_ingest", ingest)
    monkeypatch.setattr(sys.modules["utils"], "fits_ingest", ingest, raising=False)
    monkeypatch.setitem(sys.modules, "utils.session_store", module)
    monkeypatch.setattr(sys.modules["utils"], "session_store", module, raising=False)
    st.clicked.add(f"fr21_replay_{job['job_id']}")
    ui.render_processing_controls(finished, sessions_root=root)
    assert loaded_paths == [root / "batches" / manifest["batch_id"] /
                            "jobs" / job["job_id"] / "session.json"]
