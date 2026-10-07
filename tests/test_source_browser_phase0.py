# test_source_browser_phase0.py — FR-01: tests for the UAT-feedback revision of Page 01 + the Phase 0 File_check.
#
# Covers: folder-navigator helpers, File_check workspace/link handling, the File_check integration glue, and
# clc/File_check.py's Phase 0 behaviour (callable, re-runnable, no os.chdir, same block output).
# File_check's scientific sorting is NOT re-tested here beyond a known-good dataset — it is unchanged legacy logic.
# Assumes hartspec_gui/ is on sys.path (as for the other tests) and that clc/ is importable as a package.

import os
from pathlib import Path

import pytest

from clc import File_check
from utils import source_browser_logic as sbl


def _entry(path: Path) -> sbl.SourceFileEntry:
    return sbl.SourceFileEntry(path=path, filename=path.name, size_mb=0.0, status="OK")


def _fake_load_file(path):
    """Stand-in for clc.load_file.load_file: encodes position/pointing in the name, e.g. 20260812_01_HPN_1.fits."""
    parts = Path(path).name[:-5].split("_")
    return {"position": parts[2], "pointing": int(parts[3])}


class _FakeHdu:
    def __init__(self, header=None, data=None):
        self.header, self.data = header or {}, data


def _fake_fits_open(path):
    if "BAD" in Path(path).name:
        raise IOError("corrupt")
    pos, pointing = _fake_load_file(path)["position"], _fake_load_file(path)["pointing"]
    return [_FakeHdu({"SPPOINT": pointing}), _FakeHdu(), _FakeHdu({"POSITION": pos}, {"Vlsr": [1.0]})]


@pytest.fixture
def patched_file_check(monkeypatch):
    """File_check with its two FITS-reading dependencies faked, so no real FITS data is needed."""
    monkeypatch.setattr(File_check.lf, "load_file", _fake_load_file, raising=False)
    monkeypatch.setattr(File_check.pyfits, "open", _fake_fits_open)
    return File_check


FULL_DAY = ["{d}_01_HPN_1", "{d}_02_HPS_1", "{d}_03_HPE_1", "{d}_04_HPW_1",
            "{d}_05_ON_1", "{d}_06_OFF_1", "{d}_07_ON_0", "{d}_08_OFF_0"]


def _make_dataset(folder: Path, days=("20260812", "20260813"), extra=()):
    folder.mkdir(parents=True, exist_ok=True)
    names = [t.format(d=d) for d in days for t in FULL_DAY] + list(extra)
    for name in names:
        (folder / f"{name}.fits").write_text("")
    return names


# --------------------------------------------------------------------------- File_check (Phase 0)

def test_run_file_check_sorts_blocks_and_logs_bad_files(tmp_path, patched_file_check):
    _make_dataset(tmp_path / "OB" / "FR", extra=["20260813_99_BAD_0"])
    result = patched_file_check.run_file_check("OB", "FR", tmp_path)
    assert [Path(p).name for p in result["block_files"]] == ["20260812_0.txt", "20260813_0.txt"]
    first_block = Path(result["block_files"][0]).read_text().split()
    assert first_block == [f"{t.format(d='20260812')}.fits" for t in FULL_DAY]  # real filenames, in order
    assert Path(result["bad_data_file"]).read_text().split() == ["20260813_99_BAD_0.fits"]


def test_run_file_check_does_not_change_working_directory(tmp_path, patched_file_check):
    _make_dataset(tmp_path / "OB" / "FR")
    before = os.getcwd()
    patched_file_check.run_file_check("OB", "FR", tmp_path)
    assert os.getcwd() == before  # the original os.chdir() broke every relative path in the app


def test_run_file_check_can_run_repeatedly_on_same_folder(tmp_path, patched_file_check):
    _make_dataset(tmp_path / "OB" / "FR")
    first = patched_file_check.run_file_check("OB", "FR", tmp_path)
    second = patched_file_check.run_file_check("OB", "FR", tmp_path)
    assert [Path(p).read_text() for p in first["block_files"]] == [Path(p).read_text() for p in second["block_files"]]
    assert second["num_files"] == 16  # not 32: the old file list is not appended to


def test_run_file_check_missing_folder_raises_clearly(tmp_path, patched_file_check):
    with pytest.raises(FileNotFoundError):
        patched_file_check.run_file_check("OB", "FR", tmp_path)


# --------------------------------------------------------------------------- folder navigator helpers

