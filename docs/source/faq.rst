==========================
Frequently Asked Questions
==========================


.. note::

   Explanation (why the format looks like this). Learning path:
   :doc:`tutorial`. Task recipes: :doc:`howto`.

What CON is for
---------------

CON stores one atomic configuration that rare-event codes already
depend on. A frame keeps the cell, type-grouped coordinates, a
per-direction constraint mask, a pre-group ``atom_id``, optional
per-atom sections, and line-2 JSON. Tools that invent a private dump
lose the mask or the identity on the first rewrite.

.. table::

    +--------------------------+----------------------------------------------------------------------------------------------------+
    | On disk                  | Role                                                                                               |
    +==========================+====================================================================================================+
    | Cell + angles            | Periodic box                                                                                       |
    +--------------------------+----------------------------------------------------------------------------------------------------+
    | Type-grouped coordinates | Stable ``head``-able layout                                                                        |
    +--------------------------+----------------------------------------------------------------------------------------------------+
    | Column 4 fixed mask      | Per-direction constraints (bitmask 0-7)                                                            |
    +--------------------------+----------------------------------------------------------------------------------------------------+
    | Column 5 ``atom_id``     | Pre-group index for NEB / dimer / reference matching                                               |
    +--------------------------+----------------------------------------------------------------------------------------------------+
    | Optional sections        | Velocities, forces, energies, charges, spins, magmoms, displacements, spreads (v2/v3 ``sections``) |
    +--------------------------+----------------------------------------------------------------------------------------------------+
    | Line-2 JSON              | ``con_spec_version``, ``energy``, ``neb_bead``, ``units``, …                                       |
    +--------------------------+----------------------------------------------------------------------------------------------------+

Saddle, dimer, and NEB pipelines already depend on that payload.
``readcon-core`` is the spec v2-v3 reader/writer and the hourglass
``rkr_*`` ABI in each language. Chemfiles converts **into** CON; DLPack
and metatensor export **out** of it.
`index\_proj <https://docs.rs/readcon-core/latest/readcon_core/index_proj/>`_
and ``readcon-db`` index corpora that stay CON text. Spec:
:doc:`spec`. Design history: :doc:`evolution`.

Is frame topology (``bonds``) required?
---------------------------------------

No. ``bonds`` is an optional v2 metadata key (not a ``sections`` block and
not a CON spec v3 change). Legacy files omit it. When present, each
entry is a 0-based ``atom_data`` index pair (optionally with chemfiles-style
order). It enables tools such as chemfiles selection (``bonds:`` / ``angles:`` /
``is_bonded``) when the library is built with ``--features chemfiles``.

How do I select atoms (and optional bonds) on a CON frame?
----------------------------------------------------------

Selection is a CON API: strings such as ``name H`` or ``bonds: all`` return
``atom_data`` indices (or structured matches) via ``select_on_frame`` /
``select_atom_indices`` / ``rkr_frame_select`` and language wrappers. ``name`` /
``type`` / ``all`` need only symbols. Topology selectors need ``metadata["bonds"]``
(hand-authored or filled when converting **into** CON). All languages share one
evaluator.

The ``con`` format has no residue table, stores pair ``bonds`` only, and keeps a
thin optional property subset after foreign-format import. So ``resname``, most
external property maps, impropers, and geometry-threshold minidialects are not
on the selection surface: there is simply no data for them. Detail:
``chemfiles-explain.org`` (**What selection cannot see on CON**).

Foreign formats (XYZ, PDB, …) enter through an **optional** conversion feature
(Cargo ``chemfiles``, PyPI ``readcon-chemfiles``). Lean builds still expose the
selection **symbols** but error clearly until that feature is linked. Docs for
conversion live under ``docs/orgmode/chemfiles-*.org``; language APIs in
``bindings.org``; on-disk ``bonds`` in ``spec.org``.

On **import** only, display names such as ``H1`` versus types such as ``H`` may be
kept in sidecars (``chemfiles_atom_names`` / ``chemfiles_atom_types``); the on-disk
column remains a single ``symbol``. Hand-built frames without sidecars use
``symbol`` for both.

