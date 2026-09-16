"""`mesc-io` on the command line: look inside a .mesc, get frames out, put frames back."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .errors import MescIOError
from .reader import MescFile


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


def _writeback(args) -> int:
    from .frames_io import load_frames
    from .writeback import write_frames

    frames, in_file = load_frames(args.frames, dataset=args.dataset)
    if args.reader_units:
        units = True
    elif args.stored_units:
        units = False
    elif in_file is not None:
        units = in_file
        print(f"  {Path(args.frames).name} says its values are in "
              f"{'reader' if units else 'stored'} units")
    else:
        print("  the frames do not say which units they are in — pass --reader-units or "
              "--stored-units. Getting this wrong writes a file that looks right and is not.",
              file=sys.stderr)
        return 1

    report = write_frames(args.source, args.out, {args.unit: {f"Channel_{args.channel}": frames}},
                          reader_units=units, tag=None if args.no_tag else args.tag,
                          tolerance=args.tolerance)
    for w in report["warnings"]:
        print(f"  note: {w}")
    for what, delta in report["agreement"].items():
        print(f"  {what}: agrees with the frames it replaced to {delta:+.0f} counts")
    print(f"  {report['out']}")
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

    p = sub.add_parser("writeback",
                       help="put processed frames back into a copy of a .mesc")
    p.add_argument("source", help="the original .mesc — it is copied, never modified")
    p.add_argument("out", help="the copy to write")
    p.add_argument("unit", help="MUnit_0, or MSession_0/MUnit_0")
    p.add_argument("frames", help=".h5 or .tif holding the processed frames")
    p.add_argument("--channel", type=int, default=0)
    p.add_argument("--dataset", default=None,
                   help="which dataset in the .h5 (only needed if there is more than one)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--reader-units", action="store_true",
                   help="the frames hold the values the reader displays")
    g.add_argument("--stored-units", action="store_true",
                   help="the frames hold the file's own integers")
    p.add_argument("--tag", default="_MC",
                   help="appended to the written unit's comment (default: _MC)")
    p.add_argument("--no-tag", action="store_true", help="do not mark the written unit")
    p.add_argument("--tolerance", type=float, default=60.0,
                   help="how far, in stored counts, the new frames may differ from the ones "
                        "they replace before the write is refused (default: 60)")
    p.set_defaults(func=_writeback)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except (MescIOError, FileNotFoundError, KeyError, ImportError, MemoryError) as exc:
        print(f"  {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
