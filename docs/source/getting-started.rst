===============
Getting started
===============


.. tip::

   Install one language, then run the :doc:`tutorial`. XYZ/PDB/GRO
   conversion is a separate path: :doc:`chemfiles-tutorial`.

Install
-------

Pick **one** language. Version pins match this tree (``0.14.7``).

.. table::

    +--------------------+-------------------------------------------------------------------------------------+---------------------------------------------------------------------------------------------------------------------------------------------+
    | Package            | Install                                                                             | Destination                                                                                                                                 |
    +====================+=====================================================================================+=============================================================================================================================================+
    | Python CON I/O     | ``pip install 'readcon==0.14.7'``                                                   | `PyPI <https://pypi.org/project/readcon/>`_                                                                                                 |
    +--------------------+-------------------------------------------------------------------------------------+---------------------------------------------------------------------------------------------------------------------------------------------+
    | Python + chemfiles | ``pip install 'readcon-chemfiles==0.14.7'``                                         | `PyPI <https://pypi.org/project/readcon-chemfiles/>`_ (do not mix with lean ``readcon`` in the same venv)                                   |
    +--------------------+-------------------------------------------------------------------------------------+---------------------------------------------------------------------------------------------------------------------------------------------+
    | Rust CON I/O       | ``cargo add readcon-core@0.14.7``                                                   | `docs.rs <https://docs.rs/readcon-core>`_                                                                                                   |
    +--------------------+-------------------------------------------------------------------------------------+---------------------------------------------------------------------------------------------------------------------------------------------+
    | Rust + chemfiles   | ``cargo add readcon-core@0.14.7 --features chemfiles``                              | same crate                                                                                                                                  |
    +--------------------+-------------------------------------------------------------------------------------+---------------------------------------------------------------------------------------------------------------------------------------------+
    | Campaign store     | ``cargo add readcon-db`` / ``pip install readcon-db``                               | `docs <https://lode-org.github.io/readcon-db/>`_ · `docs.rs <https://docs.rs/readcon-db>`_ · `PyPI <https://pypi.org/project/readcon-db/>`_ |
    +--------------------+-------------------------------------------------------------------------------------+---------------------------------------------------------------------------------------------------------------------------------------------+
    | Julia              | from this repo: ``julia --project=julia/ReadCon -e 'using Pkg; Pkg.instantiate()'`` | :doc:`bindings`                                                                                                                  |
    +--------------------+-------------------------------------------------------------------------------------+---------------------------------------------------------------------------------------------------------------------------------------------+
    | C / C++ / Fortran  | CMake FetchContent, Meson wrap, or ``pkg-config readcon-core``                      | :doc:`bindings`                                                                                                                  |
    +--------------------+-------------------------------------------------------------------------------------+---------------------------------------------------------------------------------------------------------------------------------------------+
    | Prebuilt C lib     | ``readcon-core-clib-$VERSION-$target.tar.gz`` on the GitHub Release                 | :doc:`bindings` (Windows row is lean; chemfiles not shipped)                                                                     |
    +--------------------+-------------------------------------------------------------------------------------+---------------------------------------------------------------------------------------------------------------------------------------------+

Python: CON I/O
~~~~~~~~~~~~~~~

.. code:: shell

    pip install 'readcon==0.14.7'

Python: CON I/O plus format conversion
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code:: shell

    pip install 'readcon-chemfiles==0.14.7'
    # do not also install lean readcon in the same venv

Rust: CON I/O
~~~~~~~~~~~~~

.. code:: shell

    cargo add readcon-core@0.14.7

Rust: with conversion
~~~~~~~~~~~~~~~~~~~~~

.. code:: shell

    cargo add readcon-core@0.14.7 --features chemfiles

