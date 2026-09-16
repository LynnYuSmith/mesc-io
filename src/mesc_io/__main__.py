"""`mesc-io` on the command line: look inside a file, or get one unit out of it."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .reader import MescError, MescFile


def _info(args) -> int:
    with MescFile(args.file) as f:
        units = f.units()
        print(f"{Path(args.file).name}: {len(units)} unit(s)")
        print(f"{'unit':<18}{'frames':>8}{'size':>12}{'rate':>11}{'pixel':>11}  comment")
        for u in units:
            rate = f"{u.frame_rate_hz:.3f} Hz" if u.frame_rate_hz else "unknown"
            px = f"{u.pixel_size_um:.4f} um" if u.pixel_size_um else "unknown"
            print(f"  {u.path:<16}{u.n_frames:>8}{f'{u.height}x{u.width}':>12}"
                  f"{rate:>11}{px:>11}  {u.comment[:44]}")
    return 0


def _check(args) -> int:
    from .check import check
    rep = check(args.file)
    print(rep)
    if rep.ok:
        print("  nothing that would mislead an analysis")
    return 0


def _export(args) -> int:
    from . import export as _ex
    with MescFile(args.file) as f:
        out = Path(args.out)
        writer = _ex.to_tiff if out.suffix.lower() in (".tif", ".tiff") else _ex.to_hdf5
        written = writer(f, args.unit, out, channel=args.channel,
                         reader_units=not args.stored_units)
        print(f"  {written}  ({'stored' if args.stored_units else 'reader'} units)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="mesc-io", description=__doc__)
    ap.add_argument("--version", action="version", version=f"mesc-io {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("info", help="list the units in a .mesc and what they say about themselves")
    p.add_argument("file")
    p.set_defaults(func=_info)

    p = sub.add_parser("check", help="report what in a .mesc disagrees with itself")
    p.add_argument("file")
    p.set_defaults(func=_check)

    p = sub.add_parser("export", help="write one unit to .h5 or .tif (by the output's suffix)")
    p.add_argument("file")
    p.add_argument("unit", help="MUnit_0, or MSession_0/MUnit_0")
    p.add_argument("out")
    p.add_argument("--channel", type=int, default=0)
    p.add_argument("--stored-units", action="store_true",
                   help="write the file's own integers instead of the values the reader shows")
    p.set_defaults(func=_export)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except (MescError, FileNotFoundError, KeyError, ImportError) as exc:
        print(f"  {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
