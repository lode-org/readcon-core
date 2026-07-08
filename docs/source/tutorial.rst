====================================
Tutorial — your first CON checkpoint
====================================


.. note::

   Diátaxis *tutorial* (learning-oriented). One successful path under guidance.
   Multi-language recipes: :doc:`howto`. Format conversion: :doc:`chemfiles-tutorial`.
   API tables: :doc:`bindings`. Format rules: :doc:`spec`.

   **CI:** GitHub Actions ``ci_python.yml`` (lean matrix) runs the same steps as
   ``tests/python/test_tutorial_core.py`` under ``pytest tests/python/``. A broken
   tutorial path fails that job.

In this tutorial we open a real CON trajectory from the repository fixtures,
inspect cell and ``atom_id`` data, write a round-trip file, then build a small
checkpoint with total energy.

We use **Python** and the package ``readcon`` only (no chemfiles, no ASE). Run
commands from the repository root so fixture paths match the tree. If you work
from another directory, adjust the paths.

The assertions below match ``tests/python/test_tutorial_core.py`` (iter multi-frame
count 2, round-trip length, forces fixture, built energy ``-1.25``).

What we will do
---------------

1. Install ``readcon``.

2. Iterate every frame of ``resources/test/tiny_multi_cuh2.con``.

3. Print cell size, atom count, and the first atom's ``atom_id``.

4. Write the frames back to a new file and confirm the frame count.

5. Build a two-atom frame with total energy, then write it.

When you finish, you will have two output files and a working CON I/O habit you
can repeat in any language (see `howto <howto.rst>`_).

Install once
------------

.. code:: shell

    python -m venv .venv && source .venv/bin/activate
    pip install -U 'readcon==0.14.0'
    python -c "import readcon; print(readcon.__version__, readcon.CON_SPEC_VERSION)"

You should see a version string and a library spec version (integer ``2`` or
higher). If ``import readcon`` fails, the venv is inactive or the install did not
land.

From a clone of this repository you can instead run:

.. code:: shell

    pixi r -e python python-build
    # or: maturin develop --features python

Step 1 — open a multi-frame CON
-------------------------------

The fixture ``resources/test/tiny_multi_cuh2.con`` holds two small Cu/H frames.

.. code:: python

    import readcon

    path = "resources/test/tiny_multi_cuh2.con"
    n = 0
    for frame in readcon.iter_con(path):
        n += 1
        print(n, frame.cell, len(frame))

    print("frames:", n)

Expected shape of the output (numbers match this fixture):

::

    1 [15.3456, 21.702, 100.0] 4
    2 [15.3456, 21.702, 100.0] 4
    frames: 2

Each frame reports a cell and an atom count. The iterator yields one parsed
frame at a time.

If the path is wrong you get a file error immediately: fix the working
directory and run the block again.

Step 2 — inspect identity columns
---------------------------------

Still on the first frame of the same file:

.. code:: python

    import readcon

    frame = readcon.read_first_frame("resources/test/tiny_multi_cuh2.con")
    print("spec_version:", frame.spec_version)
    print("energy:", frame.energy)  # None when the JSON omits energy
    for atom in list(frame.atoms)[:2]:
        print(
            atom.symbol,
            round(atom.x, 4),
            round(atom.y, 4),
            round(atom.z, 4),
            "fixed=",
            atom.is_fixed,
            "atom_id=",
            atom.atom_id,
        )

Look at ``atom_id``: it is column 5 of the coordinate block, the pre-grouping
index used by NEB and dimer tools. Fixed flags come from column 4.

Step 3 — write a round-trip
---------------------------

.. code:: python

    import readcon

    frames = readcon.read_con("resources/test/tiny_multi_cuh2.con")
    readcon.write_con("tutorial_roundtrip.con", frames)
    again = list(readcon.iter_con("tutorial_roundtrip.con"))
    print("wrote", len(frames), "frames; reread", len(again))
    assert len(again) == len(frames)

Expected:

::

    wrote 2 frames; reread 2

Open ``tutorial_roundtrip.con`` in an editor if you like: line 2 is JSON metadata
and coordinate blocks follow the same layout as the fixture.

Step 4 — build a checkpoint with energy
---------------------------------------

Read a forces-bearing fixture so you see optional sections on disk, then build a
tiny frame of your own:

.. code:: python

    import readcon

    ref = readcon.read_first_frame("resources/test/tiny_cuh2_forces.con")
    print("has_forces:", ref.has_forces, "energy:", ref.energy)

    atoms = [
        readcon.Atom("Cu", 0.0, 0.0, 0.0, atom_id=0, mass=63.546),
        readcon.Atom("H", 1.5, 0.0, 0.0, atom_id=1, mass=1.008),
    ]
    frame = readcon.ConFrame(
        cell=[10.0, 10.0, 10.0],
        angles=[90.0, 90.0, 90.0],
        atoms=atoms,
    )
    frame.set_energy(-1.25)
    frame.write_con("tutorial_built.con")

    check = readcon.read_first_frame("tutorial_built.con")
    print("built atoms:", len(check), "energy:", check.energy)

You should see ``has_forces: True`` and a numeric energy for the fixture, then
``built atoms: 2`` with energy ``-1.25`` for your file.

Checkpoint
----------

You now:

- install and import ``readcon``

- iterate and materialize multi-frame CON

- read ``atom_id`` and fixed flags

- write round-trips

- construct a frame with metadata energy

Next steps (pick by need, not in order):

.. table::

    +------------------------------------------------+------------------------------------------------------------------+
    | Need                                           | Page                                                             |
    +================================================+==================================================================+
    | Same tasks in Rust / C / C++ / Julia / Fortran | `howto <howto.rst>`_                                             |
    +------------------------------------------------+------------------------------------------------------------------+
    | XYZ / PDB / GRO → CON                          | `chemfiles-tutorial <chemfiles-tutorial.rst>`_                   |
    +------------------------------------------------+------------------------------------------------------------------+
    | Declared sections (``forces``, ``charges``, …) | `faq <faq.rst>`_, `spec <spec.rst>`_                             |
    +------------------------------------------------+------------------------------------------------------------------+
    | Full API tables                                | `bindings <bindings.rst>`_                                       |
    +------------------------------------------------+------------------------------------------------------------------+
    | Why CON looks this way                         | `evolution <evolution.rst>`_, `architecture <architecture.rst>`_ |
    +------------------------------------------------+------------------------------------------------------------------+
