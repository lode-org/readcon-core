================================
How-to — atom correspondence
================================


.. note::

   Diátaxis *how-to*. The file layout is the :doc:`tutorial`. Language
   recipes for read and write are :doc:`howto`.

Column 5 is ``atom_id``, the atom's index before type-grouping. readcon-core
keeps that id through read and write. The in-memory order is still the
type-grouped file order, so a positional zip of two frames pairs whatever
atoms happen to share a slot. A writer that emits oxygen before carbon, or
a band image whose rows were renumbered, then reports a displacement for
the wrong atom.

The CPC paper treats that stable id as what makes atom correspondence
possible. These four calls are that correspondence. ``reference`` is frame A.
``other`` is frame B. Errors name the frame index and the ``atom_id``.

.. list-table::
   :header-rows: 1
   :widths: 32 68

   * - Call
     - Result
   * - ``atom_id_permutation``
     - ``perm[i]`` is the index in B of the atom with A's id at index ``i``
   * - ``reorder_like``
     - B in A's order. Positions, velocities, forces, and the other per-atom sections move with the atom. Bond endpoints are remapped
   * - ``check_atom_id_consistency``
     - The first frame in a trajectory or NEB band that disagrees with frame 0, and the atom
   * - ``minimum_image_displacements``
     - Wrapped ``r_B - r_A`` for each matched pair, shape ``(N, 3)`` in A's order

Duplicate ids, a missing id, an extra id, and a symbol mismatch fail in
both modes. ``strict`` (the default) also requires the mass and the fixed
mask to agree. Masses within ``1e-8`` agree, the same tolerance the builder
uses for one mass per CON type. ``strict`` false keeps the id and symbol
checks and allows a mass or mask difference.

The displacement uses the reference frame's cell. ``FrameHeader::cell_matrix``
supplies the lattice (a stored ``lattice_vectors`` matrix, otherwise the
matrix built from lines 3–4) and ``pbc_effective`` supplies the periodic
axes. A missing ``pbc`` key is fully periodic. The helper inverts that
matrix.

Rust
----

.. code:: rust

    use readcon_core::{
        IdentityCheck, atom_id_permutation, check_atom_id_consistency,
        minimum_image_displacements, reorder_like,
    };

    let perm = atom_id_permutation(&reactant, &product, IdentityCheck::Strict)?;
    let product_in_reactant_order = reorder_like(&reactant, &product, IdentityCheck::Strict)?;
    check_atom_id_consistency(&band, IdentityCheck::Strict)?;
    let disp = minimum_image_displacements(&reactant, &product, IdentityCheck::Strict)?;

``disp[i]`` is the minimum-image step of reactant atom ``i``. A coordinate that
was stored one cell away comes back as the short vector.

Python
------

.. code:: python

    import readcon

    perm = readcon.atom_id_permutation(reactant, product)
    ordered = readcon.reorder_like(reactant, product)
    readcon.check_atom_id_consistency(band)
    disp = readcon.minimum_image_displacements(reactant, product)  # (N, 3)

Pass ``strict=False`` to allow a mass or fixed-mask difference. A failure
raises ``ValidationError``. ``frame_index``, ``atom_id``, and ``atom_index`` are
set when the failure names them. Frame 0 is the reference. Frame 1 is the
other frame. In a band, ``frame_index`` is the first image that disagrees
with image 0.

C and C++
---------

.. code:: c

    uint64_t perm[/* N */];
    rkr_frame_atom_id_permutation(frame_a, frame_b, 1, perm, n);

    RKRConFrame *ordered = rkr_frame_reorder_like(frame_a, frame_b, 1);

    uint64_t frame_index, atom_id;
    rkr_frames_check_atom_ids(frames, nframes, 1, &frame_index, &atom_id);

    double disp[/* 3 * N */];
    rkr_frame_minimum_image_displacements(frame_a, frame_b, 1, disp, 3 * n);

``strict`` is ``0`` for the lenient mass and mask check. On failure the detail
is ``rkr_last_error_message``. The consistency call writes ``UINT64_MAX`` to
both outputs when the band agrees. ``rkr_frame_reorder_like`` returns a
handle the caller frees with ``free_rkr_frame``.

The C++ wrappers are ``ConFrame::atom_id_permutation``,
``ConFrame::reorder_like``, ``ConFrame::minimum_image_displacements``, and
``check_atom_id_consistency``. They throw ``readcon::Error`` with that same
message.

A Claisen-like allyl vinyl ether, written with carbon before oxygen in the
reactant and oxygen before carbon in the product, is the regression for
the positional zip. One image of a three-image band stored with two atoms
swapped is the regression for a renumbered band.
