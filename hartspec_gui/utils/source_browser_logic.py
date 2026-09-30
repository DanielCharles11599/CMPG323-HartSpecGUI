# source_browser_logic.py — pure/testable logic backing pages/01_Source_Browser.py
# (FR-01: Source & Frequency Browser). Kept separate from the Streamlit page
# script so it's importable by pytest without a Streamlit runtime — see the
# module-level note in 01_Source_Browser.py for why that split matters.
#
# Rebuilt against the FR-01 functional breakdown (supersedes the earlier
# Figma-mockup-only reading of this page):
#   - CLC modules replaced: Interact.py (terminal menu — naturally superseded
#     by real Streamlit widgets, no source needed) and File_check.py (file
#     sorting — see run_file_check_placeholder() below, which is NOT yet the
#     real integration; clc/File_check.py's actual signature wasn't available
#     when this was written).
#   - Only raw FITS files (.fits / .fit) under a user-editable directory path
#     are in scope — no PSS files on this page.
#   - Source Name and Frequency are filter dropdowns populated from what's
#     actually found on disk, not a fixed list.
#   - The browser is a directory tree (nested expandable containers), not a
#     flat checkbox list.
#   - Nothing is written to disk permanently here; only
#     session_state["pipeline_data"] gets the filtered FITS paths, chosen
#     source name, chosen frequency, and earliest observation date.
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


def run_file_check_placeholder(fits_paths: List[Path], workspace_dir: Path) -> Path:
    """NOT the real clc.File_check integration -- see the chat response for
    the full writeup.

    The real clc/File_check.py has now been reviewed, and it can't be wired
    in as a simple function call the way clc.load_file / clc.load_file2 are
    in fits_ingest.py. As written, File_check.py is a bare top-level
    script, not a function:
      - It calls Interact.interaction() to prompt for Observation/Frequency
        via terminal input() -- the same blocking-input problem the
        Phase-0 fix already removed from Option.py, apparently not yet
        applied here.
      - It calls os.chdir() into a working directory it builds itself --
        an unsafe global side effect in a shared Streamlit server process.
      - It shells out via os.system('ls *.fits > ...') and reads/writes
        several files relative to that chdir'd cwd, rather than an
        explicit workspace_dir passed in.
      - Its file-to-block sorting (grouping FITS files into observation
        blocks by 'position'/'pointing' header values -- HPN/HPS/HPE/HPW/
        ON/OFF) is a real, fairly intricate state machine, not incidental
        GUI plumbing -- reimplementing it here would mean reinterpreting
        domain-specific observational logic, which the "never modify the
        underlying scientific algorithms" rule says not to do without
        asking first. It also appears to contain a bug (two `elif`
        branches with an identical guard condition, the second
        unreachable) -- not something to silently "fix" one way or the
        other on a guess.

    This stays as the explicit stand-in until the team decides how to
    handle it -- see the chat response for the options raised.

    INDEPENDENTLY CONFIRMED against the real clc/File_check.py source (not
    just inferred): the os.chdir()/os.system()/Interact.interaction()
    concerns above are all real and present exactly as described. The
    "identical elif guards" bug is also confirmed -- two branches, both
    guarded by
    `(file['position']=='ON' or file['position']=='OFF') and file['pointing']==0
    and Pcount==0 and dirs!=Dates[0]`, appear back-to-back; the second is
    unreachable dead code, not something to silently resolve one way or the
    other on a guess. OBJECT/RESTFREQ/DATE/POSITION are all confirmed read
    from the HDUs this module already assumes (see _scan_fits_file's own
    header comment) -- that part of the pre-existing header-reading logic
    needed no correction, only the DATE-OBS/DATE fallback fixed alongside
    this note.
    """
    workspace_dir = Path(workspace_dir)
    workspace_dir.mkdir(parents=True, exist_ok=True)
    block_file = workspace_dir / "observation_block_001.txt"
    block_file.write_text("\n".join(str(p) for p in fits_paths))
    return block_file
