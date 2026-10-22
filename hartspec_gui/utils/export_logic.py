# export_logic.py — FR-18: pure builders for the Page 08 exports
# (CSV + FITS of all the numbers, PDF of the graphs only).
#
# System-owner decisions implemented here:
#   * CSV is the only data export, and it must carry everything: both polarisations, the pair average, Graph 3, the
#     fit, and the metadata (source, date, PSS, pointing correction, fit parameters) as constant columns so the file
#     reads back cleanly with pandas / Excel with no comment lines to strip.
#   * FITS carries the same numbers as the CSV (same columns, same metadata) as a binary table, so it can be opened in
#     astropy / DS9 / TOPCAT. It is a NEW file built from the session's arrays --
#     the raw archive in /data/fits/ is never touched (read-only except for the quarantine function).
#   * The PDF contains graphs only -- no tables, parameter values, metadata or log text.
#   # TODO: confirm against design -- the owners' list of extra export columns is still pending; the metadata
#   # columns below (incl. MJD + decimal year, as in the example Spec_*.txt) are a proposal and are all in
#   # build_metadata(), so adding or removing one is a one-line change.
#
# The PDF is drawn with matplotlib's object API (Figure + PdfPages), never pyplot, so it is safe to build inside a
# multi-session Streamlit server (pyplot's global current-figure state is not). matplotlib is imported lazily.
from __future__ import annotations

import io
import math
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from utils.fitting_inputs import GRAPH3_FORMULA, GRAPH3_UNIT, PssValue

FIT_COLOR_PRINT = "#DC2626"  # the style guide's light-mode fit colour; the PDF is always on white paper


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

def _column_safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", str(name)).strip("_") or "value"


def _time_fields(observation_date: Any) -> Dict[str, Any]:
    """MJD and decimal year from the FITS DATE string; blanks if it can't be parsed (or astropy is unavailable)."""
    if not observation_date:
        return {"mjd": "", "decimal_year": ""}
    try:
        from astropy.time import Time

        parsed = Time(str(observation_date), format="isot")
        return {"mjd": round(float(parsed.mjd), 5), "decimal_year": round(float(parsed.decimalyear), 5)}
    except Exception:  # noqa: BLE001 -- metadata only; a bad date must never block an export
        return {"mjd": "", "decimal_year": ""}


