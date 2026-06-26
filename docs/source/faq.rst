==========================
Frequently Asked Questions
==========================


.. contents::


1 Why another atomic structure format?
--------------------------------------

The ``con`` format addresses a specific gap: lossless round-tripping of
atomic configurations through saddle-point search, NEB, and dimer
calculations. Existing formats lose information during read-write
cycles:

- **XYZ**: no cell data, no fixed-atom flags, no atom identity
  tracking. A 218-atom slab written to XYZ and read back has lost
  the original atom ordering, constraint information, and periodicity.

- **POSCAR/CONTCAR**: VASP-specific. No velocity or force sections.
  Selective dynamics is all-or-nothing per direction. No metadata
  for potential parameters or convergence state.

- **extxyz**: extensible but underspecified. Every tool invents its own
  key names. No formal specification means round-trip fidelity depends
  on implementation details. Parsing performance suffers from
  per-atom key-value overhead.

- **CIF**: designed for crystallography, not molecular dynamics. Verbose.
  No velocity or force representation. Overkill for transient
  simulation snapshots.

The ``con`` format is deliberately minimal: a fixed 9-line header, typed
atom blocks, and optional velocity/force sections. The v2 JSON
metadata line adds extensibility without breaking the core simplicity.

2 Is frame topology (``bonds``) required?
-----------------------------------------

No. ``bonds`` is an optional v2 metadata key (not a ``sections`` block and
not a CON spec v3 change). Legacy files omit it. When present, each
entry is a 0-based ``atom_data`` index pair (optionally with chemfiles-style
order). It enables tools such as chemfiles selection (``bonds:`` / ``angles:`` /
``is_bonded``) when the library is built with ``--features chemfiles``.

3 How does chemfiles fit in?
----------------------------

Chemfiles is an optional Cargo/build feature (default off for lean C-only
builds and for the default PyPI wheel). When enabled, readcon-core provides:

1. A **multi-format converter** (``chemfiles_import``): chemfiles ``Frame`` /
   trajectory path or memory → ``ConFrame``, with optional ``metadata["bonds"]``
   and name/type sidecars.

2. A **bond / angle / atom selector** (``chemfiles_selection``): chemfiles
   selection-language strings evaluated on a ``ConFrame`` after projecting
   geometry and topology into a temporary chemfiles frame
   (``select_on_frame`` / ``rkr_frame_select`` / Rust ``select_atom_indices``).

Documentation is Diátaxis-shaped under ``docs/orgmode/chemfiles-*.org``:

- Tutorial (conversion-first): ``chemfiles-tutorial.org``

- How-to recipes: ``chemfiles-howto.org``

- Explanation (optional feature, bonds, indices): ``chemfiles-explain.org``

- Reference (APIs, grammar, install matrix): ``chemfiles-reference.org``

Binding matrix and gaps: ``bindings.org``. On-disk ``bonds``: ``spec.org``.

Supported topology selectors (``bonds:``, ``angles:``, ``dihedrals:``, ``is_bonded``,
``is_angle``, ``is_dihedral``) need ``bonds`` or an import that carried topology;
name/type/=all= work without it. Surfaces share one evaluator; multiset
parity with chemfiles is tested against ``tests/selection.cpp`` topology cases
(see ``chemfiles_selection_cpp_regression``).

Chemfiles display ``name`` vs atomic ``type`` (e.g. ``H1`` / ``H``) is preserved on
****import**** via metadata ``chemfiles_atom_names`` / ``chemfiles_atom_types`` (not a
second CON column); projection restores both for selection. Hand-built frames
without those keys use ``symbol`` for both.

Remaining gaps: residue/=resname=, extra props not copied on import, improper
extras beyond ``bonds``, numeric geometry blocks from full ``selection.cpp`` unless
trivially projected; multiset-after-remap not byte-identical chemfiles indices.

4 What problems does atom\ :sub:`id`\ solve?
--------------------------------------------

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

5 Why JSON on line 2?
---------------------

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

6 When should I use HDF5 instead?
---------------------------------

Use ``con`` for:

- Single structures and short trajectories (< 10k frames)

- Interoperability with eOn, readcon-core, and ASE

- Human-readable files that can be inspected with ``head``

- Situations where simplicity and round-trip fidelity matter

Use HDF5 for:

- Large-scale MD trajectories (millions of frames, billions of atoms)

