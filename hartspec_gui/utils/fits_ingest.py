"""Application-layer FITS ingestion wrapper (FR-02) and structural
verification (FR-03).

Wraps `clc/load_file.py` (DATE convention) and `clc/load_file2.py`
(DATE-OBS convention) defensively. Neither module is modified, per the
project's "scientific modules are off-limits" rule.

Both loaders raise `KeyError` the moment a header key they expect isn't
present -- `load_file.py` bails out as early as the `TCAL1` check (before
it even reaches `RESTFREQ`), and `load_file2.py` bails out on its first
access, `DATE-OBS`, if a file actually uses the `DATE` convention instead.
This means a `KeyError` from either loader is ambiguous by itself: it could
mean "wrong convention" or "this file is missing real science data". This
module resolves that ambiguity the only way that's actually reliable --
try both loaders and see which one (if either) succeeds:

  - `load_file` succeeds                       -> convention = "date"
  - `load_file` fails, `load_file2` succeeds   -> convention = "date-obs"
  - both fail                                  -> convention = "unknown";
    both underlying errors are kept so a human can tell "wrong convention"
    apart from "genuinely corrupt/incomplete" during review.

FR-03 structural corruption detection lives here too now, as
`verify_fits_file()` -- see its docstring for exactly what it does and
does not catch. Quarantine (shutil.move to Flagged/) is NOT wired in yet
-- that's a later step, separate review.

Known open gap (flagged, not fabricated): neither loader returns RA/Dec
source coordinates -- only telescope `LONGITUD`/`LATITUDE` are present.
Anything downstream that wants RA/Dec must say so explicitly rather than
silently substituting telescope pointing for source coordinates.
"""

from __future__ import annotations

import os
import shutil
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

# clc/load_file.py and clc/load_file2.py both do `import matplotlib.pyplot
# as plt` at module level, even though neither ever actually plots
# anything -- it's a dead import inherited from the original CLI scripts.
# On Windows, matplotlib commonly defaults to the TkAgg GUI backend, and
# initializing Tkinter on a background thread is a known hang (Tkinter
# isn't thread-safe) -- which is exactly the thread Streamlit's AppTest
# (and, less obviously, Streamlit's own script-runner) executes page code
# on. This MUST run before `import load_file` / `import load_file2` below,
# and before those modules are imported anywhere else in the process.
# Can't fix this in the CLC modules themselves (off-limits), so it's
# forced here instead -- "Agg" is a headless, file-only backend, safe on
# any thread, and this call is a no-op if a backend was already set.
import matplotlib

matplotlib.use("Agg")

from astropy.io import fits

from utils.env import load_dotenv_if_present

load_dotenv_if_present()

# Default FITS archive root per the project's mandated folder layout
# (/data/fits/, read-only, separate from the app directory). Overridable
# via FITS_ARCHIVE_PATH -- the SAME env var pages/01_Source_Browser.py
# reads (via source_browser_logic.DEFAULT_FITS_ARCHIVE_PATH), matching the
# naming convention documented in HARTSPEC-Claude_Project_Prompt.md
# ("FITS_ARCHIVE_PATH=./data/fits"). Read on every call (not cached at
# import time) so a test can set the env var right before calling, even if
# this module was already imported.
#
# CONFIRMED 2026-08-26: this module previously invented its own name,
# HARTSPEC_FITS_ARCHIVE_ROOT, before Page 01's real archive-scanning code
# existed to expose the conflict -- Page 01 would resolve one directory,
# Page 02 a different one, and every file Page 01 handed off would 404 on
# Page 02 even though the archive genuinely existed (just at the other
# path). Standardized on FITS_ARCHIVE_PATH; HARTSPEC_FITS_ARCHIVE_ROOT is
# retired outright, not kept as a silent fallback -- a stale .env should
# fail loudly (empty archive / FileNotFoundError) rather than quietly keep
# reading the wrong directory.
DEFAULT_ARCHIVE_ROOT = Path("./data/fits")


