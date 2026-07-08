===========================================
How-to — Chemfiles conversion and selection
===========================================


.. note::

   Diátaxis *how-to guides*. Learning path: :doc:`chemfiles-tutorial`.
   Executable Org: :doc:`chemfiles-notebook` (``scripts/run-chemfiles-notebook.sh``).

(`tutorials <tutorials.rst>`_) or finish `the chemfiles tutorial <chemfiles-tutorial.rst>`_ once.

How to convert a single structure file (XYZ, PDB, GRO, …) to CON
----------------------------------------------------------------

**Goal:** one file on disk → one ``.con``.

**Rust** (requires ``--features chemfiles``):

.. code:: rust

    use readcon_core::chemfiles_import::con_frame_from_trajectory_path;
    use readcon_core::writer::ConFrameWriter;

    let frame = con_frame_from_trajectory_path("input.pdb")?; // or .xyz, .gro, …
    let mut w = ConFrameWriter::from_path("output.con")?;
    w.write_frame(&frame)?;

Chemfiles selects the reader from the path. If the format has topology, CON
line-2 JSON may include ``bonds`` (0-based ``atom_data`` indices after import
remap).

**Python** (``readcon-chemfiles``):

.. code:: python

    import readcon
    frame = readcon.read_chemfiles_first("input.pdb")  # or .xyz, .gro, …
    frame.write_con("output.con")
    # multi-frame:
    for i, f in enumerate(readcon.read_chemfiles("traj.xyz")):
        f.write_con(f"frame_{i}.con")
    # or one multi-frame CON via write_con(list) — use readcon.write_con(path, frames)
    frames = readcon.read_chemfiles("traj.xyz")
    readcon.write_con("traj.con", frames)

How to convert a multi-frame trajectory into multi-frame CON
------------------------------------------------------------

**Goal:** every chemfiles step becomes a CON frame in one file.

.. code:: rust

    use readcon_core::chemfiles_import::con_frames_from_trajectory_path;
    use readcon_core::writer::ConFrameWriter;

    let frames = con_frames_from_trajectory_path("traj.xyz")?;
    let mut w = ConFrameWriter::from_path("traj.con")?;
    for f in &frames {
        w.write_frame(f)?;
    }

How to convert from an in-memory buffer
---------------------------------------

**Goal:** bytes already in memory (HTTP download, archive member).

.. code:: rust

    use readcon_core::chemfiles_import::con_frames_from_memory;

    let data = std::fs::read_to_string("snippet.xyz")?;
    // Second argument is a chemfiles format name, e.g. "XYZ", "PDB", "GRO"
    let frames = con_frames_from_memory(&data, "XYZ")?;

How to select atoms by name or type on a CON frame
--------------------------------------------------

**Goal:** indices in CON ``atom_data`` order (not ``atom_id`` column unless they
coincide).

**Python** (``readcon-chemfiles``):

.. code:: python

    import readcon
    frame = readcon.read_first_frame("structure.con")
    print(readcon.select_atom_indices(frame, "name O"))
    print(readcon.select_atom_indices(frame, "type H"))
    print(readcon.select_atom_indices(frame, "all"))

**Rust:**

.. code:: rust

    use readcon_core::chemfiles_selection::select_atom_indices;
    // frame: &ConFrame
    let oxygens = select_atom_indices("name O", frame)?;

Works **without** ``bonds`` for atom selectors. On lean builds / lean wheels,
APIs exist but return ``FeatureDisabled`` / ``RuntimeError`` — install full
chemfiles support.

How to select bonds and angles
------------------------------

**Goal:** topology-aware matches.

Requires ``metadata["bonds"]`` on the frame (from chemfiles import of a bonded
format, or ``ConFrameBuilder::set_bonds`` / ``header.set_bonds``).

.. code:: python

    import readcon
    frame = readcon.read_first_frame("with_bonds.con")
    assert frame.has_bonds
    print(readcon.select_on_frame(frame, "bonds: all")["matches"])
    print(readcon.select_on_frame(frame, "angles: all")["matches"])
    print(readcon.select_on_frame(frame, "is_bonded"))  # pair context

