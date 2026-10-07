# source_browser_logic.py — pure/testable logic backing pages/01_Source_Browser.py
# (FR-01: Source & Frequency Browser). Kept separate from the Streamlit page
# script so it's importable by pytest without a Streamlit runtime — see the
# module-level note in 01_Source_Browser.py for why that split matters.
#
# Rebuilt against the FR-01 functional breakdown (supersedes the earlier
# Figma-mockup-only reading of this page):
#   - CLC modules replaced: Interact.py (terminal menu — naturally superseded
#     by real Streamlit widgets, no source needed) and File_check.py (file
#     sorting — now REAL: see run_observation_block_sort() below, which calls
#     clc/File_check.py's run_file_check() after its Phase 0 revision).
#   - Only raw FITS files (.fits / .fit) under a user-editable directory path
#     are in scope — no PSS files on this page.
#   - Source Name and Frequency are filter dropdowns populated from what's
#     actually found on disk, not a fixed list.
#   - The browser is a directory tree (nested expandable containers), not a
#     flat checkbox list.
#   - Nothing is written to disk permanently here; only
#     session_state["pipeline_data"] gets the filtered FITS paths, chosen
#     source name, chosen frequency, and earliest observation date. (The one
#     exception is File_check's observation-block files, written into the
#     session's own workspace folder -- never into the read-only FITS archive.)
#
# UAT-feedback revision: adds list_subdirectories()/count_fits_files()/
# parent_directory() for the in-page folder navigator, and replaces
# run_file_check_placeholder() with the real clc.File_check integration.
#
# --------------------------------------------------------------------------
# QUARANTINE-RESURFACING FIX (this revision)
# --------------------------------------------------------------------------
# Real bug, reported after Page 02's FR-03 quarantine work went live: a
# quarantined file (moved into `<archive_root>/Flagged/` by
# fits_ingest.move_to_quarantine()) kept getting re-discovered by this
# module's own directory scan on the very next Page 01 visit, since
# `_scan_directory()` had no exclusion for that subdirectory and walks
# every directory under the archive root. A re-discovered quarantined file
# looks like any other selectable .fits file, so it could be re-selected,
# handed to Page 02, fail to load again for the exact reason it was
# quarantined in the first place, and -- if quarantined again -- collide
# with its own already-suffixed name in Flagged/ (observed in the wild as
# filenames like "..._G328.24-0.55__2__2.fits", i.e. the same file
# suffix-collision-avoided twice across two separate accidental
# re-quarantine cycles).
#
# Fix: `_scan_directory()` now skips descending into any directory named
# `fits_ingest.QUARANTINE_DIRNAME` ("Flagged") entirely -- it's never
# added as a DirectoryNode, so nothing inside it (files or further
# subdirectories) can ever appear as a selectable source file again. This
# reuses fits_ingest.py's own constant rather than a second hardcoded
# "Flagged" string, so the two modules can't drift apart on the name.
#
# NOTE for anyone hitting this same symptom again after upgrading: this
# fix only stops the problem going forward. It does NOT retroactively
# clean an already-corrupted `pipeline_data["01_source_browser"]
# ["selected_files"]` list sitting in a currently-open browser session or
# an already-saved session JSON that references a "Flagged\..." path from
# before this fix. If a session saved before this fix still errors, re-run
# Page 01's selection (or start a fresh session) rather than assuming the
# code fix alone repairs old, already-serialized selections.
# --------------------------------------------------------------------------

import re
import shutil
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from astropy.io import fits

from utils import fits_ingest

# ---------------------------------------------------------------------------
# Pipeline-wide constants
# ---------------------------------------------------------------------------

# This page's own key in utils/session_store.py's `pipeline_data` dict and
# `completed_stages` set (passed to session_store.mark_stage_complete()).
# CONFIRMED: 02_File_Loader.py imports this exact constant
# (`from utils.source_browser_logic import THIS_STAGE_KEY as
# SOURCE_BROWSER_STAGE_KEY`) rather than hardcoding its own copy of the
# string, so the *outer* dict key can't drift between the two pages. The
# *inner* dict's field names could, and did -- see build_selected_files()
# below.
THIS_STAGE_KEY = "01_source_browser"

FITS_EXTENSIONS = (".fits", ".fit")

