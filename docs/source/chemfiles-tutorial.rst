=====================================================
Tutorial — Convert other formats into CON (chemfiles)
=====================================================


.. contents::

/Executable form is ****Org-mode only****: ``docs/orgmode/chemfiles-notebook.org``
(Babel; run ``scripts/run-chemfiles-notebook.sh``). The ``.py`` under ``docs/notebooks/``
is ****tangled**** from that Org file — do not hand-edit it. Optional Papermill is
only on tangled output (``READCON_NB_PAPERMILL=1``).

*Diátaxis: **tutorial** (learning). Goal: succeed once end-to-end. For goals like "only convert PDB" see `chemfiles how-to guides <chemfiles-howto.rst>`_. For **why** lean vs full wheels and index remap, see `chemfiles explanation <chemfiles-explain.rst>`_. For API tables see `chemfiles reference <chemfiles-reference.rst>`_ and `bindings <bindings.rst>`_.*

1 What you will build
---------------------

In this tutorial you:

1. Install a ****chemfiles-linked**** build (Python ``readcon-chemfiles`` or Rust
   ``--features chemfiles``).

2. ****Drive conversion from another format**** (we use XYZ; the same APIs accept
   PDB, GRO, LAMMPS dump, etc. via chemfiles).

3. Inspect geometry and optional ****bonds**** on the resulting CON frame.

4. Run a ****selection**** (``name O``, ``angles: all``) in CON atom order.

5. ****Write**** a ``.con`` (and optionally multi-frame) file you can feed to eOn /
   amsel / any CON consumer.

You do **not** need a pre-existing ``.con`` file. The point of the chemfiles path
is ****ingress from the wider ecosystem into CON****.

2 Step 0 — Choose one install path
----------------------------------

Pick ****one**** environment. Do not install both ``readcon`` and ``readcon-chemfiles``
in the same venv (both provide ``import readcon``).

2.1 Path A — Python full wheel (recommended for this tutorial)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code:: shell

    python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
    pip install -U pip
    pip install 'readcon-chemfiles==0.13.0'
    python -c "import readcon; print(readcon.has_chemfiles_support())"   # must print True

If that prints ``False``, you installed lean ``readcon`` by mistake. Uninstall and
install ``readcon-chemfiles`` only.

2.2 Path B — Rust with chemfiles
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code:: shell

    # From a clone of readcon-core
    cargo build --features chemfiles
    # Optional: run the suite that exercises import + selection
    cargo test --features chemfiles --lib chemfiles

Modern CMake may need ``CMAKE_POLICY_VERSION_MINIMUM=3.5`` while building
``chemfiles-sys``; this repo sets it in ``.cargo/config.toml``.

2.3 Path C — Editable Python from source
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code:: shell

    # From the repo root
    cp pyproject.chemfiles.toml pyproject.toml   # or: maturin with explicit features
    maturin develop --features python,chemfiles
    python -c "import readcon; assert readcon.has_chemfiles_support()"

3 Step 1 — A small XYZ to convert
---------------------------------

Create ``water.xyz`` (chemfiles XYZ; free-form cell omitted → non-PBC CON cell
markers are fine for this demo):

.. code:: text

    3
    water demo for readcon-core chemfiles tutorial
    O  0.000  0.000  0.000
    H  0.957  0.000  0.000
    H -0.240  0.927  0.000

Any chemfiles-readable file works the same way later (``structure.pdb``,
``conf.gro``, LAMMPS dump, …). Only the path (and for in-memory import, the
format string) changes.

4 Step 2 — Convert XYZ → CON frame (Rust)
-----------------------------------------

