"""Motion-correct the units of a `.mesc` with Suite2p.

Suite2p does the registration. What this module adds is the part that matters when a file
holds several recordings:

* **each unit gets its own reference, unless you say otherwise.** One file usually holds
  several different fields, and registering one field to another field's reference is not
  registration: the search finds its best match against structure that is not there and
  quietly returns displaced frames. So the default is per unit.
* **`groups` is how you say two recordings are the same field.** Repeats of one field do
  need one shared reference, or they end up in two coordinate frames and a structure cannot
  be followed from one to the next. Name them together — `groups=[["MUnit_0", "MUnit_1"]]` —
  and they share a reference while everything else keeps its own. Aligning *between* fields
  is a separate problem and is not this module's job.
* **a group's reference comes from one recording, not from all of them.** Tissue drifts and
  deforms over a session. A reference built over a group's concatenation would be an average
  of early and late states and match neither. Taking it from the group's first unit anchors
  the group to the state it started in. Pass `reference_from` to anchor elsewhere.
* **the other channels follow.** Registration is computed on one channel and the same shifts
  are applied to the rest, because they were recorded simultaneously and moving them
  independently would break their alignment to each other.

Optional non-rigid registration corrects a smooth, position-dependent warp that a whole-frame
shift cannot — typically strongest at the edges of the field and growing over a session. Keep
`max_shift_nr` small: the warp is a pixel or two, and a loose cap lets blocks slide onto the
wrong features.

Needs Suite2p: `pip install mesc-io[register]`.
"""
from __future__ import annotations

import warnings
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import numpy as np

from .errors import MescIOError
from .reader import MescFile

__all__ = ["register_file", "compute_reference_image", "leading_flat_frames",
           "RegistrationError", "INT16_MAX"]

INT16_MAX = 32767
# A frame with this little spatial contrast, relative to the recording's own, holds nothing to
# register on.
FLAT_FRACTION = 0.5


#: The four Suite2p options that separate this module's defaults from the calcium-imaging
#: pipeline's motion correction (``lib/mesc/concat_mc._suite2p_ops_base``, measured against it
#: 2026-09-24: 5 of 90 keys differed, and ``input_format`` only matters to ``run_s2p``, which
#: is not the path taken here). Non-rigid is the substantive one — it warps each block by its
#: own subpixel shift, which resamples EVERY frame, so the output is softer than the input even
#: where nothing moved. That is a deliberate trade there: it corrects the smooth peripheral
#: warp from the immersion gel drying inward over a session, which a rigid shift cannot touch.
#: Grouping is NOT part of this: units stay one-reference-each unless `groups` says otherwise.
#: Checked against a real session (abf001 260918_1, MUnit_2, 300 frames), as the fraction of
#: the raw frame's pixel-to-pixel variance that survives: raw 1.000, rigid default 1.000 (a
#: rigid shift costs nothing), this preset 0.382 alone and 0.354 with the group's anchor as
#: reference, against 0.357 for the same unit inside the pipeline's own master.
PIPELINE_OPS = {
    "nonrigid": True,
    "block_size": [64, 64],     # 6x6 = 36 blocks on a 256 px frame; they overlap
    "maxregshiftNR": 3.0,       # the warp is 1-2 px; a loose cap slides blocks onto neighbours
    "soma_crop": False,
}

PRESETS = {"pipeline": PIPELINE_OPS}

#: Fewest usable frames (after the flat head) a unit needs before Suite2p can build a
#: reference from it. `compute_reference` sorts frames by their correlation to a running
#: average and averages the best fraction of them; below a handful that selection comes out
#: empty and the mean of it is NaN, which surfaces as `cannot convert float NaN to integer`
#: deep inside suite2p. A session normally carries a unit or two like this — one aborted
#: frame, commented "ignore" — so this is the ordinary case, not the exceptional one.
MIN_FRAMES_FOR_REFERENCE = 16


class RegistrationError(MescIOError, RuntimeError):
    """Registration could not be run, or the data does not suit it."""


class RegistrationWarning(UserWarning):
    """A unit was left unregistered; the rest of the file went through."""


