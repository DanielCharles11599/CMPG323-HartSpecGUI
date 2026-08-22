# source_browser_logic.py — FR-01: pure/testable logic backing
# pages/01_Source_Browser.py. Kept separate from the Streamlit page script (rather
# than defined inline in the page) specifically so it can be unit-tested without a
# Streamlit ScriptRunContext — importing a pages/*.py file directly would execute
# st.set_page_config()/st.* calls at import time and fail outside a running app.
#
# Nothing in this module hardcodes a color, coordinate, or theme value — those all
# live in utils/styles.py (theme tokens) and the page script's layout constants,
# which are derived from HARTSPEC-Page_Build_Spec.md §4/§6/§7.

from dataclasses import dataclass, field
from typing import Dict, List, Optional

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

    observation_date/declination are Optional because, outside the sample data
    reproduced from the build spec, the real values only become known once a
    file's FITS header is actually read (FR-02, the next stage) — a lightweight
    archive listing shouldn't fabricate header data it hasn't read.
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
    displayed_count: int
    files: List[SourceFileEntry] = field(default_factory=list)


def get_source_groups() -> List[SourceGroupEntry]:
    """Return the file groups to render in the Source Browser.

    TODO: confirm against design — see build spec §3. This is a placeholder for
    a live scan of FITS_ARCHIVE_PATH / PSS_DATA_PATH (grouped by observation
    month), most likely via clc/File_check.py. The exact grouping rule (FITS
    header date vs. filesystem mtime vs. folder name) isn't specified in any of
    the three source docs, so it isn't guessed here — this reproduces only the
    two groups and their named files given in build spec §7 ("Sample data to
    reproduce exactly"). The build spec states "2026-08 Observations" holds 12
    files and "2026-07 Observations" holds 8, but only 3 and 2 filenames
    (respectively) are actually specified — displayed_count intentionally keeps
    the spec's stated totals even though `files` only has the known rows, so the
    group header text matches the mockup while the row list stays honest about
    what data we actually have.
    """
    return [
        SourceGroupEntry(
            label="2026-08 Observations",
            displayed_count=12,
            files=[
                SourceFileEntry("spectrum_001.fits", "FITS", 42, "OK"),
                SourceFileEntry(
                    "spectrum_002.fits", "FITS", 38, "OK",
                    observation_date="2026-08-12", declination="+12°34'",
                ),
                SourceFileEntry("spectrum_003.fits", "FITS", 41, "OK"),
            ],
        ),
        SourceGroupEntry(
            label="2026-07 Observations",
            displayed_count=8,
            files=[
                SourceFileEntry("pss_survey_014.txt", "PSS", 3, "OK"),
                SourceFileEntry("pss_survey_015.txt", "PSS", 3, "OK"),
            ],
        ),
    ]


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
