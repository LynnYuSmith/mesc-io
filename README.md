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

Early. The API may change before 0.1.0. See `docs/` for what is in scope.

## Install

    pip install mesc-io

## Use

```python
from mesc_io import MescFile

with MescFile("recording.mesc") as f:
    for unit in f.units():
        print(unit.name, unit.shape, f"{unit.frame_rate_hz:.3f} Hz",
              f"{unit.pixel_size_um:.4f} um/px")

    frames = f.read(unit="MUnit_0", channel=0, reader_units=True)
```

`reader_units=True` returns what the Femtonics reader displays. `False` returns the stored
integers untouched. Nothing in between, and no silent conversion.

## From the command line

```
mesc-io info recording.mesc                        # what is in the file
mesc-io export recording.mesc MUnit_0 unit0.h5     # one unit out
mesc-io export recording.mesc MUnit_0 unit0.tif    # ...or a TIFF ImageJ can scale
```

`info` prints, per unit: frames, frame size, frame rate, pixel size and the comment typed at
the rig. A unit whose file does not state its frame rate prints `unknown` — never a plausible
default.

`export` picks its writer from the output suffix. Both carry the frame rate, the pixel size
and the conversion that produced the values; the TIFF puts them where ImageJ and Fiji read
them back as frame interval and spatial scale. Reader values are written as float32, since
they can be negative — which makes an exported stack four times the size of the stored
integers. Pass `--stored-units` for the file's own uint16 if size matters more than meaning.

## What this package will not do

It does not parse the unit comment. `area1 axon stim 550 …` is a convention some lab agreed
on, not part of the format, so the comment comes back verbatim and what it means is yours to
decide. It does not motion-correct, segment, or compute anything about the signal. It reads
files and writes them out correctly, which is the part that is fiddly and shared.

## Licence

MIT — see [LICENSE](LICENSE).
