"""The file writer must not keep a second copy of every frame."""

import os

import pytest

import readcon


def _hwm_kib() -> int:
    for line in open("/proc/self/status", encoding="utf-8"):
        if line.startswith("VmHWM:"):
            return int(line.split()[1])
    return 0


def test_gzip_write_does_not_retain_every_frame(tmp_path):
    atoms = [
        readcon.Atom("Cu", float(i % 10), 1.0, 2.0, atom_id=i) for i in range(48)
    ]
    frame = readcon.ConFrame((20.0, 20.0, 20.0), (90.0, 90.0, 90.0), atoms)
    frames = [frame] * 6000
    before = _hwm_kib()
    dest = tmp_path / "out.con.gz"
    readcon.write_con(str(dest), frames)
    grew = _hwm_kib() - before
    # One converted frame is a few hundred KiB. Holding all 6000 is tens of MiB.
    assert grew < 16 * 1024, grew
    back = readcon.read_con(str(dest))
    assert len(back) == 6000
    assert back[0].atoms[3].x == pytest.approx(3.0)
    assert back[-1].atoms[0].symbol == "Cu"
    assert os.path.getsize(dest) > 1000
    # Frames from read_con still hold the parser's atoms. Writing them must
    # not attach a Python atom to every site of every frame.
    again = tmp_path / "again.con.gz"
    before = _hwm_kib()
    readcon.write_con(str(again), back)
    grew = _hwm_kib() - before
    assert grew < 16 * 1024, grew


def test_con_frame_list_write_does_not_build_every_python_frame(tmp_path):
    atoms = [
        readcon.Atom("Cu", float(i % 10), 1.0, 2.0, atom_id=i) for i in range(48)
    ]
    frame = readcon.ConFrame((20.0, 20.0, 20.0), (90.0, 90.0, 90.0), atoms)
    src = tmp_path / "src.con.gz"
    readcon.write_con(str(src), [frame] * 20000)
    loaded = readcon.read_con(str(src), n_threads=1)
    dest = tmp_path / "out.con.gz"
    before = _hwm_kib()
    readcon.write_con(str(dest), loaded)
    grew = _hwm_kib() - before
    # Building a Python frame per index is about a kilobyte each, so
    # 20000 frames is well past 8 MiB. Streaming the stored frames is not.
    assert grew < 8 * 1024, grew
    assert len(readcon.read_con(str(dest))) == 20000