Campaign store (``readcon-db``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Separate package; CON text stays authoritative.

.. code:: shell

    cargo add readcon-db
    # or: pip install readcon-db

Julia
~~~~~

From a checkout of this repository:

.. code:: shell

    julia --project=julia/ReadCon -e 'using Pkg; Pkg.instantiate()'

Point the wrapper at a cargo-c prefix or shared library with
``READCON_LIB_PATH`` or ``READCON_CORE_LIB`` (both names work). The
Windows clib tarball is lean; chemfiles is not in that asset.

Language API notes: :doc:`bindings`.

Fortran / C / C++
~~~~~~~~~~~~~~~~~

Headers in ``include/`` are shipped. cbindgen is **not** required.
CMake FetchContent / ``find_package(readcon-core)``, Meson
``dependency('readcon-core')``, or ``pkg-config --libs readcon-core``
after a prefix install. The cxx tarball on the GitHub Release is
``readcon-core-cxx-$VERSION.tar.gz``.

.. code:: cmake

    include(FetchContent)
    FetchContent_Declare(
      readcon-core
      URL https://github.com/lode-org/readcon-core/releases/download/v0.14.7/readcon-core-cxx-0.14.7.tar.gz
      URL_HASH SHA256=14710ec007b2131d2c0e13931bf3e7e443ce87627ace2fb21497a05ea0b5df43
    )
    FetchContent_MakeAvailable(readcon-core)
    target_link_libraries(app PRIVATE readcon-core::shared)

The slim cxx tarball on the ``v0.14.7`` GitHub Release is the FetchContent
URL. A vendor tarball (``readcon-core-cxx-0.14.7-vendor.tar.gz``) ships
crates for offline builds. The Meson wrap file is
``packaging/wrapdb/readcon-core.wrap`` on that same release.

.. code:: meson

    readcon_dep = dependency('readcon-core')

From a git checkout:

.. code:: shell

    cmake -S . -B build -DCMAKE_INSTALL_PREFIX=$PWD/prefix
    cmake --build build && cmake --install build
    export PKG_CONFIG_PATH=$PWD/prefix/lib/pkgconfig
    pkg-config --cflags --libs readcon-core

Fortran smoke from a checkout (after a release build of the cdylib):

.. code:: shell

    cd fortran/ReadCon && fpm test --flag "-L../../target/release" \
      --link-flag "-L../../target/release -lreadcon_core -ldl -lpthread -lm"

Prebuilt C library tarball (lean cargo-c)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The GitHub Release also attaches
``readcon-core-clib-$VERSION-$target.tar.gz`` (headers + shared
library + ``readcon-core.pc``). This is a cargo-c prefix, not the
cxx *source* tarball. cbindgen is not required.

.. code:: shell

    tar xf readcon-core-clib-0.14.7-x86_64-unknown-linux-gnu.tar.gz
    prefix=$PWD/readcon-core-clib-0.14.7-x86_64-unknown-linux-gnu
    export PKG_CONFIG_PATH=$prefix/lib/pkgconfig:$PKG_CONFIG_PATH
    export LD_LIBRARY_PATH=$prefix/lib:$LD_LIBRARY_PATH
    pkg-config --cflags --libs readcon-core

Julia: ``READCON_LIB_PATH`` or ``READCON_CORE_LIB`` (file or prefix).
Fortran: same ``PKG_CONFIG_PATH``, then ``fpm test`` in
``fortran/ReadCon`` (``link = ["readcon_core"]``).

The Windows clib tarball is the **lean** DLL. chemfiles is **not**
shipped for Windows here (explicit matrix).

.. table::

    +--------------------------------+-------------------------------------+------------------+
    | Target                         | Runner                              | chemfiles        |
    +================================+=====================================+==================+
    | ``x86_64-unknown-linux-gnu``   | ubuntu-24.04 (BFD, same as wheels)  | off (lean)       |
    +--------------------------------+-------------------------------------+------------------+
    | ``aarch64-unknown-linux-gnu``  | ubuntu-24.04-arm                    | off (lean)       |
    +--------------------------------+-------------------------------------+------------------+
    | ``aarch64-apple-darwin``       | macos-15                            | off (lean)       |
    +--------------------------------+-------------------------------------+------------------+
    | ``x86_64-apple-darwin``        | macos-15-intel                      | off (lean)       |
    +--------------------------------+-------------------------------------+------------------+
    | ``x86_64-pc-windows-msvc``     | windows-2022                        | **not shipped**  |
    +--------------------------------+-------------------------------------+------------------+

Conversion on Windows: ``pip install 'readcon-chemfiles==0.14.7'``, or
build from source with ``--features chemfiles``.

Smoke test
----------

From the repository root (fixtures live under ``resources/test/``):

.. code:: python

    import readcon
    frame = readcon.read_first_frame("resources/test/tiny_cuh2.con")
    print(frame.cell, len(frame))

.. code:: rust

    use readcon_core::iterators::read_first_frame;
    let frame = read_first_frame(std::path::Path::new("resources/test/tiny_cuh2.con"))?;
    println!("{:?} {}", frame.header.boxl, frame.atom_data.len());

Where to go next
----------------

Documentation follows `Diátaxis <https://diataxis.fr/>`_. Use one quadrant at a time.

.. table::

    +-------------------------------------------------+------------------------------------------------+-------------+
    | Goal                                            | Page                                           | Kind        |
    +=================================================+================================================+=============+
    | Learn CON I/O end-to-end                        | :doc:`tutorial`                     | Tutorial    |
    +-------------------------------------------------+------------------------------------------------+-------------+
    | Migrate foreign formats → CON (+ db, selection) | :doc:`migrate`                       | How-to      |
    +-------------------------------------------------+------------------------------------------------+-------------+
    | Task recipes by language                        | :doc:`howto`                           | How-to      |
    +-------------------------------------------------+------------------------------------------------+-------------+
    | XYZ / PDB / GRO → CON                           | :doc:`chemfiles-tutorial` | Tutorial    |
    +-------------------------------------------------+------------------------------------------------+-------------+
    | Batch convert / C conversion API                | :doc:`chemfiles-howto`       | How-to      |
    +-------------------------------------------------+------------------------------------------------+-------------+
    | Why conversion is optional; bonds               | :doc:`chemfiles-explain`   | Explanation |
    +-------------------------------------------------+------------------------------------------------+-------------+
    | Why CON / sections / stack                      | :doc:`faq`, :doc:`evolution` | Explanation |
    +-------------------------------------------------+------------------------------------------------+-------------+
    | On-disk format                                  | :doc:`spec`                             | Reference   |
    +-------------------------------------------------+------------------------------------------------+-------------+
    | API tables                                      | :doc:`bindings`                     | Reference   |
    +-------------------------------------------------+------------------------------------------------+-------------+
    | Measurements (ASV / Cachegrind / peers)         | :doc:`benchmarks`                 | Explanation |
    +-------------------------------------------------+------------------------------------------------+-------------+

Scope (map of the stack)
------------------------

.. table::

    +---------------------------------+------------------------------------------------------------------------------------------------------------------------------------+
    | Task                            | Path                                                                                                                               |
    +=================================+====================================================================================================================================+
    | Read / write CON                | ``readcon`` / ``readcon-core``                                                                                                     |
    +---------------------------------+------------------------------------------------------------------------------------------------------------------------------------+
    | Link from Fortran / C / C++     | Hourglass ``rkr_*`` ABI                                                                                                            |
    +---------------------------------+------------------------------------------------------------------------------------------------------------------------------------+
    | Campaign store (install)        | ``cargo add readcon-db`` / ``pip install readcon-db``                                                                              |
    +---------------------------------+------------------------------------------------------------------------------------------------------------------------------------+
    | Many trajectories, multi-reader | `readcon-db docs <https://lode-org.github.io/readcon-db/>`_ · `docs.rs API <https://docs.rs/readcon-db>`_ (CON text authoritative) |
    +---------------------------------+------------------------------------------------------------------------------------------------------------------------------------+
    | Campaign field projection       | ```index_proj`` <https://docs.rs/readcon-core/latest/readcon_core/index_proj/>`_ (same meanings as db indexes)                     |
    +---------------------------------+------------------------------------------------------------------------------------------------------------------------------------+
    | Foreign structure file → CON    | Optional chemfiles build                                                                                                           |
    +---------------------------------+------------------------------------------------------------------------------------------------------------------------------------+
    | ASE calculator hand-off         | Optional ``to_ase`` / ``from_ase``                                                                                                 |
    +---------------------------------+------------------------------------------------------------------------------------------------------------------------------------+
    | Migrate foreign stack → CON     | :doc:`migrate` (CLI ``convert``, ``convert_to_con``)                                                                     |
    +---------------------------------+------------------------------------------------------------------------------------------------------------------------------------+
    | PR / CI speed gates             | :doc:`benchmarks` (ASV + Cachegrind)                                                                                  |
    +---------------------------------+------------------------------------------------------------------------------------------------------------------------------------+

Library layout: :doc:`architecture`.
