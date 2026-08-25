# source_browser_logic.py — FR-01: pure/testable logic backing
# pages/01_Source_Browser.py. Kept separate from the Streamlit page script (rather
# than defined inline in the page) specifically so it can be unit-tested without a
# Streamlit ScriptRunContext — importing a pages/*.py file directly would execute
# st.set_page_config()/st.* calls at import time and fail outside a running app.
#
# Nothing in this module hardcodes a color, coordinate, or theme value — those all
# live in utils/styles.py (theme tokens) and the page script's layout constants,
# which are derived from HARTSPEC-Page_Build_Spec.md §4/§6/§7.

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from astropy.io import fits

# ---------------------------------------------------------------------------
# Pipeline-wide constants
# ---------------------------------------------------------------------------

# This page's own key in utils/session_store.py's `pipeline_data` dict and
# `completed_stages` set (passed to session_store.mark_stage_complete()).
# TODO: confirm against design — see build spec §3. session_store.py itself
# doesn't enforce or enumerate a canonical key format (mark_stage_complete
# accepts any string), so this must match whatever convention the other 7
# already-built pages use for their own stage keys.
THIS_STAGE_KEY = "01_source_browser"

# Build spec §7 (page 01) gives exactly one confirmed frequency: "1420.405 MHz —
# HI line". No other selectable frequencies are specified anywhere in the three
# source docs.
# TODO: confirm against design — ask the user to pull the full FR-01 frequency
# menu (e.g. OH/CH3OH/H2O maser lines used at HartRAO) from NotebookLM rather
# than inventing additional entries here.
FREQUENCY_OPTIONS: List[str] = [
    "1420.405 MHz — HI line",
]

# Matches the .env conventions in HARTSPEC-Claude_Project_Prompt.md
# ("FITS_ARCHIVE_PATH=./data/fits", "PSS_DATA_PATH=./data/pss"). Read once at
# import time as *defaults only* — scan_source_groups() below always accepts
# explicit paths too, so tests (and callers who want a different archive) never
# have to touch environment variables or the real /data directory.
DEFAULT_FITS_ARCHIVE_PATH = os.environ.get("FITS_ARCHIVE_PATH", "./data/fits")
DEFAULT_PSS_DATA_PATH = os.environ.get("PSS_DATA_PATH", "./data/pss")

# Status badge tokens this page can render, mapped to utils/styles.py's
# StatusName literal ("ok" / "warning" / "error" / "info") so the return value
# can be passed straight into styles.render_badge().
_STATUS_TO_BADGE_FAMILY: Dict[str, str] = {
    "OK": "ok",
    "FLAGGED": "error",
    "QUARANTINED": "error",
    "WARNING": "warning",
}


def status_css_class(status: str) -> str:
    """Map a file's validation status to one of styles.py's StatusName values.

    Args:
        status: Raw status string (e.g. "OK", "FLAGGED").

    Returns:
        One of "ok", "warning", "error", "info" — matches
        utils.styles.StatusName / STATUS_BADGES exactly.
    """
    return _STATUS_TO_BADGE_FAMILY.get(status.upper(), "info")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class SourceFileEntry:
    """A single selectable row in the FR-01 file browser.

    observation_date/declination are Optional because they come from a FITS
    header read (see _scan_fits_file below) that can legitimately fail or be
    missing the relevant keyword — a file listing shouldn't fabricate header
    data it couldn't actually read.
    """

    filename: str
    file_type: str  # "FITS" or "PSS"
    size_mb: float
    status: str
    observation_date: Optional[str] = None
    declination: Optional[str] = None


@dataclass
class SourceGroupEntry:
    """A checkbox group of files, keyed by observation month."""

    label: str
    files: List[SourceFileEntry] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Live archive scanning