.. code:: rust

    use readcon_core::chemfiles_import::{
        chemfiles_enabled, con_frame_from_trajectory_path, con_frames_from_trajectory_path,
    };
    use readcon_core::writer::ConFrameWriter;

    fn main() -> Result<(), Box<dyn std::error::Error>> {
        assert!(
            chemfiles_enabled(),
            "rebuild with --features chemfiles (stubs return FeatureDisabled otherwise)"
        );

        // First frame only — works for single-structure XYZ/PDB/GRO/...
        let frame = con_frame_from_trajectory_path("water.xyz")?;
        println!(
            "atoms={} has_bonds={} bonds={}",
            frame.atom_data.len(),
            frame.has_bonds(),
            frame.bonds().len()
        );
        for (i, a) in frame.atom_data.iter().enumerate() {
            println!(
                "  [{i}] {} id={} ({:.3},{:.3},{:.3})",
                a.symbol, a.atom_id, a.x, a.y, a.z
            );
        }

        // Write a CON file consumers understand
        let mut w = ConFrameWriter::from_path("water_from_xyz.con")?;
        w.write_frame(&frame)?;
        println!("wrote water_from_xyz.con");

        // Multi-frame trajectories (e.g. multi-model PDB or multi-frame XYZ)
        let all = con_frames_from_trajectory_path("water.xyz")?;
        println!("trajectory frames: {}", all.len());
        Ok(())
    }

Build and run with ``--features chemfiles``. On success you have
``water_from_xyz.con`` with JSON metadata on line 2 (``con_spec_version`` 2). If
the source format carried topology, ``metadata["bonds"]`` is populated (indices
in ``atom_data`` order after type-grouping; see explanation doc).

5 Step 3 — Convert XYZ → CON entirely in Python
-----------------------------------------------

With ``readcon-chemfiles``, Python has first-class ingress APIs (same job as Rust
``con_frame_from_trajectory_path`` / ``con_frames_from_*``):

.. code:: python

    import readcon

    assert readcon.has_chemfiles_support(), "pip install readcon-chemfiles (not lean readcon)"

    # All frames (usually one for a single XYZ)
    frames = readcon.read_chemfiles("water.xyz")
    frame = frames[0]
    # Or first frame only:
    frame = readcon.read_chemfiles_first("water.xyz")

    print("atoms", len(frame.atoms), "has_bonds", frame.has_bonds)
    for i, a in enumerate(frame.atoms):
        print(f"  [{i}] {a.symbol} id={a.atom_id} ({a.x:.3f},{a.y:.3f},{a.z:.3f})")

    # Write CON for LODE / eOn / amsel consumers
    frame.write_con("water_from_xyz.con")

    # In-memory (downloaded bytes, etc.) — format is a chemfiles name
    data = open("water.xyz", encoding="utf-8").read()
    mem_frames = readcon.read_chemfiles_memory(data, "XYZ")
    assert len(mem_frames) == 1

    # Idiomatic selection on the frame (module-level aliases also exist)
    print("oxygens", frame.select_atoms("name O"))
    # readcon.select_atom_indices(frame, "name O")

Plain XYZ usually has ****no bonds****. Conversion still yields CON geometry;
use PDB (or Step 4) when you need ``angles:`` / ``bonds:``.

6 Step 4 — Drive topology: prefer formats with bonds, or set bonds in CON
-------------------------------------------------------------------------

**\*4a — Prefer a format chemfiles reads \*with** topology (best for LODE pipelines)\*\*

.. code:: rust

    // PDB / mol2 / some chemfiles formats populate topology → CON metadata bonds
    let frame = con_frame_from_trajectory_path("ligand.pdb")?;
    assert!(frame.has_bonds() || frame.bonds().is_empty());
    // If has_bonds(), angles: / is_bonded work after projection

****4b — Or attach bonds on a builder after ingress (indices = atom\ :sub:`data`\ order)****

