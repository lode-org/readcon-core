import gzip
import os
import shutil

import pytest
import readcon

RESOURCES = os.path.join(os.path.dirname(__file__), "..", "..", "resources", "test")


def _key(frame):
    return readcon.write_con_string([frame])


@pytest.fixture
def long_con(tmp_path):
    with open(os.path.join(RESOURCES, "tiny_multi_cuh2.con")) as fh:
        one = fh.read()
    path = tmp_path / "long.con"
    path.write_text(one * 300)
    return path


def _check(path, **kw):
    want = [_key(f) for f in readcon.read_all_frames(str(path))]
    traj = readcon.ConTrajectory(path, **kw)
    n = len(want)
    assert len(traj) == n
    assert [_key(traj[i]) for i in range(n)] == want
    assert _key(traj[0]) == want[0]
    assert _key(traj[-1]) == want[-1]
    assert _key(traj[-n]) == want[0]
    assert [_key(f) for f in traj] == want
    assert [_key(f) for f in traj[1:7:2]] == want[1:7:2]
    assert [_key(f) for f in traj[::-5]] == want[::-5]
    assert traj[n:] == []
    for bad in (n, -n - 1, 2**62):
        msg = f"^frame index {bad} is out of range for a trajectory of {n} frames$"
        with pytest.raises(IndexError, match=msg):
            traj[bad]
    with pytest.raises(TypeError):
        traj["0"]
    return traj


def test_fixtures(tmp_path):
    for name in ("tiny_multi_cuh2.con", "tiny_multi_cuh2.convel"):
        path = tmp_path / name
        shutil.copy(os.path.join(RESOURCES, name), path)
        _check(path, write_index=False)
        assert not os.path.exists(str(path) + ".rcidx")


def test_sidecar_written_and_reused(long_con):
    side = str(long_con) + ".rcidx"
    assert len(_check(long_con, write_index=False)) == 600
    assert not os.path.exists(side)
    _check(long_con)
    assert os.path.exists(side)
    _check(long_con)


def test_gzip(tmp_path, long_con):
    gz = tmp_path / "long.con.gz"
    gz.write_bytes(gzip.compress(long_con.read_bytes()))
    assert len(_check(gz)) == 600
    assert not os.path.exists(str(gz) + ".rcidx")


def test_errors(tmp_path):
    with pytest.raises(IOError):
        readcon.ConTrajectory(tmp_path / "missing.con")
    with open(os.path.join(RESOURCES, "tiny_multi_cuh2.con")) as fh:
        text = fh.read()
    bad = tmp_path / "bad.con"
    bad.write_text(text.replace("6.9752", "6.9x52", 1))
    traj = readcon.ConTrajectory(bad, write_index=False)
    assert len(traj) == 2
    traj[0]
    with pytest.raises(IOError, match="frame 1"):
        traj[1]
