# The viewer, second layout

Sketched by hand on 2026-09-18, then worked out. This is the shape; the page is built from it,
not the other way round. Anything marked **?** is still open.

## The picture

```
┌──────────────┬──────────────────────────────────────────┬──────────────────────┐
│ units        │                                          │ instruments          │
│  MUnit_0     │                                          │  [+] [−] [AVG] [mean]│
│  MUnit_1  ◀──│──── the image ─────────────────────────  │                      │
│  MUnit_2     │     (the thing this tool is about)       │ rois                 │
│  …  (scrolls)│                                          │  [ filter…        ]  │
│──────────────│                                          │  ROI 1               │
│ metadata     │                                          │  ROI 2               │
│  of the unit │  ▸ ▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮ frame 812/3010 │  ROI 3   (scrolls)  │
│  on screen   │  ch 0 · ch 1                             │                      │
├──────────────┴──────────────────────────────────────────┴──────────────────────┤
│ traces                                            [stack | overlay]  [grid] [⤢]│
│  ROI 1 ───╮╭──╮────────╭╮──────────                                            │
│  ROI 2 ────╯╰──╯────────╯╰──────────           (scrolls when stacked)          │
│  ──────────────────────────────────────────── time ──────────────────────────▸ │
└────────────────────────────────────────────────────────────────────────────────┘
```

Three columns over one full-width strip. The image is the centre and gets the most room; the
unit list is navigation; the instruments are the working panel; the traces get the whole
width because time is horizontal and 3000 frames in 300 px was unreadable.

## Panels

**units** — one row per MUnit: name, frames, fs, the comment's first words. Scrolls. Click
selects; the image, metadata and traces follow. The selected unit is marked, not merely
highlighted on hover.

**metadata** — *of the unit on screen*, not of the file. fs, frame size, pixel size, duration,
comment, stage position (VirtX/VirtY/VirtZ), and the check findings that concern this unit.
The arrow in the sketch means exactly this: the panel is context for the picture.

**image** — the unit's frames. Under it, one thin strip: play/pause, the frame slider with the
frame number, the channel choice. No other control lives here.

*Averaged frames.* A window of N frames is shown instead of the single frame — the running
mean centred on the slider position. N is set in instruments; N=1 is the raw frame. This is
what makes a dim bouton visible while scrubbing.

*Zoom by selection.* Drag a rectangle on the image → the view zooms to it, as the report does.
Double-click or a small ⤢ returns to the whole frame. Wheel zooms around the cursor, drag pans
when zoomed. ROIs are drawn in image coordinates so they stay put under any zoom.

*Contrast* lives in instruments, folded away: by default a **fixed** window in reader units, from the file's own LUT and editable per unit and channel; **auto %** (lo/hi percentiles of each frame) is the alternative; a palette per channel and an **overlay** of all channels sit beside it — set once per file, not once
a minute.

**instruments**

```
[+]  add an ROI (spot or polygon — the current tool; a second click on [+] toggles which)
[−]  remove the selected ROI
[AVG]  the frame-averaging window N — a small stepper, 1 · 4 · 8 · 16 · 32
[mean] show the mean image of the whole unit instead of frames (toggle)
```

AVG and mean are different things and are labelled so: AVG is *how many frames the slider
shows at once*, mean is *the whole recording collapsed into one picture*.

**rois** — a list that scrolls, with a filter box above it (matters at 200 ROIs, harmless at 8).
Each row: name, kind, size in px. Click selects (image outline brightens, trace highlights);
checkbox chooses whether it is drawn in the trace strip. Under the list: `traces` (compute for
the unit/channel), and the exports — csv · imagej · json.

**traces** — full width.

*Two modes, a toggle:* **stack** — every chosen ROI on its own line with an offset, the strip
scrolls vertically when there are more than fit; **overlay** — all on one axis, one colour per
ROI, for comparing shapes. The mode persists.

*Zoom in time* by dragging a span on the time axis; wheel zooms around the cursor; ⤢ resets.
When zoomed, the frame slider's range follows the zoom so scrubbing stays inside what you are
looking at.

*A real grid*: labelled time ticks (seconds, not frames — fs is known), a faint line per
tick, y-ticks in reader units. The cursor line in the trace strip and the frame slider are the
same number: move one, the other moves.

*The frame marker*: a vertical line at the slider's frame, in every trace.

## Session, saved by itself

Like pupil-monitor: no button. `<file>.mesc-io.json` beside the .mesc, written on every change
(debounced): unit, channel, frame, AVG window, contrast, zoom rectangle, trace mode, trace
zoom, selected ROI, which ROIs are drawn. The ROI set stays where it is (`PUT /api/rois`, the
same file as now). Reopening the file restores the view.

## Calm

