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

FR-03 structural corruption detection lives here too, as
`verify_fits_file()` -- see its docstring for exactly what it does and
does not catch.

Known open gap (flagged, not fabricated): neither loader returns RA/Dec
source coordinates -- only telescope `LONGITUD`/`LATITUDE` are present.
Anything downstream that wants RA/Dec must say so explicitly rather than
silently substituting telescope pointing for source coordinates.

--------------------------------------------------------------------------
WINDOWS QUARANTINE-DELETE FIX (this revision)
--------------------------------------------------------------------------
Symptom reported from a real Windows dev machine: confirming quarantine on
a flagged file copies it into `Flagged/` but the original file is NOT
removed from the active archive -- the file ends up living in both places
at once, silently, with no error surfaced to the page.

Root cause: `astropy.io.fits.open()` memory-maps FITS files by default
(`memmap=True`). On Windows, an active memory mapping keeps a real OS-level
handle open on the underlying file until the Python object that created it
is actually closed or garbage-collected -- unlike POSIX, Windows generally
refuses to rename OR delete a file that still has such a handle open
(`PermissionError` / WinError 32, "the process cannot access the file
because it is being used by another process"). `shutil.move()`'s internal
fallback path (used whenever a plain `os.rename()` fails, e.g. because the
file is memory-mapped) is `copy2()` then `os.unlink()` -- the copy succeeds
regardless (reading a memory-mapped file is fine), but the trailing
`os.unlink()` on the ORIGINAL path can fail for the same open-handle
reason, leaving a real duplicate on disk. `clc/load_file.py` /
`load_file2.py` open every FITS file this way and, being simple adapted
CLI scripts, never explicitly close what they open -- and both are
off-limits to modify, so this can't be fixed at the source.

Two changes, both at this wrapper layer (same justification pattern as
the `matplotlib.use("Agg")` fix below: can't fix clc/, so the safe default
is forced here instead):

1. `fits.conf.use_memmap = False`, set once at import time, applies
   process-wide to every `fits.open()` call with no explicit `memmap=`
   argument -- including calls made from inside `clc/load_file.py` /
   `load_file2.py`, since Python config state is shared across modules in
   the same process. This means FITS data is read fully into memory
   up-front rather than memory-mapped, so there's no lingering OS-level
   mapping left behind once the returned dict/object goes out of scope.
2. Defensive belt-and-braces in `move_to_quarantine()` itself: force a
   `gc.collect()` immediately before the move (closes out any HDUList
   object that's already unreferenced but hasn't been swept yet), then
   retry the actual `shutil.move()` a few times with a short backoff if it
   raises `PermissionError` specifically, rather than failing on the very
   first attempt. This covers the case where a loader is still holding a
   plain (non-memmapped) file handle open at the exact moment quarantine
   is confirmed.

Not verified on a real Windows machine by this assistant (no Windows
environment available here) -- this is the standard, documented fix for
this exact astropy/Windows failure signature, but please confirm for real:
after confirming quarantine, check the original directory in Explorer/
`dir` directly, not just the browser's QUARANTINED badge, since the UI
badge is exactly what silently lied before this fix.
--------------------------------------------------------------------------
"""

from __future__ import annotations

import gc
import os
import shutil
import sys
import time
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

from astropy.io import fits  # noqa: E402 -- must follow matplotlib.use("Agg") above

# Windows quarantine-delete fix -- see this module's header comment for
# the full diagnosis. Setting this BEFORE `clc/load_file.py` /
# `load_file2.py` are imported below matters less than it did for the
# matplotlib backend (this is a mutable config flag read at each
# `fits.open()` call, not a one-time backend selection), but it's kept in
# the same "configure astropy before anything else touches it" spot for
# consistency and to make the fix trivially easy to find later. This is
# an I/O default, not a change to any scientific algorithm or output
# value -- it does not affect what data is read, only whether the OS
# keeps a memory mapping open afterward.
fits.conf.use_memmap = False

from utils.env import load_dotenv_if_present  # noqa: E402 -- must follow fits.conf.use_memmap above

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


# Single source of truth for the quarantine destination's directory name --
# `move_to_quarantine()` below writes into `<archive_root>/<this>`, and
# `source_browser_logic.py`'s directory scanner imports this same constant
# to make sure a quarantined file's new home is never re-discovered as a
# selectable source file (see that module's own comment on the bug this
# caused: a quarantined file kept getting re-scanned, re-selected, and
# re-quarantined into an increasingly suffixed duplicate).
QUARANTINE_DIRNAME = "Flagged"


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


# Windows quarantine-delete fix, part 2 -- see this module's header
# comment. Short, bounded retry: three attempts, doubling backoff, only
# for PermissionError specifically (the concrete symptom of a lingering
# Windows file handle) -- anything else (missing file, real permissions
# problem unrelated to a stale handle, etc.) still fails immediately
# rather than being retried pointlessly.
_QUARANTINE_MOVE_RETRY_ATTEMPTS = 3
_QUARANTINE_MOVE_RETRY_DELAY_S = 0.15


def _move_with_retry(source_path: Path, dest_path: Path) -> None:
    """Attempt `shutil.move`, retrying past a transient Windows file lock.

    A `gc.collect()` runs before every attempt (including the first) to
    close out any FITS `HDUList` object that clc's loaders opened and
    never explicitly closed, but that has already gone out of scope --
    this is the actual fix for the reported symptom, not just a delay.
    Only `PermissionError` triggers a retry; any other `OSError`/
    `shutil.Error` propagates immediately to the caller, unchanged from
    before this revision.
    """
    last_error: OSError | None = None
    for attempt in range(1, _QUARANTINE_MOVE_RETRY_ATTEMPTS + 1):
        gc.collect()
        try:
            shutil.move(str(source_path), str(dest_path))
            return
        except PermissionError as exc:
            last_error = exc
            if attempt < _QUARANTINE_MOVE_RETRY_ATTEMPTS:
                time.sleep(_QUARANTINE_MOVE_RETRY_DELAY_S * attempt)
    # All retries exhausted -- re-raise the last real error rather than a
    # generic message, so the resulting QuarantineError still tells the
    # user (and the audit log) what Windows actually said.
    raise last_error


def quarantine_dir(base_dir: str | Path | None = None) -> Path:
    """Return the folder `move_to_quarantine()` will move files into, without touching the disk.

    Used by both the move itself and the Page 02 confirm text, so the folder shown to the researcher is always
    the folder actually used. `base_dir=None` means the archive root; a `base_dir` already named `Flagged` is
    used as-is rather than nested.
    """
    root = get_archive_root() if base_dir is None else Path(base_dir).expanduser()
    if base_dir is not None and root.name.lower() == QUARANTINE_DIRNAME.lower():
        return root
    return root / QUARANTINE_DIRNAME


def move_to_quarantine(filename: str, base_dir: str | Path | None = None) -> Path:
    """Move one file into a `Flagged/` folder inside `base_dir` (the directory
    the user browsed to on Page 01), or inside the archive root when
    `base_dir` is None (the original behaviour, kept for callers that have
    no browsed directory, e.g. the Page 02 developer-default file).

    Why `base_dir` exists: `Flagged/` used to ALWAYS be created under
    `FITS_ARCHIVE_PATH`, even when the user had browsed to a different
    directory. Researchers never edit `.env`, so they would not know where
    the quarantined files went. `Flagged/` now sits in the directory the
    user entered, so the files are always where they expect them.

    `base_dir` only decides where `Flagged/` is created. The SOURCE file is
    still resolved as `get_archive_root() / filename` (absolute filenames
    pass through unchanged), exactly as ingestion resolves it, so the file
    that was validated is the file that gets moved.

    If `base_dir` is itself named `Flagged` (the user browsed straight into a
    quarantine folder), that folder is used as the destination rather than
    creating `Flagged/Flagged/`; a file already directly inside it is
    reported as already quarantined and is not moved.

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

    The actual move is delegated to `_move_with_retry()` -- see this
    module's header comment for why a plain single-shot `shutil.move()`
    was not reliable on Windows.

    Raises QuarantineError (never a raw OSError/shutil.Error) if the move
    can't complete, so the caller can show one consistent message.
    """
    archive_root = get_archive_root()
    source_path = archive_root / filename

    if not source_path.is_file():
        raise QuarantineError(f"{filename} was not found under the archive root ({source_path}).")

    if base_dir is not None and not Path(base_dir).expanduser().is_dir():
        # Never fall back to FITS_ARCHIVE_PATH here -- that would silently recreate the original bug.
        raise QuarantineError(
            f"the browsed directory {Path(base_dir).expanduser()} does not exist, so Flagged/ cannot be created."
        )
    flagged_dir = quarantine_dir(base_dir)

    if source_path.resolve().parent == flagged_dir.resolve():
        return source_path  # already in the quarantine folder; moving it onto itself would only create a __2 duplicate

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
        _move_with_retry(source_path, dest_path)
    except (OSError, shutil.Error) as exc:
        raise QuarantineError(
            f"could not move {filename} to {dest_path}: {exc}. "
            "On Windows this usually means another handle to the file is "
            "still open (e.g. from FITS ingestion) -- try again in a "
            "moment, and close any external program that may have the "
            "file open."
        ) from exc

    return dest_path
