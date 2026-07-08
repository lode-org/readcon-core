======================
Performance Benchmarks
======================



Measurement hierarchy
---------------------

.. table::

    +--------+-----------------------------------------------------------------------------------+---------------------------------------------------------------------------------------+
    |   Rank | Command / artifact                                                                | Answers                                                                               |
    +========+===================================================================================+=======================================================================================+
    | 1 (CI) | ``examples/cachegrind_harness.rs`` via ``scripts/run_cachegrind_bench.sh``        | Instruction-count deltas on fixed CON parse / skip / write / float paths              |
    +--------+-----------------------------------------------------------------------------------+---------------------------------------------------------------------------------------+
    |      2 | ``benches/compare_readers.py``                                                    | CON parse order vs ASE ``ase.io.eon`` and eOn-style C sscanf on equal CON text        |
    +--------+-----------------------------------------------------------------------------------+---------------------------------------------------------------------------------------+
    |      3 | ``benches/multiformat_traj.py`` → ``benches/results/multiformat_traj_terra.json`` | Equal-geometry multi-frame wall times vs other ASCII readers (measurement peers only) |
    +--------+-----------------------------------------------------------------------------------+---------------------------------------------------------------------------------------+

Product speed claims use ranks 1–2 first (CON path and CON peers). Rank 3
records additional ASCII peers on the same geometry; it does not define the
CON contract. Criterion microbenches are local latency history.

CI Cachegrind (regression authority)
------------------------------------

On every ``main`` push, CI runs Valgrind **Cachegrind** on
``examples/cachegrind_harness.rs`` and commits instruction counts into the docs.

.. include:: _generated/cachegrind_results.rst

Reproduce (needs Valgrind; minutes on a quiet machine):

.. code:: shell

    scripts/run_cachegrind_bench.sh
    # outputs docs/source/_generated/cachegrind_results.{json,rst}

**Why Cachegrind instead of Criterion on CI?** Wall-clock medians on shared
GitHub runners move with neighbours and CPU migration. Cachegrind counts
**instruction references** for a fixed binary, which diffs cleanly across
commits. Criterion still works for local latency; PR workflow ``Benchmark PR``
compares Criterion baselines with ``critcmp``.

Conversion cost appears as ``chemfiles_*`` Cachegrind scenarios when the
``chemfiles`` feature is linked. CON I/O remains the core library cost.

CON peer timing (``compare_readers.py``)
----------------------------------------

Ordering against ASE ``ase.io.eon`` and an eOn-style C reader on the **same CON text**. Historical single-host snapshot; re-run to refresh:

.. table::

    +----------------------------+-----------+-------------------+
    | Reader                     | Time (ms) | vs ASE (that run) |
    +============================+===========+===================+
    | ASE (``ase.io.eon``)       |      36.1 | 1.0×              |
    +----------------------------+-----------+-------------------+
    | C sscanf (eOn-style)       |      10.6 | 3.4×              |
    +----------------------------+-----------+-------------------+
    | readcon-core (file path)   |       4.4 | 8.2×              |
    +----------------------------+-----------+-------------------+
    | readcon-core (from string) |       4.1 | 8.7×              |
    +----------------------------+-----------+-------------------+

.. figure:: img/parsing_throughput.svg

    Parsing throughput across trajectory sizes (log scale; illustrative)

Structural reasons the C/Rust path can beat ASE/=sscanf= **in principle**:

- **fast-float2**: tuned decimal kernel vs typical ``sscanf`` dispatch

- **Zero-copy iteration**: borrows lines from the input ``&str``, no ``fgets`` buffer copies

- **Pre-allocated vectors**: atom count known from header before parsing

- **No stdio overhead**: entire file in memory (mmap or read\_to\_string) vs per-line ``fgets``

Skip path: ``forward()`` / ``forward_fast`` avoid materializing atoms when only
counts or selected frames are needed (see Cachegrind ``forward_*`` scenarios).

Equal-geometry multi-frame (``multiformat_traj.py``)
----------------------------------------------------

Secondary wall-clock check on one geometry against other ASCII structure
readers (ASE CON among them). Artifact:
``benches/results/multiformat_traj_terra.json``. On that recorded 218×100 run,
readcon CON full-parse median is about 12× ASE CON on that host. Prefer the
CON peer table above for CON-reader comparisons.

.. code:: shell

    uv run --with ase --with numpy python benches/multiformat_traj.py

Pareto / throughput SVGs use measured points from that JSON plus
``compare_readers.py``; ASE CON is labeled CON.

Public API model and hot path (what the code does)
--------------------------------------------------

****Public API (full frames only)****

- Load: ``read_all_frames`` / ``ConFrameIterator`` / Python ``iter_con`` /
  ``read_first_frame`` (always full ``ConFrame`` fidelity).

