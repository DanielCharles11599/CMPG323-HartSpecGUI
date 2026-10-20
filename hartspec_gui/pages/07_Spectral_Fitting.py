# 07_Spectral_Fitting.py — FR-14/15/16/17/19: CLC-backed fitting, Plotly results and replayable state.
"""Stage 7 on Streamlit 1.32.0. Heavy fits run only on the explicit Run Fit buttons.

Scientific adapters live in utils/fitting_helpers.py; JSON-safe active state and
cached results live in pipeline_data['07_spectral_fitting']. The existing Graph 3
calibration arithmetic is preserved, including the owner's additive pointing term.
"""
from __future__ import annotations

import copy
import json
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from utils import baseline_editor_bridge, fit_figures, fitting_helpers as fh, fitting_inputs
from utils import fitting_state as fs, session_store, spectrum_resolution, styles
from utils.sidebar import render_sidebar

THIS_STAGE_KEY = fs.STAGE_KEY
CURRENT_STAGE = 7
NEXT_PAGE = "pages/08_Export_and_Session.py"
FIT_TYPES = fh.FIT_TYPES
CHART_KEYS = dict(zip(FIT_TYPES, ("chart_fit_1d", "chart_fit_poly", "chart_fit_2d", "chart_fit_multicomp")))
GRAPH3_COLORS = {"light": "#4B5563", "dark": "#CBD5E1"}


def _chart(title: str, fig: go.Figure, key: str, source: str = "") -> None:
    """Render one accessible, independently keyed Plotly panel without selection callbacks."""
    with st.container(border=True):
        st.markdown(f"**{title}**")
        fig.update_layout(uirevision=f"{key}:{source}")
        styles.render_plotly_chart(fig, key=key, use_container_width=True, theme=None,
                                   config={"displaylogo": False, "responsive": True})


def _lines(traces: list, unit: str, window: Any = None, **kwargs: Any) -> go.Figure:
    """Build a themed spectral chart; all supplied x/y arrays remain full resolution."""
    theme = styles.get_theme()
    return fit_figures.spectrum_figure(traces, f"Intensity ({unit})", theme,
                                      styles.plotly_layout_theme(theme), window=window, **kwargs)


def _widget_scope(mode: str, source: str) -> str:
    """Keep widget state separate between modes, observations and loaded sessions."""
    return f"fit_{fs.MODE_IDS[mode]}_{st.session_state['session_id']}_{source[:16]}"


def _options(entry: dict, options: dict, mode: str) -> None:
    """Persist every control change and append a small parameter audit record, not spectral arrays."""
    options = fs.json_safe(options)
    previous = entry.get("options", {})
    if previous and previous != options:
        session_store.log_event(f"{mode} parameters changed — {json.dumps(options, ensure_ascii=False)}")
    entry["options"] = options


def _result_table(result: dict | None) -> None:
    """Show result rows and explicitly disclose unconstrained covariance/nonconvergence."""
    if not result:
        return
    rows = result.get("rows", [])
    if rows:
        styles.render_dataframe(pd.DataFrame(rows, columns=["Parameter", "Value", "± Error"]),
                                hide_index=True, use_container_width=True)
    for note in result.get("notes", []):
        (st.caption if result.get("converged") else st.warning)(note)


def _status(entry: dict, request: str, heavy: bool = False) -> bool:
    """Explain errors/stale results, returning whether the cached result may be committed."""
    if entry.get("failed_request") == request:
        st.error(entry["error"])
    current = fs.result_is_current(entry, request)
    if entry.get("result") and entry.get("result_request") == request and not entry["result"].get("ok"):
        st.info("No components satisfied the fit criteria. " + entry["result"].get("stop_reason", ""))
    elif entry.get("result") and not current:
        st.warning("Controls changed or the last fit failed. The previous fit is not current and cannot be saved."
                   + (" Press Run Fit to update it." if heavy else ""))
    elif not entry.get("result") and heavy:
        st.caption("Set the initial guesses, then press Run Fit.")
    return current