# Status badge tokens this page can render, mapped to utils/styles.py's
# StatusName literal ("ok" / "warning" / "error" / "info") so the return
# value can be passed straight into styles.render_badge().
_STATUS_TO_BADGE_FAMILY: Dict[str, str] = {
    "OK": "ok",
    "FLAGGED": "error",
    "QUARANTINED": "error",
    "WARNING": "warning",
}


def status_css_class(status: str) -> str:
    """Map a file's validation status to one of styles.py's StatusName values."""
    return _STATUS_TO_BADGE_FAMILY.get(status.upper(), "info")


def default_fits_directory() -> str:
    """Default value for the FR-01 directory path text input.

    Delegates to fits_ingest.get_archive_root() instead of independently
    re-reading FITS_ARCHIVE_PATH and re-deriving its own fallback. This
    used to have its own separate fallback branch (checking whether
    `/data/fits/` exists on this machine) that fits_ingest.get_archive_root()
    doesn't have -- meaning the two pages could resolve two different
    directories whenever FITS_ARCHIVE_PATH wasn't set. fits_ingest.py's own
    2026-08-26 note describes this exact failure mode already happening once
    before (under a different env-var name) -- Page 01 resolving one
    directory, Page 02 a different one, so every handoff 404'd. Calling the
    same function Page 02 uses is what actually prevents that class of bug,
    rather than just carefully keeping two copies of the same logic in sync
    by hand.
    """
    return str(fits_ingest.get_archive_root())


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class SourceFileEntry:
    """A single FITS file discovered under the browsed directory.

    source_name/frequency_mhz/observation_date/position are Optional because
    they come from a header read that can legitimately fail or be missing
    the relevant keyword — this shouldn't fabricate header data it couldn't
    read.

    position is the raw HPN/HPS/HPE/HPW/ON/OFF pointing-position tag (HDU 2's
    POSITION keyword) shown for the user's own information only. It is NOT
    File_check.py's real observation-block sorting — see
    run_file_check_placeholder()'s docstring for why that stateful grouping
    algorithm is deliberately not reimplemented here.
    """

    path: Path
    filename: str
    size_mb: float
    status: str
    source_name: Optional[str] = None
    frequency_mhz: Optional[float] = None
    observation_date: Optional[str] = None
    position: Optional[str] = None


@dataclass
class DirectoryNode:
    """One level of the directory tree view ("nested expandable containers")."""

    name: str
    path: Path
    subdirectories: List["DirectoryNode"] = field(default_factory=list)
    files: List[SourceFileEntry] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Live directory scanning
#
# CONFIRMED against clc/File_check.py's own (commented-out) reference
# implementation: OBJECT and RESTFREQ are both read from hdulist[0] (the
# primary header), exactly as this module already does. POSITION comes from
# hdulist[2] -- the same HDU 03_Bandpass_Correction.py's own
# _read_observation_metadata() already reads it from -- so position below
# reuses that same convention rather than guessing a different one.
#
# DATE, however, is read from hdulist[0].header['DATE'] in that same
# reference dict -- not DATE-OBS. fits_ingest.py's ingest_fits_file() exists
# specifically because both conventions are real (load_file.py = DATE,
# load_file2.py = DATE-OBS); a file using the older DATE-only convention was
# silently landing in the "Unknown date" browse group and being excluded
# from earliest/latest date calculations, since this function previously
# only ever checked DATE-OBS. Fixed below to check both.
# ---------------------------------------------------------------------------