What problems does atom\_id solve?
----------------------------------

The ``con`` format groups atoms by element type. A structure with atoms
C, C, C, O, C, C (indices 0-5) gets written as five C atoms followed
by one O atom. Without a persistent identity field, the original
ordering vanishes after one read-write cycle.

This matters for:

- **NEB calculations**: interpolated images must maintain consistent
  atom ordering across the band. If atom ordering drifts, the
  interpolation produces nonsense.

- **Dimer searches**: the displacement vector references specific atom
  indices. Reordering atoms invalidates the mode.

- **Reference comparisons**: comparing a relaxed structure against a
  reference (e.g., Baker test set) requires matching atoms by index.

The ``atom_id`` field (column 5) stores the pre-grouping index,
allowing exact reconstruction of the original ordering after any
number of read-write cycles.

Why JSON on line 2?
-------------------

Line 2 was historically unused ("Time" or empty in eOn files). JSON
provides:

- **Forward compatibility**: new keys can be added without format
  changes. Unknown keys are preserved through round-trips.

- **Machine readability**: no custom parser needed. Every language has
  a JSON library.

- **Section declaration**: the ``sections`` key tells the parser exactly
  what per-atom data to expect, eliminating ambiguity.

- **Provenance**: ``potential``, ``energy``, ``generator`` keys make files
  self-documenting.

