# HARTSPEC GUI — Page-by-Page Build Spec

*Reverse-engineered from `HARTSPEC-Web-GUI-Mockups` (Figma file key
`6g2Eubc4KVT0MHK9duMfDI`). Companion to `HARTSPEC_Style_Guide.md` — that doc is the
source of truth for colors, typography, and component styling; this doc is the source of
truth for exact page layout, coordinates, and per-page content. Don't duplicate values
between them — if a token or component spec changes, it changes in the style guide only.*

---

## Resolved from the first pass

1. **Content gutter**: raw Figma measured 48px between sidebar and content; the style
   guide's documented 24px token wins. Content starts at `x=244` (`sidebar 220 + 24`),
   not the raw `x=268`, and widens to `1172px` to keep its right edge fixed at `x=1416`.
   Every coordinate below already reflects this — see §3 for the transformation rule.
2. **Pipeline progress bar layout**: use the compact 260px top-right track (identical
   across all 8 dark-mode frames) on every page, both themes. The full-width 8-segment
   bar seen on light-mode frames 01–07 is a superseded draft, not part of this spec.

---

## 1. Tech stack — exact pinned versions

```
streamlit==1.32.0
plotly==5.20.0
dash==2.16.0
astropy>=5.3,<6.0
numpy>=1.24
scipy>=1.10
pandas>=2.0
pytest>=7.4
pytest-cov>=4.0
```

Framework roles, folder structure, `clc/` handling, and coding standards are already
covered in the project's Claude instructions doc — this file assumes those and doesn't
repeat them.

## 2. Theme state — implementation specifics

Beyond what the style guide's §5 already covers (one Python dict per theme, injected via
`st.markdown`), the concrete wiring:

- Active theme lives in `st.session_state["theme"]` (`"light"` or `"dark"`), toggled from
  a control in the sidebar (see §5 below).
- Every page calls a shared `inject_theme_css()` helper from `utils/styles.py` at the top
  of its script — reads `st.session_state["theme"]`, injects the matching CSS variables.
- Plotly `paper_bgcolor` / `plot_bgcolor` must be set explicitly per chart from the active
  theme's `bg-panel` token — they don't inherit from injected CSS.

## 3. Coordinate transformation rule

Raw Figma measured content starting at `x=268` (48px from sidebar), width `1148`. Per the
resolution above, this spec uses `CONTENT_X=244` / `CONTENT_WIDTH=1172` (right edge fixed
at `x=1416`). Every coordinate in §6 has already been transformed:

- **Left-anchored elements** (panel starts, titles, list rows, left-aligned labels):
  `new_x = old_x - 24`.
- **Full-width containers** (panels, plot areas, tables spanning the content column):
  `new_width = old_width + 24`, `new_x = old_x - 24`, right edge stays at 1416.
- **Right-anchored elements** (status badges near a panel's right edge, the Quarantine
  button, session-history Load buttons, the pipeline progress bar): **unchanged** — these
  were already positioned relative to the fixed right edge.
- **Multi-column tables**: 16px gaps and 10px/6px left/right padding held fixed; the
  extra 24px of width is distributed across columns proportionally to original widths —
  already recomputed per table in §6.
- **Fixed-width controls at the left edge** (dropdowns, pills, buttons): position shifts
  `-24`, width unchanged.

## 4. Global layout constants

```python
FRAME_WIDTH = 1440          # design reference canvas; actual Streamlit width is fluid
FRAME_HEIGHT = 900
SIDEBAR_WIDTH = 220
CONTENT_X = 244              # SIDEBAR_WIDTH + 24px gutter
CONTENT_WIDTH = 1172         # right edge fixed at x=1416
HEADER_HEIGHT = 64
PROGRESS_BAR_WIDTH = 260
```

(Radii, row heights, section gaps, and other spacing tokens are in the style guide §3 —
not repeated here.)

## 5. Sidebar — page-generation specifics

