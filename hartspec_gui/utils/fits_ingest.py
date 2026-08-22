"""FR-02/FR-03 FITS ingestion wrapper around the clc/ scientific modules.

This module never modifies clc/load_file.py or clc/load_file2.py -- per
explicit project instruction, their internals are off-limits. Instead it
calls them defensively and adds the application-layer behavior FR-02/FR-03
need: validation status, date-convention detection, a raw-header fallback
for the FITS Extension Viewer, manual column mapping, and the quarantine
move (which this project's spec says to write ourselves -- clc/File_check.py
does not provide one).

Two real integration gaps were found by running both loaders against a real
sample file (not guessed -- verified in a sandbox):

1. clc/load_file.py raises ``KeyError`` on files that lack a RESTFREQ key in
   HDU0 (the module assumes the key exists but may be falsy; some real
   files don't have the key at all). When this happens, ``ingest_fits``
   reports status "error" and falls back to a raw-header read so the page
   still has something to show, rather than crashing.

2. clc/load_file2.py hard-codes a DATE-OBS lookup with no fallback, so it
   also raises KeyError on any file using the legacy DATE convention --
   which is exactly the condition FR-02's "auto-detect date convention"
   feature is supposed to surface. Rather than patch load_file2.py, this
   module calls it as a *probe*: if it raises specifically on DATE-OBS,
   that failure IS the detection signal (legacy-convention file). If it
   succeeds, the file uses the modern convention.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import numpy as np
from astropy.io import fits as pyfits

import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from clc import load_file as _load_file_mod
from clc import load_file2 as _load_file2_mod

# --------------------------------------------------------------------------
# Paths -- mirrors the convention already used in utils/session_store.py,
# but resolved live via a function rather than baked into a module-level
# constant. This matters for testability: Streamlit's AppTest harness
# reuses Python's module cache across runs in the same process, so a
# monkeypatched *constant* set after first import is invisible to it.
# Reading the env var at call time avoids that, and as a side effect lets
# ops override the archive location in deployment without a code change.
# --------------------------------------------------------------------------
_DEFAULT_FITS_ARCHIVE_DIR = Path(__file__).resolve().parents[2] / "data" / "fits"


def get_fits_archive_dir() -> Path:
    return Path(os.environ.get("HARTSPEC_FITS_ARCHIVE_DIR", _DEFAULT_FITS_ARCHIVE_DIR))


def get_flagged_dir() -> Path:
    return get_fits_archive_dir() / "Flagged"


# Kept as module-level names too, for readability at call sites and
# backward-compat with anything importing them directly -- but these are
# only a snapshot at import time, so prefer the get_*() functions above in
# new code and in anything that needs to respect a test-time override.
FITS_ARCHIVE_DIR = get_fits_archive_dir()
FLAGGED_DIR = get_flagged_dir()

# Keys in clc/load_file.py's returned dict that hold full per-channel or
# per-record arrays rather than one scalar per file. Hard-coded because
# they're intrinsic to that module's fixed dict contract, not something
# that varies per FITS file.
ARRAY_FIELDS = {"Vlsr", "LCP", "RCP", "Cal1_lcp", "Cal2_rcp", "mjd_date"}

Status = Literal["ok", "warning", "error"]


@dataclass
class IngestResult:
    """Everything the File Loader page needs to render one FITS file."""

    filepath: Path
    status: Status
    issues: list[str] = field(default_factory=list)
    scalar_fields: dict[str, Any] | None = None  # from clc/load_file.py, minus array fields
    array_fields: dict[str, Any] | None = None  # the array-valued entries, split out for display
    date_convention: str | None = None  # "DATE-OBS" | "DATE (legacy)" | None if undeterminable
    raw_header: dict[str, Any] = field(default_factory=dict)  # always populated -- used for
    # both the crash fallback AND manual column mapping, regardless of whether load_file.py succeeded

    @property
    def filename(self) -> str:
        return self.filepath.name


def _split_scalar_and_array_fields(spectrum: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    scalars = {k: v for k, v in spectrum.items() if k not in ARRAY_FIELDS}
    arrays = {k: v for k, v in spectrum.items() if k in ARRAY_FIELDS}
    return scalars, arrays


def _probe_date_convention(filepath: Path) -> tuple[str | None, str | None]:
    """Call clc/load_file2.py purely to detect the date-header convention.

    Returns (convention, issue_message). We treat a KeyError on DATE-OBS
    specifically as a successful *detection* (legacy file), not a failure
    of this probe -- see module docstring.
    """
    try:
        _load_file2_mod.load_file(str(filepath))
        return "DATE-OBS", None
    except KeyError as exc:
        if "DATE-OBS" in str(exc):
            return "DATE (legacy)", (
                "Legacy DATE convention detected (no DATE-OBS key) -- "
                "clc/load_file2.py's DATE-OBS probe failed, which is the detection signal."
            )
        return None, f"load_file2.py convention probe failed unexpectedly: {exc}"
    except Exception as exc:  # noqa: BLE001 -- surface anything else as a probe issue, don't crash the page
        return None, f"load_file2.py convention probe raised {type(exc).__name__}: {exc}"


def _read_raw_header_fallback(filepath: Path) -> dict[str, Any]:
    """Read every scalar header value directly via astropy, namespaced by HDU.

    Always computed (not just on load_file.py failure) -- used both as the
    crash fallback AND as the source of choices for manual column mapping,
    since the user needs to be able to remap a priority field even when the
    automatic extraction succeeded.
    """
    fallback: dict[str, Any] = {}
    with pyfits.open(filepath) as hdulist:
        for hdu_index in range(len(hdulist)):
            header = hdulist[hdu_index].header
            for card in header.cards:
                if card.keyword in ("COMMENT", "HISTORY", ""):
                    continue
                fallback[f"HDU{hdu_index}.{card.keyword}"] = card.value
    return fallback


def ingest_fits(filepath: Path | str) -> IngestResult:
    """Load one FITS file's metadata for the File Loader page.

    Always calls clc/load_file.py first (per FR-02, this is the required
    extractor). If it raises, status becomes "error" and a raw-header
    fallback is attached so the Extension Viewer / table still has data.
    clc/load_file2.py is then probed purely for date-convention detection
    (FR-02's auto-detect requirement) -- see module docstring.
    """
    filepath = Path(filepath)
    issues: list[str] = []
    scalar_fields: dict[str, Any] | None = None
    array_fields: dict[str, Any] | None = None
    status: Status = "ok"

    # Raw header is always read -- cheap (header cards only, no bulk data),
    # and needed for manual column mapping even on a clean auto-detect.
    try:
        raw_header = _read_raw_header_fallback(filepath)
    except FileNotFoundError:
        return IngestResult(filepath=filepath, status="error", issues=[f"File not found: {filepath}"])
    except Exception as exc:  # noqa: BLE001
        return IngestResult(
            filepath=filepath,
            status="error",
            issues=[f"Could not open file at all: {type(exc).__name__}: {exc}"],
        )

    try:
        spectrum = _load_file_mod.load_file(str(filepath))
        scalar_fields, array_fields = _split_scalar_and_array_fields(spectrum)
    except KeyError as exc:
        status = "error"
        issues.append(f"load_file.py: missing expected header key {exc}")
    except Exception as exc:  # noqa: BLE001 -- any other clc failure is a validation issue, not a crash
        status = "error"
        issues.append(f"load_file.py raised {type(exc).__name__}: {exc}")

    date_convention, convention_issue = _probe_date_convention(filepath)
    if convention_issue:
        issues.append(convention_issue)
        if status == "ok":
            status = "warning"

    return IngestResult(
        filepath=filepath,
        status=status,
        issues=issues,
        scalar_fields=scalar_fields,
        array_fields=array_fields,
        date_convention=date_convention,
        raw_header=raw_header,
    )


# --------------------------------------------------------------------------
# FITS Extension Viewer (FR-02)
# --------------------------------------------------------------------------
@dataclass
class ExtensionInfo:
    index: int
    name: str
    hdu_type: str
    dimensions: str
    n_header_cards: int
    n_data_columns: int | None


def list_extensions(filepath: Path | str) -> list[ExtensionInfo]:
    """List every HDU in a FITS file, for the Extension Viewer dropdown."""
    extensions: list[ExtensionInfo] = []
    with pyfits.open(filepath) as hdulist:
        for idx, hdu in enumerate(hdulist):
            n_cols = len(hdu.data.columns.names) if hasattr(hdu.data, "columns") else None
            dims = "()" if hdu.data is None else str(getattr(hdu.data, "shape", "()"))
            extensions.append(
                ExtensionInfo(
                    index=idx,
                    name=hdu.name or f"HDU{idx}",
                    hdu_type=type(hdu).__name__,
                    dimensions=dims,
                    n_header_cards=len(hdu.header),
                    n_data_columns=n_cols,
                )
            )
    return extensions


def read_extension_header(filepath: Path | str, hdu_index: int) -> list[tuple[str, Any, str]]:
    """Read one HDU's header as (keyword, value, comment) tuples.

    Returned as tuples rather than a dict because FITS headers can have
    repeated keywords (e.g. multiple COMMENT cards), which would silently
    collide and overwrite each other in a dict.
    """
    with pyfits.open(filepath) as hdulist:
        header = hdulist[hdu_index].header
        return [(card.keyword, card.value, card.comment) for card in header.cards]


# --------------------------------------------------------------------------
# FR-03 quarantine -- written here per explicit instruction, since
# clc/File_check.py does not provide a move function.
# --------------------------------------------------------------------------
def move_to_flagged(filepath: Path | str, flagged_dir: Path | None = None) -> Path:
    """Move a corrupt/flagged FITS file into the Flagged/ subdirectory.

    This is the one write action permitted against the otherwise read-only
    /data/fits/ archive (see FR-03 / the project's data-access rules). The
    `hartspec` service account needs write permission specifically on
    `flagged_dir` -- it stays read-only everywhere else under
    /data/fits/, so this will raise PermissionError until that's configured
    on the server; that's expected, not a bug in this function.

    Parameters
    ----------
    flagged_dir:
        Defaults to `get_flagged_dir()` (live-resolved) if not given --
        pass an explicit path in tests rather than relying on the default.

    Raises
    ------
    FileNotFoundError
        If `filepath` doesn't exist.
    PermissionError
        If the process can't write to `flagged_dir` (expected until IT
        grants write access there, per the path-convention answer this was
        built against).
    """
    filepath = Path(filepath)
    if flagged_dir is None:
        flagged_dir = get_flagged_dir()
    if not filepath.exists():
        raise FileNotFoundError(f"Cannot quarantine -- file not found: {filepath}")

    flagged_dir.mkdir(parents=True, exist_ok=True)
    destination = flagged_dir / filepath.name

    if destination.exists():
        # Don't silently overwrite a previously quarantined file with the
        # same name -- append a UTC timestamp instead.
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        destination = flagged_dir / f"{filepath.stem}__{stamp}{filepath.suffix}"

    shutil.move(str(filepath), str(destination))
    return destination


# --------------------------------------------------------------------------
# Priority field display (build spec's 9 highlighted fields)
# --------------------------------------------------------------------------
def format_array_summary(arr: Any, unit: str = "") -> str:
    arr = np.asarray(arr)
    if arr.size == 0:
        return "(empty)"
    suffix = f" {unit}".rstrip()
    return f"{np.nanmin(arr):.2f} to {np.nanmax(arr):.2f}{suffix} ({arr.size} chans)"


def priority_field_rows(
    result: IngestResult, manual_mapping: dict[str, str] | None = None
) -> list[tuple[str, str]]:
    """Build the 9 build-spec priority (label, value) rows for the top of
    the header table, from whichever data source succeeded.

    Falls back gracefully field-by-field -- a single missing key doesn't
    blank the whole row, it shows "not available" for just that field.

    Parameters
    ----------
    manual_mapping:
        Optional ``{priority_label: raw_header_key}`` overrides (raw_header_key
        being one of `result.raw_header`'s namespaced keys, e.g.
        ``"HDU0.DATE"``). When a label has an override, it wins over the
        auto-detected value -- this is the FR-02 manual column mapping
        feature.
    """
    scalars = result.scalar_fields or {}
    arrays = result.array_fields or {}
    raw = result.raw_header

    def scalar(key: str, raw_key: str | None = None) -> str:
        if key in scalars:
            return str(scalars[key])
        if raw_key and raw_key in raw:
            return f"{raw[raw_key]} (raw fallback)"
        return "not available"

    rows: list[tuple[str, str]] = []

    if "Vlsr" in arrays:
        rows.append(("Vlsr", format_array_summary(arrays["Vlsr"], "km/s")))
    else:
        rows.append(("Vlsr", "not available"))

    if "LCP" in arrays and "RCP" in arrays:
        lcp, rcp = np.asarray(arrays["LCP"]), np.asarray(arrays["RCP"])
        rows.append(("LCP/RCP", f"peak {np.nanmax(lcp):.2f} K / {np.nanmax(rcp):.2f} K"))
    else:
        rows.append(("LCP/RCP", "not available"))

    rows.append(("HPBW", scalar("HPBW", "HDU1.HPBW")))

    tsys_lcp = scalars.get("Tsys_lcp")
    tsys_rcp = scalars.get("Tsys_rcp")
    if tsys_lcp is not None and tsys_rcp is not None:
        rows.append(("Tsys", f"{tsys_lcp:.2f} K / {tsys_rcp:.2f} K (LCP/RCP)"))
    else:
        rows.append(("Tsys", "not available"))

    rows.append(("Date", scalar("date", "HDU0.DATE")))
    rows.append(("Object", scalar("object", "HDU0.OBJECT")))
    # RA/Dec: not produced by load_file.py, and not present as a raw header
    # key on the sample file this was verified against (only telescope
    # LONGITUD/LATITUDE are present, which are a different quantity).
    # Flagged rather than guessed -- ask before wiring a source here.
    rows.append(("RA/Dec", "not available -- no RA/Dec key found; see note in page docstring"))
    rows.append(("Focus", scalar("Focus", "HDU0.FOCUS")))
    rows.append(("Humidity", scalar("Humid", "HDU0.HUMIDITY")))

    if manual_mapping:
        overridden = {}
        for label, raw_key in manual_mapping.items():
            if raw_key and raw_key in raw:
                overridden[label] = f"{raw[raw_key]} (manual: {raw_key})"
        rows = [(label, overridden.get(label, value)) for label, value in rows]

    return rows


def list_available_fits(archive_dir: Path | None = None) -> list[Path]:
    """List loadable .fits files directly under archive_dir, excluding Flagged/.

    Defaults to `get_fits_archive_dir()` (live-resolved) if not given.
    """
    if archive_dir is None:
        archive_dir = get_fits_archive_dir()
    if not archive_dir.exists():
        return []
    return sorted(
        p for p in archive_dir.glob("*.fits") if p.parent == archive_dir
    )