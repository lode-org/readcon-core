=================================
How-to — migrate a stack onto CON
=================================


.. note::

   Diátaxis *how-to* (goal-oriented). Learning paths:
   :doc:`tutorial` (native CON I/O) and :doc:`chemfiles-tutorial` (foreign formats).
   Executable conversion (CI): :doc:`chemfiles-notebook` /
   ``scripts/run-chemfiles-notebook.sh``.

:doc:`The frequently asked questions <faq>` explain what a code gains by moving onto .con, and what ``readcon-db``, the frame application programming interface (API) and the plotting tools add.

Moving to 0.19
--------------

``read_all_frames`` and ``read_con`` without ``n_threads`` stay on the calling
thread. Pass ``n_threads`` of 2 or more for a Rayon pool. The older docs
that described a 48 KiB automatic pool do not match this reader.

``read_extxyz`` returns a dict with ``positions``, ``masses``, ``cell``, ``species``,
and ``arrays``. It used to return a tuple of the three numeric arrays.
Index the dict. ``species`` rows are tuples, and a repeated symbol is one
string object.

``write_con`` streams one frame at a time and flushes before it returns.
``append=True`` extends an uncompressed file. ``.gz`` and ``.zst`` select the
codec from the extension. ``write_con_string`` takes ``start`` and ``stop``.

The ASE formats are the ``ase-readcon`` package, entry point group
``ase.ioformats``, names ``readcon-con`` and ``readcon-convel``.

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

    pip install 'readcon-chemfiles==0.19.0'   # or: maturin develop --features python,chemfiles

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

Into readcon-db
---------------

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

More chemfiles recipes: :doc:`chemfiles-howto`.

After conversion
----------------

.. table::

    +------------------------------+-----------------------------------------------------------------------------------------------------------------------------------------------------+
    | Goal                         | Page                                                                                                                                                |
    +==============================+=====================================================================================================================================================+
    | Learn native CON I/O         | :doc:`tutorial`                                                                                                                          |
    +------------------------------+-----------------------------------------------------------------------------------------------------------------------------------------------------+
    | Selection / bonds on CON     | :doc:`chemfiles-howto`, :doc:`faq`                                                                                          |
    +------------------------------+-----------------------------------------------------------------------------------------------------------------------------------------------------+
    | Declared sections / validate | :doc:`faq`, :doc:`spec`                                                                                                                |
    +------------------------------+-----------------------------------------------------------------------------------------------------------------------------------------------------+
    | Link C / Fortran / Julia     | :doc:`bindings`, :doc:`howto`                                                                                                    |
    +------------------------------+-----------------------------------------------------------------------------------------------------------------------------------------------------+
    | readcon-db                   | `readcon-db <https://github.com/lode-org/readcon-db>`_ · `docs <https://lode-org.github.io/readcon-db/docs/>`_                                     |
    +------------------------------+-----------------------------------------------------------------------------------------------------------------------------------------------------+
    | Plotting                     | `chemparseplot <https://chemparseplot.rgoswami.me>`_ · `rgpycrumbs <https://rgpycrumbs.rgoswami.me>`_                                               |
    +------------------------------+-----------------------------------------------------------------------------------------------------------------------------------------------------+