def _light_fit(stage: dict, mode: str, v: np.ndarray, y: np.ndarray, source: str, unit: str) -> tuple:
    """FR-14/15: numeric controls and cached automatic recomputation on parameter changes only."""
    entry = fs.mode_state(stage, mode, source)
    saved = entry["options"]
    key = _widget_scope(mode, source)
    amp0, center0, width0 = fh.default_gaussian_guess(v, y)
    step = max(float(np.median(np.abs(np.diff(v)))), 1e-9)
    columns = st.columns(3)
    window = None
    if mode == "1D Gaussian":
        span = max(float(np.max(np.abs(y))), abs(float(saved.get("amplitude_initial_guess", amp0))), 1e-6) * 2
        amp = columns[0].slider("Amplitude guess", -span, span,
                                float(saved.get("amplitude_initial_guess", amp0)),
                                step=span / 400, key=f"{key}_amplitude")
        center = columns[1].slider("Center Velocity guess (km/s)", float(v.min()), float(v.max()),
                                   float(np.clip(saved.get("center_initial_guess_kms", center0), v.min(), v.max())),
                                   step=step, key=f"{key}_center")
        width = columns[2].number_input("HPBW (km/s, fixed)", min_value=1e-9,
                                        value=max(float(saved.get("hpbw_kms_fixed", width0)), 1e-9),
                                        step=step, format="%.6f", key=f"{key}_hpbw",
                                        help="Defaults to the measured half-maximum width; held constant in Gaussf.py.")
        options = {"amplitude_initial_guess": amp, "center_initial_guess_kms": center, "hpbw_kms_fixed": width}
    else:
        center = columns[0].number_input("Velocity Center (km/s)", min_value=float(v.min()), max_value=float(v.max()),
                                         value=float(np.clip(saved.get("peak_velocity_kms", center0),
                                                             v.min(), v.max())),
                                         step=step, format="%.6f", key=f"{key}_center")
        half = int(columns[1].number_input("Peak Half-Width (channels)", min_value=1,
                                           value=max(1, int(saved.get("half_width_channels", 10))),
                                           step=1, key=f"{key}_half"))
        order0 = saved.get("polynomial_order", 4)
        order = columns[2].selectbox("Polynomial Order", fh.POLYNOMIAL_ORDERS,
                                     index=fh.POLYNOMIAL_ORDERS.index(order0) if order0 in fh.POLYNOMIAL_ORDERS else 2,
                                     format_func=lambda n: {2: "2nd", 3: "3rd", 4: "4th"}[n], key=f"{key}_order")
        window = fh.fit_max_window(v, center, half)
        options = {"peak_velocity_kms": center, "half_width_channels": half, "polynomial_order": order}
        st.caption("The window is selected numerically. Half-width is in channels; "
                   "the CLC upper endpoint is exclusive.")
    _options(entry, options, mode)
    request = fs.request_key(source, entry["options"])
    if entry.get("last_attempt") != request:
        with st.spinner("Fitting spectrum..."):
            fit = (fh.run_gaussf(v, y, width, amp, center, unit) if mode == "1D Gaussian"
                   else fh.run_fit_max(v, y, center, half, order, unit))
        if fit.ok:
            fs.save_result(entry, request, fit)
        else:
            fs.save_failure(entry, request, "; ".join(fit.notes))
    current = _status(entry, request)
    result = entry.get("result")
    traces = [("Combined / calibrated spectrum", v, y, GRAPH3_COLORS[styles.get_theme_name()], "solid")]
    if result:
        curve_x = result.get("curve_x")
        traces.append(("Model fit" if current else "Previous fit (not current)",
                       v if curve_x is None else curve_x, result["curve"], styles.get_fit_line_color(), "dash"))
    _chart("Graph 3 — Combined / calibrated spectrum + fit", _lines(traces, unit, window), CHART_KEYS[mode], source)
    _result_table(result)
    return entry, request, current


