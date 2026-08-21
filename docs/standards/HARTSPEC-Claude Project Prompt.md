# HARTSPEC Web GUI — Claude Project Instructions

Paste this into the "Custom instructions" / "Project knowledge" field of your individual
Claude Project. The three source documents (technical spec, functional scope, business
case) are **not** uploaded here to save context — they live in a shared NotebookLM. If you
need a detail this prompt doesn't cover (an FR number, an exact field name, a requirement
you're unsure about), **ask the user directly instead of guessing or inventing one.** The
user will query NotebookLM and bring back the answer. Don't fabricate spec details, and
don't silently proceed on an assumption when the real answer is one query away.

---

## Project context

We are building a web-based GUI for **HARTSPEC**, the data reduction pipeline used by
HartRAO (Hartebeesthoek Radio Astronomy Observatory) for maser monitoring and spectrum
survey programs. It replaces a CLI-only tool that requires researchers to edit source code
by hand. End users are postgrad students, postdocs, and visiting scientists — not software
engineers. Assume the reader wants working code, not an astronomy lesson.

This is an 8-person team project (~5 programmers) with a shared codebase. Multiple people
are prompting Claude independently, so **consistency matters more than personal style
preference.** Follow these instructions exactly, even where they conflict with a "usual"
way of doing things.

## Mandated tech stack — do not substitute

- **Python 3.9+ (target 3.11)**
- **Streamlit 1.30+** — main framework, multipage app
- **Plotly Dash 5.x** — used *only* for the interactive Baseline Block Editor (FR-05),
  because Streamlit's stateless execution model can't handle the callback-driven updates
  needed for dragging and selecting velocity ranges on a live spectrum. Everything else
  stays in Streamlit.
- The Dash editor runs as a sub-component inside the Streamlit interface via an **iframe**
  or the **`streamlit-plotly-dash-bridge`** — it is not a separate standalone app users
  navigate to. Streamlit is the principal framework; Dash is embedded, not parallel.
- Flask was evaluated during feasibility and explicitly not chosen — don't reach for it or
  suggest it as an alternative.
- **Astropy 5.x+, NumPy, SciPy, Pandas** — the HartRAO scientific stack, already assumed
  available
- **Plotly** for all interactive charts (panning/zooming/tooltips required)
- No Flask, no FastAPI, no REST API layer of any kind — the 19 original HartSpec modules
  are imported directly as Python libraries inside the Streamlit/Dash process, never called
  over HTTP.
- No SQL/NoSQL database. Session state and reproducibility are handled via **JSON files**
  written to `/data/sessions/`.
- No cloud hosting, no internet dependency — this runs on a local Ubuntu 22.04 LTS
  intranet server with no client-side installation.

If a suggestion would require any of the above, don't offer it as the default path — flag
the tradeoff instead and let the user decide.

## Mandated folder structure

Server deployment root is `/opt/hartspec/`. Repo layout mirrors this:

```
/opt/hartspec/
├── hartspec_gui/
│   ├── Home.py              # Streamlit entry point — run via `streamlit run hartspec_gui/Home.py`
│   ├── pages/              # Streamlit multipage stages, numbered consecutively
│   │   ├── 01_Source_Browser.py
│   │   ├── 02_File_Loader.py
│   │   └── ...
│   ├── dash_apps/          # Plotly Dash app(s) — Baseline Block Editor lives here
│   ├── utils/              # Shared helpers — e.g. sidebar.py (global nav), styles.py (CSS)
│   └── clc/                # Symlink to the original 19 HartSpec modules
├── requirements.txt         # Pinned versions of all Python dependencies, at repo root
└── .streamlit/
    └── config.toml          # Server + theme config

/data/                        # Separate from the app root — persistent storage
├── fits/                     # Read-only archive of raw telescope FITS files
├── sessions/                 # Read-write — session JSON files for reproducibility
└── pss/                      # PSS database text files used for calibration

<repo root>/
├── docs/                     # User Manual, Developer Guide, analysis diagrams
└── tests/                    # Automated tests + reference spectra for regression testing
```

New pages go in `hartspec_gui/pages/`, numbered to match their position in the pipeline.
Don't invent alternate structures (e.g. `src/`, `components/`) even if that's a common
Streamlit pattern elsewhere — stick to this layout so everyone's imports and file paths
resolve the same way. Note the split: `/data/` (FITS, sessions, PSS) lives outside the app
directory entirely — never hardcode paths that assume data lives alongside the app code.
`/data/fits/` is read-only in code; only the quarantine function may move files out of it.

## Working with `clc/` (the original 19 modules)

These are the existing HartSpec modules (`File_check.py`, `load_file.py`, `Baseline.py`,
`Blocks.py`, `Calibrate_PSS_PWR.py`, `Point_cor.py`, `Gaussf.py`, `plot_spec.py`, etc.),
imported directly as libraries. Rules:

- **Never modify the underlying scientific algorithms.** Fitting math, calibration
  formulas, and baseline subtraction logic are out of scope to change — bugs in the GUI
  layer, not the science, are ours to fix.
- **Phase 0 refactoring is already complete** — the honours students have already fixed
  the known GUI-integration blockers (global variable conflicts in `Point_cor.py`,
  resource leaks in `load_file.py`, removal of `ipywidgets`/`input()` calls in
  `Option.py`). Treat `clc/` as GUI-integration-ready. Don't re-flag these as open issues
  or re-do this refactoring — if you spot something that looks like a leftover from one of
  these problems, ask before assuming it's still broken, since it may be intentional or
  already handled elsewhere.
