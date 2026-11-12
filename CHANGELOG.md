# Changelog

## Unreleased

- Viewer: secondary controls moved into dropdown panels (`name ▾`), like the report's playground — one open at a
  time, a click outside or Esc closes it, and a panel with a mode switched on inside (box, measure, crop, a trace
  filter) lights its name. Traces: `baseline ▾`, `filter ▾`, `axis ▾`; 3D: `window ▾`, `view ▾`, `box ▾`,
  `measure ▾`; mosaic: `show ▾`, `crop ▾`, `export ▾`; instruments: `view ▾` (AVG, ↕ MESc, PNG). Every control keeps
  its id and behaviour.
- Viewer: the instruments in groups — a `roi` row (spot, rect, polygon, ruler, size, + −), an `image` row (mean,
  max, AVG, ↕ MESc, 3D / mosaic / XYZ, `view ▾`), contrast on one compact row; `ROIs ▾` (clear all, zip, json) by
  the ROI list and `export ▾` (csv, png) by `traces ⏎`. `view ▾` adds the report's on-screen brightness, contrast and
  gamma (gamma < 1 lifts the dim): a canvas filter on the frame only — ROIs, numbers and data exports untouched.
- Viewer: display filters for the traces — Gaussian (σ in frames, with the ms it equals) and Savitzky–Golay (window,
  order; mirrored at the ends, the same numbers as `scipy.signal.savgol_filter(mode="mirror")`). Only what is drawn:
  the axis limits and the hover read the filtered line, the PNG says the filter in its caption, the csv and the zip
  stay unfiltered.
- Viewer: the units column resizes by dragging its edge, like the instruments and the traces. Default sizes: traces
  338 px, instruments 661 px (the grid still caps them on a small window).
- Viewer: the automatic y-limits of the traces no longer cut the peaks off. The top was the 99th percentile of
  the visible frames, and a calcium transient is exactly the top 1 % of a sparse trace — on a trace with a few
  short transients the window showed only the noise. The bottom stays on the 1st percentile (a black head or a
  dropped frame still does not flatten the rest); the top is now the true maximum. NaNs are dropped before the
  limits are taken. The margin each side is 3 % of the range (was 6 %).

## 0.6.3 — 2026-11-11

- `write_frames` (and `mesc-io write`) builds the copy as `<out>.partial` and renames it when every frame and tag
  is in. Written straight to `out`, an interrupted run left a file of that name that opened like any other: a whole
  copy, part of its frames replaced, not yet tagged. `out` naming the source itself is refused, as registration
  already did.
- `frame_times`: for a channel with no name, the curve taken by position must say it is a stamp curve
  (`Comment` containing `TIMESTAMP`), so a recorded I/O signal is never returned as frame times; when no curve
  carries a comment, position is used as before. A stamp curve with no Y conversion scale now gives `None` and a
  warning — its ticks used to come back as "seconds" with a scale of 1.
- The viewer answers only its own page on this machine: a request whose `Host` is not a loopback name, or whose
  `Origin` is not the viewer itself, gets 403. Listening on 127.0.0.1 kept other machines out but not other web
  pages in the same browser, which could start an export or copy ROIs, and through DNS rebinding read frames.
  Scripts and curl (no `Origin`) work as before; an `Engine` mounted in another server leaves the check to its host.

## 0.6.2 — 2026-11-09