def _scan_fits_file(path: Path) -> SourceFileEntry:
    """Header-only read of one FITS file (never touches pixel/table data).

    Opens the file once and reads two header blocks -- the primary HDU
    (OBJECT, RESTFREQ, DATE/DATE-OBS) and, when present, HDU 2 (POSITION,
    the HPN/HPS/HPE/HPW/ON/OFF pointing-position tag) -- rather than one
    fits.getheader() call per HDU.
    """
    size_mb = path.stat().st_size / (1024 * 1024)
    position: Optional[str] = None
    try:
        with fits.open(path) as hdul:
            primary_header = hdul[0].header
            status = "OK"
            if len(hdul) > 2:
                raw_position = hdul[2].header.get("POSITION")
                position = str(raw_position).strip().upper() if raw_position else None
    except Exception:
        # Real validation is FR-03's job downstream — flag here, don't crash
        # the browser.
        primary_header = {}
        status = "FLAGGED"

    raw_source = primary_header.get("OBJECT")
    source_name = str(raw_source).strip() or None if raw_source else None

    frequency_mhz: Optional[float] = None
    raw_freq_hz = primary_header.get("RESTFREQ")
    if raw_freq_hz is not None:
        try:
            frequency_mhz = round(float(raw_freq_hz) / 1e6, 3)
        except (TypeError, ValueError):
            frequency_mhz = None

    raw_date = primary_header.get("DATE-OBS") or primary_header.get("DATE")
    observation_date = str(raw_date)[:10] if raw_date else None

    return SourceFileEntry(
        path=path,
        filename=path.name,
        size_mb=size_mb,
        status=status,
        source_name=source_name,
        frequency_mhz=frequency_mhz,
        observation_date=observation_date,
        position=position,
    )


def _is_quarantine_directory(entry: Path) -> bool:
    """True for any directory named after fits_ingest's quarantine target.

    Case-insensitive on purpose -- Windows filesystems (this project's
    deployment target for the dev/test machines hitting this bug) treat
    directory names case-insensitively, so a stray "flagged"/"FLAGGED"
    would otherwise slip past a case-sensitive comparison and reintroduce
    the exact bug this function exists to prevent.
    """
    return entry.name.lower() == fits_ingest.QUARANTINE_DIRNAME.lower()


def scan_fits_directory_tree(root_dir: Path, max_depth: int = 4) -> Optional[DirectoryNode]:
    """Recursively scan root_dir for .fits/.fit files, building a directory tree.

    Returns None if root_dir doesn't exist — callers should treat that as
    "nothing to browse yet" (a freshly typed path, or a not-yet-mounted
    archive) rather than an error.

    max_depth caps recursion to guard against a pathologically deep directory
    structure; symlinked subdirectories are not followed, to avoid cycles.

    Never descends into the quarantine directory (fits_ingest.
    QUARANTINE_DIRNAME, "Flagged") -- files moved there by FR-03's
    quarantine action have been deliberately removed from the active
    pipeline and must never resurface as selectable source files. See this
    module's header comment for the real bug this prevents.
    """
    root_dir = Path(root_dir)
    if not root_dir.is_dir():
        return None
    return _scan_directory(root_dir, depth_remaining=max_depth)


def _scan_directory(directory: Path, depth_remaining: int) -> DirectoryNode:
    node = DirectoryNode(name=directory.name or str(directory), path=directory)

    try:
        entries = sorted(directory.iterdir())
    except OSError:
        return node

    for entry in entries:
        if entry.is_dir() and not entry.is_symlink():
            if _is_quarantine_directory(entry):
                continue  # quarantined files are off-limits to the browser -- see module header
            if depth_remaining > 0:
                node.subdirectories.append(_scan_directory(entry, depth_remaining - 1))
            # else: stop descending silently — avoids runaway recursion.
        elif entry.is_file() and entry.suffix.lower() in FITS_EXTENSIONS:
            node.files.append(_scan_fits_file(entry))

    return node


def flatten_files(node: Optional[DirectoryNode]) -> List[SourceFileEntry]:
    """All files in a tree, depth-first."""
    if node is None:
        return []
    files = list(node.files)
    for child in node.subdirectories:
        files.extend(flatten_files(child))
    return files


def distinct_source_names(node: Optional[DirectoryNode]) -> List[str]:
    """Unique, sorted source names found anywhere in the tree (for the dropdown)."""
    return sorted({f.source_name for f in flatten_files(node) if f.source_name})


def distinct_frequencies_mhz(node: Optional[DirectoryNode]) -> List[float]:
    """Unique, sorted frequencies (MHz) found anywhere in the tree (for the dropdown)."""
    return sorted({f.frequency_mhz for f in flatten_files(node) if f.frequency_mhz is not None})


def matching_files(
    node: Optional[DirectoryNode],
    source_name: Optional[str],
    frequency_mhz: Optional[float],
) -> List[SourceFileEntry]:
    """Every file anywhere in the tree matching the current filters.

    A None filter matches everything for that field — used when a filter
    hasn't been (or can't yet be) set.
    """
    return [
        f for f in flatten_files(node)
        if (source_name is None or f.source_name == source_name)
        and (frequency_mhz is None or f.frequency_mhz == frequency_mhz)
    ]