def _map_fit(stage: dict) -> tuple:
    """FR-16: seven spin boxes, button-gated CLC fit, observed heatmap and adjacent covariance."""
    mode = "2D Gaussian"
    raw = st.session_state.get("map_2d_data")
    synthetic = raw is None
    if synthetic:
        stage.pop("map_snapshot", None)
        stage.pop("map_signature", None)
        st.info("Synthetic Test Map Active")
        st.caption("Deterministic demonstration data, not an observation. "
                   "Fitting is enabled; observation commit is not.")
        try:
            data = fh.synthetic_map_2d()
        except fh.ClcLoadError as exc:
            st.error(str(exc))
            return None, "", False, True
    else:
        data = fh.coerce_map_2d(raw)
        if data is None:
            st.error("map_2d_data must contain finite data of shape (len(y), len(x)) and strictly monotonic x/y axes.")
            return None, "", False, False
    source = fs.signature(data.x, data.y, data.data,
                          context={"mode": mode, "synthetic": synthetic,
                                   "unit": data.unit, "axis_unit": data.axis_unit})
    if not synthetic and stage.get("map_signature") != source:
        stage["map_snapshot"] = fs.json_safe(data)
        stage["map_signature"] = source
    entry = fs.mode_state(stage, mode, source)
    entry["synthetic"] = synthetic
    defaults = fh.default_p0_2d(data.x, data.y, data.data)
    saved = entry["options"].get("p0", defaults)
    if len(saved) != 7:
        saved = defaults
    scope = _widget_scope(mode, source)
    labels = ("Amplitude", "X center", "Y center", "Major axis (σ_x)", "Minor axis (σ_y)",
              "Position angle (degrees)", "Offset")
    values = []
    for indices in (range(4), range(4, 7)):
        for column, index in zip(st.columns(len(indices)), indices):
            values.append(float(column.number_input(labels[index], value=float(saved[index]), format="%.6f",
                                                     min_value=1e-9 if index in (3, 4) else None,
                                                     key=f"{scope}_p{index}")))
    st.caption("Axis widths are the backend's σ_x / σ_y, not FWHM; they are not reordered. Angle input is in degrees.")
    _options(entry, {"p0": values}, mode)
    request = fs.request_key(source, entry["options"])
    if st.button("Run Fit", type="primary", key="fit_2d_run"):
        with st.spinner("Fitting spectrum..."):
            fit = fh.run_2d_gauss(data.x, data.y, data.data, values, data.unit, data.axis_unit)
        if fit.ok:
            fs.save_result(entry, request, fit)
            session_store.log_event(f"2D Gaussian fitted — {'synthetic' if synthetic else 'observed'} map")
        else:
            fs.save_failure(entry, request, "; ".join(fit.notes))
    current = _status(entry, request, heavy=True)
    result = entry.get("result")
    left, right = st.columns([1.4, 1])
    with left:
        fig = fit_figures.map_figure(data.data, data.x, data.y, None if result is None else result["model"],
                                     f"Intensity ({data.unit})", data.axis_unit, styles.get_theme(),
                                     styles.plotly_layout_theme(styles.get_theme()),
                                     fit_color=styles.get_fit_line_color(), dashed_contours=True)
        _chart("2D Gaussian — observed intensity and fitted contours", fig, CHART_KEYS[mode], source)
    with right:
        st.markdown("**Covariance matrix — backend angle units: radians**")
        if result:
            cov = np.asarray(result["pcov"], dtype=float)
            styles.render_dataframe(pd.DataFrame(cov, index=fh.COV_LABELS_2D, columns=fh.COV_LABELS_2D),
                                    use_container_width=True)
            _result_table(result)
        else:
            st.caption("The 7 × 7 covariance matrix appears after a successful fit.")
    return entry, request, current, synthetic


