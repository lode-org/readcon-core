===============
Getting started
===============


.. tip::

   Install here, then take the :doc:`tutorial` (One Good Tutorial). Conversion
   from XYZ/PDB/GRO is a separate path: :doc:`chemfiles-tutorial`.

Install
-------

Pick **one** language. Version pins match this tree (``0.14.0``).

.. table::

    +--------------------+-------------------------------------------------------------------------------------+---------------------------------------------------------------------------------------------------------------------------------------------+
    | Package            | Install                                                                             | Destination                                                                                                                                 |
    +====================+=====================================================================================+=============================================================================================================================================+
    | Python CON I/O     | ``pip install 'readcon==0.14.0'``                                                   | `PyPI <https://pypi.org/project/readcon/>`_                                                                                                 |
    +--------------------+-------------------------------------------------------------------------------------+---------------------------------------------------------------------------------------------------------------------------------------------+
    | Python + chemfiles | ``pip install 'readcon-chemfiles==0.14.0'``                                         | `PyPI <https://pypi.org/project/readcon-chemfiles/>`_ (do not mix with lean ``readcon`` in the same venv)                                   |
    +--------------------+-------------------------------------------------------------------------------------+---------------------------------------------------------------------------------------------------------------------------------------------+
    | Rust CON I/O       | ``cargo add readcon-core``                                                          | `docs.rs <https://docs.rs/readcon-core>`_                                                                                                   |
    +--------------------+-------------------------------------------------------------------------------------+---------------------------------------------------------------------------------------------------------------------------------------------+
    | Rust + chemfiles   | ``cargo add readcon-core --features chemfiles``                                     | same crate                                                                                                                                  |
    +--------------------+-------------------------------------------------------------------------------------+---------------------------------------------------------------------------------------------------------------------------------------------+
    | Campaign store     | ``cargo add readcon-db`` / ``pip install readcon-db``                               | `docs <https://lode-org.github.io/readcon-db/>`_ · `docs.rs <https://docs.rs/readcon-db>`_ · `PyPI <https://pypi.org/project/readcon-db/>`_ |
    +--------------------+-------------------------------------------------------------------------------------+---------------------------------------------------------------------------------------------------------------------------------------------+
    | Julia              | from this repo: ``julia --project=julia/ReadCon -e 'using Pkg; Pkg.instantiate()'`` | `bindings <bindings.rst>`_                                                                                                                  |
    +--------------------+-------------------------------------------------------------------------------------+---------------------------------------------------------------------------------------------------------------------------------------------+
    | C / C++ / Fortran  | build ``libreadcon_core`` then link                                                 | `bindings <bindings.rst>`_                                                                                                                  |
    +--------------------+-------------------------------------------------------------------------------------+---------------------------------------------------------------------------------------------------------------------------------------------+

Python — CON I/O
~~~~~~~~~~~~~~~~

.. code:: shell

    pip install 'readcon==0.14.0'

Python — CON I/O plus format conversion
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code:: shell

    pip install 'readcon-chemfiles==0.14.0'
    # do not also install lean readcon in the same venv

Rust — CON I/O
~~~~~~~~~~~~~~

.. code:: shell

    cargo add readcon-core

Rust — with conversion
~~~~~~~~~~~~~~~~~~~~~~

.. code:: shell

    cargo add readcon-core --features chemfiles

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

Language API notes: `bindings <bindings.rst>`_.

Fortran / C / C++
~~~~~~~~~~~~~~~~~

Build the shared library from this repository, then link as in
`bindings <bindings.rst>`_. Headers: ``include/readcon-core.h`` /
``include/readcon-core.hpp``.

.. code:: shell

    cargo build --release
    # Fortran smoke (example):
    # cd fortran/ReadCon && fpm test --flag "-L../../target/release" \
    #   --link-flag "-L../../target/release -lreadcon_core -ldl -lpthread -lm"

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
    | Learn CON I/O end-to-end                        | `tutorial <tutorial.rst>`_                     | Tutorial    |
    +-------------------------------------------------+------------------------------------------------+-------------+
    | Migrate foreign formats → CON (+ db, selection) | `migrate <migrate.rst>`_                       | How-to      |
    +-------------------------------------------------+------------------------------------------------+-------------+
    | Task recipes by language                        | `howto <howto.rst>`_                           | How-to      |
    +-------------------------------------------------+------------------------------------------------+-------------+
    | XYZ / PDB / GRO → CON                           | `chemfiles-tutorial <chemfiles-tutorial.rst>`_ | Tutorial    |
    +-------------------------------------------------+------------------------------------------------+-------------+
    | Batch convert / C conversion API                | `chemfiles-howto <chemfiles-howto.rst>`_       | How-to      |
    +-------------------------------------------------+------------------------------------------------+-------------+
    | Why conversion is optional; bonds               | `chemfiles-explain <chemfiles-explain.rst>`_   | Explanation |
    +-------------------------------------------------+------------------------------------------------+-------------+
    | Why CON / sections / stack                      | `faq <faq.rst>`_, `evolution <evolution.rst>`_ | Explanation |
    +-------------------------------------------------+------------------------------------------------+-------------+
    | On-disk format                                  | `spec <spec.rst>`_                             | Reference   |
    +-------------------------------------------------+------------------------------------------------+-------------+
    | API tables                                      | `bindings <bindings.rst>`_                     | Reference   |
    +-------------------------------------------------+------------------------------------------------+-------------+
    | Measurements (ASV / Cachegrind / peers)         | `benchmarks <benchmarks.rst>`_                 | Explanation |
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
    | Migrate foreign stack → CON     | `migrate <migrate.rst>`_ (CLI ``convert``, ``convert_to_con``)                                                                     |
    +---------------------------------+------------------------------------------------------------------------------------------------------------------------------------+
    | PR / CI speed gates             | `benchmarks <benchmarks.rst>`_ (ASV + Cachegrind)                                                                                  |
    +---------------------------------+------------------------------------------------------------------------------------------------------------------------------------+

Library layout: `architecture <architecture.rst>`_.
