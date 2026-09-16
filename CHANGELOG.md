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

### Everything else

- Every error raised on purpose derives from `MescIOError`, while staying its specific self.
- Tested on Python 3.9, 3.12, 3.13 and 3.14, each with a real install, from outside the
  source tree.