def _multi_fit(stage: dict, v: np.ndarray, y: np.ndarray, source: str, unit: str) -> tuple:
    """FR-17: editable components, preview-only reruns, explicit heavy fit and full covariance."""
    mode = "Multi-Component"
    entry = fs.mode_state(stage, mode, source)
    saved = entry["options"]
    scope = _widget_scope(mode, source)
    with st.expander("Auto-Decomposition settings", expanded=True):
        columns = st.columns(3)
        limit = int(columns[0].number_input("max_components", min_value=1, max_value=fh.MAX_COMPONENTS,
                                            value=int(saved.get("max_components", 10)), step=1, key=f"{scope}_limit"))
        cutoff = float(columns[1].number_input("rms_cutoff (σ_RMS)", min_value=0.0,
                                               value=float(saved.get("rms_cutoff", 5.0)), step=0.5,
                                               key=f"{scope}_cutoff"))
        threshold = float(columns[2].number_input("chi2_threshold (Δ reduced χ²)", min_value=0.0,
                                                  value=float(saved.get("chi2_threshold", 0.01)), step=0.01,
                                                  format="%.4f", key=f"{scope}_threshold"))
        auto = st.checkbox("Auto-Decomposition: add components up to the stopping criteria",
                           value=bool(saved.get("auto", True)), key=f"{scope}_auto")
    st.caption("Checked Fixed/Free = fixed: amplitude, center and FWHM are all held constant. "
               "Add or remove rows in the editor. Editing previews the model but does not run an optimizer.")
    version = int(entry.get("editor_version", 0))
    editor_key = f"{scope}_editor_{version}"
    # A data_editor's base must stay constant while its delta state exists. On page
    # revisit/session load that delta is gone, so rebuild the base from the saved values.
    if editor_key not in st.session_state or "editor_base" not in entry:
        entry["editor_base"] = copy.deepcopy(saved.get("components", []))
    edited = st.data_editor(
        fh.df_from_params(entry["editor_base"]), key=editor_key, num_rows="dynamic", hide_index=True,
        use_container_width=True, disabled=[fh.COL_ID], column_config={
            fh.COL_ID: st.column_config.TextColumn("Component ID"),
            fh.COL_AMP: st.column_config.NumberColumn("Amplitude", help=f"Intensity in {unit}", format="%.6f"),
            fh.COL_CENTER: st.column_config.NumberColumn("Center Velocity", help="km/s", format="%.6f"),
            fh.COL_FWHM: st.column_config.NumberColumn("FWHM", help="km/s; must be greater than zero",
                                                      min_value=1e-9, format="%.6f"),
            fh.COL_LOCK: st.column_config.CheckboxColumn("Fixed/Free", default=False,
                                                        help="Checked = fixed; unchecked = free."),
        })
    params, problems = fh.params_from_df(edited)
    for message in problems:
        st.warning(message)
    options = {"components": params, "auto": auto, "max_components": limit,
               "rms_cutoff": cutoff, "chi2_threshold": threshold}
    _options(entry, options, mode)
    request = fs.request_key(source, entry["options"])
    run_col, clear_col, _ = st.columns([1, 1, 3])
    run = run_col.button("Run Fit", type="primary", key="fit_multicomp_run",
                         disabled=bool(problems) or (not auto and not params))
    if clear_col.button("Clear components", key="fit_multicomp_clear"):
        entry["options"]["components"] = []
        entry["editor_base"] = []
        entry["editor_version"] = version + 1
        entry.pop("result", None)
        session_store.log_event("Multi-Component table cleared")
        fs.invalidate_commit(st.session_state, stage, "cleared")
        st.rerun()
    if run:
        try:
            with st.spinner("Fitting spectrum..."):
                if auto:
                    output = fh.run_auto_decomposition(v, y, limit, cutoff, threshold, params=params)
                else:
                    if all(p["fixed"] for p in params):
                        fitted, errors = copy.deepcopy(params), [None] * len(params)
                        covariance = np.zeros((3 * len(params), 3 * len(params))).tolist()
                    else:
                        fitted, errors, covariance = fh.refit_free(v, y, params)
                    output = {"params": fitted, "uncertainties": errors, "covariance": covariance,
                              "statistics": fh.compute_stats(v, y, fitted), "history": [],
                              "sigma_rms": fh.estimate_noise(y), "stop_reason": "Manual component fit"}
            fitted = output["params"]
            estimable = bool(np.all(np.isfinite(np.asarray(output["covariance"], dtype=float))))
            output.update(ok=bool(fitted), converged=estimable, curve=fh.composite(v, fitted),
                          rows=[[r["parameter"], r["value"], r["error"]]
                                for r in fh.summary_rows(fitted, output["uncertainties"])],
                          notes=[output["stop_reason"]] + ([] if estimable else ["Covariance could not be estimated."]))
            # Replace the editor only after success. Store the final displayed controls as
            # the cache key, and keep the actual starting guesses as provenance.
            output["initial_options"] = copy.deepcopy(entry["options"])
            entry["options"]["components"] = fitted
            entry["editor_base"] = fitted
            entry["editor_version"] = version + 1
            fs.save_result(entry, fs.request_key(source, entry["options"]), output)
            session_store.log_event(f"Multi-Component fit — {len(fitted)} components; {output['stop_reason']}")
            st.rerun()
        except (fh.DecompositionError, fh.FitError, ImportError, ValueError) as exc:
            fs.save_failure(entry, request, str(exc))
    current = _status(entry, request, heavy=True) and not problems
    fig = fit_figures.multi_figure(v, y, params, unit, styles.get_theme(),
                                   styles.plotly_layout_theme(styles.get_theme()),
                                   data_color=GRAPH3_COLORS[styles.get_theme_name()],
                                   fit_color=styles.get_fit_line_color())
    _chart("Graph 3 — decomposition and residual" + (" (preview)" if not current else ""),
           fig, CHART_KEYS[mode], source)
    if current:
        result = entry["result"]
        _result_table(result)
        stats = result["statistics"]
        st.caption(f"RMS residual = {stats['rms_residual']:.6g} {unit} · σ_RMS = {result['sigma_rms']:.6g} {unit}")
        with st.expander("Full 3N × 3N covariance matrix"):
            labels = [f"{p['id']} {name}" for p in params for name in ("Amplitude", "Center Velocity", "FWHM")]
            styles.render_dataframe(pd.DataFrame(result["covariance"], index=labels, columns=labels),
                                    use_container_width=True)
            st.caption("Ordering: amplitude, center, FWHM per component. Fixed rows/columns are zero; "
                       "unknown covariance is null in JSON, not zero.")
    return entry, request, current


