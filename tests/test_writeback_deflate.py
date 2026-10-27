"""The threaded-deflate write path: the same stored bytes as h5py's own write, or h5py's write.

MESc stores one gzip chunk per frame. `writeback` deflates those frames with zlib in a few
threads and hands HDF5 the finished chunks; every other layout goes through h5py. Either way the
file must hold exactly what h5py alone would have written — chunk for chunk, byte for byte.
"""
import shutil
import zlib

import h5py
import numpy as np
import pytest

import mesc_io.writeback as wb
from mesc_io.values import from_reader_units
from mesc_io.writeback import write_frames

OFFSET = -786.0


def _frames(n, h=32, w=40, seed=0):
    """Structured frames with noise, and a few of pure noise that deflate cannot shrink."""
    rng = np.random.RandomState(seed)
    ys, xs = np.mgrid[0:h, 0:w]
    base = 900 + 400 * np.exp(-((ys - h / 2) ** 2 + (xs - w / 3) ** 2) / 40.0)
    out = (base + rng.normal(0, 8, (n, h, w))).clip(0).astype(np.uint16)
    out[3] = rng.randint(0, 65536, (h, w), dtype=np.uint16)          # incompressible
    out[-2] = 0                                                      # all zero
    return out


def _make(path, n=150, h=32, w=40, **layout):
    """A one-unit, two-channel `.mesc` whose channels use `layout` (h5py create_dataset kwargs)."""
    with h5py.File(path, "w") as f:
        u = f.create_group("MSession_0").create_group("MUnit_0")
        for k in range(2):
            u.create_dataset(f"Channel_{k}", data=_frames(n, h, w, seed=k), **layout)
            u.attrs[f"Channel_{k}_Conversion_ConversionLinearOffset"] = OFFSET
            u.attrs[f"Channel_{k}_Conversion_ConversionLinearScale"] = 1.0
        u.attrs["Comment"] = np.array([ord(c) for c in "unit"] + [0], dtype=np.uint8)
    return path


def _h5py_reference(source, out, new_by_channel, lead=0):
    """What h5py alone writes: copy the file, assign the frames, tag nothing."""
    shutil.copy2(source, out)
    with h5py.File(out, "r+") as f:
        for ch, arr in new_by_channel.items():
            f["MSession_0/MUnit_0"][ch][lead:lead + arr.shape[0]] = arr
    return out


def _chunks(path, ch):
    """Every stored chunk of a channel as (filter mask, bytes), or the raw array if contiguous."""
    with h5py.File(path, "r") as f:
        ds = f["MSession_0/MUnit_0"][ch]
        if ds.chunks is None:
            return ds[()].tobytes()
        out = []
        for i in range(ds.id.get_num_chunks()):
            info = ds.id.get_chunk_info(i)
            out.append((info.chunk_offset, ds.id.read_direct_chunk(info.chunk_offset)))
        return sorted(out)


@pytest.fixture
def compress_calls(monkeypatch):
    calls = []
    real = zlib.compress

    def spy(data, level=-1, **kw):
        calls.append(level)
        return real(data, level, **kw)

    monkeypatch.setattr(wb.zlib, "compress", spy)
    return calls


def _new(n=150, h=32, w=40):
    return {"Channel_0": np.roll(_frames(n, h, w, 0), 2, axis=2),
            "Channel_1": np.roll(_frames(n, h, w, 1), -1, axis=1)}


@pytest.mark.parametrize("level", [1, 4, 9])
def test_threaded_deflate_stores_the_bytes_h5py_would(tmp_path, compress_calls, level):
    src = _make(tmp_path / "src.mesc", chunks=(1, 32, 40), compression="gzip",
                compression_opts=level)
    new = _new()
    write_frames(src, tmp_path / "fast.mesc", {"MUnit_0": new}, reader_units=False, tag=None)
    _h5py_reference(src, tmp_path / "ref.mesc", new)
    assert compress_calls and set(compress_calls) == {level}   # the threaded path was taken
    for ch in new:
        fast, ref = _chunks(tmp_path / "fast.mesc", ch), _chunks(tmp_path / "ref.mesc", ch)
        assert len(fast) == 150
        assert fast == ref
        assert all(mask == 0 for _, (mask, _) in fast)


def test_threaded_deflate_converts_reader_units_block_by_block(tmp_path, compress_calls):
    """Reader values are converted 64 frames at a time; the stored result is the whole-array one."""
    src = _make(tmp_path / "src.mesc", chunks=(1, 32, 40), compression="gzip",
                compression_opts=1)
    stored = _new()
    reader = {ch: a.astype(np.float64) + OFFSET + 0.3 for ch, a in stored.items()}
    write_frames(src, tmp_path / "fast.mesc", {"MUnit_0": reader}, reader_units=True, tag=None)
    whole = {ch: from_reader_units(a, offset=OFFSET, dtype=np.uint16)
             for ch, a in reader.items()}
    _h5py_reference(src, tmp_path / "ref.mesc", whole)
    for ch in stored:
        assert _chunks(tmp_path / "fast.mesc", ch) == _chunks(tmp_path / "ref.mesc", ch)