Style guide §4 covers the sidebar's visual spec (colors, widths, button styling). Specific
to code generation:

- Exact nav labels, in order: `01 Source Browser`, `02 File Loader`,
  `03 Bandpass Correction`, `04 Baseline Block Editor`, `05 Calibration Dashboard`,
  `06 Pointing Correction`, `07 Spectral Fitting`, `08 Export & Session`.
- Active-item highlight pill: `x=12, width=196, height=32` relative to the sidebar,
  vertically centered on the 40px nav row.
- Theme toggle: placed directly below the nav list — **new requirement, not in the
  original mockup** (style guide left this as a product decision). Implement as a small
  Light/Dark segmented control, same visual language as the pill spec, bound to
  `st.session_state["theme"]`.
- "SESSION" eyebrow label at local `y=712` (i.e. `FRAME_HEIGHT - 188`), 24px inset.
- Three session buttons below it — **Save Session**, **Load Session**, **Reset
  Session** — each `x=24, width=172, height=32`, 44px row spacing. Implement once in
  `utils/sidebar.py`, called from every page — not rebuilt per page.

## 6. Pipeline progress bar — exact formula

Style guide §4 covers styling (fixed colors, not theme tokens). Position, used
identically on every page:

- Track: `x=1156` (`FRAME_WIDTH - 24 - 260`), `y=52`, 260×8px, 4px radius.
- Fill: same radius, `width = (completed_stages / 8) × 260` — compute at runtime.
- Label "Stage {n} of 8": `x=1156, y=34`.
- Caption "{completed}/8 stages complete": `x=1156, y=66`.
- "Completed" = stages strictly before the current page (current page = in-progress, not
  complete). Derive `completed_stages` from which stage keys already exist in the current
  session JSON — don't track a separate progress variable that can drift out of sync.

All other shared components (buttons, dropdowns, search input, pills, tables, status
badges, chart panels) follow the style guide §4 spec exactly — no page-specific
overrides exist for these.

## 7. Page-by-page build spec

All coordinates are **frame-local** (0,0 = top-left of the 1440×900 content canvas),
already transformed per §3. Header band is identical on every page:

- Title: `x=244, y=44, w=1172, h=29`
- Subtitle: `x=244, y=78, w=1172, h=16`
- Progress bar: per §6
- First content panel starts at `y=104`

---

#### 01 — Source Browser (`FR-01`)

Subtitle: *"FR-01 — file browser for source & frequency selection"*

| Element | x | y | w | h |
|---|---|---|---|---|
| Sources & Frequencies panel | 244 | 104 | 1172 | 380 |
| Panel title "Source Browser — FR-01" | 256 | 114 | 1148 | 13 |

Grouped file list (checkbox groups by observation month):
- Group header row: 10×10 checkbox at `x=260`, group label + file count stacked
  (label 14px, count 11px, 4px gap), first group at `y=148`.
- File rows nested under each group: 10×10 checkbox at `x=280` (20px indent), filename
  (14px) + type/size caption (11px) at `x=298`, OK status badge (`32.4×18`)
  right-anchored at `x=1346`.
- Row spacing: 34px between file rows, 68px before the next group header.
- Sample data to reproduce exactly: Group "2026-08 Observations" (12 files) containing
  `spectrum_001.fits` (FITS · 42MB), `spectrum_002.fits` (FITS · 38MB),
  `spectrum_003.fits` (FITS · 41MB), all OK. Group "2026-07 Observations" (8 files)
  containing `pss_survey_014.txt` (PSS · 3MB, OK) and `pss_survey_015.txt` (PSS · 3MB,
  OK) — include both rows (dark-mode mockup only rendered the first; light-mode has both).

| Element | x | y | w | h |
|---|---|---|---|---|
| "FREQUENCY" eyebrow label | 244 | 500 | 320 | 12 |
| Frequency dropdown | 244 | 518 | 320 | 36 |

