"""Application-layer FITS ingestion wrapper (FR-02).

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

FR-03 corruption detection (fits.verify) and quarantine (shutil.move to
Flagged/) are NOT in this module yet -- that's a separate step, separate
review.

Known open gap (flagged, not fabricated): neither loader returns RA/Dec
source coordinates -- only telescope `LONGITUD`/`LATITUDE` are present.
Anything downstream that wants RA/Dec must say so explicitly rather than
silently substituting telescope pointing for source coordinates.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

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