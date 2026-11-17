# Motion correction and registration presets

`mesc-io register` motion-corrects the units of a `.mesc` with Suite2p. The result is written
into a **copy** of the file. The source is not modified. Requires the extra:

```
pip install "mesc-io[register]"
```

## Default run

```
mesc-io register recording.mesc recording_MC.mesc
```

- **One reference per unit.** A file usually holds several fields. Registering one field onto
  the reference of another gives displaced frames without any warning.
- **Default settings** (the ones we use on our own recordings): non-rigid, 64-px blocks,
  non-rigid cap 3 px per block, rigid cap 0.1 of the frame. Non-rigid registration corrects
  peripheral warping from the immersion gel drying during a session. It also resamples every
  frame, so the output is slightly blurred even where there was no motion. `--rigid` disables
  it.
- **Skipped units:** z-stacks (third axis is depth, not time) and units too short for a
  reference. They are copied unchanged and listed as `UNREGISTERED`.
- **Other channels** receive the shifts computed on `--channel` (default 0, green).

Repeats of one field need a shared reference to end up in one coordinate frame. Groups are
given per run:

```
mesc-io register rec.mesc rec_MC.mesc --group MUnit_1 MUnit_2 MUnit_3 --group MUnit_4 MUnit_5
```

## Presets

A preset is a small JSON file with **registration settings only**:

| setting        | flag on `register` | default |
|----------------|--------------------|---------|
| `nonrigid`     | `--rigid` turns it off | `true` |
| `block_size`   | `--block-size`     | `64` (px, block *edge*; blocks overlap) |
| `max_shift`    | `--max-shift`      | `0.1` (fraction of the frame) |
| `max_shift_nr` | `--max-shift-nr`   | `3.0` (px) |
| `ops`          | `--ops KEY=VALUE`  | any other Suite2p option |

A preset does **not** define groups. Which units show the same field depends on the file, not on
the settings. Groups are therefore always given on the run, and a preset cannot put two fields
on one reference.

### Save

```
mesc-io preset save soma --block-size 128 --max-shift-nr 5 \
    --ops smooth_sigma=2.0 --description "soma fields: coarser blocks, looser warp cap"
```

Only the given settings are stored; the rest stay at default. Unknown Suite2p options are
rejected at saving. An existing name is overwritten only with `--force`.

### Use

```
mesc-io register rec.mesc rec_MC.mesc --preset soma
mesc-io register rec.mesc rec_MC.mesc --preset soma --max-shift-nr 3     # a flag still wins
mesc-io register rec.mesc rec_MC.mesc --preset ./presets/soma.json      # a file, anywhere
```

Order of precedence: **flag → preset → default.** `--ops` overrides the `ops` of the preset.
The run prints the preset, its source and the settings actually used.

### List, show, delete

```
mesc-io preset list            # built-in and saved, and the directory they live in
mesc-io preset show soma       # one in full
mesc-io preset delete soma
```

A preset is a single file and is shared by sending it. The recipient passes it by path
(`--preset soma.json`) or copies it into their preset directory. For presets kept with a
project, pass the path or set `MESC_IO_PRESETS` to the project directory.

### Location

1. a path given on the command line: `--preset something.json`;
2. `$MESC_IO_PRESETS`, if set;
3. otherwise `$XDG_CONFIG_HOME/mesc-io/presets` (usually `~/.config/mesc-io/presets`).

`pipeline` is built in, equals the defaults, and cannot be overwritten or deleted.

### File format

```json
{
  "mesc_io_preset": 1,
  "name": "soma",
  "description": "soma fields: coarser blocks, looser warp cap",
  "settings": {"block_size": 128, "max_shift_nr": 5.0, "ops": {"smooth_sigma": 2.0}}
}
```

Files can be written by hand. They are validated on reading. Unknown keys, wrong types and
block edges under 8 px are rejected with a reason.

## From Python

```python
from mesc_io.registration import register_file
from mesc_io.presets import save_preset

save_preset("soma", {"block_size": 128, "max_shift_nr": 5.0}, "coarser blocks for soma")
rep = register_file("rec.mesc", "rec_MC.mesc", preset="soma")      # or a path, or a dict
rep["settings"], rep["preset"], rep["skipped"]
```

The report stores the full preset (`name`, `source`, `description`, `settings`) and the resolved
settings. A corrected file can thus be traced to the exact settings used.

## Memory and speed

- **One unit in memory at a time.** Each unit is written to the output after registration and
  then released. Memory use is that of the largest unit. Example: three two-channel 512²
  recordings of 3,715 frames each. Peak memory 4.3 GB; before 0.3.12, one unit took about 8 GB
  and the whole file about 23 GB.
- **Atomic output.** The output is written as `<out>.partial` and renamed when complete. A failed
  or interrupted run removes the partial file. The output cannot be the source.
- **Batch size scales with frame size.** Suite2p receives a fixed number of pixels per batch
  (`registration.BATCH_PIXELS` = 1000 × 256²): 1000 frames of 256², 250 frames of 512². This
  keeps the FFT buffers small. With 1000 frames of 512², the buffers took ~2 GB and registration
  ran at half speed. Each frame is registered independently, so the output is unchanged.
  `register_file(..., batch=N)` sets the batch size. Use `batch=1000` to reproduce an older run
  exactly if `smooth_sigma_time` or `do_bidiphase` is set; these two Suite2p options combine
  frames within a batch.
- **Threaded compression.** MESc stores one gzip chunk per frame. Frames are compressed with zlib
  in several threads and passed to HDF5 as finished chunks. The bytes are identical to those of
  HDF5's own deflate; this is checked on the first frame of each channel. If they differ, that
  channel is written through h5py. Only zlib runs in the threads. All HDF5 calls are made from
  one thread under the h5py lock. Other layouts are written through h5py.