Dropdown value: `1420.405 MHz — HI line`.

| Element | x | y | w | h |
|---|---|---|---|---|
| Selection summary bar | 244 | 570 | 1172 | 90 |
| Summary text | 260 | 584 | 1140 | 14 |
| "Load into Pipeline →" primary button | 260 | 618 | 190 | 32 |

Summary text: *"Selected: spectrum_002.fits · 2026-08-12 · HI line · Dec +12°34'"*

---

#### 02 — File Loader (`FR-02` / `FR-03`)

Subtitle: *"FR-02 FITS load & FR-03 validation / quarantine"*

| Element | x | y | w | h |
|---|---|---|---|---|
| Load progress panel | 244 | 104 | 1172 | 64 |
| "Loading spectrum_002.fits" label | 260 | 114 | 1140 | 14 |
| Progress track | 260 | 138 | 1140 | 10 |
| Progress fill | 260 | 138 | 729.6 | 10 |
| "3.2s elapsed · 64%" caption | 260 | 152 | 200 | 11 |

Progress fill width = `track_width × pct_complete` — compute at runtime.

| Element | x | y | w | h |
|---|---|---|---|---|
| Validation table panel | 244 | 184 | 1172 | 116 |
| Table header row | 244 | 184 | 1172 | 32 |

Columns: **File** `x=254, w=511.6` · **Issue** `x=781.6, w=394.5` · **Status**
`x=1192.1, w=218.3`. Body rows 28px tall starting `y=216`:
1. `spectrum_002.fits` / `—` / **OK** badge
2. `spectrum_003.fits` / `Header checksum mismatch` / **FLAGGED** badge
3. `pss_survey_015.txt` / `—` / **OK** badge

A **Quarantine** secondary button (`x=1298, y=242, w=106, h=24`, right-anchored) sits
next to the FLAGGED row specifically — the FR-03 "move to quarantine" action, scoped to
that row, not global.

| Element | x | y | w | h |
|---|---|---|---|---|
| Column search input | 244 | 316 | 280 | 32 |

Placeholder: *"Search 30+ fields…"*

| Element | x | y | w | h |
|---|---|---|---|---|
| Header-fields table panel | 244 | 360 | 1172 | 116 |
| Table header row | 244 | 360 | 1172 | 32 |

Exactly 9 equal-width columns, `w=114.2` each, left pad `x0=254`:

| Column | x |
|---|---|
| Vlsr | 254.0 |
| LCP/RCP | 384.2 |
| HPBW | 514.4 |
| Tsys | 644.6 |
| Date | 774.8 |
| Object | 905.0 |
| RA/Dec | 1035.2 |
| Focus | 1165.4 |
| Humidity | 1295.6 |

LCP and RCP are combined into one "LCP/RCP" column — 9 visible columns for the FR spec's
10 priority fields. Reproduce this combined-column treatment exactly. Body rows 28px
tall, sample data:
- Row 1: `-4.2 km/s` · `12.3/11.8K` · `0.23°` · `48.1K` · `08-12` · `W3(OH)` ·
  `02:27+61°` · `3.1mm` · `38%`
- Row 2: `-3.8 km/s` · `11.9/11.5K` · `0.23°` · `47.6K` · `08-12` · `W49N` ·
  `19:10+09°` · `3.0mm` · `37%`
- Row 3: `-5.1 km/s` · `13.0/12.4K` · `0.23°` · `48.9K` · `08-11` · `G34.3` ·
  `18:53+01°` · `3.2mm` · `41%`

This previews a 30+ field dataframe — use `st.dataframe` column_config or a styled
`pandas.Styler`; don't hand-roll HTML unless the search-filter interaction requires it.

---

#### 03 — Bandpass Correction (`FR-04`)

Subtitle: *"FR-04 — mode selector + spectrum overlay"*