def get_archive_root() -> Path:
    """Return the active FITS archive root, honoring the env-var override."""
    override = os.environ.get("FITS_ARCHIVE_PATH")
    return Path(override) if override else DEFAULT_ARCHIVE_ROOT


# clc/ is a flat directory of modules that import each other directly
# (e.g. `import File_Manage as FE` inside File_Manage.py itself), not a
# Python package -- so we add it to sys.path rather than assuming
# `from clc import load_file` works with a package-style import.
#
# LAYOUT (confirmed 2026-08-27): clc/ is a symlink INSIDE hartspec_gui/,
# a sibling of utils/ and pages/ -- matching the project's mandated
# folder structure exactly. This supersedes the earlier parents[2] lookup
# (clc/ as a sibling of hartspec_gui/ itself), which was a real,
# confirmed-different on-disk layout at the time, not a guess -- the
# symlink has since been fixed to match the spec, so this now does too.
CLC_DIR = Path(__file__).resolve().parents[1] / "clc"
if str(CLC_DIR) not in sys.path:
    sys.path.insert(0, str(CLC_DIR))


try:
    import load_file as _lf_date  # DATE convention
    _LF_DATE_IMPORT_ERROR: str | None = None
except ImportError as exc:  # pragma: no cover - environment-dependent
    _lf_date = None
    _LF_DATE_IMPORT_ERROR = str(exc)

try:
    import load_file2 as _lf_dateobs  # DATE-OBS convention; imports specutils
    _LF_DATEOBS_IMPORT_ERROR: str | None = None
except ImportError as exc:  # pragma: no cover - specutils missing
    _lf_dateobs = None
    _LF_DATEOBS_IMPORT_ERROR = str(exc)


Convention = Literal["date", "date-obs", "unknown"]


@dataclass
class IngestResult:
    """Result of attempting to load one FITS file's header/spectrum."""

    filename: str
    path: Path
    ok: bool                         # a loader succeeded
    convention: Convention
    spectrum: dict[str, Any] | None
    load_errors: dict[str, str] = field(default_factory=dict)  # {"date": "...", "date-obs": "..."}
    attempts: list[str] = field(default_factory=list)          # human-readable trace, in order