def _suite2p():
    try:
        from suite2p.registration import register as _reg
        from suite2p import default_ops
    except ImportError as exc:  # noqa: BLE001
        raise ImportError(
            "motion correction needs Suite2p — pip install mesc-io[register]") from exc
    # newer Suite2p exposes `suite2p.default_ops` as the MODULE and the function lives inside it;
    # older ones re-export the function. Calling the module was the CI failure of 2026-09-21.
    if not callable(default_ops):
        default_ops = default_ops.default_ops
    return _reg, default_ops


def _ops(fs: float, nonrigid: bool, block_size: int, max_shift: float,
         max_shift_nr: float, extra: Optional[Dict] = None, batch: int = 1000) -> Dict:
    """The settings a two-photon bouton pipeline has been running these recordings with.

    These are the DEFAULTS, not a mode to opt into: the point of this module is to reproduce
    that correction, and a reader that quietly ran something else would be worse than useless.

    Not a fresh guess: they are what the calcium-imaging pipeline's sessions run — the ops
    ``lib/mesc/concat_mc._suite2p_ops_base`` builds (`maxregshift=0.1`, `smooth_sigma_time=0`,
    `snr_thresh=1.2`, `batch_size=1000`), called with `PipelineConfig`'s `block_size=64` and
    `maxregshift_nr=3.0` and with `suite2p_nonrigid: true`, which every session YAML sets. The ones that happen to agree
    with Suite2p's own defaults are spelled out anyway — a silent agreement is not a decision,
    and if a future Suite2p moves one of them we want to see it move.

    Non-rigid is ON, with 64 px blocks and a tight 3 px cap. It warps each block by its own
    subpixel shift, so it RESAMPLES every frame and the output is softer than the input even
    where nothing moved — measured at 0.36 of the raw pixel-to-pixel variance and 0.87 of the
    mean image's sharpness. That is bought deliberately: the immersion gel dries from its edges
    inward over a session, the refractive index changes with it, and the image warps at the
    periphery in a way no whole-frame shift can touch. `nonrigid=False` turns it off and costs
    nothing measurable, but it is then not the same correction.

    What `block_size` buys is not what it looks like: Suite2p's blocks OVERLAP, and
    `calculate_nblocks` gives `ceil(1.5 * L / block_size)` per axis. On a 256 px frame 64 is a
    6x6 grid of 36 blocks and 128 would be 3x3 — not the 4x4 and 2x2 the division suggests.
    Only matters when `nonrigid` is on.

    `extra` is applied last and wins over all of it.
    """
    _, default_ops = _suite2p()
    ops = default_ops()
    ops.update({
        "fs": float(fs), "do_registration": True, "roidetect": False, "spikedetect": False,
        "nonrigid": bool(nonrigid), "block_size": [int(block_size)] * 2,
        "maxregshift": float(max_shift), "maxregshiftNR": float(max_shift_nr),
        "smooth_sigma_time": 0, "snr_thresh": 1.2, "batch_size": int(batch), "nimg_init": 300,
        "reg_tif": False, "reg_tif_chan2": False,
    })
    if extra:
        unknown = sorted(k for k in extra if k not in ops)
        if unknown:
            raise RegistrationError(
                f"Suite2p has no such option(s): {', '.join(unknown)}. "
                "A misspelled key would have changed nothing and said nothing.")
        ops.update(extra)
    return ops


def _as_int16(block: np.ndarray, scale: int) -> np.ndarray:
    """Suite2p registers int16. `scale` halves the data when it would otherwise overflow.

    The scale is chosen from a sample of frames, so a brighter pixel elsewhere can still exceed
    int16. A plain cast wraps it round to negative, and the write-back then clips that to 0: a
    bright pixel came out black. It is saturated at the int16 ceiling instead, and said so.
    On the 2026-09-18 bouton session the true peak over every frame was 14718, so this is a
    guard, not a correction that normally fires.
    """
    b = block // scale if scale > 1 else block
    over = int(np.count_nonzero(b > INT16_MAX))
    if over:
        warnings.warn(f"{over} pixel(s) above the int16 range at scale {scale} were saturated "
                      "at 32767 rather than wrapped", RegistrationWarning, stacklevel=2)
        b = np.minimum(b, INT16_MAX)
    return b.astype(np.int16)


