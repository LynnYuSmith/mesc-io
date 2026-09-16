"""Look a `.mesc` over before you trust it.

A file can be perfectly readable and still not be what you assume. These are the
disagreements worth knowing about before an analysis is built on top of one — each is
something a file has actually done, not a hypothetical:

* **units recorded at different frame rates.** Normal in a session where the field or the
  zoom changed, and ruinous if you take one rate for the whole file. A z-stack saved
  alongside the recordings reports a frame period that is not a frame rate at all.
* **units at different pixel sizes.** The zoom was changed between recordings, so distances
  in one unit are not distances in another.
* **conversion attributes missing.** Then the values you read are the stored integers and the
  package has nothing to convert them with — it says so rather than assuming a common offset.
* **channels with different conversions across units**, which means a per-file constant is
  the wrong model for that file.
* **empty or single-frame units**, which are usually a snapshot or an aborted recording and
  will surprise anything that expects a movie.

`check` reports; it never repairs. What is a problem depends on what you are doing, so the
severities are advisory and the report names the units so you can look.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, List

from .reader import MescFile

__all__ = ["check", "Report", "Finding"]


@dataclass(frozen=True)
class Finding:
    level: str          # "note" | "warn"
    code: str
    message: str
    units: tuple = ()

    def __str__(self) -> str:
        where = f"  [{', '.join(self.units[:6])}{'…' if len(self.units) > 6 else ''}]" if self.units else ""
        return f"{self.level:>4}: {self.message}{where}"


@dataclass
class Report:
    path: str
    n_units: int
    findings: List[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(f.level == "warn" for f in self.findings)

    def __str__(self) -> str:
        head = f"{self.path}: {self.n_units} unit(s), {len(self.findings)} finding(s)"
        return "\n".join([head] + [str(f) for f in self.findings])


def _group(values: Dict[str, object]) -> Dict[object, List[str]]:
    out = defaultdict(list)
    for unit, v in values.items():
        out[v].append(unit)
    return dict(out)


def check(path) -> Report:
    """Read a `.mesc`'s metadata and report what disagrees with what."""
    with MescFile(path) as f:
        units = f.units()
        rep = Report(path=str(f.path.name), n_units=len(units))

        rates = {u.path: (round(u.frame_rate_hz, 3) if u.frame_rate_hz else None) for u in units}
        missing = [u for u, r in rates.items() if r is None]
        if missing:
            rep.findings.append(Finding(
                "warn", "no-frame-rate",
                f"{len(missing)} unit(s) do not state a frame rate", tuple(missing)))
        present = {u: r for u, r in rates.items() if r is not None}
        by_rate = _group(present)
        if len(by_rate) > 1:
            common = Counter(present.values()).most_common(1)[0][0]
            odd = tuple(u for u, r in present.items() if r != common)
            rep.findings.append(Finding(
                "warn", "mixed-frame-rates",
                f"{len(by_rate)} different frame rates in one file "
                f"({', '.join(f'{r:g} Hz x{len(v)}' for r, v in sorted(by_rate.items()))}) — "
                f"use each unit's own rate, never one for the file", odd))

        sizes = {u.path: u.pixel_size_um for u in units if u.pixel_size_um}
        by_size = _group(sizes)
        if len(by_size) > 1:
            rep.findings.append(Finding(
                "warn", "mixed-pixel-sizes",
                f"{len(by_size)} different pixel sizes "
                f"({', '.join(f'{s:.4f} um x{len(v)}' for s, v in sorted(by_size.items()))}) — "
                "distances are not comparable across these units", ()))
        if len(sizes) < len(units):
            rep.findings.append(Finding(
                "note", "no-pixel-size",
                f"{len(units) - len(sizes)} unit(s) do not state a pixel size",
                tuple(u.path for u in units if not u.pixel_size_um)))

        shapes = _group({u.path: (u.height, u.width) for u in units})
        if len(shapes) > 1:
            rep.findings.append(Finding(
                "note", "mixed-frame-shapes",
                f"{len(shapes)} different frame shapes "
                f"({', '.join(f'{h}x{w}' for h, w in sorted(shapes))})", ()))

        thin = tuple(u.path for u in units if u.n_frames <= 1)
        if thin:
            rep.findings.append(Finding(
                "note", "not-a-movie",
                f"{len(thin)} unit(s) hold one frame or none — a snapshot or an aborted "
                "recording", thin))

        no_conv, per_channel = [], defaultdict(dict)
        for u in units:
            for c in u.channels:
                per_channel[c.name][u.path] = (c.offset, c.scale)
                if c.offset == 0.0 and c.scale == 1.0:
                    no_conv.append(f"{u.path}/{c.name}")
        if no_conv:
            rep.findings.append(Finding(
                "warn", "no-conversion",
                f"{len(no_conv)} channel(s) carry no conversion attributes — their values "
                "cannot be put in reader units and come back as stored", tuple(no_conv)))
        for name, per_unit in sorted(per_channel.items()):
            distinct = set(per_unit.values())
            if len(distinct) > 1:
                rep.findings.append(Finding(
                    "warn", "mixed-conversion",
                    f"{name} does not use one conversion across the file "
                    f"({len(distinct)} different) — convert per unit, never per file", ()))

        counts = Counter(len(u.channels) for u in units)
        if len(counts) > 1:
            rep.findings.append(Finding(
                "note", "mixed-channel-counts",
                f"units carry different channel counts "
                f"({', '.join(f'{n} ch x{k}' for n, k in sorted(counts.items()))})", ()))
    return rep
