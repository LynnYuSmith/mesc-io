# mesc-io

Read Femtonics `.mesc` two-photon recordings in Python, in the units the native reader shows.

A `.mesc` is an HDF5 container. What it does not tell you plainly: the frame rate is a frame
*period* in an axis attribute and differs per unit, the pixel size is another attribute, and
the stored integers are not the displayed values — each channel carries its own linear
conversion. This package reads all of that from the file's own attributes.

## Install

```
pip install mesc-io            # + [tiff] for TIFF export
```

## Python

```python
from mesc_io import MescFile

with MescFile("recording.mesc") as f:
    for u in f.units():
        print(u.path, u.shape, u.frame_rate_hz, u.pixel_size_um)

    frames = f.read("MUnit_0", channel=0)              # reader units, float64
    frames = f.read("MUnit_0", reader_units=False)     # the stored integers
    for block in f.iter_frames("MUnit_0", block=500):  # bigger than memory
        ...
```

`read` refuses over 4 GB by default (`max_gb=None` to override). A unit name that matches in
more than one session is refused, not resolved to the first; `MSession_1/MUnit_0` always works.

## Command line

```
mesc-io info      recording.mesc                            # units, rates, pixel sizes
mesc-io check     recording.mesc                            # what the file disagrees with itself about
mesc-io export    recording.mesc MUnit_0 u0.h5              # or u0.tif
mesc-io writeback recording.mesc out.mesc MUnit_0 u0.h5     # processed frames back in
```

`info` and `check` take `--json`.

`export` records which units the values are in; `writeback` reads that record, and asks if the
file does not carry one. Before writing it compares the new frames with the ones they replace
and refuses on disagreement. It copies the source, never modifies it, and tags the written
unit's comment (`_MC`).

## Not in scope

Unit comments are returned verbatim, never parsed — their format is a lab convention, not the
file's. No motion correction, no segmentation, no signal analysis.

## Development

```
pip install -e ".[tiff,dev]"
pytest
```

The package lives under `src/`, so tests run against the installed copy.
Tested on Python 3.9–3.14, Linux/macOS/Windows.

## Licence

MIT — see [LICENSE](LICENSE).