def _scale_for(f: MescFile, unit_paths: Sequence[str], channel: int) -> int:
    """1, or 2 when any sampled frame would not fit in int16.

    Halving is lossy by one count and is only done when the alternative is wrapping a bright
    pixel round to negative. Sampling rather than scanning keeps this cheap; the margin makes
    a near-miss safe.
    """
    peak = 0
    for path in unit_paths:
        u = f.unit(path)
        idx = np.unique(np.linspace(0, u.n_frames - 1, min(12, u.n_frames)).astype(int))
        block = f.read(path, channel=channel, frames=idx, reader_units=False, max_gb=None)
        peak = max(peak, int(np.max(block)))
    return 2 if peak > INT16_MAX * 0.9 else 1


def leading_flat_frames(f: MescFile, unit: str, channel: int = 0,
                        fraction: float = FLAT_FRACTION, look: int = 60) -> int:
    """How many frames at the START of a recording carry no image to register on.

    A `.mesc` recording commonly opens with a short run of frames recorded before the scan is
    really under way. They are not dark — their mean sits at the recording's own level — but
    they are **flat**: only detector noise, no structure. Registration has nothing to match
    them on, so it matches them to noise and returns shifts of tens of pixels, while the rest
    of the recording may need none at all. Moving them by those shifts damages the only thing
    they still hold.

    Measured, not assumed: the run at the front whose spatial standard deviation is below
    `fraction` of the recording's own typical frame contrast. On a real recording this finds
    exactly the nine frames the rate of the movie says are pre-scan.
    """
    u = f.unit(unit)
    look = int(min(look, u.n_frames))
    head = f.read(u.path, channel=channel, frames=slice(0, look), reader_units=False,
                  max_gb=None)
    contrast = head.reshape(look, -1).std(axis=1)
    typical = float(np.median(contrast))
    if typical <= 0:
        return 0
    flat = contrast < fraction * typical
    n = 0
    while n < look and flat[n]:
        n += 1
    return n


def compute_reference_image(source, unit: str, channel: int = 0, *, nonrigid: bool = True,
                            block_size: int = 64, max_shift: float = 0.1,
                            max_shift_nr: float = 3.0) -> np.ndarray:
    """The reference image Suite2p picks from one unit, as int16."""
    reg, _ = _suite2p()
    with MescFile(source) as f:
        u = f.unit(unit)
        ops = _ops(u.frame_rate_hz or 30.0, nonrigid, block_size, max_shift, max_shift_nr)
        scale = _scale_for(f, [u.path], channel)
        take = min(ops["nimg_init"], u.n_frames)
        idx = np.unique(np.linspace(0, u.n_frames - 1, take).astype(int))
        frames = f.read(u.path, channel=channel, frames=idx, reader_units=False, max_gb=None)
    return reg.compute_reference(_as_int16(frames, scale), ops=ops)


def _resolve_groups(f, units, groups, reference_from) -> List[List[str]]:
    """The unit paths to register, split into the sets that share one reference.

    Default: every unit is its own group, because a file holds several fields and one
    field's reference means nothing to another. `groups` names the sets that ARE one field.
    `reference_from` on its own is read as the older, explicit request for a single shared
    reference over everything named — that is what it always meant, so it keeps meaning it.
    """
    if groups is not None:
        if units is not None:
            raise RegistrationError("pass either `units` or `groups`, not both")
        out = [[f.unit(u).path for u in g] for g in groups if len(list(g))]
        if not out:
            raise RegistrationError("`groups` is empty")
        seen = [p for g in out for p in g]
        if len(seen) != len(set(seen)):
            raise RegistrationError("a unit appears in more than one group")
        return out

    paths = [u.path for u in f.units()] if units is None else [f.unit(u).path for u in units]
    if not paths:
        raise RegistrationError("no units to register")
    if reference_from is not None:
        anchor = f.unit(reference_from).path
        return [([anchor] + [p for p in paths if p != anchor])]
    return [[p] for p in paths]


def _skip(report: Dict, group: Sequence[str], why: str, on_skip) -> None:
    """Record a group we could not register, and say so where it will be seen.

    The units keep the frames they had: `writeback` copies the source and replaces only
    what it is handed, so a skipped unit reaches the output unregistered rather than
    missing. That is the honest outcome, and the report says which ones they are.
    """
    for path in group:
        report["skipped"][path] = why
    warnings.warn(f"not registered — {why}", RegistrationWarning, stacklevel=2)
    if on_skip is not None:
        on_skip(list(group), why)


