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

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from astropy.io import fits

# ---------------------------------------------------------------------------
# Pipeline-wide constants
# ---------------------------------------------------------------------------

# This page's own key in utils/session_store.py's `pipeline_data` dict and
# `completed_stages` set (passed to session_store.mark_stage_complete()).
# TODO: confirm against design. session_store.py doesn't enforce or enumerate
# a canonical key format (mark_stage_complete accepts any string), so this
# must match whatever convention the other 7 already-built pages use.
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

    Per the FR-01 spec: "defaults to /data/fits/ with a fallback for local
    testing." FITS_ARCHIVE_PATH (this project's existing .env convention)
    wins if set; otherwise falls back to the production path if it actually
    exists on this machine, or a relative local-testing path if it doesn't —
    so a developer without /data/fits/ mounted isn't stuck with a dead default.
    """
    env_value = os.environ.get("FITS_ARCHIVE_PATH")
    if env_value:
        return env_value
    production_path = Path("/data/fits/")
    if production_path.is_dir():
        return str(production_path)
    return "./data/fits"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class SourceFileEntry:
    """A single FITS file discovered under the browsed directory.

    source_name/frequency_mhz/observation_date are Optional because they
    come from a header read that can legitimately fail or be missing the
    relevant keyword — this shouldn't fabricate header data it couldn't read.
    """

    path: Path
    filename: str
    size_mb: float
    status: str
    source_name: Optional[str] = None
    frequency_mhz: Optional[float] = None
    observation_date: Optional[str] = None


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
# TODO: confirm against design. OBJECT (source name) is close to universal in
# FITS headers; RESTFREQ (rest frequency, standard unit Hz per the FITS/WCS
# convention) is also a standard keyword — but clc/File_check.py or
# clc/load_file.py almost certainly already knows HARTSPEC's exact header
# conventions, and should be treated as the source of truth over this
# best-effort read if they differ.
# ---------------------------------------------------------------------------

def _scan_fits_file(path: Path) -> SourceFileEntry:
    """Header-only read of one FITS file (doesn't touch pixel data)."""
    size_mb = path.stat().st_size / (1024 * 1024)
    try:
        header = fits.getheader(path)
        status = "OK"
    except Exception:
        # Real validation is FR-03's job downstream — flag here, don't crash
        # the browser.
        header = {}
        status = "FLAGGED"

    raw_source = header.get("OBJECT")
    source_name = str(raw_source).strip() or None if raw_source else None

    frequency_mhz: Optional[float] = None
    raw_freq_hz = header.get("RESTFREQ")
    if raw_freq_hz is not None:
        try:
            frequency_mhz = round(float(raw_freq_hz) / 1e6, 3)
        except (TypeError, ValueError):
            frequency_mhz = None

    raw_date = header.get("DATE-OBS")
    observation_date = str(raw_date)[:10] if raw_date else None

    return SourceFileEntry(
        path=path,
        filename=path.name,
        size_mb=size_mb,
        status=status,
        source_name=source_name,
        frequency_mhz=frequency_mhz,
        observation_date=observation_date,
    )


def scan_fits_directory_tree(root_dir: Path, max_depth: int = 4) -> Optional[DirectoryNode]:
    """Recursively scan root_dir for .fits/.fit files, building a directory tree.

    Returns None if root_dir doesn't exist — callers should treat that as
    "nothing to browse yet" (a freshly typed path, or a not-yet-mounted
    archive) rather than an error.

    max_depth caps recursion to guard against a pathologically deep directory
    structure; symlinked subdirectories are not followed, to avoid cycles.
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


def earliest_observation_date(files: List[SourceFileEntry]) -> Optional[str]:
    """Earliest observation date among a set of files, or None if unknown for all."""
    dates = [f.observation_date for f in files if f.observation_date]
    return min(dates) if dates else None


def build_summary_text(
    filtered_files: List[SourceFileEntry],
    source_name: Optional[str],
    frequency_mhz: Optional[float],
    earliest_date: Optional[str],
) -> str:
    """Text for the selection-summary panel."""
    if not filtered_files:
        return "No matching FITS files for the current filters."
    freq_label = f"{frequency_mhz:.3f} MHz" if frequency_mhz is not None else "unknown frequency"
    date_label = earliest_date or "date pending"
    plural = "s" if len(filtered_files) != 1 else ""
    return (
        f"{len(filtered_files)} file{plural} matched — {source_name} · {freq_label} · "
        f"earliest observation {date_label}"
    )


def run_file_check_placeholder(fits_paths: List[Path], workspace_dir: Path) -> Path:
    """NOT the real clc.File_check integration — see the chat response.

    Per the FR-01 spec: "File_check.py executes on the server to sort files
    into temporary observation block text files in the session's active
    workspace folder." clc/File_check.py's actual function signature wasn't
    available when this was written, so this is a deliberately simple stand-
    in (writes one flat text file listing the selected paths) rather than a
    guess at File_check.py's real sorting/block-splitting behavior.

    Replace this function's body with a real call into clc.File_check once
    its signature is confirmed — the page's call site is isolated to this one
    function specifically so that swap won't require touching anything else.
    """
    workspace_dir = Path(workspace_dir)
    workspace_dir.mkdir(parents=True, exist_ok=True)
    block_file = workspace_dir / "observation_block_001.txt"
    block_file.write_text("\n".join(str(p) for p in fits_paths))
    return block_file
