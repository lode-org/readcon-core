=================
Language bindings
=================


.. contents::


1 Feature parity matrix
-----------------------

The five surfaces (Rust, Python, Julia, C, C++) cover the same core
read/write/build functionality. The table below maps coarse features
to bindings; each binding's section below has runnable examples.

.. table::

    +---------------------------------------------------------------------------------------+--------------------------------+--------------------------------------------------+--------------------------------------------------------------------+-------------------------------------------------------+-------------------------------------------------+
    | Feature                                                                               | Rust                           | Python                                           | Julia                                                              | C                                                     | C++                                             |
    +=======================================================================================+================================+==================================================+====================================================================+=======================================================+=================================================+
    | Lazy frame iterator                                                                   | yes                            | yes                                              | yes                                                                | yes                                                   | yes                                             |
    +---------------------------------------------------------------------------------------+--------------------------------+--------------------------------------------------+--------------------------------------------------------------------+-------------------------------------------------------+-------------------------------------------------+
    | Read-all-frames helper                                                                | ``iterators::read_all_frames`` | ``readcon.read_all_frames``                      | ``read_all_frames``                                                | ``rkr_read_all_frames``                               | ``ConFrameIterator::read_all_frames`` (planned) |
    +---------------------------------------------------------------------------------------+--------------------------------+--------------------------------------------------+--------------------------------------------------------------------+-------------------------------------------------------+-------------------------------------------------+
    | Parallel iterator                                                                     | yes (``parallel`` feature)     | no                                               | no                                                                 | no                                                    | no                                              |
    +---------------------------------------------------------------------------------------+--------------------------------+--------------------------------------------------+--------------------------------------------------------------------+-------------------------------------------------------+-------------------------------------------------+
    | Builder API                                                                           | ``ConFrameBuilder``            | ``PyConFrameBuilder``                            | ``ConFrameBuilder``                                                | ``rkr_frame_new`` + ``rkr_frame_add_atom_full``       | ``readcon::ConFrameBuilder``                    |
    +---------------------------------------------------------------------------------------+--------------------------------+--------------------------------------------------+--------------------------------------------------------------------+-------------------------------------------------------+-------------------------------------------------+
    | Writer API                                                                            | ``ConFrameWriter``             | ``write_frames``                                 | ``write_frames``                                                   | ``create_writer_from_path_c`` + ``rkr_writer_extend`` | ``readcon::ConFrameWriter``                     |
    +---------------------------------------------------------------------------------------+--------------------------------+--------------------------------------------------+--------------------------------------------------------------------+-------------------------------------------------------+-------------------------------------------------+
    | Velocity / force sections                                                             | yes                            | yes                                              | yes                                                                | yes                                                   | yes                                             |
    +---------------------------------------------------------------------------------------+--------------------------------+--------------------------------------------------+--------------------------------------------------------------------+-------------------------------------------------------+-------------------------------------------------+
    | Per-axis fixed mask                                                                   | yes                            | yes                                              | yes                                                                | yes                                                   | yes                                             |
    +---------------------------------------------------------------------------------------+--------------------------------+--------------------------------------------------+--------------------------------------------------------------------+-------------------------------------------------------+-------------------------------------------------+
    | Typed metadata getters (energy, time, frame\ :sub:`index`\, neb\ :sub:`\*`\)          | yes                            | yes                                              | yes                                                                | yes                                                   | yes                                             |
    +---------------------------------------------------------------------------------------+--------------------------------+--------------------------------------------------+--------------------------------------------------------------------+-------------------------------------------------------+-------------------------------------------------+
    | Typed metadata setters (set\ :sub:`energy`\, set\ :sub:`frame`\ \ :sub:`index`\, ...) | yes                            | yes                                              | yes                                                                | yes                                                   | yes                                             |
    +---------------------------------------------------------------------------------------+--------------------------------+--------------------------------------------------+--------------------------------------------------------------------+-------------------------------------------------------+-------------------------------------------------+
    | Raw JSON metadata getter                                                              | ``FrameHeader::metadata``      | ``PyConFrame.metadata``                          | ``metadata``                                                       | ``rkr_frame_metadata_json``                           | ``ConFrame::metadata_json``                     |
    +---------------------------------------------------------------------------------------+--------------------------------+--------------------------------------------------+--------------------------------------------------------------------+-------------------------------------------------------+-------------------------------------------------+
    | Strict validation (``validate=true``)                                                 | yes                            | yes                                              | yes                                                                | yes                                                   | yes                                             |
    +---------------------------------------------------------------------------------------+--------------------------------+--------------------------------------------------+--------------------------------------------------------------------+-------------------------------------------------------+-------------------------------------------------+
    | RPC server                                                                            | yes (``rpc`` feature)          | no                                               | no                                                                 | no                                                    | no                                              |
    +---------------------------------------------------------------------------------------+--------------------------------+--------------------------------------------------+--------------------------------------------------------------------+-------------------------------------------------------+-------------------------------------------------+
    | Cap'n Proto serialization                                                             | yes (``rpc`` feature)          | no                                               | no                                                                 | no                                                    | no                                              |
    +---------------------------------------------------------------------------------------+--------------------------------+--------------------------------------------------+--------------------------------------------------------------------+-------------------------------------------------------+-------------------------------------------------+
    | gzip / .gz round-trip                                                                 | yes                            | yes                                              | yes                                                                | yes                                                   | yes                                             |
    +---------------------------------------------------------------------------------------+--------------------------------+--------------------------------------------------+--------------------------------------------------------------------+-------------------------------------------------------+-------------------------------------------------+
    | zstd / .zst round-trip                                                                | yes (``zstd`` feature)         | yes (``zstd`` feature)                           | yes (``zstd`` feature)                                             | yes (``zstd`` feature)                                | yes (``zstd`` feature)                          |
    +---------------------------------------------------------------------------------------+--------------------------------+--------------------------------------------------+--------------------------------------------------------------------+-------------------------------------------------------+-------------------------------------------------+
    | Per-atom ``energies`` section                                                         | yes                            | yes                                              | yes                                                                | yes                                                   | yes                                             |
    +---------------------------------------------------------------------------------------+--------------------------------+--------------------------------------------------+--------------------------------------------------------------------+-------------------------------------------------------+-------------------------------------------------+
    | Symbol <-> Z helpers                                                                  | yes                            | derived from Atom                                | yes                                                                | ``rkr_symbol_to_z`` / ``rkr_z_to_symbol``             | ``readcon::symbol_to_z`` / ``z_to_symbol``      |
    +---------------------------------------------------------------------------------------+--------------------------------+--------------------------------------------------+--------------------------------------------------------------------+-------------------------------------------------------+-------------------------------------------------+
    | ``atom_id`` reverse index                                                             | ``build_atom_id_index``        | ``build_atom_id_index``                          | ``build_atom_id_index``                                            | ``rkr_frame_atom_index_by_id``                        | ``ConFrame::atom_index_by_id``                  |
    +---------------------------------------------------------------------------------------+--------------------------------+--------------------------------------------------+--------------------------------------------------------------------+-------------------------------------------------------+-------------------------------------------------+
    | Coords / forces / velocities / energies as NumPy ndarray                              | n/a (use AoS)                  | yes (``numpy`` ndarray + DLPack via NumPy 1.22+) | n/a                                                                | n/a                                                   | n/a                                             |
    +---------------------------------------------------------------------------------------+--------------------------------+--------------------------------------------------+--------------------------------------------------------------------+-------------------------------------------------------+-------------------------------------------------+
    | metatensor ``TensorBlock`` export                                                     | yes (``metatensor`` feature)   | n/a                                              | n/a                                                                | n/a                                                   | n/a                                             |
    +---------------------------------------------------------------------------------------+--------------------------------+--------------------------------------------------+--------------------------------------------------------------------+-------------------------------------------------------+-------------------------------------------------+
    | Optional frame ``bonds`` topology                                                     | yes                            | ``PyConFrame.bonds`` / ``has_bonds``             | ``metadata_json`` + ``frame_bond_count``                           | ``rkr_frame_bond_*``                                  | ``ConFrame::bonds()``                           |
    +---------------------------------------------------------------------------------------+--------------------------------+--------------------------------------------------+--------------------------------------------------------------------+-------------------------------------------------------+-------------------------------------------------+
    | Chemfiles import / selection                                                          | yes (``chemfiles`` feature)    | ``select_on_frame`` / ``select_atom_indices``    | ``select_on_frame`` / ``select_atom_indices`` (FFI; chemfiles lib) | ``rkr_frame_select``                                  | ``ConFrame::select``                            |
    +---------------------------------------------------------------------------------------+--------------------------------+--------------------------------------------------+--------------------------------------------------------------------+-------------------------------------------------------+-------------------------------------------------+

