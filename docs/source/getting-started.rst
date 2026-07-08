===============
Getting started
===============


.. tip::

   Install here, then take the :doc:`tutorial` (One Good Tutorial). Conversion
   from XYZ/PDB/GRO is a separate path: :doc:`chemfiles-tutorial`.

Install
-------

Pick **one** language. Version pins match this tree (``0.14.0``).

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

    +-----------------------------------+------------------------------------------------+-------------+
    | Goal                              | Page                                           | Kind        |
    +===================================+================================================+=============+
    | Learn CON I/O end-to-end          | `tutorial <tutorial.rst>`_                     | Tutorial    |
    +-----------------------------------+------------------------------------------------+-------------+
    | Task recipes by language          | `howto <howto.rst>`_                           | How-to      |
    +-----------------------------------+------------------------------------------------+-------------+
    | XYZ / PDB / GRO → CON             | `chemfiles-tutorial <chemfiles-tutorial.rst>`_ | Tutorial    |
    +-----------------------------------+------------------------------------------------+-------------+
    | Batch convert / C conversion API  | `chemfiles-howto <chemfiles-howto.rst>`_       | How-to      |
    +-----------------------------------+------------------------------------------------+-------------+
    | Why conversion is optional; bonds | `chemfiles-explain <chemfiles-explain.rst>`_   | Explanation |
    +-----------------------------------+------------------------------------------------+-------------+
    | Why CON / sections / stack        | `faq <faq.rst>`_, `evolution <evolution.rst>`_ | Explanation |
    +-----------------------------------+------------------------------------------------+-------------+
    | On-disk format                    | `spec <spec.rst>`_                             | Reference   |
    +-----------------------------------+------------------------------------------------+-------------+
    | API tables                        | `bindings <bindings.rst>`_                     | Reference   |
    +-----------------------------------+------------------------------------------------+-------------+

Scope (map of the stack)
------------------------

.. table::

    +---------------------------------+-----------------------------------------+
    | Task                            | Path                                    |
    +=================================+=========================================+
    | Read / write CON                | ``readcon`` / ``readcon-core``          |
    +---------------------------------+-----------------------------------------+
    | Link from Fortran / C / C++     | Hourglass ``rkr_*`` ABI                 |
    +---------------------------------+-----------------------------------------+
    | Many trajectories, multi-reader | ``readcon-db`` (CON text authoritative) |
    +---------------------------------+-----------------------------------------+
    | Foreign structure file → CON    | Optional chemfiles build                |
    +---------------------------------+-----------------------------------------+
    | ASE calculator hand-off         | Optional ``to_ase`` / ``from_ase``      |
    +---------------------------------+-----------------------------------------+

Library layout: `architecture <architecture.rst>`_. Measurements:
`benchmarks <benchmarks.rst>`_.