def _try_loader(loader_module, path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Call a CLC loader's `load_file(path)` defensively. Never raises."""
    try:
        return loader_module.load_file(str(path)), None
    except KeyError as exc:
        return None, f"KeyError: missing header key {exc}"
    except OSError as exc:
        # Astropy raises OSError subtypes for "not a FITS file" / truncated
        # files -- distinct from a KeyError convention mismatch.
        return None, f"OSError: {exc}"
    except Exception as exc:  # noqa: BLE001 - deliberately broad, converted to a message, not swallowed
        return None, f"{type(exc).__name__}: {exc}"


def ingest_fits_file(path: str | Path) -> IngestResult:
    """Load one FITS file's spectrum/header, auto-detecting DATE vs DATE-OBS.

    Tries `load_file` (DATE) first, then `load_file2` (DATE-OBS) only if
    the first one fails. Which loader succeeds *is* the FR-02 convention-
    detection result -- this is the intended signal, not swallowed.
    """
    path = Path(path)
    filename = path.name
    attempts: list[str] = []
    load_errors: dict[str, str] = {}

    if _lf_date is None:
        return IngestResult(
            filename=filename, path=path, ok=False, convention="unknown", spectrum=None,
            load_errors={"date": f"clc/load_file.py import failed: {_LF_DATE_IMPORT_ERROR}"},
            attempts=[f"load_file: import failed -- {_LF_DATE_IMPORT_ERROR}"],
        )

    spectrum, err = _try_loader(_lf_date, path)
    if spectrum is not None:
        attempts.append("load_file (DATE): succeeded")
        return IngestResult(
            filename=filename, path=path, ok=True, convention="date",
            spectrum=spectrum, load_errors=load_errors, attempts=attempts,
        )
    load_errors["date"] = err
    attempts.append(f"load_file (DATE): failed -- {err}")

    if _lf_dateobs is None:
        load_errors["date-obs"] = f"clc/load_file2.py import failed: {_LF_DATEOBS_IMPORT_ERROR}"
        attempts.append(f"load_file2 (DATE-OBS): unavailable -- {_LF_DATEOBS_IMPORT_ERROR}")
        return IngestResult(
            filename=filename, path=path, ok=False, convention="unknown",
            spectrum=None, load_errors=load_errors, attempts=attempts,
        )

    spectrum, err = _try_loader(_lf_dateobs, path)
    if spectrum is not None:
        attempts.append("load_file2 (DATE-OBS): succeeded")
        return IngestResult(
            filename=filename, path=path, ok=True, convention="date-obs",
            spectrum=spectrum, load_errors=load_errors, attempts=attempts,
        )
    load_errors["date-obs"] = err
    attempts.append(f"load_file2 (DATE-OBS): failed -- {err}")

    return IngestResult(
        filename=filename, path=path, ok=False, convention="unknown",
        spectrum=None, load_errors=load_errors, attempts=attempts,
    )


# ---------------------------------------------------------------------------
# FR-03: structural verification (fits.verify / checksum), independent of
# ingest_fits_file() above. A file can pass verify_fits_file() and still
# fail ingest_fits_file() (e.g. missing science keys), and vice versa (a
# byte-truncated file can sometimes still yield a header CLC can partially
# parse before it hits the missing bytes) -- these are two different
# questions, not layers of the same check, so they're kept as two separate
# functions with two separate result types rather than merged into one.
# ---------------------------------------------------------------------------

@dataclass
class VerificationResult:
    """Result of a structural corruption check on one FITS file (FR-03)."""

    filename: str
    path: Path
    ok: bool                    # no structural issues found
    issues: list[str] = field(default_factory=list)
    # True only if the file actually carried CHECKSUM/DATASUM keywords to
    # check -- most raw telescope output won't, so False here does NOT mean
    # "unverified and therefore suspect", just "nothing to checksum-check
    # in this file".
    checksum_checked: bool = False


def verify_fits_file(path: str | Path) -> VerificationResult:
    """Structural corruption check for one FITS file (FR-03).

    This is a STRUCTURAL check only, distinct from `ingest_fits_file()`
    above:
      - Opens the file with `fits.open(path, checksum=True)`, which
        validates CHECKSUM/DATASUM if present.
      - Forces every HDU's `.data` to actually be read, not just its
        header -- a truncated file can have a perfectly well-formed
        primary header and only fail once the missing/short data block is
        actually reached, so header-only inspection isn't enough.
      - Runs `HDUList.verify("exception")`, astropy's own FITS-standard
        structural check (malformed cards, inconsistent data-size
        keywords, etc.).
      - Checksum/datasum mismatches surface as warnings in some astropy
        versions rather than exceptions, so warnings are captured and
        promoted to issues too, not just raised exceptions.

    What this does NOT catch (out of scope for this function -- these are
    FR-02/ingest concerns, or unknown until we see faulty.fits): missing
    science header keys, bad/NaN data *values*, or wrong-but-well-formed
    science content. If a file passes this function but still can't be
    trusted, that gap is real and separate -- don't assume this function
    is a complete corruption check until it's been run against faulty.fits
    and the result reviewed.

    Never raises -- always returns a result, even for a file that can't be
    opened at all.
    """
    path = Path(path)
    filename = path.name
    issues: list[str] = []
    checksum_checked = False

    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")

            with fits.open(path, checksum=True) as hdul:
                for hdu in hdul:
                    try:
                        _ = hdu.data  # force the data block to actually be read
                    except Exception as exc:  # noqa: BLE001
                        issues.append(
                            f"{type(exc).__name__} reading data for HDU "
                            f"{hdu.name or hdu.__class__.__name__}: {exc}"
                        )

                try:
                    hdul.verify("exception")
                except fits.VerifyError as exc:
                    issues.append(f"VerifyError: {exc}")

            for w in caught:
                msg = str(w.message)
                if "checksum" in msg.lower() or "datasum" in msg.lower():
                    checksum_checked = True
                    issues.append(f"Checksum warning ({w.category.__name__}): {msg}")

    except OSError as exc:
        # Astropy raises OSError subtypes for "not a FITS file" / truncated
        # / unreadable files -- the most likely outcome for a byte-level
        # corrupt file, caught here rather than propagating.
        issues.append(f"OSError: could not open/read file -- {exc}")
    except Exception as exc:  # noqa: BLE001 - deliberately broad, converted to a message, not swallowed
        issues.append(f"{type(exc).__name__}: {exc}")

    return VerificationResult(
        filename=filename,
        path=path,
        ok=not issues,
        issues=issues,
        checksum_checked=checksum_checked,
    )


# ---------------------------------------------------------------------------
# FR-03: real quarantine move. Per the project's mandated architecture, the
# FITS archive is read-only everywhere EXCEPT this one action -- and even
# this is only ever triggered from a confirmed user action in the UI (see
# pages/02_File_Loader.py's confirm/cancel flow), never automatically.
# ---------------------------------------------------------------------------

class QuarantineError(Exception):
    """Raised when a file can't be moved to Flagged/ -- caught by the page,
    never allowed to crash the app. A distinct exception type (rather than
    letting OSError/shutil.Error propagate raw) so the page can show one
    consistent error message regardless of the underlying cause (missing
    file, permissions, cross-device move, etc.)."""


def move_to_quarantine(filename: str) -> Path:
    """Move one file from the archive root into `<archive_root>/Flagged/`,
    per the project's mandated folder structure (`/data/fits/Flagged/`,
    not a relative path like the original CLI scripts used).

    `filename` may include a subdirectory prefix (e.g.
    "2026-08/spectrum_002.fits", per Page 01's directory-tree scan) -- the
    destination inside Flagged/ deliberately uses only the basename, not a
    mirrored subdirectory structure, since the build spec's FR-03 section
    describes a single flat Flagged/ directory, not a parallel tree.

    Collision handling: if a file with the same basename already exists in
    Flagged/ (two different subdirectories both containing e.g.
    "spectrum_002.fits", or the same file quarantined twice), this does
    NOT silently overwrite it -- that would be silent data loss on a
    read-only-except-quarantine archive, which is exactly the failure mode
    the read-only design is meant to prevent. Instead the destination gets
    a numeric suffix (spectrum_002.fits -> spectrum_002__2.fits). This
    wasn't specified anywhere in the source docs; flagging it here as a
    real (if judgment-call) decision rather than a silent default.

    Raises QuarantineError (never a raw OSError/shutil.Error) if the move
    can't complete, so the caller can show one consistent message.
    """
    archive_root = get_archive_root()
    source_path = archive_root / filename

    if not source_path.is_file():
        raise QuarantineError(f"{filename} was not found under the archive root ({source_path}).")

    flagged_dir = archive_root / "Flagged"
    try:
        flagged_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise QuarantineError(f"could not create/access {flagged_dir}: {exc}") from exc

    dest_path = flagged_dir / source_path.name
    if dest_path.exists():
        stem, suffix = source_path.stem, source_path.suffix
        counter = 2
        while dest_path.exists():
            dest_path = flagged_dir / f"{stem}__{counter}{suffix}"
            counter += 1

    try:
        shutil.move(str(source_path), str(dest_path))
    except (OSError, shutil.Error) as exc:
        raise QuarantineError(f"could not move {filename} to {dest_path}: {exc}") from exc

    return dest_path