****Chemfiles selection parity (supported subset).**** One evaluator core; every
surface is a pass-through (``evaluate_selection_on_con_frame`` → chemfiles
``Selection`` after projecting the frame). Build with ``--features chemfiles``;
probe with ``rkr_has_chemfiles_support()`` / ``has_chemfiles_support()`` (Julia) /
feature at build time (Rust/Python).

**Chemfiles documentation (Diátaxis):** ``chemfiles-tutorial.org`` (learn conversion),
``chemfiles-howto.org``, ``chemfiles-explain.org``, ``chemfiles-reference.org`` (this
matrix is the bindings slice of reference). Release cutting: ``contributing.org``
**Release process**.

Supported contexts when topology is present (``metadata["bonds"]``, 0-based
``atom_data`` pairs): ``bonds:`` / ``angles:`` / ``dihedrals:`` / ``pairs:`` / ``two:`` /
``three:`` / ``four:``, and predicates ``is_bonded`` / ``is_angle`` / ``is_dihedral`` on
the projected chemfiles graph. Atom/name/type/~all~/~none~ work without bonds.

****Index space / multiset contract.**** CON type-groups atoms on write/import;
bond endpoints are stored in ``atom_data`` order (chemfiles import remaps via
``atom_id``). Surfaces return matches in that CON order. Parity with chemfiles
direct evaluation is an **undirected multiset** after remapping chemfiles
indices through ~atom\ :sub:`id`\~—not byte-identical index lists.

