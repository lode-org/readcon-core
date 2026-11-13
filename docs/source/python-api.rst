======================
Python and C reference
======================

Rust items are documented on the types themselves. ``cargo doc --features python,parallel,zstd --no-deps``
builds that reference. The C header ``include/readcon-core.h`` and the C++ header
``include/readcon-core.hpp`` document each exported function. This page is the
Python surface those calls correspond to. The snippets are executed by ``tests/python/test_doc_snippets.py`` and
``tests/python/test_release_examples.py``. The Rust doctests cover
``ConFrameReader``, ``ConFrameWriter::from_path_append``,
``frames_from_text``, ``read_first_frame``, ``unit_conversion_factor``,
and the ``atom_id`` correspondence helpers. ``read_positions`` and
``read_coords`` are the fast coordinate path.

.. _py-read-con:

``read_con``
------------

.. code:: python

   readcon.read_con(path, n_threads=None, *, comm=None, mode="auto")

Read a ``.con`` or ``.convel`` path. ``n_threads`` is ``None``, ``0``, or ``1``
for the calling thread, and ``n >= 2`` for a Rayon pool of that size. A plain
file of 64 KiB or more stays mapped. ``.gz`` and ``.zst`` are chosen from the
extension and from the magic bytes. A pipe, including ``/dev/stdin``, is read
through the same open and is not mapped.

``read_all_frames`` is the same function.

``read_positions`` and ``read_coords``
--------------------------------------

These are the fast coordinate path. A stock CON or convel file is one
coordinate pass, and no per-frame Python object is built. ``read_con``
remains the path that returns frames, metadata, and optional sections.

.. code:: python

   positions = readcon.read_positions(path, n_threads=None)
   coords = readcon.read_coords(path)

``read_positions`` returns one ``float64`` array of shape
``(frames, atoms, 3)``. ``n_threads`` is ``None``, ``0``, or ``1`` for the
calling thread, and ``n >= 2`` for a Rayon pool of that size when the
build has ``parallel``. ``read_coords`` returns a dict. ``positions`` has
that same shape, ``masses`` is ``(frames, atoms)``, and ``cell`` is
``(frames, 6)`` with lengths then angles. ``atom_ids`` is column 5 and
``fixed`` is the column-4 bitmask, both ``(frames, atoms)``. ``species``
is one list of ``(symbol, count)`` runs when every frame uses that order,
and one list per frame when a later frame does not. ``has_section`` is
true when a frame carries velocities or another per-atom section.
``partial_fixed`` is true when a mask holds some axes only. The dict also
carries ``n_frames``, ``n_atoms``, ``parse_s``, ``convert_s``, and
``copy_s``. A file whose frames do not share one atom count raises
``ValueError``.

.. code:: python

   import readcon

   frame = readcon.ConFrame(
       (10.0, 10.0, 10.0),
       (90.0, 90.0, 90.0),
       [readcon.Atom("H", 1.25, 0.0, 0.0, atom_id=1, mass=1.0)],
   )
   readcon.write_con("one.con", [frame])
   positions = readcon.read_positions("one.con")
   coords = readcon.read_coords("one.con")
   assert positions.shape == (1, 1, 3)
   assert positions[0, 0, 0] == coords["positions"][0, 0, 0] == 1.25
   assert coords["masses"][0, 0] == 1.0
   assert list(coords["cell"][0]) == [10.0, 10.0, 10.0, 90.0, 90.0, 90.0]

``read_con_string``
-------------------

.. code:: python

   readcon.read_con_string(text)

Parse CON text that the caller already holds. ``sys.stdin.read()`` is that
text when the stream is plain CON.

``write_con``
-------------

.. code:: python

   readcon.write_con(path, frames, precision=None, compression=None, *,
                     canonical=False, comm=None, mode="auto", append=False)