#
# TODO: confirm against design. clc/File_check.py is FR-03's dedicated
# validation module and almost certainly already knows HARTSPEC's real FITS
# header conventions (which keyword actually holds the observation date/
# declination, what a "FLAGGED" file looks like, etc.). The header-reading
# logic below is a deliberately generic, standalone best-effort (standard
# DATE-OBS / DEC keywords) so this page doesn't hardcode file *data* — but it
# duplicates rather than reuses clc's domain knowledge, since clc/File_check.py
# wasn't available to check its actual function signatures against. If it
# exposes something usable, page 01 should probably call into it directly
# instead of the two helpers below, both for correctness and to avoid two
# validation code paths existing in the same app (FR-01's lightweight browse
# check here vs. FR-03's real validation on page 02).
# ---------------------------------------------------------------------------

def _format_declination(raw: object) -> Optional[str]:
    """Best-effort conversion of a FITS DEC header value to "+DD°MM'" form.

    Accepts either a pre-formatted sexagesimal string (returned as-is) or a
    numeric value in decimal degrees. Returns None for anything unparsable
    rather than guessing, so callers fall back to "pending" instead of
    displaying a wrong-looking value.
    """
    if raw is None:
        return None
    if isinstance(raw, str):
        return raw.strip() or None
    try:
        degrees_decimal = float(raw)
    except (TypeError, ValueError):
        return None
    sign = "+" if degrees_decimal >= 0 else "-"
    degrees_decimal = abs(degrees_decimal)
    degrees = int(degrees_decimal)
    minutes = int(round((degrees_decimal - degrees) * 60))
    if minutes == 60:
        degrees += 1
        minutes = 0
    return f"{sign}{degrees}°{minutes:02d}'"


def _scan_fits_file(path: Path) -> SourceFileEntry:
    """Build a SourceFileEntry from a real FITS file via a header-only read.

    Uses astropy's `fits.getheader`, which reads only the header block, not
    the (potentially ~500MB, per the project's data conventions) pixel data —
    keeps browsing fast even for a large archive.
    """
    size_mb = path.stat().st_size / (1024 * 1024)
    try:
        header = fits.getheader(path)
        status = "OK"
    except Exception:
        # Any unreadable/corrupt header is exactly what FR-03 validation
        # further downstream is for — flag it here rather than crash the
        # browser, and let page 02 do the authoritative check.
        header = {}
        status = "FLAGGED"

    date_obs = header.get("DATE-OBS")
    observation_date = str(date_obs)[:10] if date_obs else None
    declination = _format_declination(header.get("DEC"))

    return SourceFileEntry(
        filename=path.name,
        file_type="FITS",
        size_mb=size_mb,
        status=status,
        observation_date=observation_date,
        declination=declination,
    )


def _scan_pss_file(path: Path) -> SourceFileEntry:
    """Build a SourceFileEntry from a real PSS calibration text file.

    PSS files have no header to read for date/declination (no format for
    that is specified anywhere in the three source docs), so those fields
    stay None — the summary bar already degrades this to "pending" rather
    than fabricating a value.
    """
    size_mb = path.stat().st_size / (1024 * 1024)
    try:
        with path.open("r", encoding="utf-8", errors="strict") as handle:
            handle.readline()
        status = "OK"
    except OSError:
        status = "FLAGGED"

    return SourceFileEntry(filename=path.name, file_type="PSS", size_mb=size_mb, status=status)


def _month_key_and_label(entry: SourceFileEntry, mtime: float) -> Tuple[str, str]:
    """Derive the "YYYY-MM" group key/label for a file.

    Prefers the FITS header's observation date; falls back to filesystem
    mtime (always available) for PSS files and any FITS file whose header
    didn't yield a usable date.
    """
    if entry.observation_date:
        try:
            key = datetime.strptime(entry.observation_date[:7], "%Y-%m").strftime("%Y-%m")
            return key, f"{key} Observations"
        except ValueError:
            pass
    key = datetime.fromtimestamp(mtime).strftime("%Y-%m")
    return key, f"{key} Observations"