****Chemfiles name vs type (fixed for import path).**** On-disk CON still has one
``symbol`` column (element/type for layout). Chemfiles import additionally stores
optional metadata sidecars ``chemfiles_atom_names`` / ``chemfiles_atom_types``
(indexed by chemfiles / ``atom_id`` order). Selection projection restores display
``name`` and atomic ``type`` so ``name H1`` and ``type H`` both work after import.
Hand-built frames without sidecars use ``symbol`` for both (same as before).

****Remaining documented gaps (not claimed parity).**** Residue/~resname~ and extra
atom/residue properties (beyond what import already copies into
``chemfiles_atom_properties`` / frame extras). Improper topology extras not
stored in CON ``bonds``. Numeric geometry assertion blocks from chemfiles
``tests/selection.cpp`` (``distance`` / ``angle`` / ``dihedral`` / ``out_of_plane``
thresholds with extra atoms) unless trivially projected. Multiset-after-remap
parity, not byte-identical chemfiles index lists.

2 Python (PyO3)
---------------

2.1 Installation
~~~~~~~~~~~~~~~~

.. code:: shell

    # From PyPI
    pip install readcon

    # From source with maturin
    maturin develop --features python

    # Or via pixi
    pixi r -e python python-build

2.2 Version and spec queries
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code:: python

    import readcon

    print(readcon.__version__)       # e.g. "0.5.0"
    print(readcon.CON_SPEC_VERSION)  # 2

2.3 Usage
~~~~~~~~~

