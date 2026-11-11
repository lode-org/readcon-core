"""The moved-frame paths keep the same frame data as a bulk read.

`iter_con`, the streaming reader, and trajectory indexing take the parsed
frame by value. These checks pin that hand-off against `read_all_frames`.
"""

import os

import numpy as np
import readcon

RESOURCES = os.path.join(os.path.dirname(__file__), "..", "..", "resources", "test")


def _bits(value):
    if value is None:
        return None
    return float(value).hex()


def _atom(atom):
    return (
        atom.symbol,
        atom.atom_id,
        tuple(bool(flag) for flag in atom.fixed),
        _bits(atom.x),
        _bits(atom.y),
        _bits(atom.z),
        _bits(atom.vx),
        _bits(atom.vy),
        _bits(atom.vz),
        _bits(atom.fx),
        _bits(atom.fy),
        _bits(atom.fz),
        _bits(atom.energy),
    )


def _frame(frame):
    xyz = np.ascontiguousarray(frame.xyz)
    vel = None if frame.vel is None else np.ascontiguousarray(frame.vel)
    return {
        "cell": tuple(_bits(v) for v in frame.cell),
        "angles": tuple(_bits(v) for v in frame.angles),
        "prebox": tuple(frame.prebox_header),
        "postbox": tuple(frame.postbox_header),
        "spec": frame.spec_version,
        "xyz": xyz.tobytes(),
        "vel": None if vel is None else vel.tobytes(),
        "atoms": tuple(_atom(atom) for atom in frame.atoms),
        "meta": dict(frame.metadata),
    }


def _same(left, right, where):
    assert len(left) == len(right), where
    for i, (a, b) in enumerate(zip(left, right)):
        assert a == b, f"{where} frame {i}"


def test_moved_paths_match_read_all_frames(tmp_path):
    names = ("tiny_multi_cuh2.con", "tiny_multi_cuh2.convel", "tiny_cuh2_vel_forces.con")
    for name in names:
        src = os.path.join(RESOURCES, name)
        text = open(src).read()
        path = tmp_path / name
        path.write_text(text * 4)
        path = str(path)
        bulk = [_frame(frame) for frame in readcon.read_all_frames(path)]
        assert len(bulk) >= 4

        iterated = [_frame(frame) for frame in readcon.iter_con(path)]
        _same(iterated, bulk, f"iter_con {name}")

        mapped = [_frame(frame) for frame in readcon.iter_con(path, mmap=True)]
        _same(mapped, bulk, f"iter_con mmap {name}")

        streamed = [_frame(frame) for frame in readcon.iter_con(path, stream=True)]
        _same(streamed, bulk, f"iter_con stream {name}")

        traj = readcon.ConTrajectory(path, write_index=False)
        indexed = [_frame(traj[i]) for i in range(len(traj))]
        _same(indexed, bulk, f"trajectory index {name}")
        walked = [_frame(frame) for frame in traj]
        _same(walked, bulk, f"trajectory iter {name}")
        assert _frame(traj[-1]) == bulk[-1]