One frame is converted and written, then dropped, before the next frame is
converted. A ``read_con`` result is written from the stored frames, so the
write does not build a Python frame per index. Those frames receive the same
header stamp as the C, Fortran, and Julia rewrites, and ``comm=`` writes that
same stored result, so the serial file and the collective file match. The
writer buffer is flushed before the function returns.

``compression`` is ``None`` to take the codec from the extension
(``.gz`` gzip, ``.zst`` zstd), or ``"gzip"``, ``"zstd"``, or ``"none"``.
A ``.zst`` write needs a build with the ``zstd`` feature.
``append=True`` extends an uncompressed file. Gzip, zstd, and ``comm=`` are refused.

``write_con_string``
--------------------

.. code:: python

   readcon.write_con_string(frames, precision=None, *, canonical=False,
                            start=0, stop=None)

``start`` and ``stop`` are a half-open index range. A ``read_con`` result in
that range is written from the stored frames, with the same header stamp as
``write_con``.

``read_extxyz`` and ``write_extxyz``
-------------------------------------

.. code:: python

   tables = readcon.read_extxyz(path)
   readcon.write_extxyz(path, tables)

``tables["positions"]`` has shape ``(frames, atoms, 3)``,
``tables["masses"]`` is ``(frames, atoms)``, ``tables["cell"]`` is
``(frames, 6)``, and ``tables["species"]`` is one tuple of symbols per frame.
``tables["arrays"]`` holds every per-atom column. A repeated symbol is one
string object, and a frame whose symbols match the previous frame is that
same tuple. ``tables["arrays"]["pos"]`` is ``tables["positions"]``.
``tables["arrays"]["masses"]`` is ``tables["masses"]``.
``tables["arrays"]["species"]`` is ``tables["species"]``.
``n_threads`` of 2 or more splits frames, or the atoms of one wide frame.
A file whose symbols differ, or whose header changes from frame to frame,
uses the general scan. The uniform scan is only for one species and one
column layout repeated in every frame.

``iter_con``
------------

.. code:: python

   readcon.iter_con(path, mmap=False, stream=False)

``stream=True`` decompresses and parses while it reads. ``mmap=True`` keeps
a plain file of at least 64 KiB mapped. The ASE plugin uses ``stream=True``
for a forward slice.

.. _py-atom-correspondence:

Atom correspondence
-------------------

.. code:: python

   readcon.atom_id_permutation(reference, other, *, strict=True)
   readcon.reorder_like(reference, other, *, strict=True)
   readcon.check_atom_id_consistency(frames, *, strict=True)
   readcon.minimum_image_displacements(reference, other, *, strict=True)

These calls pair atoms by column 5, ``atom_id``, and not by row.
``atom_id_permutation`` returns a ``list[int]``. Entry ``i`` is the index in
``other`` of the atom with the ``atom_id`` of ``reference`` atom ``i``.
``reorder_like`` returns a new ``ConFrame``, which is ``other`` in
``reference`` order. Each atom keeps its position, velocity, force, and
other per-atom values. Bond endpoints follow the new order.
``check_atom_id_consistency`` takes a list of frames, such as a trajectory
or a nudged elastic band (NEB), and returns ``None`` when every frame names the atoms of
``frames[0]``. A single frame checks that its ids are unique.
``minimum_image_displacements`` returns a ``float64`` array of shape
``(N, 3)`` in ``reference`` order. The cell and the periodic flags are the
reference frame's.

Duplicate ids, a missing or extra id, and a symbol mismatch fail in both
modes. ``strict=True`` also requires the masses (within ``1e-8``) and the
fixed masks to agree. ``strict=False`` allows a mass or mask difference.
A failure raises ``ValidationError``. Its ``frame_index``, ``atom_id``, and
``atom_index`` attributes are set when the failure names them.

