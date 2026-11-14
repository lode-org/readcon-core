==========================================
MPI: distributed read and collective write
==========================================



Requirement words
-----------------

The words MUST, MUST NOT, SHOULD, SHOULD NOT, and MAY on this page follow `RFC 2119 <https://www.rfc-editor.org/rfc/rfc2119>`_.

Overview
--------

readcon-core can read and write one CON file across the ranks of an MPI
communicator (behind the ``mpi`` feature flag).
Each rank owns a contiguous block of frames, and the frames of ranks
``0..P`` in rank order are always the frames of a serial read.
A collective write of those blocks produces the same bytes (sha256) as a
serial write, for any rank count.

The library MUST NOT call ``MPI_Init`` or ``MPI_Finalize`` and MUST NOT assume
``MPI_COMM_WORLD``.
Every entry point takes the communicator the host passes in (an eOn band
communicator, a LAMMPS sub-communicator, an mpi4py ``Split``), and the
library works on its own duplicate of it.

Building
--------

.. code:: bash

    cargo build --release --features mpi

The ``mpi`` feature uses rsmpi, which needs an MPI implementation (MPICH or
Open MPI) and libclang at build time.
The default build has no MPI dependency.
``include/readcon-core-mpi.h`` is header-only and compiles against the
caller's MPI.

Frame ownership
---------------

Rank ``r`` of ``P`` owns frames ``[r*q + min(r, m), ...)`` where ``q = n / P`` and
``m = n % P``; the first ``m`` ranks get one extra frame.
Ranks MAY own no frames (more ranks than frames).
``rkr_block_range`` (C) and ``distrib::block_range`` (Rust) compute it without
MPI.

Reading
-------

.. table::

    +-------------+-----------------------------------------+----------------------------------------------------------------------------------------------+
    | Mode        | When                                    | Data movement                                                                                |
    +=============+=========================================+==============================================================================================+
    | ``shared``  | file visible on every rank              | none: rank 0 broadcasts the ``.rcidx`` offsets, each rank maps the file and parses its block |
    +-------------+-----------------------------------------+----------------------------------------------------------------------------------------------+
    | ``scatter`` | gzip/zstd input, or file only on rank 0 | rank 0 reads and sends each block with ``MPI_Scatterv``                                      |
    +-------------+-----------------------------------------+----------------------------------------------------------------------------------------------+
    | ``auto``    | default                                 | ``scatter`` for compressed input, ``shared`` otherwise                                       |
    +-------------+-----------------------------------------+----------------------------------------------------------------------------------------------+

Within a rank the parse runs on rayon (``n_threads``, 0 for the global pool).
Equal frames still tile when the file ends in whitespace.
One frame is split by atom lines, so a million-atom frame uses every rank.

Writing
-------

.. table::

    +------------+------------------------------+-----------------------------------------------------------------------------------------------------------+
    | Mode       | When                         | Path                                                                                                      |
    +============+==============================+===========================================================================================================+
    | ``mpiio``  | the default collective write | one ``MPI_Allgather`` of each rank's byte length and frame count, then each rank stores into a fresh file |
    +------------+------------------------------+-----------------------------------------------------------------------------------------------------------+
    | ``gather`` | no MPI-IO                    | rank 0 collects the blocks (``MPI_Gatherv``, point-to-point above 2 GiB) and writes                       |
    +------------+------------------------------+-----------------------------------------------------------------------------------------------------------+
    | ``auto``   | default                      | ``mpiio``                                                                                                 |
    +------------+------------------------------+-----------------------------------------------------------------------------------------------------------+

