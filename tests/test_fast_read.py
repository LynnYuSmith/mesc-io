"""The fast read path (stored chunks inflated in threads) gives exactly what h5py gives — and fails where it fails."""
import h5py
import numpy as np
import pytest

from mesc_io.reader import _per_frame_gzip, _read


@pytest.fixture
def gz(tmp_path):
    p = tmp_path / "gz.h5"
    rng = np.random.RandomState(42)
    data = rng.randint(0, 4000, (40, 16, 12)).astype(np.uint16)
    with h5py.File(p, "w") as f:
        f.create_dataset("per_frame", data=data, chunks=(1, 16, 12), compression="gzip", compression_opts=1)
        f.create_dataset("shuffled", data=data, chunks=(1, 16, 12), compression="gzip", shuffle=True)
        f.create_dataset("blocks", data=data, chunks=(4, 16, 12), compression="gzip")
        d = f.create_dataset("holes", shape=data.shape, dtype=np.uint16, chunks=(1, 16, 12),
                             compression="gzip", fillvalue=7)
        d[0:10] = data[0:10]                               # frames 10.. never written
    return p, data


@pytest.mark.parametrize("frames", [None, slice(3, 30), slice(30, 3, -4), slice(1, 40, 7),
                                    [5, 2, 2, 39], np.array([0, 39]), 7, -1])
def test_the_fast_path_returns_what_h5py_returns(gz, frames):
    p, data = gz
    with h5py.File(p, "r") as f:
        d = f["per_frame"]
        assert _per_frame_gzip(d)
        want = data if frames is None else data[frames]
        got = _read(d, frames)
        assert got.dtype == want.dtype and np.array_equal(got, want)


def test_other_layouts_go_through_h5py(gz):
    p, data = gz
    with h5py.File(p, "r") as f:
        for name in ("shuffled", "blocks"):
            assert not _per_frame_gzip(f[name])
            assert np.array_equal(_read(f[name], slice(2, 9)), data[2:9])


def test_an_unwritten_chunk_reads_as_its_fill_value(gz):
    p, data = gz
    with h5py.File(p, "r") as f:
        got = _read(f["holes"], slice(8, 12))
    assert np.array_equal(got[:2], data[8:10]) and (got[2:] == 7).all()


def test_a_corrupt_chunk_raises_as_h5py_does(gz, tmp_path):
    p, _ = gz
    with h5py.File(p, "a") as f:                           # overwrite frame 5's stored bytes with junk
        d = f["per_frame"]
        mask, raw = d.id.read_direct_chunk((5, 0, 0))
        d.id.write_direct_chunk((5, 0, 0), b"\x00" * len(raw), mask)
    with h5py.File(p, "r") as f:
        d = f["per_frame"]
        with pytest.raises(OSError):
            d[4:7]
        with pytest.raises(OSError):
            _read(d, slice(4, 7))
        assert _read(d, slice(0, 5)).shape == (5, 16, 12)   # its neighbours are unharmed


def test_many_threads_reading_at_once_do_not_crash_hdf5(gz):
    """The viewer serves requests from several threads. Without h5py's lock around the raw chunk
    reads, two of them at once segfaulted inside libhdf5 (27 Oct 2026) — this test then dies with
    the process instead of failing politely, which is still a failure."""
    import threading
    p, data = gz
    with h5py.File(p, "r") as f:
        d = f["per_frame"]
        errs = []

        def hammer(k):
            try:
                for _ in range(200):
                    if k % 2:
                        assert np.array_equal(_read(d, slice(0, 40)), data)
                    else:
                        assert np.array_equal(d[k % 40], data[k % 40])     # h5py's own path alongside
            except Exception as e:  # noqa: BLE001
                errs.append(e)
        ts = [threading.Thread(target=hammer, args=(k,)) for k in range(8)]
        [t.start() for t in ts]
        [t.join() for t in ts]
    assert not errs