def build_metadata(
    *,
    spectrum: Optional[Mapping[str, Any]],
    spectrum_source: str,
    intensity_unit: str,
    pss: Optional[PssValue],
    pointing_factor: Optional[float],
    fit_summary: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Constant per-file columns. Anything not available is an empty string, so the columns are always the same."""
    spectrum = spectrum or {}
    metadata: Dict[str, Any] = {
        "source_name": str(spectrum.get("object", "")).strip(),
        "observation_date": str(spectrum.get("date", "") or ""),
        **_time_fields(spectrum.get("date")),
        # As stored in the FITS header (unit not guaranteed -- the loader doesn't expose it), hence the name.
        "restfreq_header": spectrum.get("restfreq", ""),
        "spectrum_source": spectrum_source,
        "lcp_rcp_unit": intensity_unit,
        "pss_lcp_window_mean_jy_per_k": pss.lcp_mean if pss else "",
        "pss_rcp_window_mean_jy_per_k": pss.rcp_mean if pss else "",
        "pss_used_jy_per_k": pss.value if pss else "",
        "pointing_correction_factor": pointing_factor if pointing_factor is not None else "",
        "calibrated_formula": GRAPH3_FORMULA,
        "fit_type": (fit_summary or {}).get("fit_type", ""),
    }
    for row in (fit_summary or {}).get("parameters", []) or []:
        name = _column_safe(row.get("parameter", ""))
        metadata[f"fit_{name}"] = row.get("value", "")
        metadata[f"fit_{name}_error"] = row.get("error", "")
    return metadata


def build_export_csv(
    *,
    vlsr: Any,
    lcp: Any,
    rcp: Any,
    average: Any,
    unit: str,
    calibrated: Optional[Any],
    fit_curve: Optional[Any],
    metadata: Mapping[str, Any],
) -> bytes:
    """One tidy CSV: a row per channel, spectra first, then constant metadata columns.

    `calibrated` / `fit_curve` (Graph 3 and its fit, in Jy) are omitted when None or the wrong length.
    """
    size = len(np.asarray(vlsr))
    table: Dict[str, Any] = {
        "Vlsr_kms": np.asarray(vlsr, dtype=float),
        f"LCP_{unit}": np.asarray(lcp, dtype=float),
        f"RCP_{unit}": np.asarray(rcp, dtype=float),
        f"Average_LCP_RCP_{unit}": np.asarray(average, dtype=float),
    }
    if calibrated is not None and len(calibrated) == size:
        table[f"Calibrated_{GRAPH3_UNIT}"] = np.asarray(calibrated, dtype=float)
    if fit_curve is not None and len(fit_curve) == size:
        table[f"Fit_{GRAPH3_UNIT}"] = np.asarray(fit_curve, dtype=float)
    frame = pd.DataFrame(table)
    for column, value in metadata.items():
        frame[column] = value
    return frame.to_csv(index=False).encode("utf-8")


# ---------------------------------------------------------------------------
# FITS (same numbers as the CSV)
# ---------------------------------------------------------------------------

# Characters the report text uses that FITS headers (printable ASCII only) cannot hold.
_ASCII_MAP = str.maketrans({"×": "x", "−": "-", "—": "-", "–": "-", "°": " deg", "±": "+/-", "·": "*"})
_FITS_CARD_WIDTH = 80  # a header card is exactly one 80-character line; text that cannot fit goes in COMMENT cards
_TRACE_MAX_BLOCKS = 20  # baseline blocks etc. written out one comment line each
_TRACE_MAX_LIST = 10  # short scalar lists only -- never dump a spectrum-sized array into a header


def _ascii(value: Any) -> str:
    """Printable-ASCII version of any value; FITS header cards cannot hold anything else."""
    text = unicodedata.normalize("NFKD", str(value).translate(_ASCII_MAP)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^\x20-\x7e]", " ", text).strip()


def _fits_value(value: Any) -> Any:
    """Coerce a metadata value to something a FITS header accepts; '' means 'skip it' (blank, NaN or inf)."""
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return float(value) if math.isfinite(value) else ""
    return _ascii(value) if value is not None else ""


def _write_metadata(header: Any, metadata: Mapping[str, Any]) -> None:
    """Write the CSV's constant metadata columns into a FITS header.

    OBJECT / DATE-OBS / MJD-OBS use the standard keywords; everything else is a HIERARCH keyword so the long
    descriptive names survive. Blank values are skipped (the CSV keeps them as empty columns only to keep a fixed
    schema), and long text goes into COMMENT cards.
    """
    standard = {"source_name": "OBJECT", "observation_date": "DATE-OBS", "mjd": "MJD-OBS"}
    for name, raw in metadata.items():
        value = _fits_value(raw)
        if value == "":
            continue
        key = standard.get(name) or "HIERARCH " + _column_safe(name).upper()
        if isinstance(value, str) and len(key) + len(value) + 5 > _FITS_CARD_WIDTH:  # "KEY = 'value'" must fit
            header.add_comment(f"{name}: {value}")
            continue
        try:
            header[key] = value
        except ValueError:  # card too long for one line -- keep the information rather than fail the export
            header.add_comment(f"{name}: {value}")


def _is_scalar(value: Any) -> bool:
    return isinstance(value, (str, bool, int, float, np.integer, np.floating, np.bool_))


def _stage_prefix(stage_key: Any) -> str:
    """'04_baseline_editor' -> 'S04' (short, so the HIERARCH keyword stays inside one card)."""
    match = re.match(r"(\d+)", str(stage_key))
    return f"S{match.group(1)}" if match else _column_safe(stage_key).upper()


def _flatten_stage(prefix: str, mapping: Mapping[str, Any], values: Dict[str, Any], notes: List[str], depth: int):
    """Collect a stage's committed parameters without needing to know its schema.

    Scalars become header values, one nested level of dicts is flattened (e.g. the Page 05 PSS values), short lists of
    dicts (the Page 04 baseline blocks) and short scalar lists become one COMMENT line each. Anything array-sized is
    skipped on purpose.
    """
    for key, item in mapping.items():
        name = f"{prefix}_{_column_safe(key)}"
        if _is_scalar(item):
            values[name] = item
        elif isinstance(item, Mapping):
            if depth < 1:
                _flatten_stage(name, item, values, notes, depth + 1)
        elif isinstance(item, (list, tuple)) and item:
            if all(isinstance(entry, Mapping) for entry in item) and len(item) <= _TRACE_MAX_BLOCKS:
                for number, entry in enumerate(item, start=1):
                    parts = [f"{_column_safe(k)}={entry[k]}" for k in entry if _is_scalar(entry[k])]
                    notes.append(f"{name} [{number}]: " + ", ".join(parts))
            elif all(_is_scalar(entry) for entry in item) and len(item) <= _TRACE_MAX_LIST:
                notes.append(f"{name}: " + ", ".join(str(entry) for entry in item))


def build_fits_traceability(session_id: Any, pipeline_data: Any) -> Tuple[Dict[str, Any], List[str]]:
    """BR-R05: everything needed to trace a FITS file back to the session and parameter set that produced it.

    Returns (header values, comment lines): the session id plus every committed parameter of every pipeline stage
    (bandpass mode, baseline blocks and polynomial order, ATcor / PWV / PSS, pointing, fit ...), taken from
    `pipeline_data` as it is, so a new parameter added to a stage is exported without touching this module.
    """
    values: Dict[str, Any] = {}
    notes: List[str] = []
    if session_id:
        values["session_id"] = str(session_id)
    if isinstance(pipeline_data, Mapping):
        for stage_key, stage in pipeline_data.items():
            if isinstance(stage, Mapping):
                _flatten_stage(_stage_prefix(stage_key), stage, values, notes, 0)
    return values, notes


def build_export_fits(
    *,
    vlsr: Any,
    lcp: Any,
    rcp: Any,
    average: Any,
    unit: str,
    calibrated: Optional[Any],
    fit_curve: Optional[Any],
    metadata: Mapping[str, Any],
    calibrated_unit: str = GRAPH3_UNIT,
    traceability: Optional[Mapping[str, Any]] = None,
    trace_notes: Sequence[str] = (),
) -> bytes:
    """A FITS file with the same content as `build_export_csv`: an empty primary HDU plus a `SPECTRUM` table.

    The table has one row per channel: VLSR (km/s), LCP, RCP, AVERAGE (intensity `unit`) and, when available,
    CALIBRATED and FIT (Graph 3 and its fit, `calibrated_unit`). All columns are float64, so values round-trip
    exactly (the 6-significant-figure regression requirement). `metadata` goes into both headers.
    `calibrated` / `fit_curve` are omitted when None or the wrong length, exactly as in the CSV.
    `traceability` / `trace_notes` (from `build_fits_traceability`) add the session id and every stage's parameters
    to the headers (BR-R05).
    """
    from astropy.io import fits  # lazy: keeps this module importable (and the CSV/PDF working) without astropy

    velocity = np.asarray(vlsr, dtype=float)
    size = len(velocity)

    def column(name: str, values: Any, column_unit: str) -> Any:
        return fits.Column(name=name, format="D", unit=_ascii(column_unit), array=np.asarray(values, dtype=float))

    columns = [
        column("VLSR", velocity, "km/s"),
        column("LCP", lcp, unit),
        column("RCP", rcp, unit),
        column("AVERAGE", average, unit),
    ]
    if calibrated is not None and len(calibrated) == size:
        columns.append(column("CALIBRATED", calibrated, calibrated_unit))
    if fit_curve is not None and len(fit_curve) == size:
        columns.append(column("FIT", fit_curve, calibrated_unit))

    primary = fits.PrimaryHDU()
    table = fits.BinTableHDU.from_columns(columns, name="SPECTRUM")
    for header in (primary.header, table.header):
        header["ORIGIN"] = "HARTSPEC"
        _write_metadata(header, metadata)
        _write_metadata(header, traceability or {})
        for note in trace_notes:
            header.add_comment(_ascii(note))
    # No DATE card on purpose: identical inputs give byte-identical files, which keeps tests and caching simple.

    buffer = io.BytesIO()
    fits.HDUList([primary, table]).writeto(buffer)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# PDF (graphs only)
# ---------------------------------------------------------------------------

@dataclass
class GraphTrace:
    """One line on a graph."""

    label: str
    x: Any
    y: Any
    color: str
    dashed: bool = False


@dataclass
class GraphSpec:
    """One graph: title, axis label and its lines (plus an optional horizontal reference line, unlabelled by value)."""

    title: str
    y_label: str
    traces: List[GraphTrace] = field(default_factory=list)
    x_label: str = "Vlsr (km/s)"
    hline: Optional[float] = None
    hline_label: str = ""


def build_graphs_pdf(graphs: List[GraphSpec], title: str = "HARTSPEC spectra") -> bytes:
    """Render the graphs, two per row on a landscape A4-width page, into one PDF. Graphs only -- no numbers table."""
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.figure import Figure

    if not graphs:
        raise ValueError("There are no graphs to export.")
    columns = 2
    rows = math.ceil(len(graphs) / columns)
    figure = Figure(figsize=(11.69, max(4.0, 2.9 * rows + 0.8)))
    axes = figure.subplots(rows, columns, squeeze=False)

    for index, axis in enumerate(axes.flat):
        if index >= len(graphs):
            axis.set_visible(False)
            continue
        graph = graphs[index]
        for trace in graph.traces:
            axis.plot(trace.x, trace.y, color=trace.color, linewidth=1.0,
                      linestyle="--" if trace.dashed else "-", label=trace.label)
        if graph.hline is not None and math.isfinite(graph.hline):
            axis.axhline(graph.hline, color="0.4", linewidth=0.8, linestyle=":", label=graph.hline_label or None)
        axis.set_title(graph.title, fontsize=9)
        axis.set_xlabel(graph.x_label, fontsize=8)
        axis.set_ylabel(graph.y_label, fontsize=8)
        axis.tick_params(labelsize=7)
        if len(graph.traces) > 1 or graph.hline_label:
            axis.legend(fontsize=7, frameon=False)
    figure.suptitle(title, fontsize=11)
    figure.tight_layout(rect=(0, 0, 1, 0.96))

    buffer = io.BytesIO()
    with PdfPages(buffer) as pdf:
        pdf.savefig(figure)
    return buffer.getvalue()