def test_list_subdirectories_sorted_and_skips_hidden_and_quarantine(tmp_path):
    for name in ["b_dir", "A_dir", ".hidden", sbl.fits_ingest.QUARANTINE_DIRNAME]:
        (tmp_path / name).mkdir()
    (tmp_path / "file.txt").write_text("x")
    subs, truncated = sbl.list_subdirectories(tmp_path)
    assert [p.name for p in subs] == ["A_dir", "b_dir"]
    assert truncated is False


def test_list_subdirectories_truncates(tmp_path):
    for i in range(5):
        (tmp_path / f"d{i}").mkdir()
    subs, truncated = sbl.list_subdirectories(tmp_path, limit=3)
    assert len(subs) == 3 and truncated is True


def test_list_subdirectories_unreadable_returns_empty(tmp_path):
    assert sbl.list_subdirectories(tmp_path / "does_not_exist") == ([], False)


def test_count_fits_files_counts_only_direct_fits(tmp_path):
    (tmp_path / "a.fits").write_text("")
    (tmp_path / "b.FIT").write_text("")
    (tmp_path / "c.txt").write_text("")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "d.fits").write_text("")
    assert sbl.count_fits_files(tmp_path) == 2


def test_parent_directory_of_root_is_itself():
    root = Path(Path.cwd().anchor)
    assert sbl.parent_directory(root) == root


# --------------------------------------------------------------------------- workspace + integration glue

def test_safe_path_component():
    assert sbl.safe_path_component("W3(OH)") == "W3_OH"
    assert sbl.safe_path_component("G328.24-0.55") == "G328.24-0.55"
    assert sbl.safe_path_component("../..") == "unknown"


def test_prepare_workspace_links_files_and_is_rebuilt_each_time(tmp_path):
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "20260812_01_HPN_1.fits").write_text("data")
    entries = [_entry(archive / "20260812_01_HPN_1.fits")]
    work_dir, skipped = sbl.prepare_file_check_workspace(entries, tmp_path / "ws", "W3(OH)", "1420.405")
    assert work_dir == tmp_path / "ws" / "W3_OH" / "1420.405"
    assert (work_dir / "20260812_01_HPN_1.fits").read_text() == "data"
    assert skipped == []

    # second call with a different selection must not keep the first call's file
    (archive / "20260813_01_HPN_1.fits").write_text("more")
    work_dir, _ = sbl.prepare_file_check_workspace(
        [_entry(archive / "20260813_01_HPN_1.fits")], tmp_path / "ws", "W3(OH)", "1420.405")
    assert sorted(p.name for p in work_dir.iterdir()) == ["20260813_01_HPN_1.fits"]
    assert (archive / "20260812_01_HPN_1.fits").exists()  # the archive itself is never touched


def test_prepare_workspace_skips_duplicate_basenames(tmp_path):
    for sub in ("a", "b"):
        (tmp_path / sub).mkdir()
        (tmp_path / sub / "20260812_01_HPN_1.fits").write_text(sub)
    entries = [_entry(tmp_path / "a" / "20260812_01_HPN_1.fits"), _entry(tmp_path / "b" / "20260812_01_HPN_1.fits")]
    _, skipped = sbl.prepare_file_check_workspace(entries, tmp_path / "ws", "S", "1")
    assert skipped == [str(tmp_path / "b" / "20260812_01_HPN_1.fits")]


def test_run_observation_block_sort_end_to_end(tmp_path, patched_file_check, monkeypatch):
    archive = tmp_path / "archive"
    names = _make_dataset(archive, extra=["20260813_99_BAD_0"])
    monkeypatch.setattr(sbl, "_import_run_file_check", lambda: patched_file_check.run_file_check)
    entries = [_entry(archive / f"{n}.fits") for n in names]
    outcome = sbl.run_observation_block_sort(entries, tmp_path / "ws", "W3(OH)", 1420.405)
    assert sorted(outcome.blocks) == ["20260812_0.txt", "20260813_0.txt"]
    assert len(outcome.blocks["20260812_0.txt"]) == 8
    assert outcome.discarded_files == ["20260813_99_BAD_0.fits"]
    assert outcome.not_linked == []
    assert len(os.listdir(archive)) == len(names)  # archive untouched


def test_run_observation_block_sort_propagates_file_check_errors(tmp_path, monkeypatch):
    def boom(*_args):
        raise KeyError("POSITION")
    monkeypatch.setattr(sbl, "_import_run_file_check", lambda: boom)
    (tmp_path / "x.fits").write_text("")
    with pytest.raises(KeyError):
        sbl.run_observation_block_sort([_entry(tmp_path / "x.fits")], tmp_path / "ws", "S", 1420.405)