def test_threaded_deflate_aligns_a_shorter_movie_to_the_end(tmp_path, compress_calls):
    src = _make(tmp_path / "src.mesc", chunks=(1, 32, 40), compression="gzip",
                compression_opts=1)
    new = {ch: a[11:] for ch, a in _new().items()}
    rep = write_frames(src, tmp_path / "fast.mesc", {"MUnit_0": new}, reader_units=False, tag=None)
    _h5py_reference(src, tmp_path / "ref.mesc", new, lead=11)
    assert rep["warnings"]
    for ch in new:
        assert _chunks(tmp_path / "fast.mesc", ch) == _chunks(tmp_path / "ref.mesc", ch)


@pytest.mark.parametrize("layout", [
    dict(chunks=(4, 32, 40), compression="gzip", compression_opts=1),   # several frames a chunk
    dict(chunks=(1, 16, 40), compression="gzip", compression_opts=1),   # part of a frame
    dict(chunks=(1, 32, 40), compression="gzip", compression_opts=1, shuffle=True),
    dict(chunks=(1, 32, 40), compression="gzip", compression_opts=1, fletcher32=True),
    dict(chunks=(1, 32, 40), compression="lzf"),
    dict(chunks=(1, 32, 40)),                                            # chunked, no filter
    dict(),                                                              # contiguous
], ids=["4-frame", "half-frame", "shuffle", "fletcher32", "lzf", "unfiltered", "contiguous"])
def test_other_layouts_go_through_h5py(tmp_path, compress_calls, layout):
    src = _make(tmp_path / "src.mesc", **layout)
    new = _new()
    write_frames(src, tmp_path / "out.mesc", {"MUnit_0": new}, reader_units=False, tag=None)
    _h5py_reference(src, tmp_path / "ref.mesc", new)
    assert compress_calls == []                                # zlib was never called directly
    for ch in new:
        if layout.get("compression") == "lzf":
            # h5py's LZF leaves its hash table uninitialised, so even two plain h5py writes of
            # the same frames can store different (equally valid) bytes. Compare the frames.
            with h5py.File(tmp_path / "out.mesc", "r") as a, \
                    h5py.File(tmp_path / "ref.mesc", "r") as b:
                assert np.array_equal(a["MSession_0/MUnit_0"][ch][()],
                                      b["MSession_0/MUnit_0"][ch][()])
            continue
        assert _chunks(tmp_path / "out.mesc", ch) == _chunks(tmp_path / "ref.mesc", ch)


def test_a_zlib_that_disagrees_with_hdf5s_falls_back_to_h5py(tmp_path, monkeypatch):
    """If Python's zlib would store other bytes than HDF5's (a different zlib), h5py writes."""
    src = _make(tmp_path / "src.mesc", chunks=(1, 32, 40), compression="gzip",
                compression_opts=1)
    real = zlib.compress
    monkeypatch.setattr(wb.zlib, "compress", lambda d, level=-1: real(d, 9 if level != 9 else 1))
    new = _new()
    write_frames(src, tmp_path / "out.mesc", {"MUnit_0": new}, reader_units=False, tag=None)
    _h5py_reference(src, tmp_path / "ref.mesc", new)
    for ch in new:
        assert _chunks(tmp_path / "out.mesc", ch) == _chunks(tmp_path / "ref.mesc", ch)


def test_the_write_path_is_reported_per_channel(tmp_path):
    src = _make(tmp_path / "src.mesc", chunks=(1, 32, 40), compression="gzip",
                compression_opts=1)
    shutil.copy2(src, tmp_path / "out.mesc")
    a = _new()["Channel_0"]
    with wb._Output(tmp_path / "out.mesc", tag=None) as dest:
        dest.write("MSession_0/MUnit_0", "Channel_0", a, lambda b: b, 0)
    assert dest.paths_taken == {"MSession_0/MUnit_0/Channel_0": "deflate"}
    with wb._Output(tmp_path / "out.mesc", tag=None, threads=1) as dest:   # no pool: h5py
        dest.write("MSession_0/MUnit_0", "Channel_0", a, lambda b: b, 0)
    assert dest.paths_taken == {"MSession_0/MUnit_0/Channel_0": "h5py"}


def test_a_refusal_still_writes_nothing(tmp_path):
    """Validation still covers every channel before the copy is made."""
    src = _make(tmp_path / "src.mesc", chunks=(1, 32, 40), compression="gzip",
                compression_opts=1)
    new = _new()
    new["Channel_1"] = new["Channel_1"].astype(np.int64) + 500          # wrong units
    with pytest.raises(wb.WritebackError):
        write_frames(src, tmp_path / "bad.mesc", {"MUnit_0": new}, reader_units=False)
    assert not (tmp_path / "bad.mesc").exists()