.. code:: rust

    use readcon_core::chemfiles_import::con_frame_from_trajectory_path;
    use readcon_core::chemfiles_selection::{evaluate_selection_on_con_frame, select_atom_indices};
    use readcon_core::types::{Bond, ConFrameBuilder};
    use readcon_core::writer::ConFrameWriter;

    // Start from converted geometry, then add connectivity in CON index space
    let imported = con_frame_from_trajectory_path("water.xyz")?;
    let mut b = ConFrameBuilder::new(imported.header.boxl, imported.header.angles);
    for a in &imported.atom_data {
        b.add_atom(
            a.symbol.as_ref(),
            a.x,
            a.y,
            a.z,
            [a.fixed_x, a.fixed_y, a.fixed_z],
            a.atom_id,
            a.mass,
        );
    }
    // Water: O–H, O–H in atom_data order after type-group may differ — use atom_id
    // For this tiny demo atoms are O,H,H and often stay 0,1,2:
    b.set_bonds(&[Bond::new(0, 1), Bond::new(0, 2)]);
    let frame = b.build();

    let angles = evaluate_selection_on_con_frame("angles: all", &frame)?;
    assert_eq!(angles.context_size, 3);
    assert!(!angles.matches.is_empty());
    println!("H–O–H style matches: {}", angles.matches.len());

    let mut w = ConFrameWriter::from_path("water_with_bonds.con")?;
    w.write_frame(&frame)?;

****4c — Python: convert + selection on bonded CON****

.. code:: python

    import readcon

    assert readcon.has_chemfiles_support()
    # Prefer bonded ingress when available:
    # frame = readcon.read_chemfiles_first("ligand.pdb")
    frame = readcon.read_first_frame("water_with_bonds.con")  # from step 4b, or PDB import
    assert frame.has_bonds
    print("H indices", frame.select_atoms("type H"))
    print("bonds", frame.select("bonds: all")["matches"])
    print("angles", frame.select("angles: all")["matches"])
    frame.write_con("water_selected_roundtrip.con")

7 Step 5 — Multi-format conversion habit (other ingress formats)
----------------------------------------------------------------

Treat chemfiles as the ****format router****; CON as the ****canonical LODE store****.

.. code:: rust

    use readcon_core::chemfiles_import::con_frames_from_trajectory_path;
    use readcon_core::writer::ConFrameWriter;

    // Swap the path; chemfiles picks the reader from extension / format
    for path in ["conf.gro", "system.pdb", "dump.lammpstrj", "traj.xyz"] {
        if !std::path::Path::new(path).exists() {
            continue;
        }
        let frames = con_frames_from_trajectory_path(path)?;
        let out = format!("{path}.converted.con");
        let mut w = ConFrameWriter::from_path(&out)?;
        for f in &frames {
            w.write_frame(f)?;
        }
        println!("{path} -> {out} ({} frames)", frames.len());
    }

In-memory buffers (when you already have file bytes):

.. code:: rust

    use readcon_core::chemfiles_import::con_frames_from_memory;

    let xyz = std::fs::read_to_string("water.xyz")?;
    let frames = con_frames_from_memory(&xyz, "XYZ")?;
    assert!(!frames.is_empty());

8 Step 6 — C probe (optional)
-----------------------------

Link a library built with ``--features chemfiles`` (or lean build where
``rkr_has_chemfiles_support()`` is 0 and selection returns an error status).

.. code:: c

    #include "readcon-core.h"
    #include <stdio.h>

    int main(void) {
        printf("chemfiles support: %u\n", (unsigned)rkr_has_chemfiles_support());
        /* Load a frame via your usual iterator, then: */
        /* RKRSelectionResult *sel = NULL; */
        /* rkr_frame_select(frame, "name O", &sel); */
        return 0;
    }

9 Checkpoint — you succeeded if
-------------------------------

- ``has_chemfiles_support()`` / ``chemfiles_enabled()`` is true for the build you used.

- You produced at least one ``.con`` ****from a non-CON file**** (``water_from_xyz.con``).

- You understand XYZ may lack bonds; PDB (or explicit ``set_bonds``) enables
  ``angles:`` / ``bonds:``.

- You ran at least one selection (``name O`` or ``angles: all``) and saw CON
  ``atom_data`` indices.

Next: `how-to guides <chemfiles-howto.rst>`_ (specific formats, C-only, lean wheel limits) and
`explanation <chemfiles-explain.rst>`_ (why two PyPI names, index remap, metadata bonds).
