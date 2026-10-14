# observation_log_logic.py — FR-20: read-only event history and recorded-parameter summaries.
"""Build review data from audit_log and pipeline_data; never reconstruct history.

There is deliberately no Streamlit, filesystem, checkpoint or scientific-adapter
import here. Values come only from the supplied session mapping. A current stage
value is not attached to an old event, and HH:MM:SS is never assigned a date.
"""
from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

NOT_RECORDED = "Not recorded"
_MISSING = object()
STAGES = (
    ("01_source_browser", "01 Source Browser"),
    ("file_loader", "02 File Loader"),
    ("03_bandpass_correction", "03 Bandpass Correction"),
    ("04_baseline_editor", "04 Baseline Block Editor"),
    ("05_calibration_dashboard", "05 Calibration Dashboard"),
    ("06_pointing_correction", "06 Pointing Correction"),
    ("07_spectral_fitting", "07 Spectral Fitting"),
    ("08_export_and_session", "08 Export & Session"),
)

# These are the keys the supplied pages actually publish. Do not use draft
# widgets, loaded spectra, display defaults or message-text parsing as fallbacks.
# Units below follow the producers; unconfirmed units remain blank.
_FIELDS = {
    "01_source_browser": (
        ("Source", "source_name", ""),
        ("Frequency", "frequency_mhz", "MHz"),
        ("Earliest selected observation date", "earliest_observation_date", ""),
        ("Selected files (ordered)", "selected_files", ""),
    ),
    "file_loader": (
        ("Selected files", "selected_files", ""),
        ("Eligible files", "eligible_files", ""),
        ("Flagged files", "flagged_files", ""),
        ("Quarantined files", "quarantined_files", ""),
        ("Validation policy", "validation_policy", ""),
    ),
    "03_bandpass_correction": (
        ("Bandpass mode", "mode", ""),
        ("Pair: file 1", "filename1", ""),
        ("Pair: file 2", "filename2", ""),
        ("Pair: file 1 POSITION", "position1", ""),
        ("Pair: file 2 POSITION", "position2", ""),
        ("Common velocity range", "common_velocity_range_kms", "km/s"),
        ("Output channels", "n_channels", ""),
    ),
    "04_baseline_editor": (
        ("Polynomial selection mode", "selection_mode", ""),
        ("Selected LCP order", "selected_orders.LCP", ""),
        ("Selected RCP order", "selected_orders.RCP", ""),
        ("Baseline regions (as recorded)", "blocks", "km/s (start/end)"),
        ("Selection semantics", "selection_semantics", ""),
        ("Chi-squared scores", "chi_squared", ""),
        ("Fit provider", "fit_provider", ""),
    ),
    "05_calibration_dashboard": (
        ("PWV", "atmospheric.pwv", "mm"),
        ("Elevation", "atmospheric.elevation", "deg"),
        ("Azimuth", "atmospheric.azimuth", "deg"),
        ("Zenith optical depth", "atmospheric.optical_depth", ""),
        ("ATcor", "atmospheric.atcor", "factor"),
        ("PSS LCP window mean", "pss.lcp_window_mean", "Jy/K"),
        ("PSS RCP window mean", "pss.rcp_window_mean", "Jy/K"),
        ("PSS window half-width", "pss.window_days", "days"),
        ("PSS observation MJD", "pss.observation_mjd", ""),
        ("Atmospheric error", "atmospheric_error", ""),
        ("PSS error", "pss_error", ""),
    ),
    "06_pointing_correction": (
        ("Input source", "input_source", ""),
        ("Pointing correction (pc)", "correction_factor", "factor"),
        ("North-South offset", "ns_offset_deg", "deg"),
        ("East-West offset", "ew_offset_deg", "deg"),
        ("Half-power beam width", "hpbw_deg", "deg"),
        ("Scan files", "scan_files", ""),
        ("Picked velocities", "picked_velocities", "km/s"),
        ("Peak powers (units not recorded)", "peak_powers", ""),
    ),
    "07_spectral_fitting": (
        ("Fit type used", "fit_type", ""),
        ("Fit type requested", "fit_type_requested", ""),
        ("Fitted quantity", "fitted_quantity", ""),
        ("PSS used for saved fit", "pss_jy_per_k", "Jy/K"),
        ("Pointing factor used for saved fit", "pointing_correction_factor", "factor"),
        ("Converged", "converged", ""),
        ("Fitted velocity range", "vlsr_range_kms", "km/s"),
        ("Intensity unit", "intensity_unit", ""),
        ("Fit notes", "notes", ""),
    ),
    "08_export_and_session": (
        ("Export completion recorded", "exported", ""),
        ("Spectrum source", "spectrum_source", ""),
        ("Intensity unit", "intensity_unit", ""),
        ("Channels", "n_channels", ""),
    ),
}


@dataclass(frozen=True)
class EventRow:
    """One entry in append order, with only the timestamp and text actually recorded."""

    number: int
    timestamp: str
    message: str
    note: str = ""