- Skip payload: ``count_frames`` / ``forward_fast`` when you do not need atoms.

- Coordinates on a **loaded** frame: SoA on ``ConFrame`` / Python ``coords_array()``.

- No separate public “coords-only” trajectory load.

****Fast cut (public model: full frames only)****

1. **Full multi-frame load:** ``read_all_frames`` — mmap large files; ****Rayon multi-frame parse**** when the buffer is ≥ 48 KiB (``parallel`` / Python wheels).

2. **Skip when you only need a count:** ``count_frames`` / ``forward_fast`` (``memchr``
   newline walk, no atom materialize).

3. **Python:** ``Python::detach`` around Rust multi-frame parse; ``iter_con`` streams
   full frames; coordinates via ``coords_array()`` on a loaded frame.

****Internal parse implementation (users do not see these)****

- Shared ``MemchrLines`` cursor for full parse and skip (one buffer view).

- Atom lines: single-pass byte scan + ``fast_float2::parse_partial`` (stack
  buffer; same float kernel, no extra public API).

- Default f64 positions: flat ``Vec`` then one Arc wrap; full-frame assembly
  (``con_frame_coords_only``) fills masses/ids without a second “any section?”
  scan when sections are absent; section SoA sync only when sections applied.

Criterion microbenches (local latency)
--------------------------------------

Historical `Criterion.rs <https://bheisler.github.io/criterion.rs/book/>`_ tables from ``benches/iterator_bench.rs`` (single core,
default settings). Useful for local latency intuition and PR ``critcmp``. Prefer
Cachegrind I-refs and ``compare_readers`` for CON-path comparisons.

Run locally:

.. code:: shell

    cargo bench
    # or: pixi r bench

Frame parsing (microbench sizes)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. table::

    +------------------------+-------------+---------------------+----------------------------------+
    | Benchmark              | Dataset     | Time (illustrative) | Notes                            |
    +========================+=============+=====================+==================================+
    | Single frame parse     | 4 atoms     | ~1.5 µs             | Microbench only                  |
    +------------------------+-------------+---------------------+----------------------------------+
    | 2-frame parse (next)   | 2×4 atoms   | ~2.3 µs             | Microbench only                  |
    +------------------------+-------------+---------------------+----------------------------------+
    | 2-frame skip (forward) | 2×4 atoms   | ~0.6 µs             | Prefer Cachegrind ``forward_*``  |
    +------------------------+-------------+---------------------+----------------------------------+
    | 100-frame sequential   | 100×4 atoms | ~212 µs             | Prefer CON peer benches          |
    +------------------------+-------------+---------------------+----------------------------------+
    | 100-frame forward skip | 100×4 atoms | ~29 µs              | Prefer Cachegrind                |
    +------------------------+-------------+---------------------+----------------------------------+
    | 218-atom frame (cuh2)  | 218 atoms   | ~42 µs              | Prefer ``parse_cuh2_218`` I-refs |
    +------------------------+-------------+---------------------+----------------------------------+

Velocity overhead (illustrative)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. table::

    +--------------------+---------+--------------------------+
    | Benchmark          | Time    | Overhead vs coords-only  |
    +====================+=========+==========================+
    | Coords only (2×4)  | ~2.3 µs | (baseline)               |
    +--------------------+---------+--------------------------+
    | Coords + vel (2×4) | ~3.9 µs | ~+70% on that microbench |
    +--------------------+---------+--------------------------+
    | Vel skip (forward) | ~0.9 µs | (skip mode)              |
    +--------------------+---------+--------------------------+

Float parsing: fast-float2 vs stdlib (illustrative; see also Cachegrind)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. table::

    +-----------------------+---------------+---------+
    | Parser                | 5-column line | Speedup |
    +=======================+===============+=========+
    | fast-float2           | ~100 ns       | ~2×     |
    +-----------------------+---------------+---------+
    | str\:\:parse\:\:<f64> | ~202 ns       | 1.0×    |
    +-----------------------+---------------+---------+

readcon-core uses `fast-float2 <https://github.com/aldanor/fast-float-rust>`_ for coordinate, velocity, and force lines.
Cachegrind scenarios ``float_fast_float2`` vs ``float_std_parse`` are the
commit-stable comparison.

I/O strategy: mmap vs read\_to\_string (illustrative)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. table::

    +------------------+------------------------+----------------------------------+
    | Strategy         | 218-atom file (16 KiB) | Notes                            |
    +==================+========================+==================================+
    | read\_to\_string | ~42 µs                 | Slight edge for small files      |
    +------------------+------------------------+----------------------------------+
    | mmap             | ~44 µs                 | Fixed overhead (VMA, page fault) |
    +------------------+------------------------+----------------------------------+

