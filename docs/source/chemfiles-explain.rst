================================================
Explanation — Chemfiles ingress and CON topology
================================================


   *Anatomy + geometry* — layered CON layout next to an in-memory structure
   (``tiny_cuh2.con``). Selection indices follow ``atom_data`` order.

   *Why CON matters for viz* — chemparseplot / rgpycrumbs 2D reaction-valley
   landscapes consume CON NEB paths; readcon-core is the reliable I/O layer.

   *Full ecosystem* — eOn, rgpot, LODE consumers; chemparseplot, rgpycrumbs,
   pychum for viz and inputs.



.. note::

   Diátaxis *explanation*. Learning path: :doc:`chemfiles-tutorial`.
   Executable Org: :doc:`chemfiles-notebook` (``scripts/run-chemfiles-notebook.sh``).

:doc:`chemfiles-tutorial` and :doc:`chemfiles-howto`.

Why drive conversion from other formats at all?
-----------------------------------------------

   Chemfiles owns format diversity; readcon-core owns CON fidelity.


CON is a complete checkpoint format (typed blocks, fixed flags, velocities /
forces / energies, JSON line-2 metadata). Structures still often arrive from
elsewhere as XYZ, PDB, GRO, LAMMPS dumps, and other chemfiles-readable layouts.

Rather than reimplement every reader in readcon-core, v0.13 uses **chemfiles as the ingress router**: chemfiles owns format diversity; readcon-core owns
**CON fidelity** (atom\_id, sections, writer, FFI, multi-language builders). The
job is to **land foreign trajectories in CON** for every CON-native consumer
(eOn, amsel, LODE tooling, campaign stores, and the rest).

Why is chemfiles optional (Cargo feature + two PyPI names)?
-----------------------------------------------------------

.. figure:: /_static/figures/lean-vs-conversion.svg
   :alt: Lean versus full builds
   :align: center
   :width: 100%


Linking libchemfiles pulls CMake, a C++ library, slower builds, and weaker
cross targets. Many consumers only need CON read/write.

.. table::

    +--------------------------------------+-------------------+----------------------------+
    | Artifact                             | Chemfiles linked? | Typical use                |
    +======================================+===================+============================+
    | crates.io ``readcon-core`` default   | No (stubs)        | Embed CON I/O              |
    +--------------------------------------+-------------------+----------------------------+
    | ``cargo build --features chemfiles`` | Yes               | Conversion + selection     |
    +--------------------------------------+-------------------+----------------------------+
    | PyPI ``readcon``                     | No (stubs)        | Lean ``pip install``       |
    +--------------------------------------+-------------------+----------------------------+
    | PyPI ``readcon-chemfiles``           | Yes               | Conversion-oriented Python |
    +--------------------------------------+-------------------+----------------------------+

Public Rust modules ``chemfiles_import`` / ``chemfiles_selection`` **always compile**. Without the feature they return
``ChemfilesImportError::FeatureDisabled`` so call sites do not need ``cfg``.
Python always registers ``has_chemfiles_support`` / ``select_*``; lean wheels
raise ``RuntimeError`` with a rebuild/install hint.

Two distributions avoid impossible dual wheels under one PyPI name (same
platform tag cannot carry two different binaries). Install **one** of
``readcon`` or ``readcon-chemfiles`` per environment.

Why bonds live in frame JSON, not sections
------------------------------------------

.. figure:: /_static/figures/con-frame-layout.svg
   :alt: CON frame layout
   :align: center
   :width: 100%

   Header + JSON line-2 + type-group blocks + optional per-atom sections.


``sections`` is the channel for **per-atom** optional blocks (velocities,
forces, energies) with fixed column layouts and one row per atom. Bonds are
**frame-scoped edges** (variable count, not N-aligned). Putting them in JSON
metadata matches ``energy`` / ``pbc`` / ``lattice_vectors``: optional, preservable
by ignorant readers, validated when ``validate=true``.

Angles and dihedrals are **not** required on disk in v0.13: chemfiles derives
them from bonds at selection projection time (``add_bond`` graph). That keeps
CON files small while still supporting ``angles:`` / ``is_angle`` when bonds
exist.

Index spaces: chemfiles order vs atom\_data vs atom\_id
-------------------------------------------------------

CON writers **type-group** atoms (all Cu, then all H, …). Column 5 ``atom_id``
stores the **pre-group** index so NEB and comparisons can recover original
order.

On chemfiles **import**:

1. Chemfiles atoms are read in chemfiles order; ``atom_id`` is set to that
   index.

2. The builder type-groups into ``atom_data``.

3. Bond endpoints are **remapped** into ``atom_data`` indices via ``atom_id`` so
   on-disk ``bonds`` always mean "indices into this frame's atom list".

Selection results are returned in **``atom_data`` index space**. Parity tests
against chemfiles C++ compare **undirected multisets** of matches after
remap—not byte-identical index lists.

Display ``name`` (e.g. ``H1``) vs atomic ``type`` (``H``) cannot both live in CON's
single symbol column; import stores optional sidecars
``chemfiles_atom_names`` / ``chemfiles_atom_types`` (chemfiles/=atom\_id= order)
and restores them when projecting for selection.

How does selection work on a CON frame?
---------------------------------------

You pass a selection string; the library returns matches as CON ``atom_data``
indices (type-grouped order on that frame). Typical strings:

- **Always useful**: ``name H``, ``type O``, ``all`` (need symbols, or import sidecars
  for display names distinct from ``symbol``).

- **Need topology**: ``bonds:`` / ``angles:`` / ``dihedrals:`` and ``is_bonded`` /
  ``is_angle`` / ``is_dihedral`` when ``metadata["bonds"]`` is present. Angles and
  dihedrals are derived from the pair list at evaluation time; v0.13 does not
  store them as separate on-disk sections.

- **Empty topology**: without ``bonds``, topology selectors return no matches (not
  a hard error unless the string is invalid).

Under the hood, evaluation may go through a small optional ingress stack
(currently chemfiles when that feature is linked). Callers do not need to care:
the public APIs (``select_on_frame``, ``select_atom_indices``, ``rkr_frame_select``,
trajectory helpers such as ``select_atom_positions_on_frames``) all speak CON
indices.

What selection cannot see on CON
--------------------------------

Selection only sees what the frame stores (plus a few import sidecars). In
particular:

- **No residues**: there is no residue table, so ``resname`` and residue-centric
  filters have nothing to attach to. Import does not invent residues.

- **Thin properties**: optional ``chemfiles_atom_properties`` (and similar) may
  carry a subset of foreign keys after conversion; most per-atom property maps
  from other formats are dropped.

- **Pair bonds only**: ``bonds`` is an undirected edge list. No impropers, no ring
  tables, no residue connectivity beyond those pairs.

- **No geometry minidialect**: distance / angle / dihedral **threshold** strings
  that depend on carefully staged extra atoms (as in some third-party test
  suites) are not part of the CON regression surface. A string may still parse;
  that is not a promise of behaviour from another toolkit.

APIs and install matrices: :doc:`bindings`,
:doc:`chemfiles-reference` (feature-gated conversion stack).

Place in the broader stack
--------------------------

   Interchange hub: CON on disk; potentials (rgpot); rare-event clients
   (eOn and others); analysis (rgpycrumbs); multi-format ingress (chemfiles);
   campaigns (readcon-db); multi-language and ML consumers (hourglass ABI,
   DLPack, metatensor).
