# HartSpec Stage 7 update

This is a drop-in source update built against the supplied Pages4.zip, Utils4.zip,
CLC_zip.zip and Tests4.zip. It is not a complete repository and does not contain
observations, environments or third-party packages. Preserve newer local changes
when merging the shared helpers. The companion patch shows the exact changes.

## Install

1. Back up the current repository or create a Git branch.
2. Extract this archive into the repository root: the directory that contains
   `hartspec_gui/` and `tests/`. Merge the directories; do not replace them wholesale.
3. Use the existing Python 3.11 project environment with `streamlit==1.32.0`,
   `plotly==5.20.0` and the supplied requirements. No new dependency is introduced.
4. Stop and restart Streamlit after replacing the files, especially the CLC import
   guard. Run `streamlit run hartspec_gui/Home.py` from the repository root.
5. Run the tests listed below before marking the feature accepted.

Alternatively, review and apply `stage7.patch` from the repository root with
`git apply --check --ignore-space-change stage7.patch`, then
`git apply --ignore-space-change stage7.patch`. The whitespace option accommodates
the CRLF line endings in the uploaded archives. The patch and the
archive are alternative application methods; do not apply both.

## Changed production files

| File under hartspec_gui/ | Purpose |
|---|---|
| pages/07_Spectral_Fitting.py | Four modes, controls, charts, explicit heavy-fit actions, session cache and commit |
| utils/fitting_helpers.py | Actual CLC adapters, arbitrary-count decomposition orchestration, fixed/free covariance, all-mode session mapping, compatibility run_fit |
| utils/fitting_state.py | New pure per-mode state, full-input signatures, JSON-safe caches and stale-commit invalidation |
| utils/fit_figures.py | Spatial contour styling; retains spectral and dual-panel figure builders |
| utils/accessibility_ui.py | Explicit chart-key forwarding, separate accessibility-control identity, stable trace IDs |
| utils/spectral_fitting_logic.py | Backward-compatible optional numeric parameter/covariance fields on FitResult |
| utils/session_store.py | All-mode stages.fitting serialization, map restoration and cleanup, legacy selector compatibility |
| clc/2D_Gauss_fit.py | Main guard around the existing standalone demo; numerical function is unchanged |

`Gaussf.py`, `fit_max.py` and `Spec_comp.py` are unchanged. The numerical definition
of `twoD_Gaussian` is unchanged; direct execution of its demo remains possible.

## Behaviour

The selector is ordered **1D Gaussian → Polynomial Peak → 2D Gaussian →
Multi-Component**. All selections are numeric; the page has no Plotly selection
callback or Streamlit segmented_control dependency.

Graph 1 is LCP blue, Graph 2 is RCP orange, and Graph 3 uses a neutral observed-data
line. Models are dashed red; individual decomposition components are dotted.
The fit replaces/overlays Graph 3 rather than appearing in a redundant Graph 4.

### 1D Gaussian

Amplitude and center sliders are starting guesses, not fixed fitted parameters.
The HPBW number input defaults to the measured half-maximum width and is fixed in
`Gaussf.gaussf`. Only amplitude and center are optimized. The backend has no offset
parameter. A change in science inputs triggers a fit; a theme/font-only rerun
reuses the per-mode result. Full numeric parameters and covariance are preserved
separately from formatted display rows.

### Polynomial peak

Choose velocity center, half-width in channels (default 10, minimum 1), and order
2, 3 or 4. The selected window and the actual 50-point curve returned by
`fit_max.py` are drawn on Graph 3. The CLC upper channel endpoint is exclusive.
An off-edge or underdetermined window produces a warning/error rather than
wrapping negative channel indices or silently fitting a different region.

### 2D Gaussian

Supply `st.session_state['map_2d_data']` with `data`, `x`, `y` and optional `unit`
and `axis_unit`. Data shape is `(len(y), len(x))`; axes must be finite and strictly
monotonic. A missing/None map activates the deterministic 41×41 test map and the
exact banner **Synthetic Test Map Active**. An invalid supplied map is reported,
not silently replaced with synthetic data.

Seven spin boxes feed `p0`. The backend's major/minor fields are **sigma_x and
sigma_y, not FWHM**, and are not reordered. Position angle input is in degrees;
SciPy/backend parameters and the covariance use radians. Only **Run Fit** invokes
the optimizer. A successful result provides the observed heatmap, fitted contours,
parameter table and adjacent 7×7 covariance table.

Plotly 5.20 Contour.line has no dash property. The chart therefore retains the
native go.Contour model/hover trace and overlays dashed go.Scatter level paths.
Matplotlib computes those display paths from the already-fitted surface; it does
not refit data or open a GUI window.

The synthetic map can be fitted and its active state can be retained by global
Save Session, but **Save fit to session** is disabled for that demonstration so it
cannot be marked as a completed observed result. Real map snapshots are included
in fitting state for replay. Large maps consequently increase session JSON size.

### Multi-component

The dynamic editor has the required five columns. **Checked Fixed/Free means
fixed**: all three parameters in that row remain unchanged. Add/delete rows in
the editor. Edits update the model/residual preview without running an optimizer.
An incomplete/invalid row is reported and blocks Run Fit instead of being silently
committed. Component IDs are regenerated in row order.

