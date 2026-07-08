======================
Performance Benchmarks
======================



What we measure
---------------

.. table::

    +--------+----------------------------------------------------------------------------+--------------------------------------------------------------------------+
    |   Rank | Command / artifact                                                         | Answers                                                                  |
    +========+============================================================================+==========================================================================+
    | 1 (CI) | ``examples/cachegrind_harness.rs`` via ``scripts/run_cachegrind_bench.sh`` | Instruction-count deltas on fixed CON parse / skip / write / float paths |
    +--------+----------------------------------------------------------------------------+--------------------------------------------------------------------------+
    | 2 (PR) | ``benchmarks/`` + ``asv.conf.json`` (ASV) → ``asv-spyglass compare``       | Python surface wall-time on PR vs base                                   |
    +--------+----------------------------------------------------------------------------+--------------------------------------------------------------------------+
    |      3 | ``benches/compare_readers.py``                                             | Same CON text vs ASE ``ase.io.eon`` and eOn-style C sscanf               |
    +--------+----------------------------------------------------------------------------+--------------------------------------------------------------------------+
    |      4 | ``benches/multiformat_traj.py``                                            | Equal-geometry wall times: ASE XYZ/extXYZ/CON vs readcon CON             |
    +--------+----------------------------------------------------------------------------+--------------------------------------------------------------------------+
    |      5 | ``benches/ase_traj_vs_con.py``                                             | ASE ``.traj`` / NetCDF / XYZ vs ``readcon.read_chemfiles`` vs native CON |
    +--------+----------------------------------------------------------------------------+--------------------------------------------------------------------------+
    |      6 | ``benches/h5md_vs_con.py``                                                 | MDAnalysis H5MD / h5py positions vs CON / chemfiles XYZ                  |
    +--------+----------------------------------------------------------------------------+--------------------------------------------------------------------------+
    |  local | ``cargo bench`` (Criterion)                                                | Rust microbench latency; optional PR job saves baselines                 |
    +--------+----------------------------------------------------------------------------+--------------------------------------------------------------------------+

Regression gates in CI:

- **Cachegrind I-refs** — path-filtered + weekly job (``ci_cachegrind.yml``); commits
  ``docs/source/_generated/cachegrind_results.*`` on ``main`` when counts change.

- **Python ASV + spyglass** — every PR (``ci_benchmark.yml``); comment via asv-perch.

Peer scripts under ``benches/`` are for local re-runs. JSON under
``benches/results/`` is what you produce when you run them — this page does not
embed host wall-clock tables.

CI Cachegrind (instruction-count gate)
--------------------------------------

Workflow ``ci_cachegrind.yml`` runs Valgrind **Cachegrind** on
``examples/cachegrind_harness.rs`` when CON-path sources (or this doc) change on
``main``, on a weekly schedule, or on manual dispatch. With
``CACHEGRIND_FEATURES=chemfiles`` it also records conversion scenarios.

Current committed include (refreshed by that job):

.. include:: _generated/cachegrind_results.rst

Reproduce (needs Valgrind):

.. code:: shell

    scripts/run_cachegrind_bench.sh
    # writes docs/source/_generated/cachegrind_results.{json,rst}

I-refs for a fixed binary are stable across noisy shared runners; wall-clock
medians on GHA are not. That is why Cachegrind is the commit-stable gate and
ASV is the PR Python surface compare.

Python ASV (PR surface)
-----------------------

Workflow ``Benchmark PR`` (``ci_benchmark.yml``):

1. Matrix builds **base** and **PR** with
   ``maturin develop --features python,chemfiles --release``.

2. Runs `ASV <https://asv.readthedocs.io/>`_ on ``benchmarks/`` with
   ``-E existing:$(which python)`` (no re-install mid-bench).

3. ``asv-spyglass compare`` writes ``results/comparison.txt`` (job fails if empty).

4. ``ci_bench_commenter.yml`` posts that file via `asv-perch <https://github.com/HaoZeke/asv-perch>`_.

A separate ``criterion-benchmark`` job may save Criterion baselines; it uses
``continue-on-error: true`` so a Rust microbench miss does not fail the workflow
conclusion that asv-perch requires.

Suite (calls shipped ``readcon`` only):

.. table::

    +----------------------+---------------------------------------------------------------------------+
    | Class                | API timed                                                                 |
    +======================+===========================================================================+
    | ``TimeReadConTiny``  | ``read_con_string`` / ``read_con`` / ``iter_con`` on multi-frame tiny CON |
    +----------------------+---------------------------------------------------------------------------+
    | ``TimeReadConCuh2``  | ``read_con`` on multi-frame ``cuh2.con`` (218 atoms/frame)                |
    +----------------------+---------------------------------------------------------------------------+
    | ``TimeChemfilesXyz`` | ``read_chemfiles`` multi-frame XYZ → ``ConFrame`` (skipped if lean)       |
    +----------------------+---------------------------------------------------------------------------+
    | ``TimeSelectAtoms``  | ``frame.select_atoms("name Cu")`` (skipped if lean)                       |
    +----------------------+---------------------------------------------------------------------------+

Local:

.. code:: shell

    maturin develop --features python,chemfiles --release
    # uv pip install asv numpy ase
    asv machine --yes
    asv run -E "existing:$(which python)" --set-commit-hash "$(git rev-parse HEAD)" \
      --record-samples --quick
    uvx --from "git+https://github.com/airspeed-velocity/asv_spyglass.git" \
      asv-spyglass compare .asv/results/*/<base>*.json .asv/results/*/<pr>*.json \
      .asv/results/benchmarks.json \
      --label-before main --label-after pr

