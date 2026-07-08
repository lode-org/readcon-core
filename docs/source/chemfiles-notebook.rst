=============================
Executable Chemfiles notebook
=============================


.. note::

   This page is the *Org-mode Babel source* for the chemfiles conversion
   tutorial. ``scripts/run-chemfiles-notebook.sh`` tangles then executes it.
   GitHub Actions ``ci_python.yml`` (chemfiles matrix) runs that script after
   ``maturin develop --features python,chemfiles``. Learning narrative:
   :doc:`chemfiles-tutorial`.

Literate, plain-text notebook (not a committed ``.ipynb``). Requires
``readcon-chemfiles`` or ``maturin develop --features python,chemfiles``.

Parameters
----------

.. code:: python
    :name: params

    from __future__ import annotations

    import os
    from pathlib import Path

    work_dir = Path(os.environ.get("READCON_NB_WORK", "docs/notebooks/out/work"))
    work_dir.mkdir(parents=True, exist_ok=True)
    xyz_path = work_dir / "water.xyz"
    con_path = work_dir / "water_from_xyz.con"
    bonded_path = work_dir / "water_with_bonds.con"
    require_chemfiles = True
    print("work_dir =", work_dir.resolve())

Setup
-----

.. code:: python
    :name: setup

    import json
    import sys

    import readcon

    print("readcon", getattr(readcon, "__version__", "?"))
    ok = readcon.has_chemfiles_support()
    print("has_chemfiles_support =", ok)
    if require_chemfiles and not ok:
        raise SystemExit(
            "chemfiles not linked: pip install readcon-chemfiles "
            "or maturin develop --features python,chemfiles"
        )

Convert XYZ to CON
------------------

.. code:: python
    :name: ingress

    xyz_path.write_text(
        "3\n"
        "water demo — org-mode executable tutorial\n"
        "O  0.000  0.000  0.000\n"
        "H  0.957  0.000  0.000\n"
        "H -0.240  0.927  0.000\n",
        encoding="utf-8",
    )
    print("wrote", xyz_path.resolve())

    frame = readcon.read_chemfiles_first(str(xyz_path))
    print("atoms", len(frame.atoms), "has_bonds", frame.has_bonds)
    for i, a in enumerate(frame.atoms):
        print(
            f"  [{i}] {a.symbol} id={a.atom_id} "
            f"({a.x:.3f}, {a.y:.3f}, {a.z:.3f})"
        )

    frame.write_con(str(con_path))
    assert con_path.is_file()
    print("wrote", con_path.resolve())

    mem = readcon.read_chemfiles_memory(xyz_path.read_text(encoding="utf-8"), "XYZ")
    assert len(mem) == 1 and len(mem[0].atoms) == 3

    all_frames = readcon.read_chemfiles(str(xyz_path))
    assert len(all_frames) == 1
    print("read_chemfiles frames =", len(all_frames))

Topology and selection
----------------------

.. code:: python
    :name: selection

    bonded = readcon.ConFrame(
        cell=list(frame.cell),
        angles=list(frame.angles),
        atoms=list(frame.atoms),
        metadata={"con_spec_version": 2, "bonds": [[0, 1], [0, 2]]},
    )
    assert bonded.has_bonds
    oxy = bonded.select_atoms("name O")
    assert oxy == [0], oxy
    angles = bonded.select("angles: all")
    assert angles["context_size"] == 3
    assert len(angles["matches"]) >= 1
    print("oxygens", oxy)
    print("angles", angles["matches"])

    bonded.write_con(str(bonded_path))
    print("wrote", bonded_path.resolve())

Multi-format habit
------------------

.. code:: python
    :name: multifmt

    candidates = [xyz_path]
    converted = []
    for path in candidates:
        path = Path(path)
        if not path.is_file():
            continue
        frames = readcon.read_chemfiles(str(path))
        out = work_dir / f"{path.stem}.converted.con"
        readcon.write_con(str(out), frames)
        converted.append((str(path), str(out), len(frames)))
    print(json.dumps({"converted": converted}, indent=2))

Checkpoint
----------

.. code:: python
    :name: checkpoint

    summary = {
        "has_chemfiles_support": ok,
        "xyz": str(xyz_path),
        "con": str(con_path),
        "bonded_con": str(bonded_path),
        "n_atoms": len(frame.atoms),
        "n_angle_matches": len(angles["matches"]),
    }
    (work_dir / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    print("OK — org-mode chemfiles ingress finished", file=sys.stderr)

Run from the shell
------------------

.. code-block:: shell

   scripts/run-chemfiles-notebook.sh

Emacs: open this file and use ``C-c C-c`` on each Python source block (session
``readcon-cf``). The script tangles to ``docs/notebooks/chemfiles_ingress.py``
then executes this Org buffer via Babel — do not hand-edit the tangled ``.py``.
