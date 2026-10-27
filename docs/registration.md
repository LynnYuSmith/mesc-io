# Motion correction, and keeping its settings

`mesc-io register` motion-corrects the units of a `.mesc` with Suite2p and writes the result
into a **copy** of the file; the source is never modified. It needs the extra:

```
pip install "mesc-io[register]"
```

## What a plain run does

```
mesc-io register recording.mesc recording_MC.mesc
```

- **Every unit gets its own reference.** A file usually holds several different fields, and
  registering one field onto another's reference returns displaced frames with nothing to say
  so.
- **The settings are those of the calcium-imaging pipeline:** non-rigid, 64 px blocks, a 3 px
  cap on the per-block warp and a rigid cap of 0.1 of the frame. Non-rigid corrects the
  peripheral warp from the immersion gel drying over a session. It also resamples every frame,
  so the output is softer than the input even where nothing moved. `--rigid` turns it off.
- **Z-stacks are skipped** (their third axis is depth, not time), and so are units too short to
  build a reference from. Both are copied through unchanged and listed as `UNREGISTERED`.
- **The other channels follow** the shifts computed on `--channel` (default 0, green).

Repeats of one field need one shared reference so they land in one coordinate frame. Say so per
run:

```
mesc-io register rec.mesc rec_MC.mesc --group MUnit_1 MUnit_2 MUnit_3 --group MUnit_4 MUnit_5
```

## Presets: naming a set of settings

A preset is a small JSON file holding **registration settings only**:

| setting        | flag on `register` | default |
|----------------|--------------------|---------|
| `nonrigid`     | `--rigid` turns it off | `true` |
| `block_size`   | `--block-size`     | `64` (px, the block *edge*; blocks overlap) |
| `max_shift`    | `--max-shift`      | `0.1` (fraction of the frame) |
| `max_shift_nr` | `--max-shift-nr`   | `3.0` (px) |
| `ops`          | `--ops KEY=VALUE`  | any other Suite2p option |

A preset **never** says which units share a reference. Which recordings are the same field is a
fact about one file, not a setting, so a preset cannot put two fields on one reference by
accident. Groups are always named on the run.

### Save one

```
mesc-io preset save soma --block-size 128 --max-shift-nr 5 \
    --ops smooth_sigma=2.0 --description "soma fields: coarser blocks, looser warp cap"
```

Only what you give is stored; everything else keeps the default. A Suite2p option that does not
exist is refused when you save, not ignored when you run. A name that exists is not
overwritten unless you add `--force`.

### Use one

```
mesc-io register rec.mesc rec_MC.mesc --preset soma
mesc-io register rec.mesc rec_MC.mesc --preset soma --max-shift-nr 3     # a flag still wins
mesc-io register rec.mesc rec_MC.mesc --preset ./presets/soma.json      # a file, anywhere
```

Each setting is resolved as: **the flag you pass → the preset → the default.** The preset's
`ops` go under any `--ops` you pass. The run prints the preset, where it came from, and the
settings that were actually used.

### See, share, remove

```
mesc-io preset list            # built-in and saved, and the directory they live in
mesc-io preset show soma       # one in full
mesc-io preset delete soma
```

A preset is one file, so sharing it means sending the file. The other person uses it by path
(`--preset soma.json`) or drops it into their own preset directory. To keep presets with a
project rather than per machine, put them in the project and pass the path, or point
`MESC_IO_PRESETS` at that directory.

### Where they live

1. a path you pass: `--preset something.json`;
2. `$MESC_IO_PRESETS`, if set;
3. otherwise `$XDG_CONFIG_HOME/mesc-io/presets`, i.e. `~/.config/mesc-io/presets`.

`pipeline` is built in, equals the defaults, and can be neither overwritten nor deleted.

### The file

```json
{
  "mesc_io_preset": 1,
  "name": "soma",
  "description": "soma fields: coarser blocks, looser warp cap",
  "settings": {"block_size": 128, "max_shift_nr": 5.0, "ops": {"smooth_sigma": 2.0}}
}
```

It can be written by hand. It is checked when read: unknown keys, wrong types or a block edge
under 8 px are refused with the reason.

## From Python

```python
from mesc_io.registration import register_file
from mesc_io.presets import save_preset

save_preset("soma", {"block_size": 128, "max_shift_nr": 5.0}, "coarser blocks for soma")
rep = register_file("rec.mesc", "rec_MC.mesc", preset="soma")      # or a path, or a dict
rep["settings"], rep["preset"], rep["skipped"]
```

The report keeps the preset in full (`name`, `source`, `description`, `settings`) next to the
settings that were resolved, so a corrected file can be traced to exactly what produced it.

## Memory and speed

- **One unit in memory at a time.** Each unit is written into the output as soon as it is
  registered and then let go, so a file of several recordings needs the memory of one. On a
  file of three 3,715-frame, two-channel 512² recordings the peak stayed at 4.3 GB (one unit
  held about 8 GB, and the whole file would have needed about 23 GB, before 0.3.12).
- **The output appears when it is complete.** It is written as `<out>.partial` and renamed at
  the end; a run that fails or is stopped removes the partial file and leaves nothing under
  the name asked for. The output cannot be the source.
- **Batch size follows the frame size.** By default Suite2p gets `BATCH_PIXELS` worth of frames
  at a time — 1000 frames of 256², 250 of 512² — which keeps its FFT buffers small (1000 frames
  of 512² asked for ~2 GB of them and ran at half the speed). Every frame is registered on its
  own, so the output does not change. `register_file(..., batch=N)` fixes it; do that with
  `batch=1000` to reproduce an older run exactly if you set `smooth_sigma_time` or
  `do_bidiphase`, the two Suite2p options that mix frames within a batch.
- **Frames are deflated in threads.** MESc stores one gzip chunk per frame. Those frames are
  compressed with zlib in a few threads and handed to HDF5 as finished chunks — the same bytes
  HDF5's own deflate stores, checked on the first frame of every channel (if they differ, that
  channel is written through h5py). Only zlib runs in the threads; every HDF5 call is made from
  one thread, under h5py's lock. Any other layout is written through h5py as before.