- **Backward compatibility**: pre-v2 files have non-JSON on line 2.
  The parser detects this (line 2 does not start with ``{``) and falls
  back to legacy mode (``spec_version = 1``).

How fast is readcon-core?
-------------------------

CON parse uses fast-float2, zero-copy line views, header-sized vectors,
optional mmap, and ``forward`` / ``forward_fast`` when you only need counts.
CI: Cachegrind I-refs (``ci_cachegrind.yml``). PRs: Python ASV + spyglass
(``ci_benchmark.yml``, suite in ``benchmarks/``). Local peer scripts:
``benches/compare_readers.py``, ``multiformat_traj.py``, ``ase_traj_vs_con.py``,
``h5md_vs_con.py``. How to re-run and what each gate means:
:doc:`benchmarks`.

Uncompressed files under 64 kibibytes (KiB) are read into memory, and larger ones can use the optional mmap.
With the ``parallel`` feature, Rayon parses multi-frame text of 48 KiB or more in parallel.

What is the sections mechanism?
-------------------------------

Version 2+ files can include per-atom data beyond coordinates. Each
additional section follows the same block structure as coordinates:
blank separator, symbol line, label line, data lines.

The ``sections`` key in the JSON metadata declares which sections exist
and their order. Known names on the v2/v3 surface:

.. table::

    +-------------------------------------------------------------------------+--------------------------------+
    | Name                                                                    | Layout                         |
    +=========================================================================+================================+
    | ``velocities``, ``forces``, ``magmoms``, ``displacements``, ``spreads`` | 3-vector + fixed + ``atom_id`` |
    +-------------------------------------------------------------------------+--------------------------------+
    | ``energies``, ``charges``, ``spins``                                    | scalar + fixed + ``atom_id``   |
    +-------------------------------------------------------------------------+--------------------------------+

::

    {"con_spec_version":2,"sections":["velocities","forces","charges"]}

Optional physics blocks such as ``charges`` / ``spins`` / ``magmoms`` /
``displacements`` / ``spreads`` use the same
declared-section channel; they do not require a new ``con_spec_version``.

Compared with the legacy approach (detecting velocities by peeking for a blank
separator):

- Declared sections fix what the reader must consume

- New section names need no positional guesswork once reserved in the spec

- Section order is explicit

Declared sections must be present at the declared position. Use an
empty ``sections`` array (``[]``) to state that no additional per-atom
sections follow.
When the key is absent, the reader keeps the blank-separator fallback
for existing ``.convel`` files.

Legacy ``.convel`` files without a ``sections`` key still work: the
parser falls back to blank-separator velocity detection.

What does validate=true do?
---------------------------

The ``validate`` metadata key asks v2 readers to reject frames that do
not satisfy strict ordering and schema invariants:

::

    {"con_spec_version":2,"sections":["velocities"],"validate":true}

In this mode, ``sections`` must be present. Readers verify the
declared section order, exact component labels, component symbols,
integer identity columns, matching fixed masks and atom ids across
sections, finite numeric values, physical cell geometry, positive
counts and masses, and the JSON types of reserved metadata keys.

Can I store forces, energies, charges, spins, magmoms, displacements, spreads?
------------------------------------------------------------------------------

Yes. Per-frame total energy lives in JSON under the ``energy`` key.
Per-atom data uses declared ``sections``:

- **Forces** (3-vector): ``sections`` includes ``forces``

- **Per-atom energies** (scalar): ``energies``

- **Charges** / **spins** (scalar): ``charges``, ``spins``

- **Magnetic moments** (3-vector): ``magmoms``

- **Displacement vectors** (3-vector, Angstrom, e.g. a normal mode):
  ``displacements``

- **Spreads** (3-vector, Angstrom): ``spreads``, the root-mean-square
  spread of each atom along x, y, z about its written coordinates; a
  standard deviation, 0 for a classical point

::

    {"con_spec_version":2,"sections":["forces"],"energy":-42.5,"potential":{"type":"EMT","params":{"cutoff":6.0}}}

For ML potentials that decompose total energy into per-atom
contributions, declare ``energies`` alongside ``forces``:

::

    {"con_spec_version":2,"sections":["forces","energies"],"energy":-42.5}

Charges, spins, magmoms, displacements, and spreads use the same wire format: list
them in ``sections`` and emit the matching component blocks (see
:doc:`spec`). Example fixtures:
``resources/test/tiny_cuh2_charges_spins_magmoms.con``,
``resources/test/tiny_cuh2_displacements.con``,
``resources/test/tiny_cuh2_spreads.con``.

The per-frame ``energy`` metadata key SHOULD equal the sum of the
per-atom ``energies`` section when both are present. Frames with forces
SHOULD identify the potential (``potential`` key) so downstream tools
know how to interpret the values.

Does readcon-core support compression?
--------------------------------------

Yes. Two formats are detected automatically by magic bytes:

- **gzip**: ``.con.gz`` extension or ``0x1f 0x8b`` magic; always available.

- **zstd**: ``.con.zst`` extension or ``0x28 0xb5 0x2f 0xfd`` magic; opt-in
  behind the ``zstd`` Cargo feature. Builds without the feature still
  detect zstd input and return a clear error pointing at the feature
  flag rather than producing a corrupt parse.

Writing through ``ConFrameWriter::from_path_gzip`` /
``from_path_gzip_with_precision`` or (with the ``zstd`` feature) the
matching ``from_path_zstd`` constructors compresses output transparently.

Force data adds three floats per atom (roughly 3× the coordinate payload
alone). Gzip and (with the ``zstd`` feature) zstd reduce on-disk size; measure
on your trajectories rather than treating a single ratio as fixed.

How do I look up an atom by its ``atom_id``?
--------------------------------------------

readcon-core preserves ``atom_id`` (column 5) through every read-write
cycle, but the in-memory atom order follows the file's type-grouped
layout, not the ``atom_id`` ordering. Two convenience APIs lift the
gap:

- One-shot: ``frame.atom_index_by_id(id)`` scans the atom list and
  returns ``Option<usize>``. O(N) per call.

- Repeated: ``frame.build_atom_id_index()`` returns an ``FxHashMap<u64, usize>`` (Rust) / dict (Python) / Dict{UInt64, Int} (Julia) for O(1)
  reverse lookup. Build once and reuse for every lookup against the
  same frame.

Both APIs mirror across every supported binding (Rust, C ABI, C++,
Python, Julia).

What languages are supported?
-----------------------------

.. table::

    +----------+---------------+---------------------------------+
    | Language | Mechanism     | Installation                    |
    +==========+===============+=================================+
    | Rust     | Native crate  | ``cargo add readcon-core``      |
    +----------+---------------+---------------------------------+
    | Python   | PyO3 bindings | ``pip install readcon``         |
    +----------+---------------+---------------------------------+
    | C        | FFI (cdylib)  | link ``libreadcon_core``        |
    +----------+---------------+---------------------------------+
    | C++      | RAII header   | ``#include "readcon-core.hpp"`` |
    +----------+---------------+---------------------------------+
    | Julia    | ccall wrapper | ``using ReadCon``               |
    +----------+---------------+---------------------------------+

All bindings share the same Rust core, ensuring identical parsing
behavior across languages.

How do I convert between ASE and ``con``?
-----------------------------------------

.. code:: python

    import readcon

    # con -> ASE Atoms (preserves atom_id, velocities, forces, masses)
    frames = readcon.read_con("input.con")
    ase_atoms = frames[0].to_ase()

    # ASE Atoms -> con
    frame = readcon.ConFrame.from_ase(ase_atoms)
    readcon.write_con("output.con", [frame])

    # Direct read to ASE list
    ase_list = readcon.read_con_as_ase("trajectory.con")

The conversion preserves ``atom_id`` (via a custom per-atom array),
velocities, forces (via SinglePointCalculator), masses, and
constraints (FixAtoms).

Why both ``readcon-core.h`` and ``metatensor.h`` / ``readcon-metatensor.h``?
----------------------------------------------------------------------------

readcon's cbindgen surface and metatensor-sys's cbindgen surface are separate
crates. We hand off opaque ``mts_block_t *``; values and labels use metatensor's
C API. Prefer ``include/readcon-metatensor.h`` (``metatensor.h`` first). Lean builds
still export metatensor entry points that return ``RKR_STATUS_FEATURE_DISABLED``
(``-11``), distinct from internal error (``-7``).

Lean vs fat ``libreadcon_core`` for C/Fortran?
----------------------------------------------

Same symbol names either way. Without ``--features metatensor``, blocks return
``-11``. Without ``--features zstd``, ``create_writer_zstd_*`` returns a null writer.
gzip writers and DLPack (``ArcArray`` share via dlpk; no fake ``_borrowed`` C aliases) are
always present. After a metatensor-enabled build, ``target/<profile>/readcon-metatensor.env``
lists include/lib paths for ``libmetatensor``.

What is the stack for?
----------------------

One on-disk checkpoint and one ``rkr_*`` ABI, instead of each code
hand-rolling XYZ and its own atoms type. Migration guide:
:doc:`migrate` (``readcon-core convert``,
``readcon.convert_to_con``).

.. table::

    +-------------------------------------------------------------------------------------------------------+------------------------------------------------------------------------------------------------------------------------------------+
    | Component                                                                                             | Job                                                                                                                                |
    +=======================================================================================================+====================================================================================================================================+
    | CON on disk                                                                                           | The checkpoint format (text, optional gzip/zstd)                                                                                   |
    +-------------------------------------------------------------------------------------------------------+------------------------------------------------------------------------------------------------------------------------------------+
    | ``readcon-core``                                                                                      | Frame API + hourglass ABI + chemfiles in + selection + compression + DLPack/metatensor (`docs.rs <https://docs.rs/readcon-core>`_) |
    +-------------------------------------------------------------------------------------------------------+------------------------------------------------------------------------------------------------------------------------------------+
    | ``readcon-db``                                                                                        | LMDB corpus: energy / formula / section indexes, dedup, multi-reader (`docs <https://lode-org.github.io/readcon-db/docs/>`_)       |
    +-------------------------------------------------------------------------------------------------------+------------------------------------------------------------------------------------------------------------------------------------+
    | Chemfiles                                                                                             | Land foreign structures **as** CON                                                                                                 |
    +-------------------------------------------------------------------------------------------------------+------------------------------------------------------------------------------------------------------------------------------------+
    | ASE adapters                                                                                          | Calculators without abandoning CON interchange                                                                                     |
    +-------------------------------------------------------------------------------------------------------+------------------------------------------------------------------------------------------------------------------------------------+
    | `chemparseplot <https://chemparseplot.rgoswami.me>`_ / `rgpycrumbs <https://rgpycrumbs.rgoswami.me>`_ | Plotting and analysis on CON checkpoints                                                                                           |
    +-------------------------------------------------------------------------------------------------------+------------------------------------------------------------------------------------------------------------------------------------+
    | `rgpot <https://omnipotentrpc.github.io/rgpot/>`_ / `eOn <https://eondocs.org>`_                      | Optimizers and potentials on the same CON files                                                                                    |
    +-------------------------------------------------------------------------------------------------------+------------------------------------------------------------------------------------------------------------------------------------+

One on-disk format. One library API. Campaigns, selection, and plotting share it.
Campaign field projection helpers live in
```index_proj`` <https://docs.rs/readcon-core/latest/readcon_core/index_proj/>`_
(same meanings ``readcon-db`` indexes).

Which part of the stack does each task use?
-------------------------------------------

.. table::

    +----------------------------------------------------------------+-------------------------------------------------------------------------------------------------------------------------+
    | Task                                                           | Path                                                                                                                    |
    +================================================================+=========================================================================================================================+
    | Read or write .con files                                       | ``readcon`` / ``readcon-core``                                                                                          |
    +----------------------------------------------------------------+-------------------------------------------------------------------------------------------------------------------------+
    | Link from Fortran, C or C++                                    | Hourglass ``rkr_*`` application binary interface (ABI)                                                                  |
    +----------------------------------------------------------------+-------------------------------------------------------------------------------------------------------------------------+
    | Install readcon-db                                             | ``cargo add readcon-db`` / ``pip install readcon-db``                                                                   |
    +----------------------------------------------------------------+-------------------------------------------------------------------------------------------------------------------------+
    | Many trajectories, many readers                                | `readcon-db docs <https://lode-org.github.io/readcon-db/docs/>`_ (the .con text stays authoritative)                    |
    +----------------------------------------------------------------+-------------------------------------------------------------------------------------------------------------------------+
    | Campaign field projection                                      | `index\_proj <https://docs.rs/readcon-core/latest/readcon_core/index_proj/>`_ (same meanings as the readcon-db indexes) |
    +----------------------------------------------------------------+-------------------------------------------------------------------------------------------------------------------------+
    | Structure file in another format to .con                       | Optional chemfiles build                                                                                                |
    +----------------------------------------------------------------+-------------------------------------------------------------------------------------------------------------------------+
    | Atomic Simulation Environment (ASE) calculator hand-off        | Optional ``to_ase`` / ``from_ase``                                                                                      |
    +----------------------------------------------------------------+-------------------------------------------------------------------------------------------------------------------------+
    | Move a stack from other formats onto .con                      | :doc:`The migration guide <migrate>` describes ``convert`` on the command line and ``convert_to_con``                   |
    +----------------------------------------------------------------+-------------------------------------------------------------------------------------------------------------------------+
    | Speed checks for pull requests and continuous integration (CI) | :doc:`benchmarks` (airspeed velocity (ASV) and Cachegrind)                                                              |
    +----------------------------------------------------------------+-------------------------------------------------------------------------------------------------------------------------+

The library layout is on :doc:`the architecture page <architecture>`.

What does a code gain by moving onto .con?
------------------------------------------

A code that moves onto .con can use a maintained library with a frame application programming interface (API) instead of its own parser for .xyz files and its own atoms type.
``readcon-core`` reads and writes frames with typed metadata, optional sections, validation, compression, lazy iteration over many frames and atom selection.
It has hourglass bindings in Fortran, C, C++, Python, Julia and Rust, campaign storage through ``readcon-db`` and plotting through chemparseplot.
All of them share one interchange file and one API.

On disk, the .con file is the checkpoint: the cell, the coordinates grouped by element, the constraints, ``atom_id``, optional sections and the JavaScript Object Notation (JSON) metadata.
The library is worth using even from one code in one language, because the code then does not convert atoms, constraint masks, selections or energy fields itself.

.. table::

    +-----------------------------+------------------------------------------------------------------------------------------------------------------------------------+
    | Layer                       | What you get                                                                                                                       |
    +=============================+====================================================================================================================================+
    | Frame API                   | Read, write and builders; ``energy``, sections, fixed masks and ``atom_id`` without new types                                      |
    +-----------------------------+------------------------------------------------------------------------------------------------------------------------------------+
    | Many frames and compression | Lazy iterators, gzip and zstd, a fast parse path; a trajectory stays a sequence of .con frames                                     |
    +-----------------------------+------------------------------------------------------------------------------------------------------------------------------------+
    | Selection                   | ``select_atoms`` / ``rkr_frame_select`` (``name H``, bonds and angles when the frame has topology)                                 |
    +-----------------------------+------------------------------------------------------------------------------------------------------------------------------------+
    | Hourglass ``rkr_*``         | The same behaviour in Fortran, C, C++, Python, Julia and Rust as the stack grows                                                   |
    +-----------------------------+------------------------------------------------------------------------------------------------------------------------------------+
    | ``readcon-db``              | Lightning Memory-Mapped Database (LMDB) collections of .con text: energy, formula and section indexes, deduplication, many readers |
    +-----------------------------+------------------------------------------------------------------------------------------------------------------------------------+
    | Plotting                    | `chemparseplot <https://chemparseplot.rgoswami.me>`_ / `rgpycrumbs <https://rgpycrumbs.rgoswami.me>`_ on the same checkpoints      |
    +-----------------------------+------------------------------------------------------------------------------------------------------------------------------------+
    | Ingress                     | Chemfiles: .xyz, Protein Data Bank (PDB), .gro and other formats to .con through one convert path                                  |
    +-----------------------------+------------------------------------------------------------------------------------------------------------------------------------+
    | Performance checks          | Cachegrind instruction counts on ``main``; Python ASV and asv-spyglass on pull requests; peer scripts under ``benches/``           |
    +-----------------------------+------------------------------------------------------------------------------------------------------------------------------------+

After the move, the structure object, the selector, ``readcon-db`` and the plots all read .con files.
The format rules are in :doc:`the specification <spec>`.

What readcon-db adds
~~~~~~~~~~~~~~~~~~~~

``readcon-core`` decodes and writes .con files.
`readcon-db <https://github.com/lode-org/readcon-db>`_ is the collection layer on top, and it treats the .con text as authoritative:

.. table::

    +----------------------+--------------------------------------------------------------------------------------------------------------------------------------------------------------+
    | Capability           | What you get once the files are .con                                                                                                                         |
    +======================+==============================================================================================================================================================+
    | Indexed collections  | Energy, formula and section presence flags, from the same projection that `index\_proj <https://docs.rs/readcon-core/latest/readcon_core/index_proj/>`_ uses |
    +----------------------+--------------------------------------------------------------------------------------------------------------------------------------------------------------+
    | Deduplication        | A content hash on each frame, so images ingested twice are stored once                                                                                       |
    +----------------------+--------------------------------------------------------------------------------------------------------------------------------------------------------------+
    | Many readers         | Single-writer, many-reader LMDB access, so screening jobs do not queue behind one process                                                                    |
    +----------------------+--------------------------------------------------------------------------------------------------------------------------------------------------------------+
    | Join, split, reindex | Collection operations stay on 8-bit Unicode Transformation Format (UTF-8) .con text, so there is no binary copy of the structure                             |
    +----------------------+--------------------------------------------------------------------------------------------------------------------------------------------------------------+

The install commands and links are in the answer to "Why is readcon-db a separate package?" below.
Multi-frame .con files, compressed or not, feed the same collection together with selection and ``index_proj``.
Trajectories and screening sets therefore need no second structure format.

What the frame API saves you
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Each tool can use the library types and helpers instead of converting coordinates, masks and metadata by hand:

- Frames: ``read_con`` / ``iter_con`` / ``write_con`` / ``convert_to_con`` / builders

- Per-atom: symbols, positions, fixed masks, ``atom_id``, optional force/velocity/charge fields

- Frame-level: ``energy``, units, reserved JSON keys, ``validate``

- Selection: ``frame.select_atoms("name H")`` (topology selectors when bonds exist)

- C ABI: ``rkr_frame_*`` so Fortran and C++ do not reimplement the table

Selection needs a chemfiles build such as the ``readcon-chemfiles`` wheel, and the plain ``readcon`` wheel raises ``RuntimeError`` on the ``select_atoms`` line below.

.. code:: python

    import readcon

    frame = readcon.read_first_frame("structure.con")
    h_idx = frame.select_atoms("name H")
    print(h_idx)
    # topology: frame.select("angles: all") when metadata bonds are present

Recipes are in :doc:`chemfiles-howto`, :doc:`howto` and :doc:`bindings`.

What the plotting tools add
~~~~~~~~~~~~~~~~~~~~~~~~~~~

`chemparseplot <https://chemparseplot.rgoswami.me>`_ plots and analyses the geometry of the same .con files.
Structures and reaction paths, such as nudged elastic band (NEB) paths, can be stored as .con checkpoints.
The same files feed two-dimensional reaction valley figures and geometry plots without an exporter for each code.
`rgpycrumbs <https://rgpycrumbs.rgoswami.me>`_ provides the companion command line tools.

Files in other formats, such as .xyz and Protein Data Bank (PDB) files, still go through chemfiles into .con first.
The plots then read the shared .con files and ``readcon-db`` selections, so no code needs a private output format for them.
The **Ecosystem** menu of this site and :doc:`the chemfiles explanation <chemfiles-explain>` place these tools in the wider stack.

Are ASE adapters the primary API?
---------------------------------

No. Optional ``to_ase`` / ``from_ase`` support calculator hand-off. Interchange
and multi-reader campaign storage use ``readcon`` / ``readcon-db`` with CON text
authoritative.

What is authoritative: CON text, cooked SoA, or DLPack?
-------------------------------------------------------

UTF-8 CON text is authoritative for files and for ``readcon-db`` ``frames`` (hash,
dedup, join/split, ``reindex``). Cooked RCSO / SoA / DLPack buffers accelerate
extract and device hand-off and are discardable or ephemeral.

Why is readcon-db a separate package?
-------------------------------------

``readcon-core`` is the shared decoder/writer. ``readcon-db`` owns LMDB indexes and
SWMR corpus access. That split is a **migration benefit**: once structures are
CON text, the same files plug into corpus query (energy / formula / section
indexes, dedup) without rewriting the optimizer or potential. Install
``readcon-db`` separately (``cargo add readcon-db``, ``pip install readcon-db``).
Package docs: `lode-org.github.io/readcon-db/docs <https://lode-org.github.io/readcon-db/docs/>`_.
Source: `github.com/lode-org/readcon-db <https://github.com/lode-org/readcon-db>`_.

Where do large campaigns and many frames go?
--------------------------------------------

In this stack: **CON text** remains the structure contract; ``readcon-db`` is the
LMDB corpus on top of it (indexes for energy / formula / section
presence, content-hash dedup, multi-reader SWMR). Multi-frame CON files
(optionally gzip/zstd) and ``iter_con`` / ``forward`` cover trajectory-style loads
in ``readcon-core`` itself. Large corpora stay CON text; ``readcon-db``
indexes them. Do not switch the on-disk structure to another dialect
for screening.

Install: ``cargo add readcon-db`` / ``pip install readcon-db``.
Package docs: `lode-org.github.io/readcon-db/docs <https://lode-org.github.io/readcon-db/docs/>`_.

How do XYZ, PDB, GRO, and chemfiles fit in?
-------------------------------------------

They are **ingress**. Chemfiles (Cargo ``chemfiles``, PyPI ``readcon-chemfiles``)
maps foreign structures into ``ConFrame`` / CON so the rest of the stack speaks
one format. The durable interchange is CON (constraints, ``atom_id``, sections,
JSON, hourglass ABI). Convert at the edge when inputs arrive as XYZ/PDB/GRO;
keep CON for optimizers, campaigns (``readcon-db``), selection, and plotting.
How-to: :doc:`migrate`, :doc:`chemfiles-tutorial`.

Why an hourglass C ABI?
-----------------------

Optimizers and drivers are often Fortran or C++. A single ``rkr_*`` surface
gives those codes the same CON semantics as Python and Julia without embedding
a Python interpreter on the I/O path. The 0.14.x stability contract
(ownership, sentinels, no-abort errors, Z=1..92 helpers) is on the
architecture page. A ``1.0.0`` cut is the production classifier, not a
silent ABI rewrite.