def register_file(source, out, units: Optional[Sequence[str]] = None, channel: int = 0, *,
                  groups: Optional[Sequence[Sequence[str]]] = None,
                  reference_from: Optional[str] = None, nonrigid: bool = True,
                  block_size: int = 64, max_shift: float = 0.1, max_shift_nr: float = 3.0,
                  preset: Optional[str] = None, ops: Optional[Dict] = None,
                  batch: int = 1000, tag: Optional[str] = "_MC",
                  progress=None, on_skip=None) -> Dict:
    """Register the units of `source` and write the result into a copy of it.

    **By default every unit is registered to its own reference.** A `.mesc` normally holds
    several different fields, and registering one field to another's reference is not a
    weaker result, it is a wrong one: the search returns its best match against structure
    that is not in the frame, and the frames come out displaced with nothing to say so.

    Repeats of ONE field are the case where a shared reference is needed — without it two
    recordings of the same field land in two coordinate frames and a structure cannot be
    followed between them. Say so explicitly:

        groups=[["MUnit_0", "MUnit_1", "MUnit_2"], ["MUnit_5", "MUnit_6"]]

    Each list shares one reference, taken from its first unit; units not named are left out.
    `units` selects which units to register, one reference each. `reference_from` without
    `groups` keeps its old meaning — one shared reference for every named unit, anchored
    there — because that was always an explicit request rather than a default.

The settings ARE the pipeline's (see `_ops`), non-rigid included — this reproduces that
    correction rather than offering a different one. `nonrigid=False` gives a rigid-only run,
    which changes the numbers. `preset="pipeline"` is kept as an explicit no-op for callers
    written against 0.3.0, where those settings had to be asked for.

    `ops` goes straight to Suite2p and is applied last, over everything above: anything in
    `suite2p.default_ops()` can be set — `{"smooth_sigma": 2.0}` for a noisier field,
    `{"two_step_registration": True}` to build the reference again from the registered movie,
    `{"1Preg": True, "spatial_hp_reg": 42}` when a smooth background dominates the match. A key
    Suite2p does not have raises rather than being ignored.

    Returns a report: `groups` (each with its anchor, members and reference image), and per
    unit the per-frame y/x shifts and the anchor it was registered to, so the registration
    can be inspected or reapplied. The frames are written through `mesc_io.writeback`, which
    copies the source and never modifies it.

    **Sign convention of the reported shifts.** They are Suite2p's, and they carry the same
    sign as the displacement itself: a field that moved down by two pixels reports `y_shift`
    of +2, and undoing it means moving by the negative. Verified on a synthetic recording
    displaced by known amounts — the reported shift tracked the applied displacement exactly,
    up to one constant for the whole unit. That constant is not an error: the reference is
    built from the recording, so it lands on some average state and every shift is measured
    from there. Only differences between frames are absolute.
    """
    from .writeback import write_frames

    if preset is not None:
        if preset not in PRESETS:
            raise RegistrationError(
                f"no such preset: {preset!r}. Have: {', '.join(sorted(PRESETS))}")
        ops = {**PRESETS[preset], **(ops or {})}     # an explicit ops still wins

    reg, _ = _suite2p()
    source, out = Path(source), Path(out)
    with MescFile(source) as f:
        unit_groups = _resolve_groups(f, units, groups, reference_from)
        all_paths = [p for g in unit_groups for p in g]

        for g in unit_groups:
            depth = [p for p in g if f.unit(p).z_step_um]
            if depth and len(depth) < len(g):
                raise RegistrationError(
                    f"a group mixes z-stacks ({', '.join(depth)}) with recordings — a stack's "
                    "third axis is depth, and it cannot share a reference with a movie")
            shapes = {f.unit(p).shape[1:] for p in g}
            if len(shapes) > 1:
                raise RegistrationError(
                    f"units of different frame sizes cannot share a reference: {sorted(shapes)}")

        scale = _scale_for(f, all_paths, channel)        # one scale for the whole file
        dark = {p: leading_flat_frames(f, p, channel) for p in all_paths}

        report = {"int16_scale": scale, "nonrigid": bool(nonrigid), "preset": preset,
                  "ops": dict(ops or {}),
                  "leading_flat_frames": dark, "groups": [], "units": {},
                  "skipped": {}}
        corrected: Dict[str, Dict[str, np.ndarray]] = {}

        for group in unit_groups:
            anchor = group[0]
            if f.unit(anchor).z_step_um:
                # Its frames are slices at different depths, not one field over time. Aligning
                # them to a single reference is not motion correction: on the 2026-09-24
                # calibration file it moved the slices of five stacks by 35 to 72 pixels and
                # wrote them back tagged as corrected.
                _skip(report, group, f"{anchor} is a z-stack ({f.unit(anchor).z_step_um:g} µm "
                                     "per slice) — its third axis is depth, not time, and "
                                     "there is no motion to correct across it", on_skip)
                continue
            usable = f.unit(anchor).n_frames - dark[anchor]
            if usable < MIN_FRAMES_FOR_REFERENCE:
                _skip(report, group, f"{anchor} has {usable} usable frame(s), fewer than "
                                     f"{MIN_FRAMES_FOR_REFERENCE} — no reference can be built",
                      on_skip)
                continue
            a_unit = f.unit(anchor)
            group_ops = _ops(a_unit.frame_rate_hz or 30.0, nonrigid, block_size,
                             max_shift, max_shift_nr, ops, batch)
            a_dark, a_n = dark[anchor], a_unit.n_frames
            if a_n - a_dark <= 0:
                raise RegistrationError(
                    f"{anchor}: every frame is flat, there is nothing to build a reference on")
            take = min(group_ops["nimg_init"], a_n - a_dark)
            idx = np.unique(np.linspace(a_dark, a_n - 1, take).astype(int))
            ref_src = f.read(anchor, channel=channel, frames=idx, reader_units=False,
                             max_gb=None)
            try:
                ref = reg.compute_reference(_as_int16(ref_src, scale), ops=group_ops)
                masks = reg.compute_reference_masks(ref, ops=group_ops)
            except Exception as exc:               # noqa: BLE001 — one bad unit is not the run
                _skip(report, group, f"suite2p could not build a reference from {anchor}: "
                                     f"{type(exc).__name__}: {exc}", on_skip)
                continue
            report["groups"].append({"anchor": anchor, "units": list(group), "reference": ref})

            for path in group:
                u = f.unit(path)
                n_ch = len(u.channels)
                out_by_channel = {c.name: np.empty(u.shape, dtype=np.uint16) for c in u.channels}
                ys, xs = [], []
                for start in range(0, u.n_frames, batch):
                    sl = slice(start, min(start + batch, u.n_frames))
                    block = f.read(path, channel=channel, frames=sl, reader_units=False,
                                   max_gb=None)
                    # register_frames returns the registered frames first, then the rigid
                    # offsets, their correlation, the non-rigid offsets and theirs.
                    moved_reg, y, x, _c, y1, x1, _c1, _ = reg.register_frames(
                        masks, _as_int16(block, scale), ops=group_ops)
                    ys.append(np.asarray(y)); xs.append(np.asarray(x))
                    for c in u.channels:                  # every channel takes the same shifts
                        if c.index == channel:
                            moved = moved_reg             # already shifted by register_frames
                        else:
                            raw = f.read(path, channel=c.index, frames=sl, reader_units=False,
                                         max_gb=None)
                            moved = reg.shift_frames(_as_int16(raw, scale), y, x, y1, x1,
                                                     blocks=masks[-1] if nonrigid else None,
                                                     ops=group_ops)
                        out_by_channel[c.name][sl] = np.clip(
                            np.asarray(moved, dtype=np.int32) * scale, 0, 65535).astype(np.uint16)
                # The flat head has no structure to align: registration matched it to noise, so
                # put those frames back exactly as they were and zero their recorded shifts.
                d = dark[path]
                if d:
                    for c in u.channels:
                        out_by_channel[c.name][:d] = f.read(
                            path, channel=c.index, frames=slice(0, d), reader_units=False,
                            max_gb=None)
                y_all, x_all = np.concatenate(ys), np.concatenate(xs)
                if d:
                    y_all[:d] = 0
                    x_all[:d] = 0
                report["units"][path] = {"y_shift": y_all, "x_shift": x_all,
                                         "n_frames": u.n_frames, "n_channels": n_ch,
                                         "leading_flat_frames": d,
                                         "reference_from": anchor}
                corrected[path] = out_by_channel
                if progress:
                    progress(path, report["units"][path])

    write_frames(source, out, corrected, reader_units=False, tag=tag,
                 tolerance=float("inf"))       # registration moves pixels on purpose
    report["out"] = str(out)
    return report