- Refer to module filenames in monospace in all docs/comments, e.g. `load_file.py`.

## Data conventions

- Inputs: raw FITS files (up to ~500MB) and PSS text database files.
- Outputs: NumPy arrays (spectra), Pandas DataFrames (header tables with 30+ fields),
  exported CSV / PDF / calibrated FITS files, JSON session logs.
- Units are astronomical — velocity in km/s, flux in Jy or K. Don't silently assume
  generic units.
- Chart color convention (apply everywhere, don't override per-page):
  **LCP = blue `#1F77B4`, RCP = orange `#FF7F0E`.**
- FITS archive access is **read-only** except for the quarantine function (which moves,
  not edits, corrupt files).

## Performance targets to design around

- GUI response after a parameter change: < 2 seconds for a standard 1024-channel spectrum
- Initial FITS load: < 5 seconds
- Fitting calls (e.g. `scipy.optimize.curve_fit`) are the main latency risk on large
  files — flag when a suggested approach might blow the 2-second budget, and prefer
  caching (`st.cache_data`/`st.cache_resource`) or async/callback patterns over blocking
  the main thread.

## Coding standards

- **flake8**, max line length **120 characters**
- Type hints on new functions where practical
- Docstrings on any function that isn't trivially self-explanatory (this app is used by
  non-engineers doing science, so integration code should be easy for a new teammate —
  not just the author — to follow)
- **pytest** for tests; minimum **70% line coverage** on fitting and calibration-adjacent
  code
- For anything touching numerical output from `clc/` modules, results must match the
  original CLI output to **6 significant figures** — treat this as a hard regression
  requirement, not a nice-to-have, and mention it when writing or reviewing fitting/
  calibration code
- **Standardized commenting** — apply the same commenting style on every page/module,
  regardless of who's prompting Claude or which machine it's written on:
  - Every file starts with a short header comment: what the file does, which FR(s) it
    implements (e.g. `# 04_Baseline_Editor.py — FR-05/06/07: interactive baseline block
    selection + polynomial order comparison`)
  - Every function gets a docstring (purpose, args, returns) — not just a one-liner if
    the function does anything non-trivial
  - Inline comments explain *why*, not *what* (skip `# increment counter`; keep
    `# recompute completed_stages from session JSON, not a separate counter, to avoid drift`)
  - Any deviation from the style guide or build spec gets a `# TODO: confirm against
    design — see build spec §3` comment rather than being silently resolved either way
  - Keep this consistent enough that a page written by one teammate reads like it was
    written by the same person who wrote everyone else's — that's the point of
    standardizing it at all

## Local setup — before building anything

Every teammate runs these steps once, on their own machine, before writing page code.
Goal: confirm Streamlit launches in the browser with a clean environment before anyone
starts on real pipeline pages.

1. **Create the virtual environment** (Python 3.11, per spec):
   ```
   python3.11 -m venv .venv
   ```
2. **Activate it**:
   - macOS/Linux: `source .venv/bin/activate`
   - Windows: `.venv\Scripts\activate`
3. **Confirm `requirements.txt`** at the repo root with the pinned versions from the build
   spec, plus `python-dotenv` for `.env` loading:
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
   python-dotenv
   ```
4. **Install**:
   ```
   pip install -r requirements.txt
   ```
5. **Set up `.env`**: copy `.env.example` to `.env`, fill in local paths (they don't need
   to point at real HartRAO data yet — any local folder works for a first smoke test):
   ```
   FITS_ARCHIVE_PATH=./data/fits
   SESSIONS_PATH=./data/sessions
   PSS_DATA_PATH=./data/pss
   DASH_BRIDGE_PORT=8050
   STREAMLIT_AUTH_ENABLED=false
   ```
6. **Create the entry point** so there's something to run before pages 01–08 exist.
   Streamlit multipage apps need one top-level script alongside `pages/` — the entry
   point is `hartspec_gui/Home.py`:
   ```python
   import streamlit as st

   st.set_page_config(page_title="HARTSPEC GUI", layout="wide")
   st.write("HARTSPEC GUI — environment OK. Pages will appear in the sidebar once added.")
   ```
7. **Run it**:
   ```
   streamlit run hartspec_gui/Home.py
   ```
   This opens the app at `http://localhost:8501` in your browser. Once real numbered
   pages land in `pages/`, Streamlit auto-lists them in the sidebar nav — no change to
   `Home.py` needed. If port 8050 (Dash bridge) is needed later, that's separate and only
   comes up once the Baseline Editor (page 04) work starts.

Confirm this works — clean venv, install, browser tab opens — before writing any
pipeline-stage code. If it doesn't, that's an environment problem to fix now, not
something to debug three pages in.

## Out of scope — don't suggest these

- Changing scientific/fitting algorithms
- Cloud hosting or public internet exposure
- Native mobile apps
- Any authentication beyond optional `streamlit-authenticator` (intranet firewall is the
  primary access control; only add auth if explicitly asked)

## How to respond

- Default to concrete, runnable code over abstract discussion — this team is optimizing
  for consistent, working output across 5 people, not for exploring alternatives.
- When a request conflicts with something above (wrong framework, wrong folder, skips a
  regression check), say so directly and propose the compliant version rather than
  silently going along with it.
- Assume Streamlit + Dash conventions (session_state, st.cache_data, Dash callbacks) by
  default — don't reach for generic Flask/JS patterns from training data.
- If you're missing a spec detail this document doesn't cover, ask for it rather than
  guessing — the user can pull the exact answer from NotebookLM quickly. A quick clarifying
  question beats a wrong assumption baked into shared code.