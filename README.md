# mesc-io

Read Femtonics `.mesc` two-photon recordings from Python — and get the same numbers the
native Femtonics reader shows you.

A `.mesc` file is an HDF5 container, so you can open it with `h5py` in one line. What is not
obvious is everything after that: the frame rate is an attribute on an axis conversion, the
pixel size is another, and the stored pixel values are not the values the reader displays.
Read a `.mesc` naively and your traces are off by a channel-dependent offset and a factor.

This package encodes those conventions, reads every constant from the file's own attributes
rather than hardcoding them, and refuses to guess when a file disagrees with itself.

## Status

Early. The API may change before 0.1.0.

Tested on Python 3.9, 3.12, 3.13 and 3.14 — each with a real install, run from outside the
source tree, because that is what a user gets and a source-tree test would not catch a
packaging mistake.

## Install

    pip install mesc-io

For development, install it too — the package lives under `src/`, so the tests import what is
installed rather than the working tree, and a packaging mistake fails the tests instead of
hiding behind them:

    pip install -e ".[tiff,dev]"
    pytest

## Use

```python
from mesc_io import MescFile

with MescFile("recording.mesc") as f:
    for unit in f.units():
        print(unit.name, unit.shape, f"{unit.frame_rate_hz:.3f} Hz",
              f"{unit.pixel_size_um:.4f} um/px")

    frames = f.read(unit="MUnit_0", channel=0, reader_units=True)

    for block in f.iter_frames("MUnit_0", block=500):   # a file bigger than memory
        ...
```

`read` refuses a request that would not plausibly fit in memory — a recording is commonly
several gigabytes and converting it produces float64, four times the size of the stored
integers — and tells you the two ways round it. `max_gb=None` lifts the guard.

`reader_units=True` returns what the Femtonics reader displays. `False` returns the stored
integers untouched. Nothing in between, and no silent conversion.

## From the command line

```
mesc-io info recording.mesc                        # what is in the file
mesc-io check recording.mesc                       # what in it disagrees with itself
mesc-io export recording.mesc MUnit_0 unit0.h5     # one unit out
mesc-io export recording.mesc MUnit_0 unit0.tif    # ...or a TIFF ImageJ can scale
```

`info` and `check` take `--json` when something other than a person is reading.

`check` is worth running before you build anything on a file. It reports, and never repairs,
the disagreements that quietly wreck an analysis: units recorded at different frame rates or
different pixel sizes, channels with no conversion attributes, a conversion that is not
constant across the file, units holding a single frame. On a real session it found a z-stack
saved beside the recordings, reporting a frame period that is not a frame rate, at half the
pixel size and twice the frame width — three ways to get a wrong answer from a file that
opens perfectly.

`info` prints, per unit: frames, frame size, frame rate, pixel size and the comment typed at
the rig. A unit whose file does not state its frame rate prints `unknown` — never a plausible
default.

`export` picks its writer from the output suffix. Both carry the frame rate, the pixel size
and the conversion that produced the values; the TIFF puts them where ImageJ and Fiji read
them back as frame interval and spatial scale. Reader values are written as float32, since
they can be negative — which makes an exported stack four times the size of the stored
integers. Pass `--stored-units` for the file's own uint16 if size matters more than meaning.

## The round trip

Get a unit out, process it with whatever you already use, put it back — without anyone having
to remember which units the numbers were in:

```
mesc-io export    recording.mesc MUnit_0 u0.h5
#   ...register, denoise, whatever, in any tool...
mesc-io writeback recording.mesc corrected.mesc MUnit_0 u0.h5
```

The exported file records which units its values are in, and `writeback` reads that record.
A file this package did not write carries no such record, and then you are asked to say —
`--reader-units` or `--stored-units` — rather than the tool guessing from the dtype. That
guess would be a coin flip, and losing it writes a movie that looks right and is
quantitatively wrong.

## Writing processed frames back

Registration and denoising happen outside the Femtonics software, and the result usually
stays outside it. `write_frames` puts the processed movie back into a `.mesc`, so whoever
records the data can open it the way they already know how.

```python
from mesc_io.writeback import write_frames

report = write_frames("recording.mesc", "recording_MC.mesc",
                      {"MUnit_0": {"Channel_0": registered}})
```

It copies the file and edits the copy, never the original. Before a single frame is written
it compares the new frames with the ones they would replace, on a statistic a translation
does not move, and **refuses** if they disagree — because frames handed over in the wrong
units produce a movie that still looks like tissue and is quantitatively wrong, which is the
mistake nobody catches. The units it did write get a tag appended to their comment, so a
corrected file cannot pass for the original.

Frames shorter than the original are aligned to the end of the recording, on the assumption
that whatever was dropped came off the front; the report says when that happened.

## Files with more than one session

Most `.mesc` files hold one session and `MUnit_0` names a recording unambiguously. Some hold
several, and then two sessions can each have a `MUnit_0`. A name that matches more than one is
refused with the paths to choose from, rather than resolved to the first — the alternative is
being handed the wrong recording with nothing said. `MSession_1/MUnit_0` always works.

## Errors

Everything this package raises on purpose derives from `mesc_io.MescIOError`, so a program
that only wants to know "the file could not be used" needs one except clause. The specific
classes still say what happened, and Python's own exceptions are left as they are — a missing
file is a `FileNotFoundError`, an unknown unit is a `KeyError`.

## What this package will not do

It does not parse the unit comment. `area1 axon stim 550 …` is a convention some lab agreed
on, not part of the format, so the comment comes back verbatim and what it means is yours to
decide. It does not motion-correct, segment, or compute anything about the signal. It reads
files and writes them out correctly, which is the part that is fiddly and shared.

## Licence

MIT — see [LICENSE](LICENSE).
