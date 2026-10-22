# Keyboard and accessibility help

Use this chapter as a reference while working in the eight-stage reduction interface.
The sidebar link opens this chapter in a separate tab, using the theme and font size
selected when you opened the link. Changes made later in the reduction tab do not
change this already-open help tab.

## Moving around

Press **Tab** to move forward through links and controls, and **Shift + Tab** to move
backward. A single outline shows the focused control. The **Skip to page content**
link becomes visible when focused; press **Enter** to jump past the sidebar.

Use **Enter** on a link or button and **Space** on a checkbox. For radio groups,
use the **arrow keys** to move between options. Open a dropdown with the keyboard,
use the arrow keys to choose an option, and press **Enter** to accept it.
**Escape** closes an open dropdown. Where a dropdown supports searching, type a
few letters to find an option. The normal text caret is retained for this search.

The sidebar's collapse button hides the navigation panel; the reopen button brings
it back. Both remain keyboard controls. Page navigation does not require a mouse.

## Theme and text size

In the reduction sidebar, choose **Light** or **Dark**. Under **Font size (%)**,
choose **100**, **125**, **150**, **175**, or **200**. The setting enlarges interface
text and chart labels. Browser zoom is a separate setting and can also enlarge the
page; the browser's own menu lists its zoom shortcuts.

Appearance preferences follow page navigation. Manual load/reset actions retain
your current appearance preferences; automatic checkpoint recovery restores the
saved display preferences. Enlarged controls and text can make pages longer, so
scroll to reach controls farther down the page.

## Reading and adjusting charts

Turn on **Keyboard chart controls and values** next to the chart you need.
**Visible chart series** selects the traces to display. Enter the start and end
limits under the chart's view controls and activate **Apply chart view** to change
the displayed range. **Reset chart view** removes that range override.

Turn on **Inspect chart values without hovering**, select a series, and enter a
sample number, starting at **1**, to read an exact stored value. For a grid-like
trace, choose a column number as well. This is an alternative to mouse hover.

These controls change the view, not the underlying spectrum, baseline regions,
fitted parameters or scientific export data. To change a fit or a baseline region,
use the corresponding pipeline controls instead.

## Reading tables

At **100%**, tables retain the native grid with an optional **Accessible table
view**. Above **100%**, the scalable read-only table is shown automatically.
Use **Table page** to reach later rows; a page shows up to **50 rows**.
Focus the table's scrollable region to scroll horizontally when columns do not fit.

**Download this table as CSV** contains the displayed table dataset, including its
other pages. It is not a download of the raw FITS archive. A read-only table does
not replace a page's separate editing controls.

**Page 08 exception:** observation events and committed parameters use the blue-header
read-only table at every font size. Focus it to scroll; **Table page** appears when
there are more than 50 filtered rows. **Interactive table tools** reveals the
native grid for sorting, column resizing and copying. The observation-log TXT
download still includes all recorded events and the current parameter summary,
regardless of the current search, order or page.

## Baseline Block Editor

Move into the embedded editor using **Tab**. For a new line-free region, enter
**Start velocity (km/s)** and **End velocity (km/s)**, then activate **Add flat
region**. The start must be less than the end and the region must pass the existing
spectrum-boundary and region validation.

To change an existing region, select it under **Region to edit**, change the
numeric limits, and activate **Update selected**. To remove it, select the region
and activate **Delete selected**. Invalid edits show a message and should leave
previous valid regions intact.

Use the editor's view controls and sample inspector to examine the spectrum without
dragging. Choose automatic or manual polynomial order selection and activate
**Fit Polynomial** when ready. The comparison score table provides a text-based
way to inspect polynomial results. Continue with **Tab** past the final editor
control to return to the surrounding page; use **Shift + Tab** to move backward.

## Spectral fitting messages

The fit selector affects **Graph 3**; **Graph 4** shows its fit overlay.
**Graph 1 — LCP** and **Graph 2 — RCP** show the input channels, not the chosen fit.

In the current implementation, the option labelled **2D Gaussian** fits two
Gaussian components on a **one-dimensional velocity spectrum**. It is not the
full spatial-image/heatmap fit. **Multi-component** currently fits a fixed
three-component model, not the full editable, iterative decomposition.
A warning that a single Gaussian is being shown means the requested model failed
and a fallback was used; it is not confirmation of a successful requested fit.

## Reporting a problem

Record the page, theme, font size, focused control, keyboard action and visible
message. Include a screenshot where useful. Do not share private checkpoint URLs
or observation data in a public issue. Report missing text, a lost focus indicator,
or a control that cannot be reached or exited using the keyboard.
