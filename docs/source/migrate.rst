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

    +-------------------------------------+---------------------------------------------------------------------------+
    | Payload                             | Why it matters                                                            |
    +=====================================+===========================================================================+
    | Per-direction fixed mask (column 4) | Constraints for optimizers / NEB without a sidecar                        |
    +-------------------------------------+---------------------------------------------------------------------------+
    | ``atom_id`` (column 5)              | Stable identity after type-grouping; dimer / band matching                |
    +-------------------------------------+---------------------------------------------------------------------------+
    | Optional sections                   | Velocities, forces, energies, charges, spins, magmoms on the same file    |
    +-------------------------------------+---------------------------------------------------------------------------+
    | Line-2 JSON                         | Spec version, energy, units (v3), provenance — round-trips unknown keys   |
    +-------------------------------------+---------------------------------------------------------------------------+
    | UTF-8 text                          | Diffable, greppable, campaign-storeable (``readcon-db`` indexes CON text) |
    +-------------------------------------+---------------------------------------------------------------------------+
    | Hourglass ``rkr_*`` ABI             | One semantics in Fortran / C / C++ / Python / Julia / Rust                |
    +-------------------------------------+---------------------------------------------------------------------------+

You migrate so every tool in the stack reads and writes the **same** file instead
of private dumps. This page is the task path; format rules live in
`spec.org <spec.rst>`_.

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

ASE adapters are optional; multi-reader campaigns and language-native codes
should keep CON text authoritative (``readcon-db``, hourglass consumers).

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

    +------------------------------+--------------------------------------------------------+
    | Goal                         | Page                                                   |
    +==============================+========================================================+
    | Learn native CON I/O         | `tutorial <tutorial.rst>`_                             |
    +------------------------------+--------------------------------------------------------+
    | Declared sections / validate | `faq <faq.rst>`_, `spec <spec.rst>`_                   |
    +------------------------------+--------------------------------------------------------+
    | Link C / Fortran / Julia     | `bindings <bindings.rst>`_, `howto <howto.rst>`_       |
    +------------------------------+--------------------------------------------------------+
    | Campaign store               | `readcon-db <https://github.com/lode-org/readcon-db>`_ |
    +------------------------------+--------------------------------------------------------+
