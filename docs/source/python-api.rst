======================
Python and C reference
======================

Rust items are documented on the types themselves. ``cargo doc --features python,parallel,zstd --no-deps``
builds that reference. The C header ``include/readcon-core.h`` and the C++ header
``include/readcon-core.hpp`` document each exported function. This page is the
Python surface those calls correspond to. The snippets are the ones in
``tests/python/test_release_examples.py`` and the Rust doctests on
``ConFrameReader``, ``ConFrameWriter::from_path_append``, and
``unit_conversion_factor``. ``read_positions`` and ``read_coords`` are
the fast coordinate path.

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
``(frames, 6)`` with lengths then angles. The dict also carries
``n_frames``, ``n_atoms``, ``parse_s``, ``convert_s``, and ``copy_s``.
A file whose frames do not share one atom count raises ``ValueError``.

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

``iter_con``
------------

.. code:: python

   readcon.iter_con(path, mmap=False, stream=False)

``stream=True`` decompresses and parses while it reads. ``mmap=True`` keeps
a plain file of at least 64 KiB mapped. The ASE plugin uses ``stream=True``
for a forward slice.

ASE formats
-----------

Install ``ase-readcon`` next to ``readcon``. Its ``pyproject.toml`` publishes:

.. code:: toml

   [project.entry-points."ase.ioformats"]
   readcon-con = "ase_readcon.io:readcon_con_format"
   readcon-convel = "ase_readcon.io:readcon_convel_format"

ASE loads the ``ase.ioformats`` group. The format names are ``readcon-con``
and ``readcon-convel``.

.. code:: python

   from ase.io import read, write
   images = read("run.con", index=":", format="readcon-con")
   write("again.convel", images, format="readcon-convel")

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