def group_files_by_month(files: List[SourceFileEntry]) -> List[Tuple[str, List[SourceFileEntry]]]:
    """Group (already-filtered) files by observation year-month, newest first.

    Restores the build spec's original "grouped by observation month"
    browsing structure (e.g. "2026-08 Observations") on top of the live
    directory scan. This matters for real archives: the live scan's tree
    view mirrors whatever the on-disk folder layout happens to be, which
    may not be date-organized (or may just be one flat directory) --
    for a monitoring program spanning many months at the same source and
    frequency, that's a wall of files with no structure to navigate by.
    Grouping by calendar month scales the way the original spec intended,
    regardless of how files happen to be laid out on disk.

    Files with no readable observation_date go in a trailing "Unknown
    date" bucket rather than being silently dropped from the browser.
    Within a group, files are sorted by date then filename so browsing is
    chronological, not just alphabetical.
    """
    groups: Dict[str, List[SourceFileEntry]] = defaultdict(list)
    for f in files:
        key = f.observation_date[:7] if f.observation_date else "unknown"
        groups[key].append(f)

    def _sort_key(entry: SourceFileEntry):
        return (entry.observation_date or "", entry.filename)

    ordered_keys = sorted((k for k in groups if k != "unknown"), reverse=True)
    if "unknown" in groups:
        ordered_keys.append("unknown")

    return [
        (f"{key} Observations" if key != "unknown" else "Unknown date", sorted(groups[key], key=_sort_key))
        for key in ordered_keys
    ]


def filter_by_filename(files: List[SourceFileEntry], search_text: str) -> List[SourceFileEntry]:
    """Case-insensitive filename substring filter for the browse search box.

    A blank search matches everything -- this is a narrowing aid on top of
    the Source Name / Frequency dropdowns, not a replacement for them, for
    when the user already knows roughly what filename they're looking for.
    """
    if not search_text:
        return files
    needle = search_text.strip().lower()
    return [f for f in files if needle in f.filename.lower()]


def earliest_observation_date(files: List[SourceFileEntry]) -> Optional[str]:
    """Earliest observation date among a set of files, or None if unknown for all."""
    dates = [f.observation_date for f in files if f.observation_date]
    return min(dates) if dates else None


def latest_observation_date(files: List[SourceFileEntry]) -> Optional[str]:
    """Latest observation date among a set of files, or None if unknown for all."""
    dates = [f.observation_date for f in files if f.observation_date]
    return max(dates) if dates else None


def build_summary_text(
    filtered_files: List[SourceFileEntry],
    source_name: Optional[str],
    frequency_mhz: Optional[float],
    earliest_date: Optional[str],
    latest_date: Optional[str] = None,
) -> str:
    """Text for the selection-summary panel.

    Shows a date RANGE (earliest to latest), not just the earliest date, per
    the FR-01 spec: "The UI displays a summary showing the filtered file
    count and observation date range." latest_date defaults to None so
    existing call sites passing only 4 args don't break; when it's None or
    equal to earliest_date, only one date is shown rather than a redundant
    "X to X" range.

    TODO: confirm against design. Build spec §7's example summary includes a
    declination ("Dec +12°34'"), which this deliberately does not add.
    fits_ingest.py's module docstring is explicit that neither clc loader it
    wraps returns RA/Dec source coordinates -- only telescope LONGITUD/
    LATITUDE -- and that anything downstream wanting RA/Dec "must say so
    explicitly rather than silently substituting telescope pointing for
    source coordinates." Reading some other header keyword directly here
    and hoping it's the source Dec would be exactly that silent
    substitution, so it's left out and flagged instead of guessed.
    """
    if not filtered_files:
        return "No matching FITS files for the current filters."
    freq_label = f"{frequency_mhz:.3f} MHz" if frequency_mhz is not None else "unknown frequency"

    if earliest_date and latest_date and earliest_date != latest_date:
        date_label = f"{earliest_date} to {latest_date}"
    else:
        date_label = earliest_date or latest_date or "date pending"

    plural = "s" if len(filtered_files) != 1 else ""
    return (
        f"{len(filtered_files)} file{plural} matched — {source_name} · {freq_label} · "
        f"observed {date_label}"
    )


