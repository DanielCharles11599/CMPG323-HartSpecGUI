# export_logic.py — FR-18: pure builders for the Page 08 exports (CSV of all the numbers, PDF of the graphs only).
#
# System-owner decisions implemented here:
#   * CSV is the only data export, and it must carry everything: both polarisations, the pair average, Graph 3, the
#     fit, and the metadata (source, date, PSS, pointing correction, fit parameters) as constant columns so the file
#     reads back cleanly with pandas / Excel with no comment lines to strip.
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
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

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