Every rank formats its frames with the same writer as a serial file.
A one-frame file formats that rank's atom range.
The default store is a fresh file, not a spare reused in place.
Rank 0 renames it onto the path only after every byte is stored, so the
published path is the previous complete file or the finished new one.
Until that rename the new bytes are a second copy.
On ext2, ext3, ext4, XFS, and btrfs, rank 0 then writes every slice in
order. Concurrent writes of one fresh local inode contend in the page
cache. In ``bench/h2h/scaling/camp21/strong-mpi.json`` that million-atom
frame on disk takes 0.0401 s at one rank and 0.0119 s at eight ranks,
3.4 times as fast.
Every other filesystem, including tmpfs, Lustre, GPFS, BeeGFS, and NFS,
keeps one write per rank.
``READCON_RANKED_WRITE=parallel`` or ``sequential``, read on rank 0, overrides
that choice. Leave it unset. The benchmark does.
``READCON_MPI_TEST_CHUNK=<bytes>`` lowers the gather chunk and the Gatherv
limit so a test can take the multi-round path. Leave it unset.
One gather of the offsets and block hashes then writes the ``.rcidx``
sidecar, so the next read skips the scan.
Output is uncompressed.

Errors
------

Every call is collective, and so are its failures: if any rank fails
(bad path, parse error, write error), every rank returns an error and
owns no frames.

C
-

.. code:: c

    #include "readcon-core-mpi.h"

    size_t n; uint64_t first, total, bytes;
    struct RKRConFrame **mine =
        rkr_mpi_read_block(comm, "neb.con", RKR_MPI_READ_AUTO, 0, &n, &first, &total);
    /* ... */
    rkr_mpi_write_block(comm, "out.con", (const struct RKRConFrame *const *)mine, n,
                        RKR_MPI_WRITE_MPIIO, -1, &bytes);
    free_rkr_frame_array(mine, n);

The ``_f`` variants (``rkr_mpi_read_block_f``, ``rkr_mpi_write_block_f``) take a
Fortran ``MPI_Fint`` handle and are the symbols exported by the library.

C++
---

.. code:: cpp

    #include "readcon-core-mpi.h"

    auto images = readcon::mpi::Frames::read(band_comm, "neb.con");  // RAII, move-only
    // images.first(), images.size(), images.total(), images[i]
    readcon::mpi::write(band_comm, "out.con", images, RKR_MPI_WRITE_MPIIO);

Both throw ``std::runtime_error`` on every rank when the call fails.
``examples/eon_mpi_band.cpp`` is a complete eOn-style NEB band example.
Under C++ the C types live in namespace ``readcon``, as in
``readcon-core.h``.

Fortran
-------

Module ``readcon_mpi`` (``fortran/ReadCon/mpi/readcon_mpi.f90``) builds with
an MPI Fortran compiler next to module ``readcon``.
``mpi_read_block`` and ``mpi_write_block`` accept an ``mpi_f08``
``type(MPI_Comm)`` or a legacy ``INTEGER`` communicator; both end up as
``MPI_Fint`` (``comm%MPI_VAL``).

.. code:: fortran

    use mpi_f08
    use readcon
    use readcon_mpi
    type(frame_t), allocatable :: mine(:)
    integer(c_int64_t) :: first, total
    integer :: stat
    call mpi_read_block(comm, 'neb.con', mine, first, total, stat)
    call mpi_write_block(comm, 'out.con', mine, stat, mode=rkr_mpi_write_mpiio)

.. code:: bash

    mpifort -c fortran/ReadCon/src/readcon.f90
    mpifort -c fortran/ReadCon/mpi/readcon_mpi.f90
    mpifort app.f90 readcon_mpi.o readcon.o -L target/release -lreadcon_core

Python
------

Build the wheel with ``--features python,mpi`` against the same MPI as
mpi4py; ``readcon.has_mpi_support()`` reports it.

.. code:: python

    from mpi4py import MPI
    import readcon

    comm = MPI.COMM_WORLD.Split(0, MPI.COMM_WORLD.rank)
    mine = readcon.read_con("neb.con", comm=comm)            # this rank's block
    readcon.write_con("out.con", mine, comm=comm, mode="mpiio")
    # rewrite=True keeps a spare inode at out.con.rewrite. The default does not.

``comm`` is converted with ``comm.py2f()``.
``read_all_frames`` takes the same ``comm`` and ``mode`` keywords.

Testing
-------

``.github/workflows/ci_mpi.yml`` runs on MPICH and Open MPI with 1 to 4
ranks and compares sha256 against the serial path for C, C++, Fortran,
Python and Rust.