@dataclass(frozen=True)
class ParameterRow:
    """One current recorded value, kept separate from the historical events."""

    stage_key: str
    stage: str
    parameter: str
    value: str
    unit: str
    status: str
    field: str


@dataclass(frozen=True)
class ObservationLog:
    """Detached, immutable presentation data; does not contain the live state mapping."""

    session_id: str
    events: tuple[EventRow, ...]
    parameters: tuple[ParameterRow, ...]
    warnings: tuple[str, ...]


def _json_value(value: Any, ancestors: frozenset[int] = frozenset()) -> Any:
    """Produce printable JSON metadata without evaluating arbitrary objects.

    Cycles and unsupported runtime objects get explicit labels, not repr() values
    containing memory addresses or hidden object contents. No NumPy arrays are read.
    """
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else f"{value} (non-finite)"
    if isinstance(value, (Mapping, list, tuple)):
        if id(value) in ancestors or len(ancestors) >= 20:
            return "[Nested value not displayed: cycle or depth limit]"
        seen = ancestors | {id(value)}
        if isinstance(value, Mapping):
            return {str(key): _json_value(item, seen) for key, item in value.items()}
        return [_json_value(item, seen) for item in value]
    return f"[Unsupported recorded type: {type(value).__name__}]"


def _text(value: Any) -> str:
    """Render a stored value without rounding, unit conversion or falsey-value loss."""
    if value is _MISSING or value is None or (isinstance(value, str) and not value.strip()):
        return NOT_RECORDED
    if isinstance(value, str):
        return value
    return json.dumps(_json_value(value), ensure_ascii=False, separators=(", ", ": "))


def _at_path(stage: Mapping[str, Any], field: str) -> Any:
    """Look up an explicitly supported dotted field path; missing is not zero."""
    value: Any = stage
    for part in field.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return _MISSING
        value = value[part]
    return value


def _events(raw: Any) -> tuple[tuple[EventRow, ...], list[str]]:
    """Keep every entry, including legacy text and malformed entries, in append order."""
    warnings: list[str] = []
    if raw is None:
        return (), warnings
    if not isinstance(raw, (list, tuple)):
        warnings.append("audit_log is not a list; it is displayed as one legacy entry.")
        raw = [raw]
    rows = []
    for number, item in enumerate(raw, 1):
        notes: list[str] = []
        if isinstance(item, Mapping):
            ts, message = item.get("ts", _MISSING), item.get("message", _MISSING)
            if not isinstance(ts, str) or not ts.strip():
                notes.append("Timestamp missing or not text; no date/time inferred")
            if not isinstance(message, str) or not message.strip():
                notes.append("Message missing or not text")
            rows.append(EventRow(number, _text(ts), _text(message), "; ".join(notes)))
        elif isinstance(item, str):
            rows.append(EventRow(number, NOT_RECORDED, item, "Legacy text; no separate timestamp recorded"))
        else:
            rows.append(EventRow(number, NOT_RECORDED, _text(item), "Malformed entry; retained for review"))
    if any(row.note for row in rows):
        warnings.append("Some events have incomplete or legacy fields; see the Record note column.")
    return tuple(rows), warnings


def _stage_status(stage: Any, key: str, completed: set[str]) -> str:
    """Describe recorded flags only; do not claim replay, numerical validity or completion."""
    if not isinstance(stage, Mapping) or not stage:
        return "Completion flag only; parameters missing" if key in completed else "No parameters recorded"
    if key == "06_pointing_correction" and str(stage.get("input_source", "")).upper().startswith("MOCK"):
        return "Legacy MOCK input; not a real correction"
    explicit = stage.get("complete", _MISSING)
    if explicit is False and key in completed:
        return "Conflicting completion markers"
    if explicit is False:
        return "Recorded; stage incomplete"
    if key in completed:
        return "Recorded as complete"
    if explicit is True:
        return "Payload complete; stage flag absent"
    return "Recorded; stage not marked complete"


def _fit_rows(stage: Mapping[str, Any], label: str, status: str) -> list[ParameterRow]:
    """Expose saved fit values/errors literally; individual parameter units are not guessed."""
    raw = stage.get("parameters", _MISSING)
    key = "07_spectral_fitting"
    if not isinstance(raw, (list, tuple)) or not raw:
        return [ParameterRow(key, label, "Fit parameters", _text(raw), "", status, f"{key}.parameters")]
    rows = []
    for number, item in enumerate(raw):
        prefix = f"{key}.parameters[{number}]"
        if not isinstance(item, Mapping):
            rows.append(ParameterRow(key, label, f"Fit parameter {number + 1}", _text(item), "", status, prefix))
            continue
        name = _text(item.get("parameter", _MISSING))
        for suffix, field in (("value", "value"), ("error", "error")):
            rows.append(ParameterRow(
                key, label, f"{name} — {suffix}", _text(item.get(field, _MISSING)), "", status, f"{prefix}.{field}",
            ))
    return rows