Auto defaults are max_components=10, rms_cutoff=5.0 and chi2_threshold=0.01. The
shared adapter limit is 20. Noise is MAD(second differences)/(0.67448975×sqrt(6)).
The noise scale is held fixed during the search. chi2_threshold is an **absolute
minimum improvement in reduced chi-square**, not a relative percentage. Both
residual peak and candidate amplitude must meet the significance threshold.

The supplied Spec_comp.py hard-codes three sequential fits, returns no result and
provides no covariance. The default run_spec_comp call still records that original
three-fit sequence. Auto-Decomposition obtains its first fitted component on the
current residual repeatedly and jointly refines accepted components using
curve_fit. Thus more than three components are supported without editing CLC.
This explicit GUI orchestration/refinement is **not claimed to reproduce the
original three-step CLI decomposition exactly**. Genuine-backend regression tests
remain important, particularly for blended components and reference observations.

The full 3N×3N covariance uses amplitude, center, FWHM ordering per component.
Fixed rows/columns are zero; unestimable entries are JSON null, not fabricated
zero uncertainty. The plot has shared velocity axes, 70/30 model/residual panels,
zero baseline and dashed ±sigma_RMS lines. All-free, mixed fixed/free and all-fixed
manual tables are handled. Manual all-fixed tables are evaluated without invoking
curve_fit.

## State, persistence and compatibility

Active state and all four mode caches live at
`st.session_state.pipeline_data['07_spectral_fitting']`. Content hashes include the
complete numeric arrays and scientific metadata, not just array shape/sum or
rounded calibration values. Mode changes, changed data and failed fits cannot
silently export a stale committed fit. Heavy results are reused until Run Fit is
explicitly clicked; previews and theme changes do not run an optimizer.

The existing session writer now includes:

```json
{
  "stages": {
    "fitting": {
      "type": "gaussian_1d",
      "params": {
        "amplitude_initial_guess": 8.0,
        "center_initial_guess_kms": -4.0,
        "hpbw_kms_fixed": 2.31
      },
      "state": {"schema_version": 2, "modes": {}}
    }
  }
}
```

The abbreviated state above illustrates the shape only; real files retain all
per-mode options, results and provenance. Other type values are polynomial_peak,
gaussian_2d and multi_component. Existing pipeline_data and legacy multi-component
sessions remain supported. Existing immutable-save and checkpoint behaviour is
retained. Set `SESSIONS_PATH=/data/sessions` in deployment; the existing local-path
fallback remains available for development. Session load rebuilds ordinary 1D
upstream inputs through the existing replay workflow; it does not treat stale
runtime spectra as current observations.

The `run_fit(fit_type, vlsr, intensity, unit='K')` entry point remains callable for
legacy callers/tests. Page 07 deliberately calls the explicit CLC adapters instead
of that legacy dispatcher's old two-peak approximation for "2D Gaussian".

The accessibility wrapper forwards each supplied key to st.plotly_chart and uses
separate accessibility-control keys. In Streamlit 1.32 the plotly_chart key arrives
through **kwargs rather than the later native chart-widget identity API. The page
also supplies per-mode slots, data-dependent uirevision and stable trace IDs; it
does not assume forwarding a key alone supplies later Streamlit event behaviour.

## Preserved upstream science

This patch does not change your pre-existing Graph 3 calibration formula:
`(LCP + RCP) * PSS + pointing_correction`, or the equivalent calibrated-input path
without applying PSS twice. The existing helper explicitly flags that the pointing
term is additive even though its backend describes a multiplicative factor. That
pre-existing calibration decision is not silently changed in this fitting update.
Resolve it separately with the science owner before interpreting absolute fitted
amplitudes. No baseline offset is silently subtracted in the 1D/Multi-Component fits.

## Tests and acceptance

See `validation/STAGE7_TEST_REPORT.md` for actual results and limitations. In the
normal pinned project environment, run:

```bash
python -m pytest -q tests/test_stage7_final.py tests/test_stage7_ui.py \
  tests/test_stage7_session.py tests/test_stage7_app.py \
  tests/test_spec_comp.py tests/test_fitting_adapters.py tests/test_fit_figures.py

python -m pytest -q tests/test_session_checkpoints.py \
  tests/fr22/test_ui_adapters.py tests/fr22/test_state_roundtrip.py
```

Then run the full existing repository suite. AppTest tests exercise real Streamlit
widgets/server execution; they do not replace a browser check. In a real browser,
switch through all four modes, edit/add/remove components, change theme/font size,
fit a real 2D map, and save/reload a session. Confirm that heavy fits run only on
Run Fit, covariance matches component count, and an invalid/stale result cannot be
saved as a new fit. Test NFR-01 end-to-end on the deployment hardware and reference
spectra; the included local Python timings do not prove browser latency.

The test files that were updated rather than newly added are:
- test_fit_figures.py: make the component-prefix assertion distinguish "Comp "
  from "Composite fit" (a pre-existing test ambiguity).
- test_session_checkpoints.py: exercise the new real _commit function instead of
  parsing the removed top-level save block.
- fr22/test_visual_polish.py: replace an obsolete assertion that Page 07 must
  describe fake 2D/fixed-three-component limitations.

Implementation is delivered. Pinned-runtime/browser acceptance and real CLC
Specutils/reference-observation regression are still required before marking the
whole Stage 7/NFR acceptance checklist "Done Completely".