.. code:: python

    import readcon

    # Read frames
    frames = readcon.read_con("path/to/file.con")
    first = readcon.read_first_frame("path/to/file.con")
    for frame in readcon.iter_con("path/to/file.con"):
        pass
    frames = readcon.read_con_string(contents)

    # Access data
    for frame in frames:
        print(frame.cell)           # [f64, f64, f64]
        print(frame.angles)         # [f64, f64, f64]
        print(frame.has_velocities)
        for atom in frame.atoms:
            print(atom.symbol, atom.x, atom.y, atom.z, atom.mass)
            if atom.has_velocity:
                print(atom.vx, atom.vy, atom.vz)

    # Construct frames (v0.4.0+)
    atom = readcon.Atom(symbol="Cu", x=0.0, y=0.0, z=0.0,
                        fixed=[False, False, False], atom_id=1)
    frame = readcon.ConFrame(cell=[10.0, 10.0, 10.0],
                             angles=[90.0, 90.0, 90.0],
                             atoms=[atom])
    frame.metadata["generator"] = "my-tool 1.0"
    frame.atoms.append(readcon.Atom(symbol="H", x=1.0, y=0.0, z=0.0))

    # Write frames (with optional precision)
    readcon.write_con("output.con", frames)
    readcon.write_con("precise.con", frames, precision=17)
    output_str = readcon.write_con_string(frames)

    # ASE conversion (v0.4.0+, requires ase)
    ase_atoms = frame.to_ase()
    frame2 = readcon.ConFrame.from_ase(ase_atoms)

2.4 Types
~~~~~~~~~

``readcon.Atom``
    Constructable with keyword arguments (v0.4.0+).
    Properties: symbol, x, y, z, fixed, is\ :sub:`fixed`\, atom\ :sub:`id`\, mass
    (v0.4.2+), vx, vy, vz, has\ :sub:`velocity`\, fx, fy, fz, has\ :sub:`forces`\,
    energy (v0.10.0+), has\ :sub:`energy`\ (v0.10.0+).
    Data fields are writable.

``readcon.ConFrame``
    Constructable with cell, angles, atoms, and
    optional headers and metadata (v0.4.0+).  Properties: cell, angles,
    atoms (live list), has\ :sub:`velocities`\, has\ :sub:`forces`\, has\ :sub:`energies`\
    (v0.10.0+), prebox\ :sub:`header`\, postbox\ :sub:`header`\, spec\ :sub:`version`\ (v0.6.0+),
    metadata (v0.6.0+, live dict of native JSON-compatible values),
    energy, frame\ :sub:`index`\, time, timestep, neb\ :sub:`bead`\, neb\ :sub:`band`\.
    Methods: to\ :sub:`ase`\(), from\ :sub:`ase`\() (v0.4.0+), set\ :sub:`metadata`\ \ :sub:`json`\(),
    set\ :sub:`scalar`\ \ :sub:`metadata`\(), set\ :sub:`string`\ \ :sub:`metadata`\(), set\ :sub:`energy`\(),
    set\ :sub:`frame`\ \ :sub:`index`\(), set\ :sub:`time`\(), set\ :sub:`timestep`\(), set\ :sub:`neb`\ \ :sub:`bead`\(),
    set\ :sub:`neb`\ \ :sub:`band`\(), atom\ :sub:`index`\ \ :sub:`by`\ \ :sub:`id`\(id) (v0.10.0+),
    build\ :sub:`atom`\ \ :sub:`id`\ \ :sub:`index`\() (v0.10.0+), coords\ :sub:`array`\() (v0.10.0+),
    velocities\ :sub:`array`\() (v0.10.0+), forces\ :sub:`array`\() (v0.10.0+),
    energies\ :sub:`array`\() (v0.10.0+), atom\ :sub:`ids`\ \ :sub:`array`\() (v0.10.0+).

``readcon.read_first_frame(path)``
    Parse and return only the first
    frame.

``readcon.iter_con(path)``
    Return a Python iterator over frames.
    The iterator API avoids indexing into ``read_con(path)`` for
    first-frame and loop-based workflows.