def _commit(stage: dict, entry: dict, request: str, mode: str, v: np.ndarray,
            source_key: str, unit: str) -> None:
    """Commit the current successful fit, maintain Page 08 compatibility and checkpoint FR-19 state."""
    result = entry["result"]
    stage.update(committed_request=request, fit_type=mode, fit_type_requested=mode,
                 fit_options=copy.deepcopy(entry["options"]),
                 parameters=[dict(zip(("parameter", "value", "error"), row)) for row in result.get("rows", [])],
                 converged=result.get("converged", False), notes=result.get("notes", []),
                 intensity_unit=unit, spectrum_source=source_key)
    if mode == "2D Gaussian":
        stage["fitted_quantity"] = "Observed 2D spatial map"
        for key in ("pss_jy_per_k", "pointing_correction_factor", "n_channels", "vlsr_range_kms"):
            stage.pop(key, None)
        stage["covariance"] = result["pcov"]
        stage["covariance_parameters"] = list(fh.COV_LABELS_2D)
        st.session_state.pop("latest_fit", None)
    else:
        curve = fh.align_curve(v, result["curve"], result.get("curve_x"))
        st.session_state["latest_fit"] = {
            "fit_type": mode, "spectrum_source": source_key, "intensity_unit": unit,
            "vlsr": v.tolist(), "fit_curve": fs.json_safe(curve), "input_signature": entry["input_signature"]}
    stage.pop("multi_component", None)
    if mode == "Multi-Component":
        stage["multi_component"] = fh.build_fitting_block(result["params"], result["uncertainties"],
                                                          result["covariance"], result["statistics"])
    session_store.mark_stage_complete(THIS_STAGE_KEY)
    session_store.log_event(f"Spectral fit committed — {mode}")
    session_store.checkpoint_session("Spectral fit committed")
    if not st.session_state.get("checkpoint_error"):
        st.success("Fit saved to session and checkpointed.")


