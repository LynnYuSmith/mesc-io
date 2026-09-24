# Changelog

## Unreleased

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
