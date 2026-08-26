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
# via HARTSPEC_FITS_ARCHIVE_ROOT so tests/dev machines without a real
# /data/fits mount can point at a fixtures directory instead -- read on
# every call (not cached at import time) so a test can set the env var
# right before calling, even if this module was already imported.
DEFAULT_ARCHIVE_ROOT = Path("/data/fits")


def get_archive_root() -> Path:
    """Return the active FITS archive root, honoring the env-var override."""
    override = os.environ.get("HARTSPEC_FITS_ARCHIVE_ROOT")
    return Path(override) if override else DEFAULT_ARCHIVE_ROOT


# clc/ is a flat directory of modules that import each other directly
# (e.g. `import File_Manage as FE` inside File_Manage.py itself), not a
# Python package -- so we add it to sys.path rather than assuming
# `from clc import load_file` works with a package-style import.
#
# CURRENT LAYOUT (confirmed 2026-08-23, may change): clc/ sits one level
# ABOVE hartspec_gui/ -- i.e. a sibling of hartspec_gui/, not inside it.
# This differs from the folder structure documented in the project's own
# spec (clc/ as a symlink INSIDE hartspec_gui/, sibling of utils/) -- the
# team is deciding whether to move it inside hartspec_gui/ to match the
# spec. If/when that happens, this needs to go back to parents[1]:
#   CLC_DIR = Path(__file__).resolve().parents[1] / "clc"   # inside hartspec_gui/
# For now, parents[2] is correct for the real on-disk layout:
CLC_DIR = Path(__file__).resolve().parents[2] / "clc"
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
    checksum_checked: bool = False   # True only if the file actually carried
                                      # CHECKSUM/DATASUM keywords to check --
                                      # most raw telescope output won't, so
                                      # False here does NOT mean "unverified
                                      # and therefore suspect", just "nothing
                                      # to checksum-check in this file".


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