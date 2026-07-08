====================================
Tutorial — your first CON checkpoint
====================================


.. note::

   Diátaxis *tutorial* (learning-oriented). **Source of truth is this Org file.**

   CI (``.github/workflows/ci_python.yml``, lean + chemfiles matrices) runs
   ``scripts/run-tutorial-core.sh``: Emacs ``org-babel-tangle`` into
   ``docs/notebooks/tutorial_core.py``, **fails if the committed tangle drifts**,
   then runs that file with ``python3`` against ``resources/test`` fixtures.
   Do not hand-edit the tangled ``.py``; re-tangle with
   ``READCON_TANGLE_UPDATE=1 scripts/run-tutorial-core.sh`` and commit.

   Multi-language recipes: :doc:`howto`. Format conversion: :doc:`chemfiles-tutorial`.
   API tables: :doc:`bindings`. Format rules: :doc:`spec`.

In this tutorial we open a real CON trajectory from the repository fixtures,
inspect cell and ``atom_id`` data, write a round-trip file, then build a small
checkpoint with total energy.

We use **Python** and the package ``readcon`` only (no chemfiles, no ASE).
Paths are relative to the repository root. Locally you may ``C-c C-c`` blocks in
Emacs; ****CI does not use session execute as a second path**** — it only runs the
tangled ``.py`` after a drift check so session vs tangle cannot disagree silently.

What we will do
---------------

1. Import ``readcon`` and locate fixtures under ``resources/test/``.

2. Iterate every frame of ``tiny_multi_cuh2.con``.

3. Inspect ``atom_id`` and fixed flags on the first frame.

4. Write a round-trip and confirm the frame count.

5. Build a two-atom frame with total energy and write it.

Parameters
----------

.. code:: python
    :name: params

    from __future__ import annotations

    import os
    import sys
    from pathlib import Path

    # Repo root: CI and local runs cwd to repository root.
    REPO = Path(os.environ.get("READCON_TUT_ROOT", Path.cwd())).resolve()
    FIXTURES = REPO / "resources" / "test"
    MULTI = FIXTURES / "tiny_multi_cuh2.con"
    FORCES = FIXTURES / "tiny_cuh2_forces.con"
    work_dir = Path(os.environ.get("READCON_TUT_WORK", REPO / "docs" / "notebooks" / "out" / "tutorial_core"))
    work_dir.mkdir(parents=True, exist_ok=True)
    roundtrip_path = work_dir / "tutorial_roundtrip.con"
    built_path = work_dir / "tutorial_built.con"
    print("REPO =", REPO)
    print("work_dir =", work_dir.resolve())

Setup
-----

.. code:: python
    :name: setup

    import readcon

    print("readcon", getattr(readcon, "__version__", "?"))
    print("CON_SPEC_VERSION", readcon.CON_SPEC_VERSION)
    assert MULTI.is_file(), f"missing fixture {MULTI}"
    assert FORCES.is_file(), f"missing fixture {FORCES}"

Step 1 — open a multi-frame CON
-------------------------------

The fixture ``resources/test/tiny_multi_cuh2.con`` holds two small Cu/H frames.

.. code:: python
    :name: step1_iter

    n = 0
    for frame in readcon.iter_con(str(MULTI)):
        n += 1
        print(n, list(frame.cell), len(frame))

    print("frames:", n)
    assert n == 2, n

You should see two frames with four atoms each and cell roughly
``[15.3456, 21.702, 100.0]``.

Step 2 — inspect identity columns
---------------------------------

.. code:: python
    :name: step2_inspect

    frame = readcon.read_first_frame(str(MULTI))
    print("spec_version:", frame.spec_version)
    # energy is a property (None when JSON omits it), not a method
    print("energy:", frame.energy)
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
    assert frame.spec_version >= 2
    assert frame.energy is None
    assert list(frame.atoms)[0].symbol == "Cu"
    assert list(frame.atoms)[0].atom_id == 0
    assert list(frame.atoms)[0].is_fixed is True

Look at ``atom_id``: column 5 of the coordinate block, the pre-grouping index
used by NEB and dimer tools. Fixed flags come from column 4.

Step 3 — write a round-trip
---------------------------

.. code:: python
    :name: step3_roundtrip

    frames = readcon.read_con(str(MULTI))
    readcon.write_con(str(roundtrip_path), frames)
    again = list(readcon.iter_con(str(roundtrip_path)))
    print("wrote", len(frames), "frames; reread", len(again))
    assert len(again) == len(frames) == 2
    assert len(again[0]) == 4

Open the written file under ``docs/notebooks/out/tutorial_core/`` if you like:
line 2 is JSON metadata.

Step 4 — build a checkpoint with energy
---------------------------------------

Read a forces-bearing fixture, then build a tiny frame of your own:

.. code:: python
    :name: step4_build

    ref = readcon.read_first_frame(str(FORCES))
    print("has_forces:", ref.has_forces, "energy:", ref.energy)
    assert ref.has_forces is True
    assert ref.energy == -42.5

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
    frame.write_con(str(built_path))

    check = readcon.read_first_frame(str(built_path))
    print("built atoms:", len(check), "energy:", check.energy)
    assert len(check) == 2
    assert check.energy == -1.25

Checkpoint
----------

.. code:: python
    :name: checkpoint

    import json

    summary = {
        "multi_frames": 2,
        "roundtrip": str(roundtrip_path.resolve()),
        "built": str(built_path.resolve()),
        "built_energy": check.energy,
        "has_forces_fixture": bool(ref.has_forces),
    }
    (work_dir / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    print("OK — org-mode CON checkpoint tutorial finished", file=sys.stderr)

You now:

- install and import ``readcon``

- iterate and materialize multi-frame CON

- read ``atom_id`` and fixed flags

- write round-trips

- construct a frame with metadata energy

Run from the shell
------------------

.. code-block:: shell

   # after: maturin develop --features python  (or pip install readcon)
   scripts/run-tutorial-core.sh

Emacs: open this file and ``C-c C-c`` each Python block for interactive use.
CI and ``scripts/run-tutorial-core.sh`` re-tangle, refuse drift, and run
``docs/notebooks/tutorial_core.py`` only — do not hand-edit the tangled ``.py``.

Next steps
----------

.. table::

    +------------------------------------------------+-------------------------------------------------------------------------------------------------+
    | Need                                           | Page                                                                                            |
    +================================================+=================================================================================================+
    | Same tasks in Rust / C / C++ / Julia / Fortran | `howto <howto.rst>`_                                                                            |
    +------------------------------------------------+-------------------------------------------------------------------------------------------------+
    | XYZ / PDB / GRO → CON (Babel + CI)             | `chemfiles-tutorial <chemfiles-tutorial.rst>`_ / `chemfiles-notebook <chemfiles-notebook.rst>`_ |
    +------------------------------------------------+-------------------------------------------------------------------------------------------------+
    | Declared sections (``forces``, ``charges``, …) | `faq <faq.rst>`_, `spec <spec.rst>`_                                                            |
    +------------------------------------------------+-------------------------------------------------------------------------------------------------+
    | Full API tables                                | `bindings <bindings.rst>`_                                                                      |
    +------------------------------------------------+-------------------------------------------------------------------------------------------------+
