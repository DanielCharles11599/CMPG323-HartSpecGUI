# HARTSPEC Web GUI — Style Guide

Reference for anyone building a page in `pages/` or the Dash Baseline Editor. If a screen
doesn't match this doc, fix the screen, not the doc — file a note in the team channel if
you think a token needs to change so everyone updates together.

Source of truth: [Figma mockups](https://www.figma.com/design/6g2Eubc4KVT0MHK9duMfDI/HARTSPEC-Web-GUI-Mockups)
(includes light-mode pages, dark-mode pages, and two "Component Reference" frames
showing every UI element side by side per mode).

---

## 1. Color Tokens

### Brand colors — locked, do not substitute

| Token | Hex | Notes |
|---|---|---|
| **HartRAO Light Blue** (`accent`) | `#587BBD` | HartRAO's brand color. **Same value in light mode and dark mode** — this is the one color that never changes between themes. |
| **HartRAO Dark Blue** | `#395790` | Companion shade — same hue/saturation as the brand blue, reduced lightness. Used for the sidebar and table headers in **light mode**. |

Both are set up as Figma **Paint Styles** ("HartRAO/Accent Light" and "HartRAO/Accent
Dark") — change the style once in Figma and every bound element updates. If you're
adding a new frame/component, bind to the style rather than pasting the hex, so this
keeps working.

### Light mode

| Token | Hex | Usage |
|---|---|---|
| `bg-primary` | `#FFFFFF` | Page / frame background |
| `bg-sidebar` | `#395790` (HartRAO Dark Blue) | Persistent left navigation sidebar |
| `bg-panel` | `#FFFFFF` | Card / chart / table container background |
| `bg-panel-alt` | `#F8FAFC` | Alternating table row stripe |
| `border-default` | `#CBD5E1` | Card, table, input, dropdown borders |
| `border-subtle` | `#E2E8F0` | Table outer border, chart axis lines, progress track |
| `accent` | `#587BBD` (HartRAO Light Blue) | Primary buttons, active nav item, active pill, progress fill |
| `text-heading` | `#0F172A` | Page titles |
| `text-body` | `#334155` | Body copy, table cell text, section labels |
| `text-muted` | `#64748B` | Subtitles, captions, secondary row text |
| `text-faint` | `#94A3B8` | Placeholder text |
| `sidebar-text-active` | `#FFFFFF` | Active nav item text |
| `sidebar-text-inactive` | `#B7C3DA` | Inactive nav items + session caption — **lightened from the original gray** so it doesn't wash out against the dark blue sidebar; don't revert to `#94A3B8` here |
| `sidebar-btn-bg` | `#334155` | Session buttons (Save/Load/Reset) on sidebar |
| `sidebar-btn-border` | `#475569` | Border on sidebar buttons |
| Table header (light) | `#395790` (HartRAO Dark Blue) | fill, with `#F1F5F9` text |

### Dark mode

| Token | Hex | Usage |
|---|---|---|
| `bg-primary` | `#395790` (HartRAO Dark Blue — **same value as light mode's sidebar**) | Page / frame background |
| `bg-sidebar` | `#16233D` | Sidebar — its own dark navy, kept distinct from the page background rather than literally swapping with it. (The PM's original idea was to swap the sidebar and page-background colors outright; what we landed on instead is that the *page* background picks up light mode's sidebar color, but the sidebar itself keeps a dedicated darker tone — otherwise sidebar and content would read as the same surface with nothing separating them.) |
| `bg-panel` | `#1E293B` | Card / chart / table container background |
| `bg-panel-alt` | `#243044` | Alternating table row stripe |
| `border-default` | `#334155` | Card, table, input, dropdown borders |
| `border-subtle` | `#2B3A52` | Table outer border, chart axis lines, progress track |
| `accent` | `#587BBD` (HartRAO Light Blue — **unchanged from light mode**) | Primary buttons, active nav item, active pill, progress fill |
| `text-heading` | `#F1F5F9` | Page titles |
| `text-body` | `#CBD5E1` | Body copy, table cell text |
| `text-muted` | `#94A3B8` | Subtitles, captions |
| `text-faint` | `#64748B` | Lowest-emphasis captions |
| `sidebar-text-active` | `#FFFFFF` | Active nav item text |
| `sidebar-text-inactive` | `#7F92B5` | Inactive nav items + session caption |
| `sidebar-btn-bg` | `#233450` | Session buttons on sidebar |
| `sidebar-btn-border` | `#3A4C6E` | Border on sidebar buttons |
| Table header (dark) | `#395790` (HartRAO Dark Blue — same as light mode, and now also the page background — see note below) | fill, with `#F1F5F9` text |

Note on table headers in dark mode: since the page background is now the same HartRAO
Dark Blue as the table header fill, a table sitting directly on the page could visually
blend at the top edge. The `bg-panel` (`#1E293B`) container behind the table, plus the
`border-subtle` outline, is what keeps the table legible against the page — don't drop
that container fill/border for dark-mode tables even though it might look redundant in
isolation.

**The rule that matters:** HartRAO Light Blue (`#587BBD`) and HartRAO Dark Blue
(`#395790`) are brand constants — they read identically in both themes. Everything else
(backgrounds, panels, borders, body text) flips between a light and dark neutral scale.
The sidebar is the one exception that does *not* flip — see note above.

### Status badges (pill fill / text pairs — never used alone, always paired)

| Status | Light fill / text | Dark fill / text |
|---|---|---|
| OK / success | `#DCFCE7` / `#166534` | `#14532D` / `#86EFAC` |
| Warning | `#FEF9C3` / `#854D0E` | `#78350F` / `#FDE68A` |
| Error / flagged / quarantined | `#FEE2E2` / `#991B1B` | `#7F1D1D` / `#FCA5A5` |
| Info | `#DBEAFE` / `#1E40AF` | `#1E3A5F` / `#93C5FD` |

### Spectrum polarization — locked, do not override per-page, same in both modes

| Channel | Hex |
|---|---|
| **LCP** | `#1F77B4` (blue) |
| **RCP** | `#FF7F0E` (orange) |

Applies to every chart, legend swatch, and any UI element referencing LCP/RCP. This
matches the project's mandated convention — do not substitute a different blue/orange,
and don't theme it for dark mode; scientific color coding stays fixed.

### Fit-overlay convention

| Element | Light mode | Dark mode |
|---|---|---|
| Raw spectrum line | `#1F77B4`, solid, 1.6px | same |
| Fit overlay line | `#DC2626` (red), **dashed** (`4,3`), 1.6px | `#F87171` (lighter red so it doesn't disappear on the dark panel), dashed, 1.6px |

Dashing (not just color) is what distinguishes a fit line from data — keep this even in
color-blind-unfriendly contexts.

---

## 2. Typography

**Font family: Inter** (Regular / Semi Bold / Bold only — do not introduce Medium,
Light, or Extra Bold; keeps the type ramp to 3 weights). Sizes, weights, and roles are
identical between light and dark mode — only the color token changes (swap `text-*`
values per the mode table in §1).

| Role | Size | Weight | Color token |
|---|---|---|---|
| Page title (H1) | 24px | Bold | `text-heading` |
| Page subtitle | 13px | Regular | `text-muted` |
| Sidebar logo | 18px | Bold | White (both modes) |
| Sidebar nav item (active) | 12px | Semi Bold | White (both modes) |
| Sidebar nav item (inactive) | 12px | Regular | `sidebar-text-inactive` |
| Panel/section title | 10.5–11px | Semi Bold | `text-body` |
| Table header | 10px | Semi Bold | `#F1F5F9` (on HartRAO Dark Blue header bg, both modes) |
| Table cell | 10.5px | Regular | `text-body` |
| Button label | 12px | Semi Bold (primary/secondary) / Regular (ghost) | see §4 |
| Badge label | 10px | Semi Bold | per-status pair above |
| Caption / helper text | 9.5–10px | Regular | `text-muted` / `text-faint` |
| Dropdown label (eyebrow) | 10px | Semi Bold | `text-muted` |
| Progress bar label | 10px Semi Bold ("Stage X of 8") / 9px Regular ("N/8 complete") | `text-muted` / `text-faint` |

Rule of thumb: **Semi Bold marks anything interactive or a heading; Regular is for data
and body copy.** Don't reach for Bold below 18px.

---

## 3. Layout & Spacing

| Token | Value | Notes |
|---|---|---|
| Reference frame size | 1440 × 900 | Desktop mockup canvas — actual Streamlit width is fluid, treat this as the design reference only |
| Sidebar width | 220px | Fixed, persistent on every page, same width both modes |
| Content padding (left/right) | 24px | Gutter between sidebar and content, and content right edge |
| Header height | 64px | Space reserved for page title + subtitle + progress bar |
| Section gap | 16px | Vertical space between stacked content sections |
| Card / panel corner radius | 8px | Tables, chart panels, info boxes |
| Button corner radius | 6px | |
| Pill / segmented control radius | 16px (full) | |
| Badge radius | 9px (full) | |
| Table row height | 28px (32px header) | |
| Progress bar | 260px wide, 8px tall track, 4px radius | Top-right of header, doesn't reflow other header content |

---

## 4. Components

Every component below is identical in structure between light and dark mode — only the
color *tokens* swap (per §1), not the layout, radius, or type scale.

### Pipeline progress bar
- Sits top-right of the header band, same row as the page title, so it never pushes
  other content down.
- **Uses fixed colors, not theme tokens — identical in light and dark mode:**
  track `#E2E8F0`, fill `#587BBD` (HartRAO Light Blue), label text `#64748B`, caption
  text `#94A3B8`. Don't swap these for dark-mode equivalents even though every other
  component does — this one component deliberately doesn't re-theme.
- Track: 8px tall, 4px radius, 260px wide.
- Fill: same radius, width = `(completed stages / 8) × 260px`.
- Label above: `Stage {n} of 8`, 10px Semi Bold.
- Caption below: `{completed}/8 stages complete`, 9px Regular.
- "Completed" = stages strictly before the current page (the current page itself counts
  as in-progress, not complete).

### Buttons
- **Primary** — fill `accent`, no border, white text, Semi Bold. One per section max —
  this is the "do this next" action (e.g. *Load into Pipeline*).
- **Secondary** — `bg-panel` fill, `border-default` border, `text-body` text, Semi Bold.
  Use for parallel/equal-weight actions (e.g. the three Export buttons).
- **Ghost** — no fill, `text-faint`-colored border, `text-muted` text, Regular weight.
  Use for low-emphasis inline actions (e.g. *Load* on a session history row).
- Standard height: 32px (36px for the larger Export row). Padding: 12px horizontal.

### Dropdowns
- 10px Semi Bold `text-muted` eyebrow label above the control.
- Control: `bg-panel` fill, `border-default`, 36px tall, 6px radius, value text 12px
  Regular `text-body`, chevron icon right-aligned in `text-muted`, 8px from edge.

### Search input
- `bg-panel` fill, `border-default`, 32px tall, 6px radius, magnifier icon in
  `text-faint` at 10px inset, placeholder text 11px Regular `text-faint`.

### Pill / segmented control (mode & fit-type selectors)
- Inactive: `bg-panel` fill, `border-default` border, `text-body` text, Regular.
- Active: `accent` fill, no border, white text, Semi Bold.
- 32px tall, full (16px) corner radius, 8px gap between pills.

### Tables
- Header row: HartRAO Dark Blue (`#395790`) fill in **both modes**, 32px tall, top
  corners rounded to match container (8px), text `#F1F5F9` 10px Semi Bold.
- Body rows: 28px tall, alternating `bg-panel` / `bg-panel-alt` stripe, text 10.5px
  Regular `text-body`.
- Outer container: `bg-panel` fill, `border-subtle`, 8px radius.
- Cell padding: 10px left.

### Status badges
- Pill, 18px tall, 9px radius, 10px horizontal padding, 10px Semi Bold text. Always use
  a fill/text pair from §1 for the current mode — never a bare colored dot for status
  that also needs a label.

### Chart panels
- `bg-panel` fill, `border-default`, 8px radius.
- Title: 10.5px Semi Bold `text-body`, 12px inset from top-left.
- Plot area: `border-subtle` axis lines only (no gridlines) — keep it clean, this is a
  scientific tool, not a marketing dashboard.
- Legend: swatch (10×10px, 2px radius) + 9px Regular `text-muted` label, bottom-left of
  panel, only when the panel has more than one series or the series isn't self-evident.
- LCP/RCP colors are fixed regardless of mode (see §1) — don't theme chart data colors.

### Sidebar
- Fixed 220px, `bg-sidebar` fill, full page height. **Uses its own dedicated color per
  mode (`#395790` light / `#16233D` dark) — it does not swap with the page background.**
- Logo top: "HARTSPEC", 18px Bold white, 24px inset, white in both modes.
- Nav items: 8 entries, numbered `01`–`08`, 40px row spacing, active item gets an
  `accent`-filled 6px-radius highlight pill behind it, active text always white.
  Inactive text uses `sidebar-text-inactive` (tuned per mode for contrast against that
  mode's sidebar color — don't reuse the general `text-faint` token here).
- Session controls (**Save / Load / Reset Session**) pinned near the bottom, always
  visible regardless of page — these are global actions, not page-scoped.

---

## 5. Streamlit / Dash implementation notes

These tokens need to become real config, not just visual reference.

**Light/dark theme switching** — Streamlit's native theme config
(`.streamlit/config.toml`) is static per server instance; it can't hot-swap based on a
user toggle without a page reload. If an in-app light/dark toggle (not just an OS-level
preference) is a real requirement, that needs a runtime approach: drive both palettes
from one Python dict (mirroring the token tables in §1) and inject the active one via
`st.markdown(<style>...</style>)` on every page, keyed off `st.session_state`. Raise this
with the team before building it — it's more plumbing than the mockups suggest, and
should live in `utils/styles.py` as the single source of truth for both palettes so no
one hardcodes a hex in a page file.

**`.streamlit/config.toml` theme block** (light mode, approximate — tune against the mockups):
```toml
[theme]
primaryColor = "#587BBD"
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
default qualitative palette, and don't vary these by theme:
```python
fig.add_scatter(y=lcp_data, line=dict(color="#1F77B4"), name="LCP")
fig.add_scatter(y=rcp_data, line=dict(color="#FF7F0E"), name="RCP")
```
For fit overlays: `line=dict(color="#DC2626", dash="dash")` in light mode,
`line=dict(color="#F87171", dash="dash")` in dark mode. Plotly chart *backgrounds*
(`paper_bgcolor`/`plot_bgcolor`) do need to follow the active theme's `bg-panel` token or
charts will show a white box inside a dark page.

**Pipeline progress** — the "N of 8 completed" state needs a real source of truth, not
just a mock. Simplest option: derive it from which stage keys already exist in the
current session JSON (§ FR-19/20 session schema) rather than tracking a separate
"progress" variable that can drift out of sync.

**Sidebar session controls** — since Save/Load/Reset must persist across every page,
implement once in a shared `utils/sidebar.py` helper called from every page module,
rather than each of the 5 programmers rebuilding it per-page. This is also where nav
highlighting (active page) and the progress bar should live centrally.

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

- Mobile/tablet breakpoints — not needed, intranet desktop tool only.
- Exact Plotly axis/gridline styling — use the "axis lines only, no gridlines" rule from
  §4 but pixel values weren't mocked in detail; use judgment and flag in review if unsure.
- Loading/empty/error states beyond the File Loader progress bar — not yet mocked page by
  page; ask before inventing new visual language for these.