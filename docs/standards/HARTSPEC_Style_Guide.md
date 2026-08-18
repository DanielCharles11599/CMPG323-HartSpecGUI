# HARTSPEC Web GUI — Style Guide

Reference for anyone building a page in `pages/` or the Dash Baseline Editor. If a screen
doesn't match this doc, fix the screen, not the doc — file a note in the team channel if
you think a token needs to change so everyone updates together.

Source of truth: [Figma mockups](https://www.figma.com/design/6g2Eubc4KVT0MHK9duMfDI/HARTSPEC-Web-GUI-Mockups)

---

## 1. Color Tokens

| Token | Hex | Usage |
|---|---|---|
| `bg-primary` | `#FFFFFF` | Page / frame background |
| `bg-sidebar` | `#1E293B` | Persistent left navigation sidebar |
| `bg-panel` | `#FFFFFF` | Card / chart / table container background |
| `bg-panel-alt` | `#F8FAFC` | Alternating table row stripe |
| `bg-muted` | `#F1F5F9` | Low-emphasis fill (legacy placeholder fill, avoid for new work) |
| `border-default` | `#CBD5E1` | Card, table, input, dropdown borders |
| `border-subtle` | `#E2E8F0` | Table outer border, chart axis lines, progress track |
| `accent` | `#2563EB` | Primary buttons, active nav item, active pill, progress fill |
| `text-heading` | `#0F172A` | Page titles |
| `text-body` | `#334155` | Body copy, table cell text, section labels |
| `text-primary-dark` | `#1E293B` | Default text color (fallback) |
| `text-muted` | `#64748B` | Subtitles, captions, secondary row text |
| `text-faint` | `#94A3B8` | Inactive sidebar nav items, placeholder text |
| `sidebar-text` | `#E2E8F0` | Text on dark sidebar surfaces |
| `sidebar-btn-bg` | `#334155` | Session buttons (Save/Load/Reset) on sidebar |
| `sidebar-btn-border` | `#475569` | Border on sidebar buttons |

### Status badges (pill fill / text pairs — never used alone, always paired)

| Status | Fill | Text |
|---|---|---|
| OK / success | `#DCFCE7` | `#166534` |
| Warning | `#FEF9C3` | `#854D0E` |
| Error / flagged / quarantined | `#FEE2E2` | `#991B1B` |
| Info | `#DBEAFE` | `#1E40AF` |

### Spectrum polarization — locked, do not override per-page

| Channel | Hex |
|---|---|
| **LCP** | `#1F77B4` (blue) |
| **RCP** | `#FF7F0E` (orange) |

Applies to every chart, legend swatch, and any UI element referencing LCP/RCP. This
matches the project's mandated convention — do not substitute a different blue/orange.

### Fit-overlay convention

| Element | Style |
|---|---|
| Raw spectrum line | `#1F77B4`, solid, 1.6px |
| Fit overlay line | `#DC2626` (red), **dashed** (`4,3` dash pattern), 1.6px |

Dashing (not just color) is what distinguishes a fit line from data — keep this even in
color-blind-unfriendly contexts.

---

## 2. Typography

**Font family: Inter** (Regular / Semi Bold / Bold only — do not introduce Medium,
Light, or Extra Bold; keeps the type ramp to 3 weights).

| Role | Size | Weight | Color |
|---|---|---|---|
| Page title (H1) | 24px | Bold | `text-heading` |
| Page subtitle | 13px | Regular | `text-muted` |
| Sidebar logo | 18px | Bold | White |
| Sidebar nav item (active) | 12px | Semi Bold | White |
| Sidebar nav item (inactive) | 12px | Regular | `text-faint` |
| Panel/section title | 10.5–11px | Semi Bold | `text-body` |
| Table header | 10px | Semi Bold | `#F1F5F9` (on dark header bg) |
| Table cell | 10.5px | Regular | `text-body` |
| Button label | 12px | Semi Bold (primary/secondary) / Regular (ghost) | see §4 |
| Badge label | 10px | Semi Bold | per-status pair above |
| Caption / helper text | 9.5–10px | Regular | `text-muted` |
| Dropdown label (eyebrow) | 10px | Semi Bold | `text-muted` |

Rule of thumb: **Semi Bold marks anything interactive or a heading; Regular is for data
and body copy.** Don't reach for Bold below 18px.

---

## 3. Layout & Spacing

| Token | Value | Notes |
|---|---|---|
| Reference frame size | 1440 × 900 | Desktop mockup canvas — actual Streamlit width is fluid, treat this as the design reference only |
| Sidebar width | 220px | Fixed, persistent on every page |
| Content padding (left/right) | 24px | Gutter between sidebar and content, and content right edge |
| Header height | 64px | Space reserved for page title + subtitle block |
| Section gap | 16px | Vertical space between stacked content sections |
| Card / panel corner radius | 8px | Tables, chart panels, info boxes |
| Button corner radius | 6px | |
| Pill / segmented control radius | 16px (full) | |
| Badge radius | 9px (full) | |
| Table row height | 28px (32px header) | |

---

## 4. Components

### Buttons
- **Primary** — fill `accent` (`#2563EB`), no border, white text, Semi Bold. One per
  section max — this is the "do this next" action (e.g. *Load into Pipeline*).
- **Secondary** — white fill, `border-default` border, `text-body` text, Semi Bold. Use
  for parallel/equal-weight actions (e.g. the three Export buttons).
- **Ghost** — no fill, `#94A3B8` border, `#475569` text, Regular weight. Use for
  low-emphasis inline actions (e.g. *Load* on a session history row).
- Standard height: 32px (36px for the larger Export row). Padding: 12px horizontal.

### Dropdowns
- 10px Semi Bold muted eyebrow label above the control.
- Control: white fill, `border-default`, 36px tall, 6px radius, value text 12px Regular,
  chevron icon right-aligned, 8px from edge.

### Search input
- White fill, `border-default`, 32px tall, 6px radius, magnifier icon at 10px inset,
  placeholder text 11px Regular `text-faint`.

### Pill / segmented control (mode & fit-type selectors)
- Inactive: white fill, `border-default` border, `#475569` text, Regular.
- Active: `accent` fill, no border, white text, Semi Bold.
- 32px tall, full (16px) corner radius, 8px gap between pills.

### Tables
- Header row: `#1E293B` fill, 32px tall, top corners rounded to match container (8px),
  text `#F1F5F9` 10px Semi Bold.
- Body rows: 28px tall, alternating `bg-panel` / `bg-panel-alt` stripe, text 10.5px
  Regular `text-body`.
- Outer container: white fill, `border-subtle`, 8px radius.
- Cell padding: 10px left.

### Status badges
- Pill, 18px tall, 9px radius, 10px horizontal padding, 10px Semi Bold text. Always use
  a fill/text pair from §1 — never a bare colored dot for status that also needs a label.

### Chart panels
- White fill, `border-default`, 8px radius.
- Title: 10.5px Semi Bold `text-body`, 12px inset from top-left.
- Plot area: `border-subtle` axis lines only (no gridlines) — keep it clean, this is a
  scientific tool, not a marketing dashboard.
- Legend: swatch (10×10px, 2px radius) + 9px Regular `text-muted` label, bottom-left of
  panel, only when the panel has more than one series or the series isn't self-evident.

### Sidebar
- Fixed 220px, `bg-sidebar` fill, full page height.
- Logo top: "HARTSPEC", 18px Bold white, 24px inset.
- Nav items: 8 entries, numbered `01`–`08`, 40px row spacing, active item gets a
  `accent`-filled 6px-radius highlight pill behind it.
- Session controls (**Save / Load / Reset Session**) pinned near the bottom, always
  visible regardless of page — these are global actions, not page-scoped.

---

## 5. Streamlit / Dash implementation notes

These tokens need to become real config, not just visual reference:

**`.streamlit/config.toml` theme block** (approximate — tune against the mockups):
```toml
[theme]
primaryColor = "#2563EB"
backgroundColor = "#FFFFFF"
secondaryBackgroundColor = "#F8FAFC"
textColor = "#334155"
font = "sans serif"   # Streamlit can't load Inter directly — see note below
```
Streamlit's built-in theming doesn't support custom web fonts out of the box. If Inter
matters enough to chase pixel-fidelity, inject it via `st.markdown("<style>...</style>",
unsafe_allow_html=True)` with an `@font-face` or Google Fonts `<link>` — confirm with the
team before doing this, since the intranet server has no internet dependency (per spec),
so a self-hosted font file, not a Google Fonts CDN link, is the compliant approach.

**Plotly charts** — set `LCP`/`RCP` colors explicitly per trace, don't rely on Plotly's
default qualitative palette:
```python
fig.add_scatter(y=lcp_data, line=dict(color="#1F77B4"), name="LCP")
fig.add_scatter(y=rcp_data, line=dict(color="#FF7F0E"), name="RCP")
```
For fit overlays: `line=dict(color="#DC2626", dash="dash")`.

**Sidebar session controls** — since Save/Load/Reset must persist across every page,
implement once in a shared `utils/sidebar.py` helper called from every page module,
rather than each of the 5 programmers rebuilding it per-page. This is also where nav
highlighting (active page) should live centrally.

**Tables** — `st.dataframe` won't match this header/stripe styling out of the box; use
column_config for basic formatting, or a styled `pandas.Styler` if the visual spec
matters for a given screen. Don't hand-roll HTML tables unless a page genuinely needs
custom cell content (e.g. an inline delete button per row, as in the Baseline block
table) — that likely needs `st.data_editor` or a manual row loop with `st.columns`.

**flake8 / 120-char line length** still applies to any styling code — keep long
`st.markdown` CSS blocks in a separate `utils/styles.py` constant rather than inline in
page files.

---

## 6. What's intentionally not locked down yet

- Dark mode — out of scope unless raised.
- Mobile/tablet breakpoints — not needed, intranet desktop tool only.
- Exact Plotly axis/gridline styling — use the "axis lines only, no gridlines" rule from
  §4 but pixel values weren't mocked in detail; use judgment and flag in review if unsure.
- Loading/empty/error states beyond the File Loader progress bar — not yet mocked page by
  page; ask before inventing new visual language for these.