Config: ``asv.conf.json``. Results: ``.asv/`` (gitignored).

Peer scripts (local)
--------------------

Run on your machine; write JSON under ``benches/results/`` if you want a citeable
artifact. Ordering vs ASE / C sscanf / MDA is a property of **that run**, not a
global ranking.

.. code:: shell

    # Same CON text vs ASE ase.io.eon and eOn-style C sscanf
    uv run --with matplotlib --with numpy --with ase python benches/compare_readers.py

    # Equal-geometry multi-frame: ASE XYZ/extXYZ/CON vs readcon CON
    python benches/multiformat_traj.py --fixtures cuh2 --ladder 100 --repeats 5 \
      --out benches/results/multiformat_traj.json

    # ASE .traj / NetCDF / multi-frame XYZ vs chemfiles→CON vs native CON
    maturin develop --features python,chemfiles --release
    python benches/ase_traj_vs_con.py --frames 100 --repeats 5

    # H5MD via MDAnalysis / h5py vs CON
    uv pip install MDAnalysis h5py ase numpy
    python benches/h5md_vs_con.py --frames 100 --repeats 5

Implementation details that show up in Cachegrind and peer scripts (facts about
the code, not a promise about every host):

- Atom floats: `fast-float2 <https://github.com/aldanor/fast-float-rust>`_
  (``float_fast_float2`` vs ``float_std_parse`` Cachegrind scenarios)

- Line views: zero-copy over the input buffer (``MemchrLines``)

- Atom vectors: sized from the CON header before filling

- File load: ``read_to_string`` below 64 KiB, mmap at/above (``MMAP_THRESHOLD`` in
  ``src/compression.rs``)

- Multi-frame parallel parse: Rayon when buffer ≥ 48 KiB and ``parallel`` is on
  (``PARALLEL_BYTES_THRESHOLD`` in ``src/iterators.rs``)

- Skip without atoms: ``forward`` / ``forward_fast`` (Cachegrind ``forward_*``)

h5py ``position/value`` alone is a coordinate array, not CON fidelity (no cell /
constraints / ``atom_id`` / JSON sections). MDAnalysis H5MD is the fair H5MD **API**
peer for full-frame style loads.

Plots under ``docs/orgmode/img/`` are produced by ``benches/make_plots.py`` from
JSON you generate; regenerate after peer runs if you need them current.

.. figure:: img/parsing_throughput.svg

    Parsing throughput (from peer JSON via ``make_plots.py``)

.. figure:: img/pareto_features_vs_speed.svg

    Feature coverage vs parse speed (from peer JSON via ``make_plots.py``)

Public API model and hot path
-----------------------------

****Load (full frames)****

- ``read_all_frames`` / ``ConFrameIterator`` / Python ``iter_con`` / ``read_first_frame``

- Skip payload: ``count_frames`` / ``forward_fast`` when atoms are not needed

- Coordinates on a **loaded** frame: SoA / Python ``coords_array()``

- No separate public “coords-only” trajectory load

****Python****

Multi-frame parse paths release the GIL via ``py.detach`` (``src/python.rs``) around
the Rust work; ``iter_con`` yields full frames.

Criterion (local Rust latency)
------------------------------

``cargo bench`` runs ``benches/iterator_bench.rs``. Prefer Cachegrind for I-ref
regressions and ASV for the Python PR surface. The PR Criterion job is optional
artifact collection only; the posted comment is ASV/spyglass.

Memory
------

Peak RSS depends on host and whether all frames are materialised. Streaming:

.. code:: rust

    let iter = ConFrameIterator::new(&contents);
    for result in iter {
        let frame = result?;
        // process, then drop
    }

Per frame the library keeps type symbols as shared ``Arc<str>`` (per type, not
per atom), pre-sized atom storage from headers, and parses floats from borrowed
line slices (no intermediate atom-line ``String``).

.. figure:: img/memory_usage.svg

    Peak RSS plot (from historical peer JSON; re-run ``make_plots.py`` to refresh)

Feature matrix plot
-------------------

.. figure:: img/feature_comparison.svg

    CON v2 feature matrix vs common formats (``make_plots.py``)

CON v2 on the wire can carry positions, velocities, forces, unit cell,
per-direction constraints, ``atom_id``, structured JSON, compression, multi-frame
concatenation, and streaming iteration — see `spec.org <spec.rst>`_.

Statistical analysis (optional)
-------------------------------

`bayescomp <https://github.com/HaoZeke/bayescomp>`_ can fit Gamma-family models
to Criterion JSON and ``compare_readers.py`` timings when you want credible
intervals; it is not part of the PR gate.

Reproduce (one place)
---------------------

.. code:: shell

    # Python ASV (PR surface)
    maturin develop --features python,chemfiles --release
    asv machine --yes
    asv run -E "existing:$(which python)" --set-commit-hash "$(git rev-parse HEAD)" \
      --record-samples --quick

    # CON peers / multi-format / traj / H5MD — see Peer scripts above

    # Plots from your JSON
    uv run --with matplotlib --with numpy python benches/make_plots.py

    # Cachegrind I-refs (needs Valgrind)
    scripts/run_cachegrind_bench.sh

    # Rust Criterion
    cargo bench