- Random access by frame index without scanning

- Binary data with native-endian floats (no parsing overhead)

- Complex hierarchical data (multiple properties per frame, metadata
  trees, datasets with different shapes)

The two formats complement each other. readcon-core handles the
``con``-to-data pipeline; HDF5 handles long-term archival and analysis.

7 How fast is readcon-core?
---------------------------

readcon-core parses ``con`` files 10-30x faster than pure-Python
readers (e.g., eOn's ``fileio.py``) by using:

- **fast-float2**: SIMD-accelerated float parsing (2-3x over ``str::parse``)

- **Memory-mapped I/O**: large files are mmap'd, avoiding heap copies

- **Arc<str> symbols**: one allocation per atom type, not per atom

- **Zero-copy iteration**: the ``ConFrameIterator`` borrows from the
  input string without allocating per-line

- **Forward skip**: ``forward()`` skips frames by line counting without
  parsing atom data

See `benchmarks <benchmarks.rst>`_ for measured numbers on real datasets.

8 What is the sections mechanism?
---------------------------------

Version 2 files can include per-atom data beyond coordinates. Each
additional section (velocities, forces) follows the same block
structure as coordinates: blank separator, symbol line, label line,
data lines.

The ``sections`` key in the JSON metadata declares which sections exist
and their order:

::

    {"con_spec_version":2,"sections":["velocities","forces"]}

This is more robust than the legacy approach (detecting velocities by
peeking for a blank separator) because:

- The parser knows exactly what to expect

- New section types can be added without ambiguity

- Section order is explicit

Declared sections must be present at the declared position. Use an
empty ``sections`` array (``[]``) to state that no additional per-atom
sections follow.
When the key is absent, the reader keeps the blank-separator fallback
for existing ``.convel`` files.

Legacy ``.convel`` files without a ``sections`` key still work: the
parser falls back to blank-separator velocity detection.

9 What does validate=true do?
-----------------------------

The ``validate`` metadata key asks v2 readers to reject frames that do
not satisfy strict ordering and schema invariants:

::

    {"con_spec_version":2,"sections":["velocities"],"validate":true}

In this mode, ``sections`` must be present. Readers verify the
declared section order, exact component labels, component symbols,
integer identity columns, matching fixed masks and atom ids across
sections, finite numeric values, physical cell geometry, positive
counts and masses, and the JSON types of reserved metadata keys.

10 Can I store forces and energies?
-----------------------------------

Yes, in two complementary places:

- **Per-frame total energy** lives in the JSON metadata under the
  ``energy`` key.

- **Forces** are a per-atom vector section, declared via ``sections``:

::

    {"con_spec_version":2,"sections":["forces"],"energy":-42.5,"potential":{"type":"EMT","params":{"cutoff":6.0}}}

For ML potentials that decompose total energy into per-atom
contributions, declare the ``energies`` section alongside ``forces`` and
emit one scalar per atom in an ``Energies of Component i`` block:

::

    {"con_spec_version":2,"sections":["forces","energies"],"energy":-42.5}

The per-frame ``energy`` metadata key SHOULD equal the sum of the
per-atom ``energies`` section when both are present. Forces require
potential identification (the ``potential`` key) so downstream tools
know how to interpret the values.

11 Does readcon-core support compression?
-----------------------------------------

Yes. Two formats are detected automatically by magic bytes:

- **gzip**: ``.con.gz`` extension or ``0x1f 0x8b`` magic; always available.

- **zstd**: ``.con.zst`` extension or ``0x28 0xb5 0x2f 0xfd`` magic; opt-in
  behind the ``zstd`` Cargo feature. Builds without the feature still
  detect zstd input and return a clear error pointing at the feature
  flag rather than producing a corrupt parse.

Writing through ``ConFrameWriter::from_path_gzip`` /
``from_path_gzip_with_precision`` or (with the ``zstd`` feature) the
matching ``from_path_zstd`` constructors compresses output transparently.

Force data roughly triples per-atom file size. Gzip compression
typically recovers 60-80% of that overhead; zstd usually trims an
additional 5-15% over gzip for the same content.

12 How do I look up an atom by its ``atom_id``?
-----------------------------------------------

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

13 What languages are supported?
--------------------------------

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

14 How do I convert between ASE and ``con``?
--------------------------------------------

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