def build_observation_log(state: Mapping[str, Any]) -> ObservationLog:
    """Read the current audit and stage metadata into detached review rows.

    Args:
        state: st.session_state or a loaded session JSON. Only session_id,
            audit_log, pipeline_data and completed_stages are inspected.

    Returns:
        An immutable review model, with missing data and malformed sections
        labelled. No events, parameter values, flags, snapshots or files change.
    """
    if not isinstance(state, Mapping):
        raise TypeError("Observation log input must be a session mapping.")
    events, warnings = _events(state.get("audit_log"))
    pipeline = state.get("pipeline_data", {})
    if not isinstance(pipeline, Mapping):
        warnings.append("pipeline_data is not an object; current parameters cannot be read.")
        pipeline = {}
    completed_raw = state.get("completed_stages", ())
    if not isinstance(completed_raw, (list, tuple, set, frozenset)):
        warnings.append("completed_stages is malformed; no completion flags were assumed.")
        completed_raw = ()
    completed = {item for item in completed_raw if isinstance(item, str)}
    rows: list[ParameterRow] = []
    for key, label in STAGES:
        raw = pipeline.get(key)
        stage = raw if isinstance(raw, Mapping) else {}
        status = _stage_status(raw, key, completed)
        if raw is not None and not isinstance(raw, Mapping):
            warnings.append(f"{label}: malformed parameter section; values shown as Not recorded.")
        if status in ("Conflicting completion markers", "Completion flag only; parameters missing"):
            warnings.append(f"{label}: {status.lower()}.")
        if status.startswith("Legacy MOCK"):
            warnings.append("Page 06 contains legacy MOCK input; these values are not endorsed as science results.")
        for name, field, unit in _FIELDS[key]:
            rows.append(ParameterRow(key, label, name, _text(_at_path(stage, field)), unit, status, f"{key}.{field}"))
        if key == "07_spectral_fitting":
            rows.extend(_fit_rows(stage, label, status))
    return ObservationLog(_text(state.get("session_id", _MISSING)), events, tuple(rows), tuple(warnings))


def filter_events(events: Sequence[EventRow], query: str = "", *, newest_first: bool = False) -> tuple[EventRow, ...]:
    """Literal, case-insensitive substring search; reverse append order, not timestamp sorting."""
    needle = query.strip().casefold()
    matches = tuple(row for row in events if not needle or needle in
                    f"{row.number} {row.timestamp} {row.message} {row.note}".casefold())
    return tuple(reversed(matches)) if newest_first else matches


def filter_parameters(
    rows: Sequence[ParameterRow], *, stage_key: str = "", query: str = "",
) -> tuple[ParameterRow, ...]:
    """Filter only the parameter view; never filter the full downloadable report."""
    needle = query.strip().casefold()
    return tuple(row for row in rows if (not stage_key or row.stage_key == stage_key) and (not needle or needle in
                 f"{row.stage} {row.parameter} {row.value} {row.unit} {row.status} {row.field}".casefold()))


def _quoted(value: str) -> str:
    """Quote one text field so embedded newlines/tabs cannot masquerade as extra records."""
    return json.dumps(value, ensure_ascii=False)


def build_log_download(log: ObservationLog) -> bytes:
    """Create a full UTF-8 text review report in memory, independent of UI filters.

    This is not a scientific data export, authenticated audit certificate or
    loadable session snapshot. No generation time is added: unchanged data yields
    unchanged bytes and does not cause checkpoint churn.
    """
    lines = [
        "HARTSPEC — Observation log review",
        f"Current reduction ID: {_quoted(log.session_id)}",
        "Read-only report; not a session replay file or a scientific spectrum export.",
        "Contains ALL recorded events and the CURRENT parameter summary; display filters do not apply.",
        "Current parameters are not a historical parameter-change record.",
        "Completion labels report saved markers only; numerical outputs are not revalidated here.",
        "Timestamps are reproduced as recorded. Missing dates, time zones and observer identities are not inferred.",
        "Event history may include earlier reductions carried forward by the application.",
        "Text fields are quoted; embedded line breaks and tabs are escaped.",
        "",
        "RECORDED EVENT HISTORY — append order",
        "Entry\tTimestamp (recorded)\tMessage\tRecord note",
    ]
    for row in log.events:
        lines.append("\t".join((str(row.number), _quoted(row.timestamp), _quoted(row.message), _quoted(row.note))))
    if not log.events:
        lines.append("No actions recorded.")
    lines += ["", "CURRENT RECORDED PARAMETERS — NOT EVENT HISTORY",
              "Stage\tParameter\tValue\tUnit\tRecorded stage status\tField in pipeline_data"]
    for row in log.parameters:
        lines.append("\t".join(_quoted(value) for value in (
            row.stage, row.parameter, row.value, row.unit, row.status, row.field,
        )))
    if log.warnings:
        lines += ["", "RECORD QUALITY NOTES"] + [_quoted(note) for note in log.warnings]
    return ("\n".join(lines) + "\n").encode("utf-8")


def download_filename(session_id: str) -> str:
    """Return a short filename-safe basename, never a path supplied by a session."""
    safe_id = re.sub(r"[^A-Za-z0-9_-]+", "_", session_id).strip("_")[:64] or "session"
    return f"hartspec_observation_log_{safe_id}.txt"