def scan_source_groups(fits_dir: Path, pss_dir: Path) -> List[SourceGroupEntry]:
    """Scan the real archive directories and group files by observation month.

    Deliberately takes explicit directories rather than reading environment
    variables itself, so it stays a pure function callers (including tests)
    can point at any directory — see get_source_groups() below for the
    .env-driven convenience wrapper actually used by the page.

    A missing directory is treated as "no files there yet" rather than an
    error — a freshly-cloned repo won't have /data/fits populated, and that
    shouldn't crash the browser.
    """
    fits_dir = Path(fits_dir)
    pss_dir = Path(pss_dir)

    files_by_month_key: Dict[str, List[SourceFileEntry]] = {}
    label_by_month_key: Dict[str, str] = {}

    if fits_dir.is_dir():
        for path in sorted(fits_dir.glob("*.fits")):
            entry = _scan_fits_file(path)
            key, label = _month_key_and_label(entry, path.stat().st_mtime)
            files_by_month_key.setdefault(key, []).append(entry)
            label_by_month_key[key] = label

    if pss_dir.is_dir():
        for path in sorted(pss_dir.glob("*.txt")):
            entry = _scan_pss_file(path)
            key, label = _month_key_and_label(entry, path.stat().st_mtime)
            files_by_month_key.setdefault(key, []).append(entry)
            label_by_month_key[key] = label

    groups = [
        SourceGroupEntry(
            label=label_by_month_key[key],
            files=sorted(files_by_month_key[key], key=lambda f: f.filename),
        )
        for key in files_by_month_key
    ]
    groups.sort(key=lambda g: g.label, reverse=True)  # most recent observation month first
    return groups


def get_source_groups(
    fits_dir: Optional[Path] = None,
    pss_dir: Optional[Path] = None,
) -> List[SourceGroupEntry]:
    """Convenience wrapper: scan_source_groups() using FITS_ARCHIVE_PATH /
    PSS_DATA_PATH from the environment when no explicit directories are given.

    This is what the page actually calls (wrapped in st.cache_data — see
    01_Source_Browser.py — since Streamlit reruns the whole script on every
    widget interaction, and re-scanning the archive and re-reading every FITS
    header on every checkbox click would be wasteful).
    """
    resolved_fits_dir = Path(fits_dir) if fits_dir is not None else Path(DEFAULT_FITS_ARCHIVE_PATH)
    resolved_pss_dir = Path(pss_dir) if pss_dir is not None else Path(DEFAULT_PSS_DATA_PATH)
    return scan_source_groups(resolved_fits_dir, resolved_pss_dir)


def all_filenames(groups: List[SourceGroupEntry]) -> List[str]:
    """Flatten every filename across groups, preserving group/file order."""
    return [f.filename for g in groups for f in g.files]


def files_by_name(groups: List[SourceGroupEntry]) -> Dict[str, SourceFileEntry]:
    """Index every file by filename for O(1) lookup when building the summary."""
    return {f.filename: f for g in groups for f in g.files}


def frequency_display_name(frequency_option: str) -> str:
    """Extract the short line name from a "<freq> — <name>" option string.

    "1420.405 MHz — HI line" -> "HI line". Falls back to the full string if the
    expected "—" separator isn't present, so a malformed option degrades
    gracefully instead of raising.
    """
    if "—" in frequency_option:
        return frequency_option.split("—", 1)[1].strip()
    return frequency_option.strip()


def build_summary_text(
    selected_filenames: List[str],
    files_index: Dict[str, SourceFileEntry],
    frequency_option: str,
) -> str:
    """Build the Selection summary bar text (build spec §7, page 01).

    With exactly one file selected and the default frequency, this reproduces
    the build spec's sample text exactly:
    "Selected: spectrum_002.fits · 2026-08-12 · HI line · Dec +12°34'"

    Style guide §6 leaves empty-state visual language unspecified ("ask before
    inventing new visual language for these") — this deliberately reuses the
    *same* summary-bar text style for the empty case rather than introducing a
    new component, and just changes the copy.
    """
    if not selected_filenames:
        return "No files selected — choose one or more from the list above."

    primary = files_index[selected_filenames[0]]
    freq_label = frequency_display_name(frequency_option)
    date = primary.observation_date or "date pending"
    dec = primary.declination or "pending"
    text = f"Selected: {primary.filename} · {date} · {freq_label} · Dec {dec}"

    extra = len(selected_filenames) - 1
    if extra > 0:
        text += f" (+{extra} more)"
    return text