Dark theme as it is now. What makes it calm is not colour but how little is on screen at once:
contrast and zoom controls are folded, exports sit under the list they belong to, and the only
always-visible controls are the four instrument buttons, the trace mode, and the player strip.

## Decided while building (2026-09-18)

* The filter box filters by name. The row shows the kind (spot · poly) and the point count
  beside it, which is what the eye was going to use anyway.
* Stack mode: every trace gets the same vertical room (64 px) and is scaled to its own range
  **within the visible time window** — so zooming in time re-scales each band to what is on
  screen, and a weak bouton beside a strong one stays readable. The range is printed under
  the name so nothing about the size is hidden.
* The unit list carries a thumbnail of each unit's mean image (`/api/thumb`, ≤ 96 px). One
  small PNG per unit at load; it is how you find the right area among 27 units.
* Keys: Enter computes the traces; space plays; ← → slide the time window when zoomed in (shift: half a window) and step
  a frame otherwise (shift: ten); ↑ ↓ walk the ROI list; Delete removes the selected ROI; Esc
  drops a polygon draft. Clicking in the trace strip moves the frame there; double-click goes
  home. An ROI's name is renamed by double-clicking it — it is a label, not an input, so a
  click on the row selects and Delete deletes.
* The trace strip's height is dragged from its top edge and remembered; so is the metadata
  panel's, from its top edge (30 units want a longer list than the default).

## First use (2026-09-18, on the synthetic file)

* The AVG window is **typed as a number**, not stepped through a ladder — `AVG [ 13 ]`.
* An ROI can be **dragged** to correct its place; a polygon's corner can be dragged on its
  own. Pressing on an ROI and dragging moves it; pressing on empty image and dragging is the
  zoom box. Told apart by what is under the cursor at the press, so no mode switch.
* The trace strip shows a **rubber band** while dragging. In stack mode the box zooms time;
  in overlay it zooms time and value both, because there the y axis is shared.
* A double-click used to leave two spots behind (it is preceded by two clicks). A click now
  waits 230 ms; a second click or a double-click within that cancels it. One gesture, one
  meaning.

## On the real file (260916, 11.5 GB, 30 units — 2026-09-18)

* The server is **threaded** now. Thirty thumbnails at once, six connections from Chrome,
  and a single-threaded server with its five-deep backlog refused the rest: the page sat
  blank while the process was busy. Each request opens its own file handle, so there was
  nothing to protect. Thumbnails use 40 frames, not 300 — at 96 px nobody can tell.
  Measured: 30 thumbnails in 4 s, traces over 4953 frames in 4 s.
* **Axis limits adapt**: the 1st–99th percentile of what is on screen, padded,
  in both modes — min/max let one odd frame flatten everything. In overlay a box sets the
  value range too, but any change of the time window (arrows, wheel, a new box) lets the
  y limits follow the data again.

* **Typed vertical limits**: `y [lo] – [hi] [auto]` in the trace bar. Typed limits
  apply to every band in stack and to the overlay, survive time zooms and mode switches, and
  are released by `auto`. When on auto the boxes show, greyed, the limits in force (in stack:
  of the selected band). An inverted range is refused with a word in the badge.
* The ROI store's read-modify-write is under a lock now — the server is threaded, and two
  quick saves used to be able to write over each other.

* **Hover readouts**: on the image, `x · y · value (3×3 mean)` in reader units,
  of the frame window on screen or of the mean — fetched from the server, debounced, since
  the page only holds a PNG. On the traces, the ROI under the cursor (the band in stack, the
  nearest in overlay), its frame, its second, its value.

## raw | dF/F by the pipeline's method (2026-09-18)

`raw | dF/F` in the trace bar, with the two knobs that matter beside it: the baseline's
quantile **q** (0.3, what the sessions use) and its window (60 s). The chain is the signal
stage's, step for step, in numpy alone — `src/mesc_io/dff.py`: dark current off the darkest
patch's first frames, Savitzky–Golay 5/3, the darkest 10×10 patch's trace smoothed and
polynomial-fitted (degree 5) as the background, rolling quantile + Gaussian smooth as F0,
(F − F0)/max(F0, eps). **Each piece is held against the pipeline's own function on the same
trace to 1e-9** (`tests/test_dff.py`; skipped, visibly, where the pipeline is not importable).
Both signals come from one pass; the switch is instant, the knobs refetch. The darkest patch
is drawn on the image (`bg`), the numbers used sit in the bar (dark, patch, eps, head).

What it is not: the master's number. The ROI is what was drawn here (a 3-px disc, not a
Suite2p mask) and the leading trim is not applied (the frames stay aligned with the movie;
the black head is greyed instead). Same method, this ROI.

Typed vertical limits are kept **per signal**: raw and dF/F live on different scales, so a
switch neither throws yours away nor applies raw's numbers to dF/F — each signal comes back
with the limits it had.