def main() -> None:
    """Render Stage 7; a missing 1D spectrum never prevents the independent 2D test-map workflow."""
    st.set_page_config(page_title="HARTSPEC — Spectral Fitting", layout="wide")
    session_store.init_session_state()
    render_sidebar(CURRENT_STAGE)
    styles.inject_base_css()
    styles.render_page_header("Spectral Fitting", "Gaussian / polynomial / multi-component fits",
                               CURRENT_STAGE, session_store.completed_before(CURRENT_STAGE))
    stage = fs.ensure_stage(st.session_state.pipeline_data)
    if st.session_state.get("fit_type") == "Multi-component":
        st.session_state["fit_type"] = "Multi-Component"
    st.session_state.setdefault("fit_type", stage["fit_type_requested"])
    if st.session_state["fit_type"] not in FIT_TYPES:
        st.session_state["fit_type"] = FIT_TYPES[0]
    st.markdown('<div class="hs-eyebrow">FIT TYPE</div>', unsafe_allow_html=True)
    mode = st.radio("Fit type", FIT_TYPES, horizontal=True, label_visibility="collapsed", key="fit_type")
    if stage["fit_type_requested"] != mode:
        session_store.log_event(f"Fit type changed — {mode}")
    stage.update(fit_type=mode, fit_type_requested=mode)

    resolved = spectrum_resolution.resolve_spectrum(st.session_state, read_bridge=baseline_editor_bridge.read_bridge,
                                                    fingerprint=baseline_editor_bridge.spectrum_fingerprint)
    v, lcp, rcp = resolved.vlsr, resolved.channels["LCP"], resolved.channels["RCP"]
    st.caption(f"Spectrum source: {resolved.source_label}")
    for note in resolved.notes:
        st.warning(note)
    if resolved.is_placeholder:
        st.info("Graphs 1 and 2 contain placeholder spectra. Load/reduce observations for spectral fitting.")
    source = fs.signature(v, lcp, rcp, context=resolved.source_key)
    left, right = st.columns(2)
    with left:
        _chart("Graph 1 — LCP", _lines([("LCP", v, lcp, "#1F77B4", "solid")], resolved.intensity_unit),
               "chart_fit_lcp", source)
    with right:
        _chart("Graph 2 — RCP", _lines([("RCP", v, rcp, "#FF7F0E", "solid")], resolved.intensity_unit),
               "chart_fit_rcp", source)
    with st.expander("Polarization pair average"):
        average, mean = fitting_inputs.pair_average(lcp, rcp)
        average_trace = ("Pair average", v, average, GRAPH3_COLORS[styles.get_theme_name()], "solid")
        _chart("(LCP + RCP) / 2", _lines([average_trace], resolved.intensity_unit, hline=mean),
               "chart_fit_average", source)
    entry, request, current, synthetic = None, "", False, False
    unit, export_source = fitting_inputs.GRAPH3_UNIT, ""
    if mode == "2D Gaussian":
        entry, request, current, synthetic = _map_fit(stage)
        unit = str(stage.get("map_snapshot", {}).get("unit", "map units"))
    else:
        pss = fitting_inputs.pss_from_pipeline(st.session_state.pipeline_data)
        pointing = fitting_inputs.pointing_factor_from_pipeline(st.session_state.pipeline_data)
        blockers = []
        if resolved.is_placeholder:
            blockers.append("an observed spectrum")
        elif not resolved.is_calibrated and resolved.source_key != spectrum_resolution.SOURCE_BASELINE:
            blockers.append("the baseline-flattened spectrum from Stage 04")
        if pss is None:
            blockers.append("PSS calibration from Stage 05")
        if pointing is None:
            blockers.append("pointing correction from Stage 06")
        if blockers:
            st.warning("Graph 3 needs " + "; ".join(blockers) + ".")
        else:
            # Preserve the established owner's formula. Never apply PSS twice to Stage 05 output.
            # TODO: confirm against design — see build spec §3: the pre-existing formula adds the pc factor.
            graph3 = (lcp + rcp + pointing if resolved.is_calibrated
                      else fitting_inputs.graph3(lcp, rcp, pss.value, pointing))
            export_source = fitting_inputs.graph3_source_key(resolved.source_key, pss.value, pointing)
            stage.update(pss_jy_per_k=pss.value, pointing_correction_factor=pointing,
                         fitted_quantity=("Calibrated LCP + calibrated RCP + Pointing Correction"
                                          if resolved.is_calibrated else fitting_inputs.GRAPH3_FORMULA),
                         n_channels=int(v.size), vlsr_range_kms=[float(v.min()), float(v.max())])
            source = fs.signature(v, graph3, context={"mode": mode, "source": resolved.source_key,
                                                      "pss": pss.value, "pc": pointing, "unit": unit})
            if v.size < 3 or not np.all(np.isfinite(v)) or not np.all(np.isfinite(graph3)) or v.max() <= v.min():
                st.error("Fitting needs at least three finite channels and a nonzero velocity range.")
            elif not (np.all(np.diff(v) > 0) or np.all(np.diff(v) < 0)):
                st.error("The velocity axis must be strictly monotonic; fix duplicate/unsorted channels upstream.")
            else:
                st.caption(f"Graph 3 uses PSS = {pss.value:.6g} Jy/K and the existing additive pointing term "
                           f"{pointing:.6g}; no additional baseline offset is fitted.")
                if mode == "Multi-Component":
                    entry, request, current = _multi_fit(stage, v, graph3, source, unit)
                else:
                    entry, request, current = _light_fit(stage, mode, v, graph3, source, unit)
    fs.invalidate_commit(st.session_state, stage, request)
    save_col, next_col, _ = st.columns([1, 1.5, 2])
    if save_col.button("Save fit to session", disabled=not current or synthetic,
                       key="fit_save", use_container_width=True):
        _commit(stage, entry, request, mode, v, export_source, unit)
    if next_col.button("Continue to Export & Session →", type="primary", key="fitting_next_btn",
                       use_container_width=True):
        st.switch_page(NEXT_PAGE)


main()
