================================================
Explanation — Chemfiles ingress and CON topology
================================================


.. contents::

.. note::

   Diátaxis *explanation*. Learning path: :doc:`chemfiles-tutorial`.
   Executable Org: :doc:`chemfiles-notebook` (``scripts/run-chemfiles-notebook.sh``).

`tutorial <chemfiles-tutorial.rst>`_ and `how-to <chemfiles-howto.rst>`_./

Why drive conversion from other formats at all?
-----------------------------------------------

.. figure:: /_static/figures/ingress-pipeline.svg
   :alt: Ingress pipeline diagram
   :align: center
   :width: 100%

   Chemfiles owns format diversity; readcon-core owns CON fidelity.


CON is a **deliberately small** LODE-centric format (typed blocks, fixed flags,
optional velocities/forces/energies, JSON line-2 metadata). Most of the
ecosystem does not speak CON: structures arrive as XYZ, PDB, GRO, LAMMPS
dumps, chemfiles-only formats, etc.

Rather than reimplement every reader in readcon-core, v0.13 uses **chemfiles as the ingress router**: chemfiles owns format diversity; readcon-core owns
**CON fidelity** (atom\ :sub:`id`\, sections, writer, FFI, NEB-friendly builders). The
product story is not "replace chemfiles" but **land foreign trajectories in CON** for eOn, amsel, and CON-native tools.

Why is chemfiles optional (Cargo feature + two PyPI names)?
-----------------------------------------------------------

.. figure:: /_static/figures/lean-vs-full.svg
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

Why bonds live in frame JSON, not ``sections``
----------------------------------------------

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

Index spaces: chemfiles order vs ``atom_data`` vs ``atom_id``
-------------------------------------------------------------

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
``chemfiles_atom_names`` / ``chemfiles_atom_types`` (chemfiles/=atom\ :sub:`id`\= order)
and restores them when projecting for selection.

What selection does under the hood
----------------------------------

1. Build a temporary chemfiles ``Frame`` from CON positions, cell, optional
   bonds, and name/type sidecars.

2. Run chemfiles ``Selection`` on that frame.

3. Map match indices back as CON ``atom_data`` indices (already in that order
   on the projected frame).

Without bonds, atom selectors (``name``, ``type``, ``all``) still work;
topology selectors (``bonds:``, ``angles:``, ``is_bonded``, …) yield no matches or
empty results—not a hard error unless the grammar is invalid.

Gaps (honest limits)
--------------------

Residue/=resname= filters, full chemfiles property surface, improper
topology extras, and numeric geometry assertion blocks from chemfiles
``tests/selection.cpp`` are not fully mirrored. See `bindings <bindings.rst>`_ and
`reference <chemfiles-reference.rst>`_ for the supported subset.

Place in the LODE / eOn ecosystem
---------------------------------

.. figure:: /_static/figures/ecosystem.svg
   :alt: readcon-core among eOn, rgpot, rgpycrumbs, chemfiles, bindings
   :align: center
   :width: 100%

   Interchange hub: potentials (rgpot), saddles (eOn), analysis (rgpycrumbs),
   multi-format ingress (chemfiles), multi-language consumers.
