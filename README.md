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

## Licence

Not yet chosen. Until a LICENSE file is present, no rights are granted.
