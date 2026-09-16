# Changelog

## Unreleased

First working version. Nothing is released yet, so nothing here is stable.

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
- Tested on Python 3.9, 3.12, 3.13 and 3.14, each with a real install, from outside the
  source tree.