## Three kinds of ROI, and a size you can change (2026-09-18)

`spot · rect · polygon`. A spot is a centre and a radius, a rect a centre and w × h; both
regenerate their points from those numbers, so a size is a number you type, not a shape you
redraw. The size row under the tools edits the **selected** spot or rect when there is one
(«size of roi3»), and otherwise sets what the next click will place («for new ROIs»).
Dragging moves the centre; the points follow. The server and the ImageJ export only ever see
points. An ROI from an older file is recognised as a disc or an axis-aligned rectangle by its
shape, and as a polygon otherwise.

## ROIs belong to a unit (2026-09-18)

It bit the same afternoon: the field moves between areas and between repeats, and a set
drawn on MUnit_3 says nothing about MUnit_7. The store is keyed by unit path
(`{"units": {"MSession_0/MUnit_3": [...]}}`); the list, the traces, the ImageJ export and
"clear all" are all of the unit on screen, whose name sits in the header. A **copy from…**
menu appears when another unit has ROIs, for the case where the field really is the same.
A file in the old flat shape is carried onto the first unit and rewritten, with a line in the
log saying to check it.

## Two channels in 3D (2026-10-27)

With **overlay** on (the same button
as in 2D), a two-channel stack goes to the GPU as one RG8 texture — channel 0 in r, channel 1 in
g — and the shader draws them green and magenta, added: where both are bright the voxel is white.
The file's own colours (green and red, on our rig) are not used here: their sum is yellow, which
is hard to tell from green. A palette picked for a channel in instruments still wins.

* **A window each.** The red channel is often ten times brighter than the green; one window
  would leave the green black. Each channel is fetched on its own through its own window — the
  fixed limits typed for it, or percentiles of that channel alone — and has its own floor in the
  3D bar, set from its own histogram when it opens. The ceiling and cut/clip stay shared (a
  fraction of each window), and the cut works on each channel's bytes, so a red blob does not
  take the green around it.
* **One grid.** `?share=2` halves the server's voxel budget for each channel; the block-averaging
  factor depends only on the unit's size and the share, so both come back voxel for voxel, and
  the pair costs the GPU what one channel did. The page refuses a pair that does not line up.
* **Modes.** MIP: each channel's brightest along the ray, coloured, added. Glass: both add light
  and hide what is behind; a voxel's colour is the two colours weighted by how solid each channel
  is there. Depth stays one channel — the hue already says how deep, a second colour on top of it
  would say nothing — and the info line says which.
* **XYZ** shows the same two colours (each channel's bytes as sent, no floor, as the grey views).
  A switch per channel hides it in 3D and XYZ.
* Overlay off, or a one-channel unit, is the old path untouched: same request, same R8 texture,
  same shader branch. The browser check compares the picture before and after the overlay.

## Speed on an old laptop (2026-10-27)

Measured with Chrome's CPU slowed 6×, which is roughly the first user's five-year-old Mac. The
rule throughout: the picture does not change; only what is redrawn, and when.

* **The trace strip is two layers.** The canvas holds the traces, grid and labels and is redrawn
  only when one of the things it shows changes (payload, time or value window, mode, signal,
  size, grid, selection, shown set — one key). The frame cursor is a 1-px element under the
  canvas, whose background is clear, so it still sits beneath the traces. Playing and
  scrubbing move it and nothing else.
* **Past one frame per pixel, M4.** Each pixel column draws its first, lowest, highest and last
  frame, in time order. The column spans what it spanned and joins its neighbours by the same
  segment; at one frame per pixel or fewer every frame is drawn. The old dense line also grew
  miter points past its peaks, which the new one has fewer of — the one visible difference,
  and in the right direction.
* **Limits are cached** per payload, signal, time window and trace; the overlay's by the
  payload's identity, not its unit and channel, so a refetch with another q is new numbers.
* **One frame request in flight.** A slider step while a frame is on its way only marks that
  another is wanted; when it lands, the page asks for wherever the slider is then.
* **One resize path** for the stage, the trace strip and the splitters; 3D draws coarse while the
  size moves.
* **Colour through tables.** A frame's palette and the XYZ views' colours are packed RGBA words,
  written through a Uint32 view; two channels index a 64 k table of every grey pair. The tables
  are built with the same arithmetic as the per-pixel loops they replace, and
  `tests/view_fastpaths_real_chrome.js` holds them to those loops byte for byte. A pane is
  re-cut only when its own slice changes.
* **The blob cut yields.** The same steps, paused every ~10 ms; the old picture stays meanwhile.
  Only a stack's first texture (a view restored with the cut on) still waits for it.
* **3D at rest: ≤ 1.5 device px per CSS px and ~1.5 MP**, never below one per CSS px. A MIP ray
  stops at the ceiling, past which nothing can be brighter.