- Acquisition parameters from `MeasurementParamsXML`, read from the file rather than from what was typed into the
  comment: `Unit.laser_pockels` (the Pockels cell's on-intensity), `Unit.pmt_reference_voltage` (`{"UG": 70.0, …}`),
  `Unit.objective`, and `Unit.acquisition` — every device param, every `Params` entry and every attribute of every
  stage axis, typed. On the recordings tested, the comment's numbers disagreed with the file on 34 of 413 units.
- `Unit.info` gains rows in this reader's own words after MESc's: *Stage position (absolute)* and *Stage position
  from the zero level* (the real stage x, y from `Virt*` / `Slow*`; MESc's "Centroid" x, y come from
  `GeomTransTransl`, which is 0 in these files), *Objective*, *Pockels cell (on-intensity)*, *PMT reference
  voltage*, *Acquired bits*.

## 0.6.1 — 2026-11-06

- `frame_times`: a channel with no `Channel_N_Name` took the first unnamed curve (an empty name matched an empty
  name), so channel 1 could get channel 0's stamps; unnamed channels now take their curve by position.
- `mesc-io rig-rois --out x.zip`: ROIs with the same label no longer collide in the zip (Fiji kept one); repeats get
  `_2`, `_3`, and names across several units carry the session (`MSession_0_MUnit_3_1`).
- A unit's `MeasurementParamsXML` is parsed once instead of four times: `units()` is back to 0.5.1 speed.
- Unused imports removed (`viewer`, `presets`); the `RigRoi` annotation in `reader` resolves.

## 0.6.0 — 2026-11-06

- ROIs drawn on the rig: `MescFile.rig_rois(unit)` decodes the ROI list MESc saves in `ViewerParamsXML` (base64
  Qt `QDataStream`, decoded from the public Qt format) into `RigRoi`s: label, colour, z planes, vertices in µm and
  in pixels (centre of the first pixel = 0), in drawing order. The ROI key is found directly, and an ROI with an
  unknown field is skipped by its stated length with a `RigRoiWarning`, so one odd record never hides the rest.
  `mesc-io rig-rois FILE [--unit U] [--out x.json|x.zip]` lists or exports them (ImageJ `.zip` for Fiji).
- Per-frame hardware stamps: `MescFile.frame_times(unit, channel)` returns the stamp closing each frame, in
  seconds (from the channel's `Curve_N`, found by name; the end-of-acquisition stamp dropped; None for z-stacks),
  and `frame_stalls` lists pauses (interval > 3× median). `check` notes them as `acquisition-pause`. On the
  recordings tested most units pause ≈0.6 s at frame 8, which a frame × period clock misses.
- 8-bit acquisition is flagged: `Unit.acquired_bits` (`Params/BitCompression`, 8 or 16) and `Unit.sample_shift`
  (the PMT's `compression_shift_<bits>bit`; 7 for 8-bit, so single-frame values are multiples of 128). `check`
  adds a note, `8-bit-acquisition`, listing such units. Values are read unchanged.
- The PMT A/D inversion flag is read: `Channel.ad_invert` comes from the detector's `ad_invert` in
  `MeasurementParamsXML` (matched by `channel_name`; None when the file does not say). A channel recorded with 0,
  the untested case, raises an `InvertWarning` on reads in reader units (the stored integers stay silent and exact),
  and `check` reports it as `pmt-not-inverted`. The XML parse is one helper now, shared with the stage position.
- Reader units now apply each channel's conversion limits the way MESc does: the raw integers are clamped to
  `Channel_N_Conversion_LowerLimit…`/`UpperLimit…` (the Uint16 pair, else the Double pair) before scale + offset.
  `Channel.limits` carries them; `clamp_raw` is exported for code that averages the integers before converting
  (the viewer's mean/max images, its z-stack volumes and object growth now clamp first, since the mean of clamped
  values is not the clamped mean). Limits covering the whole stored range (0–65535, every file seen so far) change
  nothing and add no pass over the data: values are bitwise the same as 0.5.1 on such files.
- README: the PMT inversion is the recording's `ad_invert` setting (tested with 1), not a property of the stored
  data; the 0.5.1 wording was wrong. The
  README describes the tool on its own terms: the dF/F method and the registration defaults are stated directly.

## 0.5.1 — 2026-11-06

- **Related tools** in the README: what roiextractors/NeuroConv, Suite2p, FIMAS and FemtoAPI already do
  with `.mesc`, and what mesc-io adds. **Not handled yet**, said plainly: PMT data stored inverted (the MESc
  3.5.7 invert flag) is not detected, and MES 7 `.mes` files are not read.
- **README says only what is true.** The registration defaults are named (Suite2p non-rigid,
  64-px blocks, `maxregshift` 0.1, non-rigid cap 3 px) as the settings of our lab's private
  pipeline; the dF/F comparison tests are said to run only where that pipeline is installed and to
  be skipped in CI; the viewer's mosaic TIFF and ImageJ ROI export are said to need `[tiff]` and
  `[imagej]`; the window is private only when Chrome, Firefox or Edge (or Brave, Chromium) is
  found, otherwise the default browser; Fiji's generic HDF5 import is said to see only the stored
  integers; the colour maps are credited as taken via the cmcrameri package (C. Rollo).
- `mesc-io view --help`: `--rois` defaults to `~/mesc-viewer/` (since 0.3.8), not beside the
  working directory.

## 0.5.0 — 2026-11-04

- **The viewer's engine, mountable in another application.** `mesc_io.engine.Engine(recording, rois=…)`
  answers the viewer's routes (`/api/frame`, `/api/mean`, `/api/pixel`, `/api/rois`, `/api/traces`, …) as
  `engine.handle(method, path, body, headers) -> (status, headers, body)`, with its own ROI file, cache
  and locks; a host server routes a prefix of its own (say `/mesc/`) to it. The viewer's own handler runs
  on a request held in memory, so the standalone viewer and a mounted engine give the same bytes for the
  same request (`tests/test_engine.py`).
- **Over another recording**: `Engine(…, opener=…)` reads through any `MescFile` subclass that points
  `_dataset` at its frames — a file holding motion-corrected frames in its own layout serves exactly as a
  .mesc does; routes that only a .mesc can answer stay quiet for it. Metadata with numpy scalars comes
  out as JSON.
- **The page's pieces as scripts a host can load**: `static/api.js` (every URL through one base, found
  from the script's own URL), `static/image.js` (image ↔ screen mapping with the MESc flip, whole-pixel
  drawing, a one-frame-in-flight loader) and `static/player.js` (playback that waits for the disk, arrow
  steps, a sliding time window, the averaging clamp). The viewer draws and plays through them.
- **A frame says which window drew it**: `X-Window: floor,ceiling` in the recording's units on
  `/api/frame`, so a host switching auto → fixed starts from the picture already on screen.

- **Objects are grown on the recording's own values**, on the server at full resolution
  (`mesc_io.objects.grow`): face neighbours at least a share of the way from the stack's background
  (its 5th percentile) to the peak, within the radius. On the page's 8-bit window bytes the same
  seed was 86 µm³ under one window and 834 µm³ under another, and its means were of clipped bytes.
  The list gives the background, the peak and the threshold used.
- **Stitching after a red team.** A link is believed by its own correlation map (peak-to-sidelobe
  ratio ≥ 6, or ≥ 4 when a loop of other links confirms it); a link no loop checks must give the
  same shift from both halves of its depth; depth is taken from a link only when confirmed; depth is
  rounded from each group's anchor; corrections are from where a tile is drawn, and those inside
  the mosaic's own loop noise are not applied, so a second auto leaves a stitched field still; a
  tile further off than one pair may move it is measured in a second pass. The report says what was
  not used, unconfirmed, joined only among itself, held in depth or moved far, in a box of its own.
- **One depth for a slice everywhere**, from the stack's geometry (µm from the rig's zero); slice 0
  is named by its end, not called the surface.
- Smaller: the mosaic's contrast follows the tile picked in the list and redraws when it changes;
  the unit's slider and channel buttons are hidden under the mosaic; the tile list starts closed;
  go takes a depth alone and says when a point is off every tile; the 3D ruler is kept with the view;
  stacks are listed in slices.

- **Mosaics in depth, from the stacks' own geometry.** A stack's slices are placed by the geometry
  it carries (`Unit.z0_um`: `GeomTransTransl` z plus the z axis's offset; slice 0 the deep end), not
  by the stage reading, which is one value taken at some moment of the scan — on a 2026-10-27 file
  one tile's reading sat 190 µm from its neighbours' while their geometries agreed. Two layers of
  tiles now sit at their depths, and a layout's `dz` is a correction on top of the geometry. The
  grid is the one most tiles share: the injection-zero stack taken first at 10 µm slices no longer
  drops every real tile behind it (it is left out, with the reason). A tile commented "ignore"
  starts hidden. `Unit.z_origin_um` carries the rig's zero.
- **The mosaic as a map.** Depth is shown in µm from the rig's zero (+ shallower) and the slider runs
  shallow to the right (↑ shallower); **slab** draws each tile as the maximum of n slices, so sparse
  axons read as lines; the hover gives x, y and z; a **map** overview with the part on screen
  framed (click or drag on it to go there); **go** centres on a point typed in µm, and a z goes to
  that depth. Each tile in the list shows its depth range. The frame endpoint takes `proj=max`.
- **Stitching on projections, then depth.** Each pair is matched across on the maximum through its
  common depth, then in depth on slabs at that shift: matching 3-D voxels let an axon running down
  through the slices make every peak a ridge in z (runner-up = winner on every pair). A match must
  stand 1.5× above the best match elsewhere (`ambiguous` otherwise); the search reaches ±25 µm (the
  stage was ~20 µm off); narrow overlaps are not reduced; loops are checked with a z tolerance of
  6 µm, a two-photon focus being several times longer in z. On three October mosaics: 20, 14 and 22
  links used (one of them: 10 before, seven tiles left unjoined); every tile with a neighbour joined.
- **The 3D ruler measures on the plane you chose.** A ruler click puts its point exactly where the
  cursor meets the current plane (the slice selected), with no snap to the brightest voxel; change
  the plane between clicks to measure across depth. The current plane is lit blue in MIP and slab
  views too, not only in glass. The readout over the 3D view no longer swallows clicks on the stack
  beneath it.
- **Shift+click removes a surface mark you can see.** The nearest of the marks drawn in that pane,
  within 14 screen pixels; a miss says so instead of doing nothing.

- **The surface of the tissue, marked in XYZ.** **surface** in the XYZ bar: each click in a pane puts
  a mark where the tissue begins, instead of moving the crosshair; shift+click removes the nearest,
  Esc the last, shift+Esc all. A surface is fitted through the marks by least squares in µm — flat
  from one or two, a tilted plane from three to five, a curved one (z = a + bx + cy + dx² + exy + fy²)
  from six — and drawn as a dashed line where each pane cuts it, with its tilt in degrees. The
  crosshair and every 3D point get their depth below it, along z, into the tissue: by default the
  brighter side of the stack, or the side set with **tissue**. **csv** writes the marks, the fit and
  the points' depths. Marks are kept per unit with the view.
- **Mosaics of z-stacks.** **mosaic** lays every z-stack of a file that carries a stage position out as
  one field, one plane at a time, hard seams (nearest centre, or by order). **auto** stitches it from
  the overlaps — masked normalised cross-correlation in 3D per overlapping pair, sub-pixel in x and y,
  one correction per tile by weighted least squares, starting from the current layout so a hand-made
  one is refined; each seam shows its correlation and residual. **edit** moves tiles by hand (drag,
  arrows, [ ] for a slice, h hides, ⌘Z undoes), **top** and **seams** choose which tile shows on an
  overlap, **flatten** puts the tiles' marked surfaces on one plane, a double-click opens a tile in
  XYZ. **crop**, planes and **TIFF** cut a piece out as a Fiji hyperstack written beside the view
  (layout in its Info); **layout** downloads the corrections; **labels** off gives the bare picture
  for a PNG. The layout is kept with the view. Python: `mesc_io.mosaic` (`tiles`, `geometry`,
  `register`, `compose`, `to_tiff`); the page places tiles by the same rule, checked pixel for pixel.
  `tools/make_synthetic.py --mosaic` writes six tiles off by known amounts, to test against.
- **Stitching that does not believe a chance match.** Which pairs to trust is set by the data
  (as ASHLAR does): the same strips are matched against tiles that do not overlap, and the best of
  those chance correlations is the bar. A match whose peak sits on the edge of the search is no
  match (the tile is further off than searched). A wrong match is found by checking each link
  against what the other links say about its two tiles; it is dropped only when the loops can name
  it — when several links could equally be the wrong one, none is dropped and they are all shown in
  red as doubtful (a grid of edge neighbours alone often cannot tell; diagonal overlaps can). Groups
  of tiles joined to nothing are left where they were instead of thrown to a minimum-norm answer.
  Each seam is coloured by what became of it. Least-squares weights were applied squared; fixed.
- The mosaic on screen is now composed pixel by pixel with the rule the export uses (the nearest
  centre among the tiles that cover the pixel): cutting tiles by bisectors left black slivers on
  screen where the TIFF had data. The check now compares every pixel, seams included, on an uneven
  layout, and fails on the old rule.
- The mosaic TIFF is written a plane at a time (peak memory a plane, not ~3× the file), with NaN
  where no tile reaches (0 is a value a recording can hold), and refused if the disk cannot take it.
- The crop is kept in stage µm, so it stays on the tissue when tiles move or one is hidden.
- All tiles take their position from the same frame: the rig's zero only when every tile has it.
- The viewer's server takes 128 waiting connections instead of 5: a page asking for many pictures at
  once (a mosaic, the unit list) had some connections reset and their pictures never arrived.
- The exploratory clicker fails its run when it finds an issue (it printed them and exited 0), and
  now clicks the surface and mosaic controls too.
- The **surface ↑** button's tooltip no longer says slice 0 is always the surface: in a stack recorded
  upward slice 0 is the deepest.
- **Gamma per channel in 3D and XYZ.** A number per channel shown (γ ch0, γ ch1 in the overlay),
  0.3–3, in the 3D bar and over the XYZ views: a brightness b is drawn as b^γ, after the window, the
  floor and the gain, in the volume shader, in the XYZ panes and so in the 3D PNG (whose caption says
  so). Below 1 the dim parts come up, a thin axon beside a bright cell. At 1 nothing is computed and
  the picture is the old one to the bit — checked by hashing every pixel of all three modes, one and
  two channels, and the XYZ panes against 0.4.0. Values, floors and picks are not touched. Saved with
  the view.
- **Objects in 3D.** **object**, beside point and measure: a click picks a seed as point does, then
  grows the connected region around it (six face neighbours) in that channel's bytes, keeping voxels
  at least a share of the seed's peak (50 % by default) and within a radius of the seed (15 µm), never
  more than 250,000 voxels — the radius is what stops a bouton running along its axon. Listed with
  its volume in µm³, voxel count, centre in µm and slice, extent, and each channel's mean in the
  recording's units; a numbered diamond at its centre in 3D, its voxels tinted and its edge outlined
  in XYZ, and in the PNG caption. Only the seed and the two numbers are saved; the region is grown
  again on load. Changing the share or the radius grows the last object again. Esc removes the last,
  shift+Esc all. `tests/view_gamma_object_real_chrome.js` checks both on the synthetic stack: the red
  cell's object is centred within 0.1 voxel of (95, 30, 16) at ~86 µm³, a bouton's stays a bouton,
  and at 10 % the axon is taken in only as far as the radius allows.

## 0.4.3 — 2026-10-28

- **No ROIs from the 3D bar.** The 3D toolbar sits inside the image's stage, and a click on its
  buttons (reset, side y, side x among them) reached the hidden 2D image underneath: a spot ROI was
  put down there and saved to the ROI file, unseen. While a 3D or XYZ view covers the image, the
  image's click, press and double-click do nothing, and no button or field ever counts as a click
  on it. If you used 3D in 0.4.0–0.4.2, look in the ROI list for spots you did not draw.
- **Backspace and Delete remove an ROI only where ROIs are shown** — not under a 3D or XYZ view,
  where the selected ROI was deleted without being seen.

## 0.4.2 — 2026-10-28

- **In the overlay each channel has its own ceiling**, by slider or typed as a number in that
  channel's own units, beside its floor. The overlay hid the ceiling's number: one ceiling for two
  channels with two windows has no single value in the recording's units. A channel's ceiling
  carries to one channel and back, as its floor does.
- The floor's and ceiling's help no longer mention a gamma, which 0.4 does not have.

## 0.4.1 — 2026-10-28

**The 3D view says what it does.** Improvements to what 0.4.0 has; nothing new besides.

- **The 3D ruler measures on the plane you chose.** A ruler click puts its point exactly where the
  cursor meets the current plane (the slice selected by the slider or the XYZ crosshair), with no
  snap to the brightest voxel along the ray; change the plane between clicks to measure across
  depth, Δz from the planes chosen. A click off the plane puts nothing down and says so.
- **The current plane is lit blue in MIP and slab views too**, not only in glass: a pixel whose
  brightest voxel lies on the selected plane is blue.
- **Floor and ceiling only decide what is shown.** They were also the black and white points, so
  moving either rescaled the brightness of every voxel between them. Brightness now comes from the
  window (contrast) and gain alone; below the floor a voxel is not drawn, above the ceiling (when it
  cuts) neither, and the rest keeps its grey. The ceiling's toggle reads "ceiling: cut / off".
- **One floor per channel.** A floor set for a channel in the overlay was a separate setting from the
  one-channel floor, so leaving the overlay showed a floor nobody had set; it now carries across, and
  across a switch of channel.
- **Display modes are transparent.** A click on a 3D or XYZ control that changes something besides
  itself — the auto floor following the mode, a slab drawing glass as a MIP, a stack reduced further
  for two channels — says what changed, from what to what, and why, in a note over the view.
- **The readout over the 3D view no longer swallows clicks** on the stack beneath it.

## 0.4.0 — 2026-10-27

**Measure, export, open in Fiji.**

- **Points in 3D.** **point** in the 3D bar: a click (a drag still turns) marks the brightest voxel
  under the cursor, snapped to the brightest of its 3×3×3 neighbours, kept in the file's own
  full-resolution voxels (so a turn, a flip or the 3D downsampling does not move it) and saved with
  the view. Points are numbered on the picture, in XYZ and in the PNG, with their position in µm, the
  slice and each channel's value. Esc removes the last, shift+Esc all.
- **A ruler in 3D.** **measure**: two points give the distance in µm with Δx, Δy, Δz (x and y from
  their pixel sizes, z from the slice step); shift+click goes on into a path whose length is an
  axon's. The label says Δz is the least certain — a two-photon PSF is several times longer along z.
- **A clip box and a thick slab.** **box** keeps six limits of the stack in its own axes; **slab**
  draws only a thickness in µm around the slider's slice, as MIP, and the slider moves it. Both only
  move the ends of each ray, so with neither on the 3D picture is the old one to the bit.
- **TIFF export is a Fiji hyperstack.** `export … out.tif` now writes every channel (`--channel N` for
  one): TCYX for a recording, ZCYX for a z-stack, composite mode with each channel in its own colour and
  its own display range (1–99.8 % of that channel, so a red ten times brighter does not set the green's
  window), the frame interval or the z spacing, x and y pixel sizes, and the comment, the units and each
  channel's conversion in the image Info. Frames are streamed. `export <file> all <folder> --tiff` writes
  every unit. Fiji has no `.mesc` reader of its own; this is the way in until there is a plugin.
- **PNG export.** **PNG** saves what is on screen, made for a figure: the image at its own pixels, each
  drawn as a whole block (no blur), with the ROIs, the ruler, a µm scale bar and a caption — file, unit,
  frame or projection, channels, window, MESc view — on the report's background; with 3D open, the 3D
  view. **png** beside csv saves the traces as drawn. The file name says what the picture is.
- **ruler**, beside spot/rect/polygon: click two points on the image and the distance between them
  is drawn and written beside the line — in µm from the file's own pixel size (x and y each by its
  own, so a non-square pixel still reads true), with Δx, Δy and the length in pixels. The second
  point follows the cursor until it is placed; a third click starts a new ruler; Esc clears it.
  It is not an ROI: nothing is saved or exported, and it works the same in the flipped MESc view.

## 0.3.14 — 2026-10-27

**Panes that fit the window.** Found by clicking through the viewer (by hand and with a scripted
monkey in a real Chrome) before 0.4.

- **The tools no longer get cut off.** The sizes of the traces pane, the metadata pane and the tools
  column were limited only while a splitter was dragged; a size saved on a bigger screen, a window made
  smaller, or one pane grown after another pushed panes off the window — the tools cut off with no
  scrollbar, the metadata below its column, at worst the traces pane over the unit list and the image
  squeezed to nothing. Saved sizes are now capped by the window as it is: the image keeps at least
  240 × 200 px, the metadata pane gives way to the unit list, and the tools column scrolls. Checked from
  1440 × 900 down to 900 × 600, with every pane at its default and at its maximum
  (`tests/view_layout_real_chrome.js`).
- **The 3D ceiling slider no longer throws** when it is moved on a file with no stack loaded.

## 0.3.13 — 2026-10-27

**Motion correction on an 8 GB laptop, and a page that keeps up.**

- **The page keeps up too.** Measured in Chrome on a current laptop, as-is and with the CPU slowed 6×
  (an old laptop's worth), on a 512² recording with 40 ROIs × 5,000 frames and a 149-slice two-channel
  stack:
  - **Playing and scrubbing no longer redraw the traces.** The frame cursor is its own element under
    the trace canvas; the traces are redrawn only when what they show changes. A frame step cost
    12 ms of trace drawing (80 ms at 6×); now ~0. Playback at 6× went from 6.5 to 12 frames/s, with
    2.9 s of blocked main thread per 6 s of playing down to none.
  - **A redraw within the same time window is ~4× cheaper** (a selection, the grid, the mode): each
    band's axis limits are kept per time window instead of sorted on every redraw, the canvas is
    reallocated only when its size changes, and past one frame per pixel each pixel column draws its
    first, lowest, highest and last frame (spikes kept; at one frame per pixel or fewer the line goes
    through every frame, as before). 12 → 3 ms (80 → 27 ms at 6×). A new time window still sorts
    each band once: unchanged at 12 ms (80 ms at 6×).
  - **Scrubbing asks for one frame at a time** — while one is on its way, only the latest position is
    remembered and fetched when it lands. 30 slider steps: 30 frame requests → 11–12.
  - **Dragging a splitter** redraws once per frame through one resize path, with 3D drawn coarse while
    the size moves: 237 → 3 ms for 20 moves (1.6 s → 9 ms at 6×).
  - **Colouring a frame** goes through packed RGBA tables in one pass, and one channel in plain grey
    is the PNG itself: 2–3 → 1 ms (13–19 → 4–7 ms at 6×). Pixel for pixel the same, checked.
  - **XYZ views:** the same tables, and a pane is re-cut only when its own slice changes. A crosshair
    step 7 → 2 ms (62 → 9 ms at 6×); the same pixels, checked.
  - **Cutting the blobs** when the ceiling is let go runs in steps that yield to the page, the old
    picture staying until the cut is ready: the page no longer freezes for 0.4 s (2.2 s at 6×); the
    bytes are the same.
  - **3D at rest is drawn at most 1.5 device pixels per CSS pixel and ~1.5 MP** (never below one per
    CSS pixel): on a retina screen 1425×899 instead of 1900×1198. A MIP ray also stops at the first
    voxel that reaches the ceiling, which cannot change what it shows.
  - Also: the hover readout on a projection sends which projection (`mode=max|mean`); the overlay's
    trace limits are cached by the payload itself, so a refetch with a new q is not shown with the
    old q's limits.

- **Motion correction needs the memory of one unit, and runs 2.7× faster** — 291 s → 109 s and
  8.0 GB → 4.1 GB peak for one two-channel 3,715-frame 512² recording; a file of three such
  recordings now peaks at 4.3 GB (it needed ~23 GB). The written `.mesc` is the same: every
  stored chunk and attribute byte-identical to 0.3.11's output on that recording.
  - **Each unit is written as soon as it is registered**, then let go, instead of every unit
    being held until the end and copied once more for the write. The output is written as
    `<out>.partial` and renamed when complete, so a failed run leaves no half-written file; an
    output path that is the source itself is refused up front.
  - **Suite2p's batch follows the frame size** (`BATCH_PIXELS`: 1000 frames of 256², 250 of
    512²). 1000 frames of 512² made ~2 GB FFT buffers and ran at half the speed. The output does
    not depend on the batch; `batch=` still fixes it (pass 1000 to reproduce an older run if you
    set `smooth_sigma_time` or `do_bidiphase`, which mix frames within a batch).
  - **Writing back deflates frames in threads.** For one-gzip-chunk-per-frame datasets (MESc's
    layout, no shuffle or checksum) frames are compressed with zlib in a few threads and stored
    with `write_direct_chunk` from one thread under h5py's lock: 4.6 s → 0.7 s per 1,000 frames of
    512², the same stored bytes (checked on each channel's first frame; h5py writes the channel
    if they differ). Other layouts go through h5py as before.
  - **Conversion to stored integers in 64-frame blocks** inside the write loop, not over whole
    arrays (which peaked at 8× the stored size); the agreement check converts only the frames
    it samples. Same values, same refusals.

## 0.3.12 — 2026-10-27

**Faster on old laptops.** Our first user's five-year-old Mac took 15–20 minutes for the traces.

- **Traces are about 5× faster** — 15.9 s → 3.0 s for 40 ROIs over 3,715 frames of 512² on a current
  laptop, with the same numbers. Three changes, each checked against the old result:
  - **Reading:** MESc stores one gzip chunk per frame. Those chunks are now read as stored bytes (under
    h5py's own lock — HDF5 is not thread-safe and the viewer serves several requests at once) and
    inflated in a few threads; h5py's own path spent most of its time outside zlib. A whole unit reads
    3.5× faster, byte-identical; any other layout goes through h5py as before, and a corrupt or
    unwritten chunk gets h5py's own error or fill value.
  - **The ROI pass:** done on the stored integers and converted at the end (the conversion is linear),
    with all ROIs gathered at once instead of each one scanning the whole frame. 2× faster; the traces
    differ by at most 1e-13.
  - **The dF/F baseline:** at the ends of the rolling window (most of a short unit, for a 60-s window)
    the quantiles came from one np.quantile call per frame — 74,000 calls for 40 ROIs. One sorted
    window is now moved a point at a time instead. Bit-identical, 4× faster.
- **Long recordings: the dF/F baseline no longer grows with the recording squared.** The rolling
  quantile now moves one sorted window over the whole trace; np.quantile over a sliding-window view
  partitioned an (n−w+1)×w copy (1.7 GB per ROI at 60,000 frames). One 15,000-frame trace: 878 → 55 ms;
  40 ROIs at 60,000 frames: 83 s → 6 s. Bit-identical.
- **The viewer's server:**
  - **Hovering on a mean or max image** rebuilt the 300-frame projection on every move (~1 s), because
    it looked in the cache under a key nothing was stored under — and in max mode it reported the
    mean's value. It now reads the projection on screen. The traces had the same cache miss (0.8 s).
  - **Traces after a new q or window** recompute dF/F from the cached raw means instead of reading
    the recording again.
  - **Mean, max, thumbnails, averaged frames, the scrub window and the 3D volume** are reduced on the
    stored integers and converted once: 300 frames of 512² were 630 MB of float64 (above 1 GB at the
    peak) and 0.5–1.6 s; now ~0.1 s. Equal to float rounding (5e-16), max bit-identical.
  - **ROI masks** test only the polygon's own box: 40 discs on 512² took 0.6 s, now ~7 ms; same masks.
  - **A frame PNG** is deflated at level 1 instead of 6: 37 ms → 2 ms of a ~40 ms scrub step, about
    10 % larger on the wire (localhost), same pixels.
  - **3D window changes** re-map a cached block-averaged volume instead of re-reading the stack.
  - **The traces payload** is built vectorised (0.2 s → ~0.01 s); the single-disc `/api/trace` uses the
    fast ROI pass (12 s → ~1 s).
  - **The cache has a ceiling** (1 GB, oldest first); it used to keep everything it ever made.
- **`to_reader_units` converts in place:** one float64 copy instead of three (a 500-frame 512² block
  peaked at 2.1 GB); bit-identical.
- **`export` to HDF5 streams** a block of frames at a time: a whole 3,715-frame 512² unit was refused
  (7.8 GB as float64); now it exports in 19 s at 1.1 GB.
- **3D keeps up on a weak GPU.** While the stack is turned, moved or zoomed it is drawn at half the CSS
  pixels with rays stepped twice as far, and ~180 ms after the hand stops at full quality again.
## 0.3.11 — 2026-10-27

**Two channels at once in 3D, in two colours.**

- **3D and XYZ: the overlay shows both channels.** With **overlay** on, a two-channel z-stack goes
  to the GPU as one RG texture and is drawn green (Channel_0) and magenta (Channel_1); the colours
  add, so where both channels are bright the voxel is white. MIP takes each channel's brightest
  along the ray and adds the colours; glass lets both add light and hide what is behind. The XYZ
  views show the same two colours. Depth stays one channel (the one picked under the image) and
  says so.
- **A window and a floor per channel.** Each channel is fetched through its own window — the fixed
  limits typed for it in instruments, or percentiles of that channel alone — since a red channel
  is often ten times brighter than the green and one window would leave the green black. In the
  3D bar each channel has its own floor (slider and number, in its own units) and a switch that
  hides it; the switches sit over the XYZ views too. A palette picked for a channel in instruments
  gives its colour in 3D as well.
- **The same voxel budget for two channels.** `/api/volume` takes `?share=2`: the 32 M-voxel cap
  is split between the channels, so the pair costs the GPU what one channel did, and both come
  back block-averaged by the same factor, voxel for voxel. On a 149-slice 512 × 512 stack that
  is ÷2 in x and y, as it was for one channel.
- One channel, and a unit with one channel, are drawn exactly as before (pixel for pixel in the
  browser check). A unit with more than two channels overlays the first two, and says so.
- `tools/make_synthetic.py --stack` writes a two-channel z-stack (three axons with boutons in
  green, two cells ten times brighter in red, one on a bouton) for the 3D browser check.

## 0.3.10 — 2026-10-15

**A private window on Windows too.**

- **The viewer opens in a private window on Windows.** Chrome and Edge are not on PATH there, so
  the viewer looked for them by name, found nothing and fell back to an ordinary window of the
  default browser, which keeps history and cached pages. It now looks where their installers put
  them (Program Files, Program Files (x86), the user's AppData) and opens Chrome with
  `--incognito`, Edge with `--inprivate` or Firefox with `-private-window`. If none is there, it
  still says plainly that the window is NOT private.

## 0.3.9 — 2026-10-12

**One folder for what you drew.**

- **ROI sets and views live in `~/mesc-viewer/`.** The viewer used to save a recording's
  `<name>_rois.json` and `<name>_view.json` in the working directory, so launched from home it
  left two files in its root for every recording it ever opened. Now they go to one folder,
  `~/mesc-viewer/`, whatever directory the viewer is started from (`--rois` still puts a set
  anywhere). A set already in the working directory, where 0.3.8 and earlier wrote it, is still
  found and used, so nothing drawn before is lost; move it into `~/mesc-viewer/` to make it the
  one copy.

## 0.3.8 — 2026-10-05

**A steady picture while scrubbing.**

- **auto % no longer flickers.** It used to stretch each frame on that frame's own percentiles,
  so the picture pumped while scrubbing: on a real 256 × 256 recording the per-frame upper
  limit swung between 676 and 841 reader units. Now the window comes from 64 frames spread
  over the whole unit (averaged in groups of n when the view averages n frames). It is
  worked out once, cached, and used for every frame. The mean grey changes 0.16 grey levels
  from one frame to the next, against 1.44 before. The mean image and the thumbnails were
  always one picture and are unchanged.

## 0.3.7 — 2026-10-05

**The metadata MESc shows, in the viewer.**

- **Metadata: the unit as MESc shows it.** The quick metadata panel now lists, under *as MESc
  shows it*, every row of MESc's own information panel in its order: item type, date (to the
  millisecond, local time), creator and revision, profile, user, host, setup, recorded I/O
  signals, measurement type, dimensions, channels, size on disk, bits per sample, pixel size,
  scanning area, the centroid in absolute coordinates and from the zero level, the rotation as
  Z-X'-Y'' Euler angles, frame rate and duration. Each is worked out from the attributes behind
  it (`Unit.info` in the reader), and compared with a photo of the panel on the rig: the centroid
  is the middle pixel *centre* (`offset + (n-1)/2` steps), which is how MESc gets x = 0. For a
  z-stack the panel gives slice step and depth instead of a rate; those two rows, its
  measurement-type wording and its z centroid have not been compared with MESc yet.
- Reader: a text attribute stored as an array of byte strings (`TypeDebugString`) no longer
  raises — it is read as text.

## 0.3.6 — 2026-10-05

**Which way is up: the surface on top in 3D, and the image as MESc draws it.**

- **3D: the surface is on top.** Femtonics records a stack from the surface down (slice 0 = the
  surface) and MESc draws the deepest slice at the top. Here depth is now the vertical axis of the
  3D view with the surface up: it opens looking straight down from the surface, turns about the
  depth axis like a turntable, and *side x* / *side y* show the depth running down. **deepest ↑
  (MESc)** turns it round. A 3D view saved by an earlier version opens with a fresh camera (its
  mode, floor and the rest are kept), since its angles meant something else.
- **2D: ↕ MESc** shows the image upside down, the way MESc draws it (row 0 at the bottom). The
  picture only: ROIs, coordinates, the pixel readout, the zoom box and every export stay in the
  file's own rows, which are also what our pipeline and its report use (the report's "Flip V
  (Femtonics view)" is the same display-only flip). The 3D view follows it.

## 0.3.5 — 2026-10-05

**The 3D view, for working inside a stack.**

- **3D: the wheel zooms where the cursor is.** The ray under the cursor is marched through the
  stack and the brightest voxel above the floor is the point zoomed into (the plane through the
  turning point when the ray finds nothing); camera and turning point both close in on it, so it
  stays under the cursor (0.8 px drift over twelve wheel steps in the browser test) and the next
  turn is about it. Shift- or right-drag moves the view; reset and double-click bring the centre
  back. The wheel can now go much closer (to 0.03 of the starting distance) for a single bouton.
- **3D: floor and ceiling can be typed** in the recording's own units, next to their sliders. The
  number is mapped into the stack's window (the bytes on the GPU span it); one outside the window
  is held at its edge and shown there. Slider and number follow each other.
- **3D glass: the current frame lights up.** Its voxels turn blue and a little more solid inside
  the glass, and its outline is drawn bright, so stepping through the stack shows which piece of
  the object each frame is. The outline is drawn whenever a single frame is shown.

- Tests: the palette test read `viewer.html` without saying UTF-8, so on Windows (cp1252) it
  failed with `UnicodeDecodeError` — the `v0.3.4` tag's CI run is red on Windows for that reason
  only; the 0.3.4 package itself is unaffected (tests do not ship). Fixed here.

## 0.3.4 — 2026-10-01

**The recording in fixed limits, as it was seen on the rig.** Every frame, mean and thumbnail now
opens through a **fixed window in reader units** — by default the window the recording was saved
with (`Channel_N_LUT_VecBounds`, typically 0–2000) — so a dimmer frame IS darker: bleaching, a
laser change or a field drifting out of focus show while scrubbing. Min and max can be typed per
unit and channel; that lives in the view, never in the `.mesc`, and **file** brings the saved
window back. The per-frame stretch is one click away as **auto %** (shape, not brightness).

**Palettes.** Each channel shows in its own colour from the file (`Channel_N_LUT_VecColors`), in
a single colour (grey, green, red, magenta, cyan, blue, yellow), or in one of 25 of **Fabio
Crameri's Scientific colour maps** (v8.0: 20 sequential incl. batlow, batlowK, oslo, lajolla, and
5 diverging incl. vik, roma, berlin) — perceptually uniform and readable with colour-vision
deficiency. The tables are the published 256-step values, embedded by `tools/gen_crameri_luts.py`;
MIT licence in `src/mesc_io/third_party/crameri_LICENSE.txt`. Cite: Crameri, F. (2018).
Scientific colour maps. Zenodo. https://doi.org/10.5281/zenodo.1243862

**Overlay** shows all channels at once, each through its own window and colour, added and
clipped. The reader exposes the saved window and colour as `Channel.lut` and `Channel.colour`.
Thumbnails that fail under the first burst of requests on a large file are asked for again.

## 0.3.3 — 2026-09-25

**A ceiling in the 3D view.** Beside the floor there is now a **ceiling**, and the window runs
between the two, so dim structure stretches to the full range. Above the ceiling a voxel is
**cut** — gone, so the brightest blobs stop hiding the axons around and behind them — or, with
**clip**, held at white. A cut takes each blob's rim with it (everything within 1.5 µm of a
voxel above the ceiling, at the stack's own voxel size): cutting only the brightest voxels left
each blob as a hollow shell that the window stretched back to white. The cut is computed when
the slider is let go; a ceiling of 1 is the picture as before.

## 0.3.2 — 2026-09-25

**A z-stack can be looked at as a stack.** The viewer counts a stack's slices in microns rather
than calling them frames in seconds, and offers **max** beside **mean**, since a bouton lives in
a few slices of thirty and an average dilutes it. **3D** puts the whole stack on the GPU and
lets you turn it: as a maximum-intensity projection, as **glass** (semi-transparent, each voxel
adding a little light and hiding a little of what is behind it), or as **depth**, a MIP
coloured by how deep its brightest voxel lies — an axon's colour says where it runs. The box is
scaled by the voxel size, so a stack of 1 µm slices over 0.14 µm pixels is the slab it is, not
a cube; depth can be stretched and says so. The floor starts at the stack's own percentile so
background noise does not fill the box. **XYZ** cuts the stack three ways through one
crosshair, Fiji's orthogonal views, with **max** turning each pane into a side projection.
WebGL2 only, no library; the state is saved with the view.

**Presets you can save.** `mesc-io preset save NAME` stores a set of registration settings
(rigid or non-rigid, block edge, both shift caps, any Suite2p option) as a small JSON file in
`~/.config/mesc-io/presets` or `$MESC_IO_PRESETS`; `list`, `show` and `delete` do what they say.
`register --preset` takes a saved name or a path to a preset file, and each setting resolves as
flag → preset → default, so a flag still wins over the preset. A preset holds settings only and
never groups, so it cannot put two fields on one reference. The report records the preset in
full and where it was read from. `pipeline` is built in and equals the defaults. Instructions:
`docs/registration.md`.

**A z-stack is no longer motion-corrected.** `register` took every unit by default, stacks
included, and aligned their slices — which are depths, not moments — to one reference. On a
calibration file with five stacks that moved slices by 35 to 72 pixels and wrote them back tagged
`_MC`. Stacks are now skipped with the reason, the recordings beside them still go through, and
a group mixing a stack with a recording is refused.

**A channel with no conversion warns when read.** Its offset and scale fell back to 0 and 1 in
silence, so "reader units" were the stored integers with the PMT offset still in them.
`ConversionWarning` now says so, and `Channel.converted` tells you in advance. No channel of the
four real files checked lacks one.

**Write-back rounds.** `from_reader_units` truncated towards zero, a −0.5-count bias on every
non-integer value; it now rounds to the nearest count.

**int16 saturates instead of wrapping.** Registration picks its int16 scale from 12 sampled
frames; a brighter pixel elsewhere wrapped to negative and came out black. It is now held at
32767 with a warning. On a 20-unit bouton session the true peak was 14718, so this is a guard.

## 0.3.1 — 2026-09-24

**The pipeline's correction is the default now, not a preset.** 0.3.0 shipped the analysis
pipeline's settings as `--preset pipeline` while the defaults stayed rigid-only, so a plain
`mesc-io register` produced numbers that were not the ones this package exists to reproduce.
Defaults are now `nonrigid=True`, `block_size=64`, `max_shift_nr=3.0` — the session config
those recordings are processed with. Verified against the pipeline's own master on the same
unit, as the fraction of the raw frame's pixel-to-pixel variance that survives: **0.354 from
these defaults against 0.357 in the master.** `--rigid` opts out and costs no sharpness, but
it is then a different correction and the gel warp at the edges goes uncorrected.
`--preset pipeline` is kept as an explicit no-op for anything written against 0.3.0.

**A unit too short to register no longer kills the run.** A session normally carries a unit or
two aborted after a frame or two, commented "ignore". Suite2p's `compute_reference` sorts
frames by their correlation to a running average and averages the best fraction; below a
handful that selection is empty, its mean is NaN, and the run died with `cannot convert float
NaN to integer` deep inside suite2p — after registering six units, losing all of it.

- `MIN_FRAMES_FOR_REFERENCE = 16` usable frames (after the flat head) is the floor, and any
  other suite2p failure while building a group's reference is caught the same way.
- The group is skipped with a `RegistrationWarning`, listed in `report["skipped"]` with the
  reason, and reported through an `on_skip` callback; the CLI prints it to stderr.
- Skipped means **not registered, not missing**: `writeback` copies the source, so those units
  reach the output exactly as they were. A test pins that.

## 0.3.0 — 2026-09-24

**Each unit is registered to its own reference now.** `register_file` used to build one
reference from the first unit and register every other unit of the file against it. A `.mesc`
normally holds several different fields, and a field registered to another field's reference
is not less accurate, it is wrong: the search returns its best match against structure that is
not in the frame, and the frames come out displaced with nothing in the output to say so.

- Default: one reference per unit.
- `groups=[["MUnit_0", "MUnit_1"]]` / `--group MUnit_0 MUnit_1` (repeatable) names the units
  that ARE one field and must share a reference, anchored on the first. Repeats of one field
  still need this — without it they land in two coordinate frames and a structure cannot be
  followed between them. Aligning *between* fields is a separate problem, not this module's.
- `reference_from` without `groups` keeps its old meaning — one shared reference over every
  named unit — because that was always an explicit request rather than a default.
- **Report shape changed**: `reference_from` and `reference` are no longer top-level. There is
  `groups`, each with its `anchor`, `units` and `reference`, and every unit entry carries the
  `reference_from` it was registered to.
- A unit whose frames are all flat now raises instead of building a reference out of nothing.
  `take` could reach zero and the reference was computed from an empty selection.
- Two different fields in one file are a test fixture now, with a positive control: asked to
  share one reference, the second field's known displacement is no longer recovered.

**The defaults are the pipeline's motion-correction settings**, written down rather than
inherited: `nonrigid=False`, `smooth_sigma_time=0`, `block_size=[128, 128]`, `maxregshift=0.1`,
`snr_thresh=1.2`, `batch_size=1000`. All but the last two agree with Suite2p's own defaults;
`batch_size` was 500 and is now the pipeline's 1000, and `nonrigid` stays off where Suite2p
turns it on. A test pins them, so a future Suite2p moving one of them is visible.

- `ops={...}` / `--ops KEY=VALUE` passes anything in `suite2p.default_ops()` straight through,
  applied last and winning over everything above — `{"smooth_sigma": 2.0}` for a noisier field,
  `{"two_step_registration": True}` to rebuild the reference from the registered movie. A key
  Suite2p does not have **raises**; a misspelled option would otherwise change nothing and say
  nothing. The report carries what was passed.
**`preset="pipeline"` / `--preset pipeline`** runs the settings the analysis pipeline runs.
Diffed key by key against its `_suite2p_ops_base`: of 90 options only four matter here —
`nonrigid=True`, `block_size=[64, 64]`, `maxregshiftNR=3.0`, `soma_crop=False`. Settings only;
units still get one reference each unless `groups` says they share a field.

Verified on a real session (abf001 260918_1, MUnit_2), as the fraction of the raw frame's
pixel-to-pixel variance that survives: raw 1.000 · rigid default **1.000** · preset 0.382 ·
preset with the group's anchor as reference 0.354 · the same unit in the pipeline's own master
0.357. So a rigid shift costs nothing and the whole softening is the non-rigid warp — which is
bought deliberately there, to correct the smooth peripheral warp of the immersion gel drying
inward over a session.

- Written down in `_ops`, because the obvious reading is wrong: Suite2p's non-rigid blocks
  overlap (`ceil(1.5 * L / block_size)` per axis), so `block_size=128` on a 256 px frame is a
  3x3 grid of nine blocks, not 2x2. Pinned by a test.

## 0.2.1 — 2026-09-24

- The metadata window has a button. `GET /api/metadata/<unit>` shipped in 0.2.0 with nothing to
  open it; **all…** beside the metadata heading now opens a panel with every attribute the unit
  and its session carry, grouped, with a filter over names and values and esc to close. The
  sidebar keeps its ten, which is what a glance wants.
- `tests/view_metadata_real_chrome.js` drives it in a real Chrome over CDP — clicks the button,
  counts the rows, types in the filter, presses esc, and fails on any console error.

## 0.2.0 — 2026-09-24

**A z-stack is no longer read as a 1000 Hz recording.** The third axis is time in a recording
and depth in a stack, and the file says which — `ZAxisGeomRole` is 0 for time and 3 for depth.
Reading its scale without asking turned a 1 µm slice spacing into "1000 Hz": a number that is
plausible, correctly typed, and would have reached a rolling baseline and an event window
without a murmur. Five of the nine units of a calibration file were read that way.

- `frame_rate_hz` is now `None` when the third axis is depth. **Breaking for those files**, and
  meant to be: a caller that used to get 1000.0 was getting a wrong number, and every caller in
  this package already handled `None`.
- `z_step_um` carries the slice spacing instead.
- `pixel_size_y_um` appears when the y pixel size differs from x. Femtonics writes the axes
  separately and they are not always equal — 0.126171875 µm against 0.12629686820504823 on a
  408×512 frame. `pixel_size_um` still carries x, as before.

### Viewer

- `GET /api/metadata/<unit>` returns **every** attribute the unit and its session carry, grouped
  and decoded. The reader keeps 15 of about 278, which is the right number for code and the
  wrong one for a person deciding whether something matters.
- Text stored as an integer array is decoded from its low bytes: Femtonics writes strings as
  uint8 in one field and int16 in the next, and reading the raw bytes of a multi-byte dtype
  prints `M E S c   4 . 0`. Empty attributes come back as `null` rather than failing the request.

## 0.1.1 — 2026-09-21

- The package description on PyPI said the package was not on PyPI: it was the README as
  built before the first upload. Now it says `pip install mesc-io`, with the PyPI badge and
  the acknowledgements. No code change.

## 0.1.0 — 2026-09-21

- The `register` extra pins Suite2p to the 0.14 line: 1.x renamed the arguments of
  `compute_reference`/`register_frames`, and 0.14 is what the registration is validated on.
- Reads and writes of the page and the sidecars are UTF-8 on every platform; the ImageJ export
  declares `roifile` (`mesc-io[imagej]`) instead of importing it unannounced.
- The reader carries the position from zero (`stage_rel_um`) next to the stage (`stage_um`).

First version. The API is young: names may still move before 1.0.

### Reading

- `MescFile` — sessions, units, and per unit: frame count, frame size, dtype, frame rate,
  pixel size, per-channel conversion, and the comment typed at the rig.
- The frame rate is the reciprocal of the stored frame **period**
  (`ZAxisConversionConversionLinearScale`, in ms) and is read per unit, because it differs
  per unit. A file that does not state it returns `None` rather than a plausible default.
- The comment is returned verbatim and never parsed. What a lab writes there is that lab's
  convention, not part of the format.
- `read()` refuses a request over 4 GB by default and names the ways round it; `iter_frames()`
  streams a recording in blocks, converting per block.

### Values

- `to_reader_units` / `from_reader_units` — the conversion the native Femtonics reader
  applies, both ways, exact round trip. Offsets and scales come from the file's own
  attributes; nothing is hardcoded.
- Converted values are float: a pixel below the PMT floor is negative, and that is
  information rather than something to clip away.

### Checking

- `check()` / `mesc-io check` reports what a file disagrees with itself about — mixed frame
  rates, mixed pixel sizes, missing or non-constant conversions, one-frame units — and never
  repairs. Given a positive control before being trusted: silent on clean files, and on a
  real session it catches the z-stack whose frame period reads as "1000 Hz", at half the
  pixel size, at 512x512 among 256x256.

### Writing

- `export` — one unit to HDF5 or to an ImageJ TIFF, with the frame rate, pixel size and
  conversion travelling with the pixels.
- `write_frames` / `mesc-io writeback` — processed frames into a **copy** of a `.mesc`.
  Before anything is copied, the new frames are compared with the ones they would replace on
  a statistic a translation does not move, and a disagreement **refuses the write**: frames
  in the wrong units make a movie that looks right and is quantitatively wrong. Written units
  are tagged in their comment so a corrected file cannot pass for the original.
- The round trip needs nobody to remember the units: export records them, writeback reads
  that record, and a file we did not write makes the tool ask rather than guess.

### Files with more than one session

- A `.mesc` can hold several sessions, and two of them can hold a `MUnit_0`. A bare unit name
  that matches in more than one is now **refused**, listing the paths to choose from, instead
  of quietly returning the first — which would hand back the wrong recording, or write over
  it. A full `MSession_1/MUnit_0` path always works, and a bare name that is unique still
  works.
- `write_frames` reaches any session; it previously looked only in the first and reported a
  unit in any other as "not in the file".

### Motion correction

- `register_file` / `mesc-io register` — Suite2p registration of the units of one field
  against **one shared reference**, taken from the **first** unit rather than sampled across
  the whole session, so everything is anchored to the state the session started in instead of
  to an average of early and late. Other channels take the registration channel's shifts.
  Optional extra: `pip install mesc-io[register]`.
- **The flat head.** A recording opens with a run of frames that are not dark — their mean
  sits at the recording's own level — but hold no structure, only detector noise. Registration
  matches them to that noise: on a real recording it moved them by up to 22 px while the rest
  of the unit needed 1. Those frames are now found by contrast (not brightness), left exactly
  as they were, and reported. The count varies per unit, 6 to 9 on one file, so a fixed trim
  is the wrong model.
- Measured on a real awake recording: registration raises the sharpness of the average field
  by 12.3 % and the frame-to-mean correlation by 1.4 %, with motion of only +-2 px.
- The reported shifts carry the same sign as the displacement, and are absolute only up to
  one constant per unit — the reference comes from the data, so it sits at some average state.
  Verified against known displacements on a synthetic recording.

### Everything else

- Every error raised on purpose derives from `MescIOError`, while staying its specific self.
- Tested on Python 3.9, 3.12 and 3.13, each with a real install, from outside the
  source tree.