| Element | x | y | w | h |
|---|---|---|---|---|
| "MODE" eyebrow label | 244 | 104 | 300 | 12 |
| "Frequency Switch" pill (active) | 244 | 122 | 122 | 32 |
| "Position Switch" pill (inactive) | 374 | 122 | 115.5 | 32 |

| Element | x | y | w | h |
|---|---|---|---|---|
| Spectrum chart panel | 244 | 174 | 1172 | 440 |
| Panel title "Bandpass-corrected spectrum" | 256 | 182 | 1148 | 13 |
| Plot area | 256 | 204 | 1148 | 384 |
| LCP legend swatch + label | 256 / 272 | 598 | 10 / 70 | 10 / 11 |
| RCP legend swatch + label | 306.5 / 322.5 | 598 | 10 / 70 | 10 / 11 |

Two traces (LCP/RCP, fixed colors per style guide). No fit line on this page — fit
overlays start at page 07.

---

#### 04 — Baseline Block Editor (`FR-05` / `FR-06` / `FR-07`) — Dash-embedded

Subtitle: *"FR-05 / 06 / 07 — Dash-embedded interactive editor"*

The one exception to "Streamlit page" — the canvas, block table, and polynomial grid
below render **inside the embedded Dash app** (`dash_apps/`), not as native Streamlit
widgets. The Streamlit page file's job is just to mount the iframe/bridge component at
these coordinates and pass session state in/out.

| Element | x | y | w | h |
|---|---|---|---|---|
| Interactive canvas panel | 244 | 104 | 1172 | 320 |
| Panel title | 256 | 114 | 1148 | 13 |
| Plot area | 256 | 138 | 1148 | 150.9 |

Title: *"Interactive canvas — click-drag to select a velocity range (0.1 km/s
precision)"*. Two committed selection regions mocked on the canvas at `x=458.3, w=134.9`
and `x=874.2, w=112.4` (both `y=138, h=270`), rendered as semi-transparent
`accent`-tinted overlays on top of the spectrum trace. Implement with Dash's `dcc.Graph`
`selectedData` prop, translating pixel drag range → velocity range at 0.1 km/s precision
before committing a block.

| Element | x | y | w | h |
|---|---|---|---|---|
| Block table panel | 244 | 440 | 1172 | 88 |
| Table header row | 244 | 440 | 1172 | 32 |

Columns: **Block** `x=254, w=159.7` · **Start (km/s)** `x=429.7, w=335.9` ·
**End (km/s)** `x=781.6, w=335.9` · delete-icon column `x=1133.5, w=277.1`. Two sample
rows (28px tall): Block `1` / `-12.4` / `-9.8` / `×`; Block `2` / `4.1` / `7.6` / `×`.
The `×` is a per-row delete — clicking it must refresh the canvas within 1 second (FR-05
UI feedback requirement) and reject/flag any edit resulting in `start >= end`.

| Element | x | y | w | h |
|---|---|---|---|---|
| "Six-panel polynomial order comparison" label | 244 | 544 | 400 | 13 |
| Order 1 cell | 244 | 564 | 382.67 | 100 |
| Order 2 cell | 638.67 | 564 | 382.67 | 100 |
| Order 3 cell | 1033.34 | 564 | 382.67 | 100 |
| Order 4 cell | 244 | 676 | 382.67 | 100 |
| Order 5 cell | 638.67 | 676 | 382.67 | 100 |
| Order 6 cell | 1033.34 | 676 | 382.67 | 100 |

3-column × 2-row grid, edge-to-edge, 12px gaps. Each cell: title `"Order N"` (13px)
top-left inset, small residual/fit-quality plot filling the remainder (~60px plot
height). This is the FR-06/FR-07 side-by-side polynomial-order comparison.

---

#### 05 — Calibration Dashboard (`FR-10` / `FR-11`)

Subtitle: *"FR-10 / 11 — atmospheric & PSS calibration"*