def _relative_to_archive(path: Path, archive_root: Path) -> str:
    """Express a scanned file's path the way Page 02 needs it.

    02_File_Loader.py resolves each handed-off entry as
    `fits_ingest.get_archive_root() / filename`, and reuses that same string
    as the display name in its validation table, its progress text, and its
    audit-log lines. So this returns a path relative to the archive root
    when the scanned file is actually under it (the normal case, now that
    default_fits_directory() always points at the archive root too) --
    giving Page 02 a short, readable name like "2026-08/spectrum_002.fits"
    instead of a full filesystem path.

    Falls back to the absolute resolved path if the scanned file isn't
    under the archive root at all (e.g. someone typed a different,
    non-archive directory into the FITS Directory field for local testing).
    This still resolves correctly on Page 02 with no change needed there:
    pathlib's `/` operator discards the left-hand operand entirely when the
    right-hand operand is already absolute, so
    `fits_ingest.get_archive_root() / "/some/other/dir/file.fits"` evaluates
    to `/some/other/dir/file.fits`, not an error -- it just won't display as
    a short filename in that fallback case.
    """
    resolved_path = path.resolve()
    resolved_root = archive_root.resolve()
    try:
        return str(resolved_path.relative_to(resolved_root))
    except ValueError:
        return str(resolved_path)


def build_selected_files(filtered_files: List[SourceFileEntry]) -> List[str]:
    """Filenames for the Page 01 -> Page 02 handoff.

    THIS IS THE FIX for the critical pipeline bug: 02_File_Loader.py reads
    `pipeline_data[THIS_STAGE_KEY]["selected_files"]`, a key this module
    never wrote -- 01_Source_Browser.py only wrote "fits_file_paths", which
    nothing downstream ever reads. As a result, Page 02's
    `pipeline_selection.get("selected_files")` was always empty, so Page 02
    always silently fell back to its single-file dev default ("good.fits")
    regardless of what was actually selected here, and every page after it
    (Page 03's bandpass correction included) operated on the wrong file(s).

    Returns filenames in the exact form Page 02 already expects
    (resolvable via `fits_ingest.get_archive_root() / filename`), so no
    change is needed on that side.
    """
    archive_root = fits_ingest.get_archive_root()
    return [_relative_to_archive(f.path, archive_root) for f in filtered_files]


# ---------------------------------------------------------------------------
# Folder navigator helpers (UAT feedback: pick the FITS folder with a button
# instead of typing the path). Streamlit has no native folder picker, and a
# tkinter dialog would open on the *server*, not the user's browser, so the
# page renders its own navigator over the server-visible filesystem using
# these pure helpers.
# ---------------------------------------------------------------------------

MAX_LISTED_SUBDIRECTORIES = 300


def parent_directory(path: Path) -> Path:
    """Parent of `path`; a filesystem root is its own parent (so "Up" can disable itself)."""
    path = Path(path)
    return path.parent


def list_subdirectories(directory: Path, limit: int = MAX_LISTED_SUBDIRECTORIES) -> Tuple[List[Path], bool]:
    """Visible subdirectories of `directory`, sorted case-insensitively.

    Hidden folders and the quarantine folder (fits_ingest.QUARANTINE_DIRNAME) are left out, for the same reason
    scan_fits_directory_tree() skips the latter. Returns (subdirectories, truncated); unreadable folders yield
    ([], False) rather than raising, so a permission error never takes the page down.
    """
    try:
        subs = [
            p for p in Path(directory).iterdir()
            if p.is_dir() and not p.name.startswith(".") and not _is_quarantine_directory(p)
        ]
    except OSError:
        return [], False
    subs.sort(key=lambda p: p.name.lower())
    return subs[:limit], len(subs) > limit


def count_fits_files(directory: Path) -> int:
    """Number of .fits/.fit files directly inside `directory` (not recursive)."""
    try:
        return sum(1 for p in Path(directory).iterdir() if p.is_file() and p.suffix.lower() in FITS_EXTENSIONS)
    except OSError:
        return 0


# ---------------------------------------------------------------------------
# Real clc/File_check.py integration (replaces run_file_check_placeholder)
# ---------------------------------------------------------------------------

