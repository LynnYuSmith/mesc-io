"""Motion-correct the units of a `.mesc` against one shared reference, with Suite2p.

Suite2p does the registration. What this module adds is the part that matters when a session
holds several recordings of the same field:

* **one reference for all of them.** Registering each recording on its own aligns its frames
  to itself and to nothing else, so two recordings of one field end up in two coordinate
  frames and a structure cannot be followed from one to the next. Here every named unit is
  registered to the same reference image.
* **the reference comes from the first recording, not from all of them.** Tissue drifts and
  deforms over a session. Suite2p's default reference is sampled across the whole movie, so a
  reference built over the concatenation would be an average of early and late states and
  match neither. Taking it from the first unit anchors everything to the state the session
  started in. Pass `reference_from` to anchor elsewhere.
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


class RegistrationError(MescIOError, RuntimeError):
    """Registration could not be run, or the data does not suit it."""


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
         max_shift_nr: float) -> Dict:
    _, default_ops = _suite2p()
    ops = default_ops()
    ops.update({
        "fs": float(fs), "do_registration": True, "roidetect": False, "spikedetect": False,
        "nonrigid": bool(nonrigid), "block_size": [int(block_size)] * 2,
        "maxregshift": float(max_shift), "maxregshiftNR": float(max_shift_nr),
        "smooth_sigma_time": 0, "snr_thresh": 1.2, "batch_size": 500, "nimg_init": 300,
        "reg_tif": False, "reg_tif_chan2": False,
    })
    return ops


def _as_int16(block: np.ndarray, scale: int) -> np.ndarray:
    """Suite2p registers int16. `scale` halves the data when it would otherwise overflow."""
    return (block // scale if scale > 1 else block).astype(np.int16)


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


def compute_reference_image(source, unit: str, channel: int = 0, *, nonrigid: bool = False,
                            block_size: int = 128, max_shift: float = 0.1,
                            max_shift_nr: float = 5.0) -> np.ndarray:
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


def register_file(source, out, units: Optional[Sequence[str]] = None, channel: int = 0, *,
                  reference_from: Optional[str] = None, nonrigid: bool = False,
                  block_size: int = 128, max_shift: float = 0.1, max_shift_nr: float = 5.0,
                  batch: int = 500, tag: Optional[str] = "_MC",
                  progress=None) -> Dict:
    """Register `units` to one reference and write the result into a copy of `source`.

    `units` defaults to every unit in the file — name them when the file holds more than one
    field, since registering two different fields to one reference is meaningless.
    `reference_from` defaults to the first named unit.

    Returns a report: the reference used, and per unit the per-frame y/x shifts, so the
    registration can be inspected or reapplied. The frames are written through
    `mesc_io.writeback`, which copies the source and never modifies it.

    **Sign convention of the reported shifts.** They are Suite2p's, and they carry the same
    sign as the displacement itself: a field that moved down by two pixels reports `y_shift`
    of +2, and undoing it means moving by the negative. Verified on a synthetic recording
    displaced by known amounts — the reported shift tracked the applied displacement exactly,
    up to one constant for the whole unit. That constant is not an error: the reference is
    built from the recording, so it lands on some average state and every shift is measured
    from there. Only differences between frames are absolute.
    """
    from .writeback import write_frames

    reg, _ = _suite2p()
    source, out = Path(source), Path(out)
    with MescFile(source) as f:
        paths = [u.path for u in f.units()] if units is None else [f.unit(u).path for u in units]
        if not paths:
            raise RegistrationError(f"{source.name}: no units to register")
        anchor = f.unit(reference_from).path if reference_from else paths[0]
        if anchor not in paths:
            paths = [anchor] + paths                      # the anchor is registered too

        shapes = {f.unit(p).shape[1:] for p in paths}
        if len(shapes) > 1:
            raise RegistrationError(
                f"units of different frame sizes cannot share a reference: {sorted(shapes)}")

        fs = f.unit(anchor).frame_rate_hz or 30.0
        ops = _ops(fs, nonrigid, block_size, max_shift, max_shift_nr)
        scale = _scale_for(f, paths, channel)

        dark = {p: leading_flat_frames(f, p, channel) for p in paths}
        a_dark, a_n = dark[anchor], f.unit(anchor).n_frames
        take = min(ops["nimg_init"], a_n - a_dark)
        idx = np.unique(np.linspace(a_dark, a_n - 1, take).astype(int))
        ref_src = f.read(anchor, channel=channel, frames=idx, reader_units=False, max_gb=None)
        ref = reg.compute_reference(_as_int16(ref_src, scale), ops=ops)
        masks = reg.compute_reference_masks(ref, ops=ops)

        report = {"reference_from": anchor, "reference": ref, "int16_scale": scale,
                  "nonrigid": bool(nonrigid), "leading_flat_frames": dark, "units": {}}
        corrected: Dict[str, Dict[str, np.ndarray]] = {}

        for path in paths:
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
                    masks, _as_int16(block, scale), ops=ops)
                ys.append(np.asarray(y)); xs.append(np.asarray(x))
                for c in u.channels:                      # every channel takes the same shifts
                    if c.index == channel:
                        moved = moved_reg                 # already shifted by register_frames
                    else:
                        raw = f.read(path, channel=c.index, frames=sl, reader_units=False,
                                     max_gb=None)
                        moved = reg.shift_frames(_as_int16(raw, scale), y, x, y1, x1,
                                                 blocks=masks[-1] if nonrigid else None,
                                                 ops=ops)
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
            if dark[path]:
                y_all[:dark[path]] = 0
                x_all[:dark[path]] = 0
            report["units"][path] = {"y_shift": y_all, "x_shift": x_all,
                                     "n_frames": u.n_frames, "n_channels": n_ch,
                                     "leading_flat_frames": dark[path]}
            corrected[path] = out_by_channel
            if progress:
                progress(path, report["units"][path])

    write_frames(source, out, corrected, reader_units=False, tag=tag,
                 tolerance=float("inf"))       # registration moves pixels on purpose
    report["out"] = str(out)
    return report
