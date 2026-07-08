=================================
How-to — migrate a stack onto CON
=================================


.. note::

   Diátaxis *how-to* (goal-oriented). Learning paths:
   :doc:`tutorial` (native CON I/O) and :doc:`chemfiles-tutorial` (foreign formats).
   Executable conversion (CI): :doc:`chemfiles-notebook` /
   ``scripts/run-chemfiles-notebook.sh``.

Why adopt CON (what you gain)
-----------------------------

Reach for a maintained library with a real frame API, not a hand-rolled XYZ
parser and a home-grown ``Atoms`` struct. ``readcon-core`` already gives you
parse/write, typed metadata, optional sections, validation, compression,
lazy multi-frame iteration, selection, hourglass bindings in every major
language, campaign storage via ``readcon-db``, and plotting via chemparseplot —
one interchange file and one API surface.

CON on disk is the checkpoint (cell, type-grouped coordinates, constraints,
``atom_id``, optional sections, JSON). The library is the reason to use it even
from a single code in a single language: you do not re-marshall atoms, masks,
selectors, or energy fields yourself.

.. table::

    +---------------------------+-------------------------------------------------------------------------------------------------------------------------------+
    | Layer                     | What you get                                                                                                                  |
    +===========================+===============================================================================================================================+
    | Frame API                 | Read/write, builders, ``energy`` / sections / fixed masks / ``atom_id`` without inventing types                               |
    +---------------------------+-------------------------------------------------------------------------------------------------------------------------------+
    | Multi-frame + compression | Lazy iterators, gzip/zstd, hot-path parse; trajectories stay usable as CON sequences                                          |
    +---------------------------+-------------------------------------------------------------------------------------------------------------------------------+
    | Selection                 | ``select_atoms`` / ``rkr_frame_select`` (``name H``, bonds/angles when topology is present)                                   |
    +---------------------------+-------------------------------------------------------------------------------------------------------------------------------+
    | Hourglass ``rkr_*``       | Same semantics in Fortran / C / C++ / Python / Julia / Rust when the stack grows                                              |
    +---------------------------+-------------------------------------------------------------------------------------------------------------------------------+
    | ``readcon-db``            | LMDB corpora on CON text: energy / formula / section indexes, dedup, multi-reader                                             |
    +---------------------------+-------------------------------------------------------------------------------------------------------------------------------+
    | Plotting                  | `chemparseplot <https://chemparseplot.rgoswami.me>`_ / `rgpycrumbs <https://rgpycrumbs.rgoswami.me>`_ on the same checkpoints |
    +---------------------------+-------------------------------------------------------------------------------------------------------------------------------+
    | Ingress                   | Chemfiles: XYZ/PDB/GRO/… → CON with one convert path                                                                          |
    +---------------------------+-------------------------------------------------------------------------------------------------------------------------------+
    | Performance gates         | Cachegrind I-refs (main); Python ASV + spyglass (PRs); peer scripts under ``benches/``                                        |
    +---------------------------+-------------------------------------------------------------------------------------------------------------------------------+

Migrate so the structure object, selector, campaign store, and plots all speak
CON. Format rules: `spec.org <spec.rst>`_.

Performance
-----------

What the library actually does on the CON path: fast-float2 on atom floats,
zero-copy line views, header-sized atom vectors, ``read_to_string`` vs mmap at
64 KiB, optional Rayon multi-frame parse at ≥ 48 KiB with ``parallel``. How CI
and local scripts measure that (Cachegrind, ASV, peers):
`benchmarks.org <benchmarks.rst>`_.

Benefit: campaign store (``readcon-db``)
----------------------------------------

``readcon-core`` is the decoder/writer. `readcon-db <https://github.com/lode-org/readcon-db>`_ is the campaign
layer that **assumes CON text is authoritative**:

.. table::

    +------------------------+------------------------------------------------------------------------------------+
    | Capability             | What you get after switching to CON                                                |
    +========================+====================================================================================+
    | Indexed corpora        | Energy, formula, section-presence flags from the same projection as ``index_proj`` |
    +------------------------+------------------------------------------------------------------------------------+
    | Dedup                  | Content hash on frame blobs so re-ingested images do not explode the store         |
    +------------------------+------------------------------------------------------------------------------------+
    | Multi-reader           | SWMR LMDB access for screening jobs without serializing on one process             |
    +------------------------+------------------------------------------------------------------------------------+
    | Join / split / reindex | Corpus ops stay on UTF-8 CON; no opaque binary fork of the structure               |
    +------------------------+------------------------------------------------------------------------------------+

Install (separate package): ``cargo add readcon-db`` / ``pip install readcon-db``.
Package docs: `lode-org.github.io/readcon-db <https://lode-org.github.io/readcon-db/>`_.
Rust API: `docs.rs/readcon-db <https://docs.rs/readcon-db>`_.
Source: `github.com/lode-org/readcon-db <https://github.com/lode-org/readcon-db>`_.
Multi-frame CON (with optional compression) plus selection and ``index_proj``
feed the same campaign path; you do not need a second structure dialect for
"real" trajectories or screening corpora.

Benefit: the API (stop owning your own atoms object)
----------------------------------------------------

Use the library types and helpers instead of marshaling coordinates, masks, and
metadata by hand in every tool:

- Frames: ``read_con`` / ``iter_con`` / ``write_con`` / ``convert_to_con`` / builders

- Per-atom: symbols, positions, fixed masks, ``atom_id``, optional force/velocity/charge fields

- Frame-level: ``energy``, units, reserved JSON keys, ``validate``

- Selection: ``frame.select_atoms("name H")`` (topology selectors when bonds exist)

