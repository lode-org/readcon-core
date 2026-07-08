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

CON is a human-readable checkpoint for **one structure or image** with the fields
multi-tool pipelines actually share:

.. table::

    +-------------------------------------+---------------------------------------------------------------------------------------------------------------------------------------------------------------+
    | Payload / stack                     | Why it matters                                                                                                                                                |
    +=====================================+===============================================================================================================================================================+
    | Per-direction fixed mask (column 4) | Constraints for optimizers / NEB without a sidecar                                                                                                            |
    +-------------------------------------+---------------------------------------------------------------------------------------------------------------------------------------------------------------+
    | ``atom_id`` (column 5)              | Stable identity after type-grouping; dimer / band matching                                                                                                    |
    +-------------------------------------+---------------------------------------------------------------------------------------------------------------------------------------------------------------+
    | Optional sections                   | Velocities, forces, energies, charges, spins, magmoms on the same file                                                                                        |
    +-------------------------------------+---------------------------------------------------------------------------------------------------------------------------------------------------------------+
    | Line-2 JSON                         | Spec version, energy, units (v3), provenance — round-trips unknown keys                                                                                       |
    +-------------------------------------+---------------------------------------------------------------------------------------------------------------------------------------------------------------+
    | Selection on CON                    | ``name H``, ``type Cu``, ``bonds: all`` → ``atom_data`` indices (same grammar in every language; chemfiles-linked build)                                      |
    +-------------------------------------+---------------------------------------------------------------------------------------------------------------------------------------------------------------+
    | Hourglass ``rkr_*`` ABI             | One semantics in Fortran / C / C++ / Python / Julia / Rust                                                                                                    |
    +-------------------------------------+---------------------------------------------------------------------------------------------------------------------------------------------------------------+
    | ``readcon-db`` campaigns            | LMDB corpora over CON text: energy / formula / section indexes, dedup, multi-reader                                                                           |
    +-------------------------------------+---------------------------------------------------------------------------------------------------------------------------------------------------------------+
    | Plotting / analysis                 | `chemparseplot <https://chemparseplot.rgoswami.me>`_ (and `rgpycrumbs <https://rgpycrumbs.rgoswami.me>`_) consume CON-shaped checkpoints and campaign outputs |
    +-------------------------------------+---------------------------------------------------------------------------------------------------------------------------------------------------------------+

You migrate so every tool in the stack reads and writes the **same** file instead
of private dumps — and so campaign query, selection, and plotting open without
a second structure format. This page is the task path; format rules live in
`spec.org <spec.rst>`_.

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
Docs: `lode-org.github.io/readcon-db <https://lode-org.github.io/readcon-db/>`_. Private dumps and per-code binary
caches do not get this layer for free; CON on disk does.

Benefit: selection API on CON frames
------------------------------------

After a structure is CON (native or converted), the same selection surface runs
in every binding (needs chemfiles-linked build for topology selectors):

.. code:: python

    import readcon

    frame = readcon.read_first_frame("structure.con")
    # geometry-only selectors work on symbols alone
    h_idx = frame.select_atoms("name H")
    # topology selectors need metadata bonds (import from PDB/GRO or hand-set)
    # oxy = frame.select_atoms("name O")
    # angles = frame.select("angles: all")

C / hourglass: ``rkr_frame_select`` / ``select_on_frame``. Recipes:
`chemfiles-howto <chemfiles-howto.rst>`_, grammar notes:
`chemfiles-explain <chemfiles-explain.rst>`_.

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

    +------------------------------+-----------------------------------------------------------------------------------------------------------+
    | Goal                         | Page                                                                                                      |
    +==============================+===========================================================================================================+
    | Learn native CON I/O         | `tutorial <tutorial.rst>`_                                                                                |
    +------------------------------+-----------------------------------------------------------------------------------------------------------+
    | Selection / bonds on CON     | `chemfiles-howto <chemfiles-howto.rst>`_, `faq <faq.rst>`_                                                |
    +------------------------------+-----------------------------------------------------------------------------------------------------------+
    | Declared sections / validate | `faq <faq.rst>`_, `spec <spec.rst>`_                                                                      |
    +------------------------------+-----------------------------------------------------------------------------------------------------------+
    | Link C / Fortran / Julia     | `bindings <bindings.rst>`_, `howto <howto.rst>`_                                                          |
    +------------------------------+-----------------------------------------------------------------------------------------------------------+
    | Campaign store               | `readcon-db <https://github.com/lode-org/readcon-db>`_ · `docs <https://lode-org.github.io/readcon-db/>`_ |
    +------------------------------+-----------------------------------------------------------------------------------------------------------+
    | Plotting                     | `chemparseplot <https://chemparseplot.rgoswami.me>`_ · `rgpycrumbs <https://rgpycrumbs.rgoswami.me>`_     |
    +------------------------------+-----------------------------------------------------------------------------------------------------------+