.. code:: rust

    use readcon_core::chemfiles_selection::evaluate_selection_on_con_frame;
    let r = evaluate_selection_on_con_frame("angles: all", frame)?;
    assert_eq!(r.context_size, 3);

Angles/dihedrals are **derived by chemfiles from bonds** at projection time;
you do not store angle arrays on disk in v0.13.

How to use the C API for selection
----------------------------------

Build ``libreadcon_core`` with ``--features chemfiles`` for real evaluation;
without it, ``rkr_has_chemfiles_support()`` is 0 and ``rkr_frame_select`` returns
``RKR_STATUS_SELECTION_ERROR``.

.. code:: c

    #include "readcon-core.h"

    if (!rkr_has_chemfiles_support()) { /* rebuild with chemfiles */ }

    RKRConFrame *frame = /* from iterator */;
    RKRSelectionResult *sel = NULL;
    if (rkr_frame_select(frame, "bonds: all", &sel) == RKR_STATUS_SUCCESS) {
        uint64_t n = rkr_selection_result_match_count(sel);
        /* ... rkr_selection_result_match_at ... */
        rkr_selection_result_free(sel);
    }

C++: ``readcon::ConFrame::select`` / ``readcon::has_chemfiles_support()`` in
``readcon-core.hpp``.

How to install lean CON I/O only (no libchemfiles)
--------------------------------------------------

.. code:: shell

    pip install 'readcon==0.13.0'          # has_chemfiles_support() is False
    cargo build                            # stubs; FeatureDisabled on import/select

Selection symbols still import in Python/Rust; they error clearly. Use this
for CI that must not compile CMake/chemfiles.

How to install full chemfiles support
-------------------------------------

.. code:: shell

    pip install 'readcon-chemfiles==0.13.0'   # preferred PyPI
    # or: pip install 'readcon[chemfiles]'   # depends on readcon-chemfiles==X.Y.Z
    cargo build --features chemfiles
    maturin develop --features python,chemfiles

Do not install ``readcon`` and ``readcon-chemfiles`` together (module clash).

How to batch-convert a directory of foreign trajectories
--------------------------------------------------------

.. code:: rust

    use readcon_core::chemfiles_import::con_frames_from_trajectory_path;
    use readcon_core::writer::ConFrameWriter;
    use std::fs;
    use std::path::Path;

    fn convert_tree(dir: &Path) -> std::io::Result<()> {
        for entry in fs::read_dir(dir)? {
            let path = entry?.path();
            let ext = path.extension().and_then(|e| e.to_str()).unwrap_or("");
            if !matches!(ext, "xyz" | "pdb" | "gro" | "lammpstrj" | "mol2") {
                continue;
            }
            let Ok(frames) = con_frames_from_trajectory_path(&path) else {
                eprintln!("skip (chemfiles failed): {}", path.display());
                continue;
            };
            let out = path.with_extension("con");
            let mut w = ConFrameWriter::from_path(&out).expect("writer");
            for f in &frames {
                w.write_frame(f).expect("write");
            }
            println!("{} -> {} ({} frames)", path.display(), out.display(), frames.len());
        }
        Ok(())
    }

Run under a chemfiles-enabled build. Extend the extension list for formats
your chemfiles build supports.

How to batch-convert in Python
------------------------------

.. code:: python

    from pathlib import Path
    import readcon

    assert readcon.has_chemfiles_support()
    exts = {".xyz", ".pdb", ".gro", ".lammpstrj", ".mol2"}
    for path in Path("incoming").iterdir():
        if path.suffix.lower() not in exts:
            continue
        try:
            frames = readcon.read_chemfiles(str(path))
        except (OSError, ValueError, RuntimeError) as e:
            print("skip", path, e)
            continue
        out = path.with_suffix(".con")
        readcon.write_con(str(out), frames)
        print(path, "->", out, len(frames), "frames")