2.5 NumPy array views and DLPack interop (v0.10.0+)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Every per-atom quantity has a contiguous NumPy ndarray accessor.
Vector quantities are ``[N, 3]`` float64 arrays in the type-grouped
order used by the underlying frame; scalars are ``[N]``. NumPy 1.22+
implements ``__dlpack__`` on its arrays, so the returned ndarrays
interoperate zero-copy with torch / jax / cupy without readcon-core
wiring DLPack itself.

.. code:: python

    import numpy as np
    import torch
    import readcon

    frame = readcon.read_first_frame("trajectory.con")

    coords = frame.coords_array()         # np.ndarray shape (N, 3) float64
    forces = frame.forces_array()         # Optional[np.ndarray]; None if absent
    velocities = frame.velocities_array() # Optional[np.ndarray]
    energies = frame.energies_array()     # Optional[np.ndarray] shape (N,)
    atom_ids = frame.atom_ids_array()     # np.ndarray shape (N,) uint64

    # Zero-copy hand-off into torch via DLPack.
    coords_torch = torch.from_dlpack(coords)
    assert coords_torch.shape == (len(frame), 3)

    # atom_id reverse index for O(1) lookup by file column-5 id.
    idx = frame.build_atom_id_index()      # dict[int, int]
    position = idx.get(42)                 # Optional[int]

- ASE conversion preserves ``atom_id`` through an ``atom_id`` array,
  velocities through ASE velocities, forces through a
  ``SinglePointCalculator``, and per-axis fixed masks through
  ``FixCartesian`` / ``FixAtoms`` constraints.

2.6 Typed metadata accessors
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Every reserved JSON key has a typed setter in addition to the live
``metadata`` dict. The setters validate the input type up front so
authoring with bad metadata fails immediately, while the dict path
remains available for raw escape-hatch use.

.. code:: python

    import readcon

    frame = readcon.read_first_frame("traj.con")

    # Read: typed getter returns None when absent
    print(frame.energy)           # Optional[float]
    print(frame.frame_index)      # Optional[int]
    print(frame.neb_bead)         # Optional[int]

    # Write: typed setters validate input shape
    frame.set_energy(-42.5)
    frame.set_frame_index(7)
    frame.set_neb_bead(3)

    # Object-shaped keys still go through the dict
    frame.metadata["potential"] = {"type": "EMT", "cutoff": 6.0}
    frame.metadata["units"] = {"length": "angstrom", "energy": "eV"}

    # Bulk-replace metadata from a JSON string (validated against the schema)
    frame.set_metadata_json('{"con_spec_version": 2, "energy": -1.0}')

3 Julia (ccall)
---------------

3.1 Installation
~~~~~~~~~~~~~~~~

Set ``READCON_LIB_PATH`` to the shared library path, or build with
``cargo build --release`` and the Julia package will find it
automatically.

.. code:: shell

    export READCON_LIB_PATH=/path/to/libreadcon_core.so

3.2 Usage
~~~~~~~~~

.. code:: julia

    using ReadCon

    frames = read_con("path/to/file.con")

    for frame in frames
        println(frame.cell)
        println(frame.angles)
        println(frame.has_velocities)
        println(frame.spec_version)
        println(frame.energy)
        for atom in frame.atoms
            println(atom.x, " ", atom.y, " ", atom.z)
        end
    end

    write_con("roundtrip.con", frames)

3.3 Types
~~~~~~~~~

``ReadCon.Atom``
    atomic\ :sub:`number`\, x, y, z, atom\ :sub:`id`\, mass, is\ :sub:`fixed`\,
    fixed, vx, vy, vz, has\ :sub:`velocity`\, fx, fy, fz, has\ :sub:`forces`\

``ReadCon.ConFrame``
    cell, angles, atoms, has\ :sub:`velocities`\,
    has\ :sub:`forces`\, prebox\ :sub:`header`\, postbox\ :sub:`header`\, spec\ :sub:`version`\,
    metadata\ :sub:`json`\, energy, frame\ :sub:`index`\, time, timestep, neb\ :sub:`bead`\,
    neb\ :sub:`band`\

