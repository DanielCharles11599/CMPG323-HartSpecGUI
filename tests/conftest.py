"""Shared pytest fixtures for the HARTSPEC GUI test suite.

Adds hartspec_gui/ to sys.path (so `from utils import ...` / `from pages import
...`-style imports work the same way they do when Streamlit runs the app),
and builds a small set of synthetic FITS files once per test session so
tests never depend on real HartRAO data being present on disk.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]  # repo root -- tests/ is a SIBLING of hartspec_gui/, not nested
HARTSPEC_GUI_DIR = REPO_ROOT / "hartspec_gui"
if str(HARTSPEC_GUI_DIR) not in sys.path:
    sys.path.insert(0, str(HARTSPEC_GUI_DIR))

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
import make_fixtures  # noqa: E402

from utils.env import load_dotenv_if_present  # noqa: E402
from utils import session_store  # noqa: E402

# Load .env once, at collection time -- before any fixture below reads
# os.environ. Without this, real_fits_archive's env check only worked by
# accident (whichever test happened to import utils.fits_ingest first).
load_dotenv_if_present()


@pytest.fixture(scope="session")
def fits_fixtures_dir(tmp_path_factory) -> Path:
    """Build the synthetic FITS fixtures once per test run, return their dir."""
    out_dir = tmp_path_factory.mktemp("fits_fixtures")
    make_fixtures.build_all(out_dir)
    return out_dir


@pytest.fixture()
def fits_archive(monkeypatch, fits_fixtures_dir, tmp_path) -> Path:
    """Point utils.fits_ingest.get_archive_root() at the synthetic fixtures
    for the duration of one test, via the same env var the app itself
    honors -- so no test-only code path exists inside fits_ingest.py.

    Also isolates session_store.SESSIONS_DIR to a fresh per-test temp
    directory. Without this, every page's sidebar.render_sidebar() reads
    real saved session files from wherever SESSIONS_DIR resolves on the
    machine running the tests (session_store._default_sessions_dir()
    falls back to the real production "/data/sessions" path if it
    happens to exist there) -- any leftover session file from manually
    running the real app leaks into the "Load Session" selectbox during
    every AppTest run, which Streamlit's AppTest harness chokes on (a
    real bug in its own selectbox-option handling, not something this
    project's code can work around other than keeping real session files
    out of test runs entirely). SESSIONS_DIR is set via monkeypatch.setattr
    rather than the SESSIONS_PATH env var, since it's a module-level
    constant computed once at import time -- setting the env var later
    wouldn't retroactively change it.

    FITS_ARCHIVE_PATH is the canonical name (matches
    source_browser_logic.DEFAULT_FITS_ARCHIVE_PATH / the project prompt's
    documented convention) -- confirmed 2026-08-26, replacing the earlier
    HARTSPEC_FITS_ARCHIVE_ROOT name that only fits_ingest.py used, which
    caused Page 01 and Page 02 to silently resolve two different
    directories.
    """
    monkeypatch.setenv("FITS_ARCHIVE_PATH", str(fits_fixtures_dir))
    monkeypatch.setattr(session_store, "SESSIONS_DIR", tmp_path / "sessions")
    return fits_fixtures_dir


@pytest.fixture()
def real_fits_archive(monkeypatch, tmp_path) -> Path:
    """Point at a folder of REAL HartRAO FITS files on your own machine,
    instead of the synthetic ones -- opt-in, via an env var only you set.
    ...(existing docstring unchanged)...
    """
    import os

    real_dir = os.environ.get("HARTSPEC_REAL_FITS_DIR")
    if not real_dir:
        pytest.skip("HARTSPEC_REAL_FITS_DIR not set -- skipping real-file test")
    path = Path(real_dir)
    if not path.is_dir():
        pytest.skip(f"HARTSPEC_REAL_FITS_DIR={real_dir} is not a directory")
    monkeypatch.setenv("FITS_ARCHIVE_PATH", str(path))
    monkeypatch.setattr(session_store, "SESSIONS_DIR", tmp_path / "sessions")
    return path


@pytest.fixture()
def isolated_fits_archive(tmp_path, monkeypatch) -> Path:
    """A FRESH, function-scoped copy of the synthetic FITS fixtures...
    ...(existing docstring unchanged)...
    """
    out_dir = tmp_path / "fits_archive"
    make_fixtures.build_all(out_dir)
    monkeypatch.setenv("FITS_ARCHIVE_PATH", str(out_dir))
    monkeypatch.setattr(session_store, "SESSIONS_DIR", tmp_path / "sessions")
    return out_dir
