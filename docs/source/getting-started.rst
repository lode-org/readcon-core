===============
Getting started
===============


.. tip::

   Install one language, then run the :doc:`tutorial`. XYZ/PDB/GRO
   conversion is a separate path: :doc:`chemfiles-tutorial`.

Install
-------

Pick **one** language. Version pins match this tree (``0.14.8``).

.. table::

    +--------------------+-------------------------------------------------------------------------------------+---------------------------------------------------------------------------------------------------------------------------------------------+
    | Package            | Install                                                                             | Destination                                                                                                                                 |
    +====================+=====================================================================================+=============================================================================================================================================+
    | Python CON I/O     | ``pip install 'readcon==0.14.8'``                                                   | `PyPI <https://pypi.org/project/readcon/>`_                                                                                                 |
    +--------------------+-------------------------------------------------------------------------------------+---------------------------------------------------------------------------------------------------------------------------------------------+
    | Python + chemfiles | ``pip install 'readcon-chemfiles==0.14.8'``                                         | `PyPI <https://pypi.org/project/readcon-chemfiles/>`_ (do not mix with lean ``readcon`` in the same venv)                                   |
    +--------------------+-------------------------------------------------------------------------------------+---------------------------------------------------------------------------------------------------------------------------------------------+
    | Rust CON I/O       | ``cargo add readcon-core@0.14.8``                                                   | `docs.rs <https://docs.rs/readcon-core>`_                                                                                                   |
    +--------------------+-------------------------------------------------------------------------------------+---------------------------------------------------------------------------------------------------------------------------------------------+
    | Rust + chemfiles   | ``cargo add readcon-core@0.14.8 --features chemfiles``                              | same crate                                                                                                                                  |
    +--------------------+-------------------------------------------------------------------------------------+---------------------------------------------------------------------------------------------------------------------------------------------+
    | Campaign store     | ``cargo add readcon-db`` / ``pip install readcon-db``                               | `docs <https://lode-org.github.io/readcon-db/>`_ · `docs.rs <https://docs.rs/readcon-db>`_ · `PyPI <https://pypi.org/project/readcon-db/>`_ |
    +--------------------+-------------------------------------------------------------------------------------+---------------------------------------------------------------------------------------------------------------------------------------------+
    | Julia              | from this repo: ``julia --project=julia/ReadCon -e 'using Pkg; Pkg.instantiate()'`` | :doc:`bindings`                                                                                                                  |
    +--------------------+-------------------------------------------------------------------------------------+---------------------------------------------------------------------------------------------------------------------------------------------+
    | C / C++ / Fortran  | CMake FetchContent, Meson wrap, or ``pkg-config readcon-core``                      | :doc:`bindings`                                                                                                                  |
    +--------------------+-------------------------------------------------------------------------------------+---------------------------------------------------------------------------------------------------------------------------------------------+
    | Prebuilt C ABI     | ``readcon-core-clib-$VER-$target.tar.gz`` on the GitHub Release                     | :doc:`bindings` (Julia / Fortran / ``pkg-config``)                                                                               |
    +--------------------+-------------------------------------------------------------------------------------+---------------------------------------------------------------------------------------------------------------------------------------------+

Python: CON I/O
~~~~~~~~~~~~~~~

.. code:: shell

    pip install 'readcon==0.14.8'

Python: CON I/O plus format conversion
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code:: shell

    pip install 'readcon-chemfiles==0.14.8'
    # do not also install lean readcon in the same venv

Rust: CON I/O
~~~~~~~~~~~~~

.. code:: shell

    cargo add readcon-core@0.14.8

Rust: with conversion
~~~~~~~~~~~~~~~~~~~~~

.. code:: shell

    cargo add readcon-core@0.14.8 --features chemfiles

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
      URL https://github.com/lode-org/readcon-core/releases/download/v0.14.8/readcon-core-cxx-0.14.8.tar.gz
      URL_HASH SHA256=5ae875b90faef98102949c9c0ec03d34ffab9ba5bdc8386c70e42cc153fcbd4e
    )
    FetchContent_MakeAvailable(readcon-core)
    target_link_libraries(app PRIVATE readcon-core::shared)

The slim cxx tarball on the ``v0.14.8`` GitHub Release is the FetchContent
URL. A vendor tarball (``readcon-core-cxx-0.14.8-vendor.tar.gz``) ships
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

Prebuilt C ABI (no local cargo): unpack
``readcon-core-clib-$VERSION-$target.tar.gz`` from the GitHub Release, then
``export READCON_CORE_LIB`` / ``PKG_CONFIG_PATH``. Attach assets to an
already-published tag with Actions → **C ABI library tarball** →
``tag=vX.Y.Z``. Windows + chemfiles is not a clib asset.

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