``ReadCon.write_con(path, frames; precision=6)``
    Writes Julia
    frames through the C FFI builder/writer path, preserving velocities,
    forces, per-axis fixed masks, atom ids, masses, and JSON metadata.

3.4 Typed metadata accessors
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Mirrors the Rust and Python typed-setter helpers. Reserved keys are
addressable by named getters and setters; arbitrary keys go through
``metadata_json``.

.. code:: julia

    using ReadCon

    frames = read_con("traj.con")
    frame = first(frames)

    # Read: typed getters return Union{Nothing, T}
    println(frame.energy)        # Union{Nothing, Float64}
    println(frame.frame_index)   # Union{Nothing, UInt64}
    println(frame.time)          # Union{Nothing, Float64}

    # Write: typed setters
    ReadCon.set_energy!(frame, -42.5)
    ReadCon.set_frame_index!(frame, 7)
    ReadCon.set_neb_bead!(frame, 3)

    # Bulk: replace from a JSON string (validated against the schema)
    ReadCon.set_metadata_json!(
        frame,
        "{\"con_spec_version\": 2, \"sections\": [\"velocities\"], \"energy\": -1.0}",
    )

4 C/C++ (FFI)
-------------

4.1 Version and spec queries
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code:: c

    #include "readcon-core.h"

    // Compile-time check
    #if RKR_CON_SPEC_VERSION < 2
    #error "readcon-core spec v2 required for atom_id support"
    #endif

    // Runtime queries
    printf("Spec version: %u\n", rkr_con_spec_version());
    printf("Library version: %s\n", rkr_library_version());

4.2 C API
~~~~~~~~~

Include ``readcon-core.h`` and link against ``libreadcon_core``.

.. code:: c

    #include "readcon-core.h"

    CConFrameIterator *iter = read_con_file_iterator("file.con");
    RKRConFrame *handle;
    while ((handle = con_frame_iterator_next(iter)) != NULL) {
        CFrame *frame = rkr_frame_to_c_frame(handle);
        printf("Atoms: %zu, Velocities: %s\n",
               frame->num_atoms, frame->has_velocities ? "yes" : "no");
        for (size_t i = 0; i < frame->num_atoms; i++) {
            CAtom *a = &frame->atoms[i];
            if (a->has_velocity) {
                printf("  vel=(%.6f, %.6f, %.6f)\n", a->vx, a->vy, a->vz);
            }
        }
        free_c_frame(frame);
        free_rkr_frame(handle);
    }
    free_con_frame_iterator(iter);

Metadata builder helpers:

.. code:: c

    RKRConFrameBuilder *builder = rkr_frame_new(cell, angles, "", "", "", "");
    if (rkr_frame_builder_set_energy(builder, -42.5) != RKR_STATUS_SUCCESS) {
        free_rkr_frame_builder(builder);
        return 1;
    }
    if (rkr_frame_builder_set_frame_index(builder, 7) != RKR_STATUS_SUCCESS) {
        free_rkr_frame_builder(builder);
        return 1;
    }
    rkr_frame_builder_set_time(builder, 3.5);
    rkr_frame_builder_set_timestep(builder, 0.2);
    rkr_frame_builder_set_neb_bead(builder, 4);
    rkr_frame_builder_set_neb_band(builder, 1);
    rkr_frame_builder_set_scalar_metadata(builder, "convergence", 1.0e-3);
    rkr_frame_builder_set_string_metadata(builder, "generator", "eon");
    rkr_frame_add_atom_with_velocity_and_forces_fixed_mask(
        builder, "Cu", 0.0, 0.0, 0.0,
        true, false, true,
        0, 63.546,
        0.1, 0.2, 0.3,
        -0.1, -0.2, -0.3);
    printf("status: %s\n", rkr_status_message(RKR_STATUS_SUCCESS));

4.3 C++ API
~~~~~~~~~~~

Include ``readcon-core.hpp`` for RAII wrappers.

