# The viewer, second layout

This file records how the viewer layout was designed. It starts with a hand sketch of
2026-09-18, followed by dated decisions made during building and testing. Later sections
supersede earlier ones. The current viewer is described in the [README](../README.md#the-viewer).

## The sketch

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

The layout has three columns above one full-width strip. The image is in the centre and gets
the most space. The unit list on the left is for navigation, the instruments on the right are
the working panel. The traces span the full width because time runs horizontally; 3000 frames
in 300 px were unreadable.

## Panels

**units.** One row per MUnit: name, frames, fs, first words of the comment. The list scrolls.
A click selects the unit, and image, metadata and traces follow. The selected unit stays marked,
not only highlighted on hover.

**metadata.** The panel shows the unit on screen, not the file. It lists fs, frame size, pixel
size, duration, comment, stage position (VirtX/VirtY/VirtZ) and the `check` findings for this
unit. The arrow in the sketch marks this link: the panel is context for the image.

**image.** The frames of the unit. Below the image is one thin strip with play/pause, the frame
slider with frame number, and the channel choice. No other controls are placed there.

*Averaged frames.* Instead of a single frame, the running mean of N frames centred on the slider
position is shown. N is set in the instruments; N = 1 is the raw frame. Averaging makes dim
boutons visible while scrubbing.

*Zoom by selection.* Dragging a rectangle on the image zooms to it. Double-click or ⤢ returns to
the full frame; the wheel zooms around the cursor, and dragging pans when zoomed. ROIs are drawn
in image coordinates, so they keep their position at any zoom.

*Contrast.* Contrast settings are in the instruments, folded by default. The default is a
**fixed** window in reader units, taken from the LUT of the file and editable per unit and
channel. The alternative is **auto %**: lo/hi percentiles of the whole unit, one window for all
frames. A palette per channel and an **overlay** of all channels are next to it. These settings
are made once per file, not repeatedly.

**instruments**

```
[+]  add an ROI (spot or polygon, the current tool; a second click on [+] toggles which)
[−]  remove the selected ROI
[AVG]  the frame-averaging window N (a small stepper: 1 · 4 · 8 · 16 · 32)
[mean] show the mean image of the whole unit instead of frames (toggle)
```

AVG and mean are separate functions with separate labels. AVG sets how many frames the slider
shows at once. Mean collapses the whole recording into one image.

**rois.** A scrolling list with a filter box above it; the filter matters at 200 ROIs. Each row
shows name, kind and size in px. A click selects the ROI: its outline brightens and its trace is
highlighted. A checkbox sets whether the ROI is drawn in the trace strip. Below the list are
`traces` (compute for the unit and channel) and the exports csv · imagej · json.

**traces.** The strip spans the full width and has two modes. In **stack**, each selected ROI is
drawn on its own line with an offset, and the strip scrolls when the lines do not fit. In
**overlay**, all ROIs share one axis with one colour each, for comparing shapes. The mode is
kept between sessions.

*Zoom in time.* Dragging a span on the time axis zooms in; the wheel zooms around the cursor;
⤢ resets. While zoomed, the range of the frame slider follows the zoom, so scrubbing stays
within the visible window.

*Grid.* Time ticks are labelled in seconds, since fs is known, with a faint line per tick.
Y ticks are in reader units. The cursor line in the traces and the frame slider show the same
frame, and moving one moves the other.

*Frame marker.* A vertical line marks the slider frame in every trace.

## Saving the session

The session is saved without a save button. On every change (debounced), the view is written
to `~/mesc-viewer/`, never next to the raw file. The view comprises unit, channel, frame, AVG
window, contrast, zoom rectangle, trace mode, trace zoom, selected ROI and the drawn ROIs. The
ROI set is stored in the same folder (`PUT /api/rois`). Reopening a file restores the view.

## Calm

The viewer keeps the existing dark theme. Calm comes from how few controls are visible, not from
colour. Contrast and zoom controls are folded, and exports sit under the list they belong to.
The only controls always visible are the four instrument buttons, the trace mode and the player
strip.

## Decided while building (2026-09-18)

* The filter box filters by name. The row shows the kind (spot · poly) and the number of points,
  which is enough to identify an ROI.
* In stack mode each trace has the same height (64 px) and is scaled to its own range within
  the visible time window. Zooming in time thus rescales each band, and a weak bouton next to a
  strong one stays readable. The range is printed under the name.
* The unit list shows a thumbnail of the mean image of each unit (`/api/thumb`, ≤ 96 px). One
  small PNG per unit is loaded at start. Thumbnails make the right area easy to find among 27
  units.
* Keys: Enter computes the traces; space plays; ← → move the time window when zoomed (shift:
  half a window) and step one frame otherwise (shift: ten); ↑ ↓ move through the ROI list;
  Delete removes the selected ROI; Esc drops a polygon draft. A click in the trace strip moves
  the frame there, and a double-click resets the time zoom.
* An ROI is renamed by double-clicking its name. The name is a label, not an input field, so a
  single click selects the row and Delete deletes the ROI.
* The heights of the trace strip and of the metadata panel are set by dragging their top edges.
  Both heights are remembered; 30 units need a longer list than the default.

## First use (2026-09-18, synthetic file)

* The AVG window is typed as a number (`AVG [ 13 ]`). The stepper from the sketch was dropped.
* ROIs can be dragged to a new position, and polygon corners can be dragged individually.
  Pressing on an ROI and dragging moves it; pressing on empty image and dragging draws the zoom
  box. The object under the cursor decides, so no mode switch is needed.
* The trace strip shows a rubber band while dragging. In stack mode the box zooms time. In
  overlay mode it zooms time and value, since the y axis is shared there.
* A click now waits 230 ms before acting. A double-click is preceded by two clicks and used to
  leave two spots. A second click or a double-click within 230 ms cancels the pending click, so
  each gesture has one effect.

## Tested on a real file (260916, 11.5 GB, 30 units; 2026-09-18)

* The server is threaded. Chrome requested 30 thumbnails over six connections, and the
  single-threaded server, with a backlog of five, refused the rest; the page stayed blank. Each
  request opens its own file handle, so no locking is needed for reading. Thumbnails use 40
  frames instead of 300, which makes no visible difference at 96 px. Measured: 30 thumbnails in
  4 s, traces over 4953 frames in 4 s.
* Axis limits adapt to the 1st–99th percentile of the visible data, with padding, in both modes.
  With min/max, a single outlier frame flattened all traces. In overlay mode a box also sets the
  value range, but any change of the time window (arrows, wheel, new box) returns the y limits to
  the data.
* Vertical limits can be typed: `y [lo] – [hi] [auto]` in the trace bar. Typed limits apply to
  every band in stack mode and to the overlay. They persist through time zooms and mode switches
  until `auto` is chosen. On auto, the boxes show the active limits greyed (in stack mode: those
  of the selected band). An inverted range is rejected with a message in the badge.
* The read-modify-write of the ROI store runs under a lock. With a threaded server, two quick
  saves could otherwise overwrite each other.
* Hover readouts show `x · y · value (3×3 mean)` in reader units, for the frame window on screen
  or for the mean image. The values come from the server (debounced), because the page holds
  only a PNG. On the traces, the readout shows the ROI under the cursor (the band in stack mode,
  the nearest trace in overlay mode) with its frame, time and value.

## raw | dF/F by the analysis pipeline's method (2026-09-18)

The trace bar has a `raw | dF/F` switch with two parameters: the baseline quantile **q** (0.3,
as in our sessions) and the baseline window (60 s). The computation reproduces, step by step
and in numpy only (`src/mesc_io/dff.py`), the signal stage of the calcium-imaging pipeline this
viewer was written alongside:

1. dark current from the first frames of the darkest patch;
2. Savitzky–Golay filter, window 5, order 3;
3. background: trace of the darkest 10×10 patch, smoothed and fitted with a degree-5 polynomial;
4. F0: rolling quantile, then Gaussian smoothing;
5. dF/F = (F − F0)/max(F0, eps).

Each step matches the corresponding pipeline function on the same trace to 1e-9
(`tests/test_dff.py`; the test is skipped, with a message, where the pipeline cannot be
imported). Both signals are computed in one pass, so switching is instant; changing a parameter
refetches. The darkest patch is drawn on the image (`bg`), and the values used (dark, patch,
eps, head) are shown in the bar.

The result is not identical to the pipeline's value for the same bouton. The ROI is the one
drawn in the viewer (a 3-px disc, not a Suite2p mask). The leading trim is not applied, so that
frames stay aligned with the movie; the dark head is greyed instead. The method is the same; the
ROI differs.

Typed vertical limits are stored per signal. Raw and dF/F have different scales, so switching
neither discards the typed limits nor applies raw limits to dF/F. Each signal returns with its
own limits.

## Three ROI kinds with editable size (2026-09-18)

The ROI kinds are `spot · rect · polygon`. A spot is defined by centre and radius, a rect by
centre and w × h. Both regenerate their points from these numbers, so size is typed, not
redrawn. The size row under the tools edits the **selected** spot or rect («size of roi3»);
with nothing selected, it sets the size of the next ROI («for new ROIs»). Dragging moves the
centre, and the points follow. The server and the ImageJ export receive points only. ROIs from
older files are classified by shape: disc, axis-aligned rectangle, otherwise polygon.

## ROIs belong to a unit (2026-09-18)

ROIs are stored per unit. The field differs between areas and between repeats, so an ROI set
drawn on MUnit_3 does not apply to MUnit_7. The store is keyed by unit path
(`{"units": {"MSession_0/MUnit_3": [...]}}`). The list, the traces, the ImageJ export and
"clear all" refer to the unit on screen, whose name is in the header. A **copy from…** menu
appears when another unit has ROIs, for the case of a truly identical field. Files in the old
flat format are assigned to the first unit and rewritten, with a log line asking to check them.

## Two channels in 3D (2026-10-27)

With **overlay** on (the same button as in 2D), a two-channel stack is sent to the GPU as one
RG8 texture: channel 0 in r, channel 1 in g. The shader draws them additively in green and
magenta, so voxels bright in both channels appear white. The file colours (green and red on our
rig) are not used here, because their sum is yellow and hard to distinguish from green. A
palette chosen for a channel in the instruments still takes precedence.

* **Separate windows.** The red channel is often ten times brighter than the green, and one
  shared window would leave the green black. Each channel is therefore fetched through its own
  window (typed fixed limits or percentiles of that channel) and has its own floor in the 3D
  bar, set from its histogram on opening. Ceiling and cut/clip remain shared as a fraction of
  each window. The cut works on the bytes of each channel, so a red blob does not remove the
  green around it.
* **One grid.** `?share=2` halves the server's voxel budget per channel. The block-averaging
  factor depends only on unit size and share, so both channels return on the same voxel grid.
  The pair costs the GPU as much as one channel did before. The page rejects a pair that does
  not align.
* **Modes.** In MIP, the brightest value of each channel along the ray is coloured and added. In
  Glass, both channels add light and occlude what is behind; voxel colour is the mix of the two
  colours, weighted by the opacity of each channel. Depth mode uses one channel, since the hue
  already encodes depth; the info line names the channel.
* **XYZ** shows the same two colours (bytes as sent, no floor, as in the grey views). A switch per
  channel hides it in 3D and XYZ.
* With overlay off, or for a one-channel unit, the old path is unchanged: same request, same R8
  texture, same shader branch. The browser test compares the image before and after the overlay
  change.

## Speed on an old laptop (2026-10-27)

Performance was measured with Chrome's CPU throttled 6×, roughly the five-year-old Mac of the
first user. The rule for all changes: the image stays the same, only what is redrawn and when
changes.

* **Two layers in the trace strip.** The canvas holds traces, grid and labels. It is redrawn only
  when one of its inputs changes (payload, time or value window, mode, signal, size, grid,
  selection, shown set), tracked as one key. The frame cursor is a 1-px element under the
  transparent canvas, so it stays beneath the traces. Playing and scrubbing move only the
  cursor.
* **M4 above one frame per pixel.** Each pixel column draws its first, lowest, highest and last
  frame in time order, and joins its neighbours with the same segment as before. At one frame
  per pixel or less, every frame is drawn. The only visible difference: the old dense line had
  more miter spikes past peaks than the new one.
* **Cached limits.** Limits are cached per payload, signal, time window and trace. Overlay limits
  are keyed by payload identity, not by unit and channel, so a refetch with another q gives new
  values.
* **One frame request in flight.** A slider step during a pending frame request only marks that
  a new frame is wanted. When the pending frame arrives, the page requests the current slider
  position.
* **One resize path** serves the stage, the trace strip and the splitters. 3D renders at low
  resolution while resizing.
* **Colour lookup tables.** Frame palettes and XYZ colours are packed RGBA words written through
  a Uint32 view; two channels index a 64 k table of all grey pairs. The tables use the same
  arithmetic as the per-pixel loops they replace, and `tests/view_fastpaths_real_chrome.js`
  checks them against those loops byte for byte. A pane is recomputed only when its own slice
  changes.
* **Yielding blob cut.** The cut runs the same steps, paused every ~10 ms, while the previous image
  stays on screen. Only the first texture of a stack (a view restored with the cut on) still
  waits for it.
* **3D at rest** renders at ≤ 1.5 device px per CSS px and ~1.5 MP, never below one device px per
  CSS px. A MIP ray stops at the ceiling, since nothing beyond it can be brighter.