- C ABI: ``rkr_frame_*`` so Fortran and C++ do not reimplement the table

.. code:: python

    import readcon

    frame = readcon.read_first_frame("structure.con")
    h_idx = frame.select_atoms("name H")
    # topology: frame.select("angles: all") when metadata bonds are present

Recipes: `chemfiles-howto <chemfiles-howto.rst>`_, `howto <howto.rst>`_,
`bindings <bindings.rst>`_.

Benefit: plotting stack (chemparseplot)
---------------------------------------

`chemparseplot <https://chemparseplot.rgoswami.me>`_ is the plotting / geometry-analysis side of the same CON
stack: once structures (and NEB / reaction paths) are CON checkpoints, the same
files feed 2D reaction-valley style figures and geometry plots without a
custom exporter per code. Companion CLIs and crumbs:
`rgpycrumbs <https://rgpycrumbs.rgoswami.me>`_.

Foreign XYZ/PDB still enter via chemfiles → CON first; viz then sits on CON
(and on campaign selections from ``readcon-db``) rather than on each code's
private dump. Ecosystem context: conf.py **Ecosystem** nav ·
`chemfiles-explain <chemfiles-explain.rst>`_.

One-command convert (CLI)
-------------------------

Build with chemfiles when the input is not already CON:

.. code:: shell

    cargo build --release --features chemfiles
    ./target/release/readcon-core convert structure.xyz structure.con
    ./target/release/readcon-core convert structure.pdb structure.con
    # native CON inspect / rewrite (no chemfiles required):
    ./target/release/readcon-core convert input.con out.con
    ./target/release/readcon-core input.con   # summary only

Library entry (same logic as the CLI):

.. code:: rust

    use readcon_core::convert::convert_path_to_con;
    use std::path::Path;

    let report = convert_path_to_con(Path::new("in.xyz"), Path::new("out.con"))?;
    assert!(report.n_atoms_last > 0);

Python one-liner
----------------

Chemfiles-linked install for foreign formats:

.. code:: shell

    pip install 'readcon-chemfiles==0.14.0'   # or: maturin develop --features python,chemfiles

.. code:: python

    import readcon

    # Foreign or CON → CON
    report = readcon.convert_to_con("structure.xyz", "structure.con")
    print(report)  # n_frames, n_atoms_last, native_con

    # Same via frame API (tutorial / notebook path; CI-run)
    frame = readcon.read_chemfiles_first("structure.xyz")
    frame.write_con("structure.con")

Executable Org Babel for the XYZ path: ``scripts/run-chemfiles-notebook.sh``
(wired in ``ci_python.yml`` chemfiles matrix).

ASE hand-off (keep CON as authority)
------------------------------------

.. code:: python

    import readcon

    frame = readcon.read_first_frame("structure.con")
    atoms = frame.to_ase()          # atom_id array + constraints when present
    # ... calculator / MD step ...
    frame2 = readcon.ConFrame.from_ase(atoms)
    frame2.write_con("after.con")   # interchange stays CON text

ASE adapters are optional. After the calculator step, write CON again so
``readcon-db`` ingest and hourglass consumers still see the interchange file.

Into a campaign store
---------------------

Once files are CON text:

.. code:: shell

    # see readcon-db docs for open/ingest/select; packages:
    #   cargo add readcon-db
    #   pip install readcon-db

Screening indexes use the same field meanings as ``readcon_core::index_proj``
(finite energy, formula, sections mask). That only works if the blob on disk is
CON, not a private trajectory dialect.

Batch: many foreign files → CON
-------------------------------

.. code:: shell

    for f in structures/*.{xyz,pdb,gro}; do
      ./target/release/readcon-core convert "$f" "con/${f##*/}.con"
    done

Python:

.. code:: python

    from pathlib import Path
    import readcon

    for path in Path("structures").glob("*.xyz"):
        readcon.convert_to_con(str(path), str(Path("con") / f"{path.stem}.con"))

More chemfiles recipes: `chemfiles-howto.org <chemfiles-howto.rst>`_.

After conversion
----------------

.. table::

    +------------------------------+-----------------------------------------------------------------------------------------------------------------------------------------------------+
    | Goal                         | Page                                                                                                                                                |
    +==============================+=====================================================================================================================================================+
    | Learn native CON I/O         | `tutorial <tutorial.rst>`_                                                                                                                          |
    +------------------------------+-----------------------------------------------------------------------------------------------------------------------------------------------------+
    | Selection / bonds on CON     | `chemfiles-howto <chemfiles-howto.rst>`_, `faq <faq.rst>`_                                                                                          |
    +------------------------------+-----------------------------------------------------------------------------------------------------------------------------------------------------+
    | Declared sections / validate | `faq <faq.rst>`_, `spec <spec.rst>`_                                                                                                                |
    +------------------------------+-----------------------------------------------------------------------------------------------------------------------------------------------------+
    | Link C / Fortran / Julia     | `bindings <bindings.rst>`_, `howto <howto.rst>`_                                                                                                    |
    +------------------------------+-----------------------------------------------------------------------------------------------------------------------------------------------------+
    | Campaign store               | `readcon-db <https://github.com/lode-org/readcon-db>`_ · `docs <https://lode-org.github.io/readcon-db/>`_ · `docs.rs <https://docs.rs/readcon-db>`_ |
    +------------------------------+-----------------------------------------------------------------------------------------------------------------------------------------------------+
    | Plotting                     | `chemparseplot <https://chemparseplot.rgoswami.me>`_ · `rgpycrumbs <https://rgpycrumbs.rgoswami.me>`_                                               |
    +------------------------------+-----------------------------------------------------------------------------------------------------------------------------------------------------+