| Element | x | y | w | h |
|---|---|---|---|---|
| Atmospheric panel | 244 | 104 | 1172 | 230 |
| Panel title "Atmospheric calibration (PWV, ATcor)" | 256 | 112 | 1148 | 13 |
| Plot area | 256 | 134 | 1148 | 174 |
| PWV legend swatch + label | 256 / 272 | 318 | 10 / 70 | 10 / 11 |
| ATcor legend swatch + label | 306.5 / 322.5 | 318 | 10 / 70 | 10 / 11 |

Two-series time-series chart. PWV/ATcor aren't LCP/RCP, so they don't inherit the fixed
polarization colors — pick two distinguishable, theme-appropriate hues (unlike LCP/RCP,
these are allowed to re-theme).

| Element | x | y | w | h |
|---|---|---|---|---|
| PSS calibration panel | 244 | 350 | 1172 | 230 |
| Panel title "PSS calibration" | 256 | 358 | 1148 | 13 |
| Plot area | 256 | 380 | 1148 | 174 |
| PSS legend swatch + label | 256 / 272 | 564 | 10 / 70 | 10 / 11 |

Single-series time-series chart (PSS gain vs. epoch).

---

#### 06 — Pointing Correction (`FR-12` / `FR-13`)

Subtitle: *"FR-12 / 13 — compass grid & offset calculation"*

Five equal panels, `220×200` each, edge-to-edge with 18px gaps (widened from the
original 12px to absorb the extra content width, panel size unchanged):

| Panel | x | y | w | h |
|---|---|---|---|---|
| N | 244 | 104 | 220 | 200 |
| S | 482 | 104 | 220 | 200 |
| E | 720 | 104 | 220 | 200 |
| W | 958 | 104 | 220 | 200 |
| Centre | 1196 | 104 | 220 | 200 |

Each panel: direction label (13px) at top-left inset (`+12,+8`), a small pointing-scan
plot filling the remainder (~160px tall, starting 22px below the label). Left-to-right
order is **N, S, E, W, Centre** — reproduce exactly, not a geographic cross layout.

| Element | x | y | w | h |
|---|---|---|---|---|
| Offset table panel | 244 | 320 | 1172 | 116 |
| Table header row | 244 | 320 | 1172 | 32 |

Columns: **Metric** `x=254, w=687.3` · **Value** `x=957.3, w=452.7`. Rows (28px tall):
`Azimuth offset` → `+0.042°`; `Elevation offset` → `-0.018°`; `RMS residual` → `0.011°`.

---

#### 07 — Spectral Fitting (`FR-14`–`FR-17`)

Subtitle: *"FR-14–17 — Gaussian / polynomial / multi-component fits"*

| Element | x | y | w | h |
|---|---|---|---|---|
| "FIT TYPE" eyebrow label | 244 | 104 | 400 | 12 |
| "1D Gaussian" pill (active) | 244 | 122 | 89.5 | 32 |
| "2D Gaussian" pill | 341.5 | 122 | 89.5 | 32 |
| "Polynomial Peak" pill | 439 | 122 | 115.5 | 32 |
| "Multi-component" pill | 562.5 | 122 | 115.5 | 32 |

Four-way segmented control implementing FR-14 through FR-17 as mutually exclusive modes.

| Element | x | y | w | h |
|---|---|---|---|---|
| Fit chart panel | 244 | 174 | 1172 | 320 |
| Panel title "Spectrum + fit overlay" | 256 | 182 | 1148 | 13 |
| Plot area | 256 | 204 | 1148 | 264 |
| Spectrum legend swatch + label | 256 / 272 | 478 | 10 / 70 | 10 / 11 |
| Fit legend swatch + label | 334 / 350 | 478 | 10 / 70 | 10 / 11 |

Spectrum trace solid; fit trace per the style guide's fit-overlay convention (dashed
red, theme-dependent hex).