C passes ``strict`` as a ``uint8_t``, with ``0`` for the lenient mass and
mask check. The C calls are ``rkr_frame_atom_id_permutation``,
``rkr_frame_reorder_like``, ``rkr_frames_check_atom_ids``, and
``rkr_frame_minimum_image_displacements``. A C failure leaves the detail in
``rkr_last_error_message``. The C++ wrappers are
``ConFrame::atom_id_permutation``, ``ConFrame::reorder_like``,
``ConFrame::minimum_image_displacements``, and
``check_atom_id_consistency``. The Rust calls take ``IdentityCheck::Strict``
or ``IdentityCheck::Lenient``. :doc:`atom-correspondence` is the how-to.

ASE formats
-----------

Install ``ase-readcon`` next to ``readcon``. Its ``pyproject.toml`` publishes:

.. code:: toml

   [project.entry-points."ase.ioformats"]
   readcon-con = "ase_readcon.io:readcon_con_format"
   readcon-convel = "ase_readcon.io:readcon_convel_format"

Install both packages, then ASE loads the ``ase.ioformats`` group:

.. code:: shell

   pip install readcon ase
   pip install -e ase-readcon

The format names are ``readcon-con`` and ``readcon-convel``. A read of
``index=":"`` returns every frame. A geometry file uses ``readcon-con``.
A file with velocities uses ``readcon-convel``, and that writer keeps the
velocities. Column 5 is ``arrays["atom_id"]``. A missing array is written
as ``0 .. n-1``. ASE tags are not column 5. A hold on every axis is
``FixAtoms``. A hold on some axes is ``FixCartesian`` with that mask.
Masses are the per-atom masses from the file, including a later frame
whose element order differs. The example below builds two frames, one
atom fixed on every axis and one fixed on z only, then reads them back.

.. code:: python

   import readcon
   from ase.constraints import FixAtoms, FixCartesian
   from ase.io import read, write

   cu = readcon.Atom("Cu", 0.0, 0.0, 0.0, fixed=[True, True, True], atom_id=4, mass=63.546)
   h = readcon.Atom("H", 1.2, 0.0, 0.0, fixed=[False, False, True], atom_id=9, mass=1.008)
   h.vx, h.vy, h.vz = 0.1, 0.0, 0.0
   frame = readcon.ConFrame((10.0, 10.0, 10.0), (90.0, 90.0, 90.0), [cu, h])
   readcon.write_con("run.con", [frame, frame])
   images = read("run.con", index=":", format="readcon-con")
   assert len(images) == 2
   assert list(images[0].arrays["atom_id"]) == [4, 9]
   assert abs(images[0].get_masses()[0] - 63.546) < 1e-6
   assert any(isinstance(c, FixAtoms) for c in images[0].constraints)
   assert any(isinstance(c, FixCartesian) for c in images[0].constraints)
   write("again.convel", images, format="readcon-convel")
   back = read("again.convel", index=":", format="readcon-convel")
   assert list(back[1].arrays["atom_id"]) == [4, 9]
   assert back[1].get_velocities()[1][0] != 0.0

C writer calls
--------------

``create_writer_from_path_append_c`` and
``create_writer_from_path_append_with_precision_c`` open an uncompressed
file at the end. ``rkr_writer_flush`` pushes the buffer.
``rkr_write_frames_to_string`` serializes frames without a file.
``rkr_read_all_frames`` stays on the calling thread.
``rkr_read_all_frames_n_threads`` takes the worker count. A count below 2
is the calling thread. ``rkr_read_positions`` returns the same coordinate
column as Python ``read_positions`` and does not build frame objects.
``rkr_position_block_values`` is the row-major ``x y z`` pointer.
``rkr_free_position_block`` frees the handle and that buffer. NULL is a
no-op. ``rkr_read_positions_n_threads`` takes the worker count. A count
below 2 is the calling thread. A file whose frames do not share one atom
count returns NULL. The declarations and the error records are in
``include/readcon-core.h``. The C++ header includes that C API. The C++ wrappers are ``ConFrameWriter::OpenMode``,
``ConFrameWriter::flush``, and ``ConFrameWriter::round_trip`` in
``include/readcon-core.hpp``.