@dataclass
class FileCheckOutcome:
    """What File_check produced for one "Load into Pipeline" click."""

    work_dir: Path
    blocks: Dict[str, List[str]] = field(default_factory=dict)  # block file name -> FITS filenames, in order
    discarded_files: List[str] = field(default_factory=list)  # File_check's Bad_data list (corrupt/superseded)
    not_linked: List[str] = field(default_factory=list)  # selected files skipped (duplicate basename)


def safe_path_component(text: object) -> str:
    """Filesystem-safe folder name from a source name / frequency (e.g. "W3(OH)" -> "W3_OH")."""
    cleaned = re.sub(r"[^A-Za-z0-9._+-]+", "_", str(text)).strip("._")
    return cleaned or "unknown"


def _link_or_copy(source: Path, destination: Path) -> None:
    """Expose `source` inside the workspace without duplicating up-to-500MB files where possible.

    Order: symlink -> hardlink -> copy (Windows dev machines often can't symlink without privileges).
    The FITS archive itself is never modified.
    """
    try:
        destination.symlink_to(source.resolve())
        return
    except (OSError, NotImplementedError):
        pass
    try:
        destination.hardlink_to(source.resolve())
        return
    except (OSError, NotImplementedError, AttributeError):
        pass
    shutil.copy2(source, destination)


def prepare_file_check_workspace(
    files: List[SourceFileEntry],
    workspace_dir: Path,
    observation: str,
    frequency: str,
) -> Tuple[Path, List[str]]:
    """Build a fresh `<workspace>/<observation>/<frequency>/` folder holding links to the selected files.

    File_check works on a folder of FITS files and writes its block files next to them, so the (read-only) archive
    can't be used directly. Any previous run's folder for this observation is deleted first, so a re-click never
    sorts stale files. Returns (work_dir, filenames_not_linked); a file is not linked only when another selected
    file already uses the same basename (File_check identifies files by name and reads the date from its first
    8 characters, so renaming isn't an option).
    """
    observation_dir = Path(workspace_dir) / safe_path_component(observation)
    if observation_dir.exists():
        shutil.rmtree(observation_dir)  # removes links/copies only; never follows symlinks into the archive
    work_dir = observation_dir / safe_path_component(frequency)
    work_dir.mkdir(parents=True, exist_ok=True)

    not_linked: List[str] = []
    for entry in files:
        destination = work_dir / entry.filename
        if destination.exists() or destination.is_symlink():
            not_linked.append(str(entry.path))
            continue
        _link_or_copy(Path(entry.path), destination)
    return work_dir, not_linked


def _import_run_file_check():
    """Import clc.File_check.run_file_check lazily, so this module stays importable (and testable) without clc."""
    try:
        from clc.File_check import run_file_check
    except ImportError:
        # clc/ modules use flat sibling imports (the original CLI style); make that work too.
        clc_dir = Path(__file__).resolve().parent.parent / "clc"
        if str(clc_dir) not in sys.path:
            sys.path.append(str(clc_dir))
        from File_check import run_file_check  # type: ignore
    return run_file_check


def _read_lines(path: Path) -> List[str]:
    try:
        return [line.strip() for line in Path(path).read_text().splitlines() if line.strip()]
    except OSError:
        return []


def run_observation_block_sort(
    files: List[SourceFileEntry],
    workspace_dir: Path,
    observation: str,
    frequency_mhz: Optional[float],
) -> FileCheckOutcome:
    """Run the real clc.File_check over the selected files and parse what it wrote.

    Raises whatever File_check raises (e.g. a file missing a header keyword); the page catches it and offers
    "continue without block sorting" instead of failing the whole hand-off. The scientific sorting logic lives
    entirely in clc/File_check.py and is not reimplemented here.
    """
    frequency_label = f"{frequency_mhz:.3f}" if frequency_mhz is not None else "unknown"
    work_dir, not_linked = prepare_file_check_workspace(files, workspace_dir, observation, frequency_label)

    result = _import_run_file_check()(
        safe_path_component(observation), safe_path_component(frequency_label), str(Path(workspace_dir)),
    )

    blocks = {Path(p).name: _read_lines(Path(p)) for p in result["block_files"]}
    return FileCheckOutcome(
        work_dir=work_dir,
        blocks=blocks,
        discarded_files=_read_lines(Path(result["bad_data_file"])),
        not_linked=not_linked,
    )