| Element | x | y | w | h |
|---|---|---|---|---|
| Fit-parameters table panel | 244 | 510 | 1172 | 116 |
| Table header row | 244 | 510 | 1172 | 32 |

Columns: **Parameter** `x=254, w=453.2` · **Value** `x=723.2, w=335.7` ·
**± Error** `x=1074.9, w=335.7`. Rows (28px tall): `Amplitude` → `8.42 K` → `0.15 K`;
`Center (Vlsr)` → `-4.20 km/s` → `0.03 km/s`; `FWHM` → `2.31 km/s` → `0.08 km/s`.

---

#### 08 — Export & Session (`FR-18` / `FR-19` / `FR-20`)

Subtitle: *"FR-18 / 19 / 20 — export, session history, observation log"*

| Element | x | y | w | h |
|---|---|---|---|---|
| Final spectrum panel | 244 | 104 | 1172 | 260 |
| Panel title "Final calibrated spectrum" | 256 | 112 | 1148 | 13 |
| Plot area | 256 | 134 | 1148 | 204 |
| LCP legend swatch + label | 256 / 272 | 348 | 10 / 70 | 10 / 11 |
| RCP legend swatch + label | 306.5 / 322.5 | 348 | 10 / 70 | 10 / 11 |

| Element | x | y | w | h |
|---|---|---|---|---|
| Export CSV (secondary button) | 244 | 380 | 150 | 36 |
| Export PDF (secondary button) | 410 | 380 | 150 | 36 |
| Export FITS (secondary button) | 576 | 380 | 170 | 36 |

Note the 36px button height (the Export row is the one place buttons are taller). 16px
gap between buttons.

| Element | x | y | w | h |
|---|---|---|---|---|
| "Session history" label | 244 | 440 | 400 | 13 |
| History row 1 | 244 | 464 | 1172 | 32 |
| History row 2 | 244 | 504 | 1172 | 32 |
| History row 3 | 244 | 544 | 1172 | 32 |

Each row: timestamp (13px, `x=256`) + description (13px, `x=424`) + Ghost-style **Load**
button (`70×26`, right-anchored at `x=1336`). Sample rows:
- `2026-08-12 14:03` — `W3(OH) — HI line reduction`
- `2026-08-11 09:47` — `G34.3 — PSS calibration run`
- `2026-08-10 16:22` — `W49N — baseline re-fit`

FR-19 session history navigator — clicking **Load** on any row must "replay" that
session, pre-filling every prior pipeline stage with its saved parameters.

| Element | x | y | w | h |
|---|---|---|---|---|
| Observation Log Panel | 244 | 600 | 1172 | 90 |
| Panel title "Observation Log Panel (FR-20)" | 258 | 610 | 1144 | 13 |
| Log text block | 258 | 630 | 1144 | 33 |

Monospace, timestamped audit trail, e.g.:
```
14:03:12 Session loaded — W3(OH)
14:03:44 Baseline block [1] added (-12.4 to -9.8 km/s)
14:04:02 Polynomial order set to 3
```
Must be a real running log sourced from the session JSON's audit trail — every parameter
change on every page appends a timestamped entry here, not static text.

## 8. Final instructions for code generation

- Implement `utils/styles.py` and `utils/sidebar.py` first — every page depends on them.
- Build pages in pipeline order (01 → 08) so each can be smoke-tested against the
  previous page's session-state output.
- Every numeric literal above is intentional and already reconciled against the style
  guide (§3 documents how). If anything still looks inconsistent once implementing
  against a live Figma file, add `# TODO: confirm against design — see build spec §3`
  rather than silently reconciling it either way.
- Don't invent visual language for loading/empty/error states beyond what's specified
  here (the File Loader progress bar is the only one mocked) — flag and ask rather than
  guessing, per the style guide's §6.
- Write tests alongside each page/module as you go, not as a final pass — 70% coverage
  target applies to fitting/calibration code specifically (pages 05 and 07, plus any
  touched `clc/` modules).