.. code:: cpp

    #include "readcon-core.hpp"

    readcon::ConFrameIterator frames("file.con");
    for (auto&& frame : frames) {
        auto& cell = frame.cell();
        auto& atoms = frame.atoms();
        bool has_vel = frame.has_velocities();
        for (const auto& atom : atoms) {
            if (atom.has_velocity) {
                std::cout << atom.vx << " " << atom.vy << " " << atom.vz << "\n";
            }
        }
    }

Builder metadata helpers:

.. code:: cpp

    readcon::ConFrameBuilder builder({10.0, 10.0, 10.0}, {90.0, 90.0, 90.0});
    builder.set_energy(-42.5);
    builder.set_frame_index(7);
    builder.set_time(3.5);
    builder.set_timestep(0.2);
    builder.set_neb_bead(4);
    builder.set_neb_band(1);
    builder.set_scalar_metadata("convergence", 1.0e-3);
    builder.set_string_metadata("generator", "eon");
    builder.set_metadata_json(R"({"custom_key":"custom_value"})");
    builder.add_atom_with_velocity_and_forces(
        "Cu", 0.0, 0.0, 0.0,
        {true, false, true},
        0, 63.546,
        0.1, 0.2, 0.3,
        -0.1, -0.2, -0.3);

4.4 Build system integration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

4.4.1 Meson subproject
^^^^^^^^^^^^^^^^^^^^^^

.. code:: meson

    readcon = subproject('readcon-core')
    readcon_dep = readcon.get_variable('readcon_dep')

    executable('my_app', 'main.cpp', dependencies: readcon_dep)

4.4.2 CMake subproject
^^^^^^^^^^^^^^^^^^^^^^

.. code:: cmake

    add_subdirectory(readcon-core)
    target_link_libraries(my_app PRIVATE readcon-core::readcon-core)

5 metatensor TensorBlock export (v0.10.0+)
------------------------------------------

The optional ``metatensor`` Cargo feature exposes a Rust module that
builds `metatensor <https://docs.metatensor.org/latest/index.html>`_ ``TensorBlock`` instances from a frame. The feature
is default-off; enabling pulls in ``metatensor-core``'s CMake build.

.. code:: toml

    [dependencies]
    readcon-core = { version = "0.10", features = ["metatensor"] }

.. code:: rust

    use readcon_core::metatensor_export::{
        frame_positions_block, frame_velocities_block,
        frame_forces_block, frame_energies_block,
    };

    let frame = /* ... */;
    let positions = frame_positions_block(&frame)?;       // [N, 3] f64
    let velocities = frame_velocities_block(&frame)?;     // Option<TensorBlock>
    let forces = frame_forces_block(&frame)?;             // Option<TensorBlock>
    let energies = frame_energies_block(&frame)?;         // Option<TensorBlock>, [N, 1]

    // Convenience entry point for the most common case:
    let positions = frame.to_metatensor_positions_block()?;

Sample labels are ``atom_id`` (the post-grouping column-5 index from the
file); property labels are ``xyz`` (0/1/2) for vector quantities and a
single ``energy`` column for the scalar block. Users wanting a
``TensorMap`` keyed by species can build one on top of these blocks; the
species-vs-atom-list partition is downstream-specific so the helpers
expose the building blocks rather than baking in one convention.

6 Compression formats
---------------------

.. table::

    +--------------+-----------------+------------------------+----------------------------+-------------------------------------+
    | Extension    | Magic bytes     | Feature                | Reader                     | Writer                              |
    +==============+=================+========================+============================+=====================================+
    | ``.con.gz``  | ``1f 8b``       | always                 | transparent decode on read | ``from_path_gzip(_with_precision)`` |
    +--------------+-----------------+------------------------+----------------------------+-------------------------------------+
    | ``.con.zst`` | ``28 b5 2f fd`` | ``zstd`` (default-off) | transparent decode on read | ``from_path_zstd(_with_precision)`` |
    +--------------+-----------------+------------------------+----------------------------+-------------------------------------+

Builds without the ``zstd`` feature still detect zstd magic bytes on
read and return ``io::ErrorKind::Unsupported`` pointing at the feature
flag, so consumers never see a corrupt parse on a zstd file produced
by another tool.
