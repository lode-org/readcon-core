"""mpirun -n N python tests/python/mpi_rw_check.py IN OUT

Distributed read of IN with ``comm=`` (mpi4py), collective write to
OUT.mpiio and OUT.gather, and a serial write of the serial read to
OUT.serial on rank 0. Compare the three with sha256sum. Needs readcon
built with the ``mpi`` feature and mpi4py on the same MPI.
"""

import hashlib
import sys

from mpi4py import MPI

import readcon


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def main():
    src, out = sys.argv[1], sys.argv[2]
    assert readcon.has_mpi_support()
    world = MPI.COMM_WORLD
    # A split communicator in reversed order: comm= must not assume the world.
    comm = world.Split(0, world.Get_size() - world.Get_rank())
    mine = readcon.read_con(src, n_threads=2, comm=comm)
    counts = comm.allgather(len(mine))
    serial = readcon.read_con(src)
    assert sum(counts) == len(serial)

    for mode in ("mpiio", "gather"):
        readcon.write_con(f"{out}.{mode}", mine, comm=comm, mode=mode)

    try:
        readcon.read_con("/nonexistent/x.con", comm=comm)
    except OSError:
        pass
    else:
        raise AssertionError("bad path did not raise on every rank")

    if comm.Get_rank() == 0:
        readcon.write_con(f"{out}.serial", serial)
        digests = {sha(f"{out}.{m}") for m in ("mpiio", "gather", "serial")}
        assert len(digests) == 1, digests
        print(f"mpi_rw_check ok on {comm.Get_size()} ranks sha256={digests.pop()[:16]}")
    comm.Free()


if __name__ == "__main__":
    main()