For files under 64 KiB, ``read_to_string`` avoids mmap overhead. For larger
trajectory files, mmap lets the OS page cache handle data without a full heap
copy. readcon-core switches automatically at the 64 KiB threshold.
Compressed files (``.con.gz``) always decompress to an in-memory buffer.

Historical scaling tables
-------------------------

Single-host snapshots from earlier ``compare_readers`` work. Re-run before citing.

.. table::

    +------------+-----------+----------+--------+---------+--------+------+
    | Dataset    | File size | C sscanf | ASE    | readcon | vs ASE | vs C |
    +============+===========+==========+========+=========+========+======+
    | 218 × 100  | 1.6 MiB   | 10.6 ms  | 36 ms  | 4.4 ms  | 8.2×   | 2.4× |
    +------------+-----------+----------+--------+---------+--------+------+
    | 218 × 1000 | 9.7 MiB   | 73 ms    | 286 ms | 55 ms   | 5.2×   | 1.3× |
    +------------+-----------+----------+--------+---------+--------+------+
    | 10k × 100  | 46.9 MiB  | 361 ms   | 956 ms | 185 ms  | 5.2×   | 2.0× |
    +------------+-----------+----------+--------+---------+--------+------+
    | 10k × 10   | 4.7 MiB   | 36 ms    | 94 ms  | 13 ms   | 7.2×   | 2.8× |
    +------------+-----------+----------+--------+---------+--------+------+

On large files the advantage over C narrows as I/O grows; prefer re-running
``compare_readers.py`` and the equal-geometry peer script after hot-path changes.

Memory usage
------------

Peak resident set size when loading all frames into memory (historical
host snapshot; re-measure if citing):

.. table::

    +------------+------------------+--------------+
    | Dataset    | readcon peak RSS | ASE peak RSS |
    +============+==================+==============+
    | 218 × 1000 | 70 MiB           | 268 MiB      |
    +------------+------------------+--------------+
    | 10k × 100  | 263 MiB          | 270 MiB      |
    +------------+------------------+--------------+
    | 10k × 10   | 263 MiB          | 270 MiB      |
    +------------+------------------+--------------+

For the 218-atom trajectory, readcon-core used ~3.8× less peak RSS than ASE
on that host. At 10k atoms both converge because atom data dominates.

.. figure:: img/memory_usage.svg

    Peak memory usage with all frames loaded

The C sscanf reader frees each frame immediately, so its peak RSS stays small.
readcon-core can achieve constant-memory processing via the iterator API:

.. code:: rust

    // Process frames one at a time (constant memory)
    let iter = ConFrameIterator::new(&contents);
    for result in iter {
        let frame = result?;
        // process frame, then drop
    }

Memory profile
--------------

readcon-core allocates:

- One ``Arc<str>`` per atom type (not per atom) for symbol storage

- One ``Vec<AtomDatum>`` (or SoA ``FloatArray``) per frame, pre-sized from header counts

- No intermediate string allocations for atom line parsing (fast-float2
  parses directly from the borrowed ``&str`` slice)

The iterator API processes one frame at a time, so multi-frame files do not
require loading the entire trajectory into memory.

Feature coverage vs other formats
---------------------------------

The CON v2 format covers features that typically require multiple formats or
lossy workarounds in other ecosystems.

.. figure:: img/feature_comparison.svg

    Feature matrix: CON v2 vs common atomic structure formats

CON v2 achieves full coverage (10/10) across: positions, velocities, forces,
unit cell, per-direction constraints, atom identity (round-trip), structured
metadata, compression, multi-frame support, and streaming iteration.

.. figure:: img/pareto_features_vs_speed.svg

    Feature coverage vs parse speed (measured ``readcon`` / ASE CON / ASE extXYZ from multiformat\_traj; C sscanf from ``compare_readers``; ASE CON is not plotted as extXYZ)

On the equal-geometry peer run, readcon CON pairs high feature coverage with
the lowest parse time among the measured text formats. Binary formats (DCD,
TRR) are off-plot.

Statistical analysis
--------------------

For credible intervals, `bayescomp <https://github.com/HaoZeke/bayescomp>`_ fits Gamma-family models with random
intercepts per test system from Criterion JSON and ``compare_readers.py``
timing data.

Reproducing these benchmarks
----------------------------

.. code:: shell

    # Equal-geometry multi-frame (ASE, chemfiles, MDA peers)
    uv run --with ase --with numpy python benches/multiformat_traj.py

    # Cross-implementation CON (ASE, C sscanf, readcon)
    uv run --with matplotlib --with numpy --with ase python benches/compare_readers.py

    # Generate plots from measured artifacts
    uv run --with matplotlib --with numpy python benches/make_plots.py

    # CI-style Cachegrind I-refs (needs Valgrind)
    scripts/run_cachegrind_bench.sh

    # Rust microbenchmarks (Criterion; local intuition / PR critcmp)
    cargo bench
