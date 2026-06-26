===============
Getting started
===============


.. contents::

.. tip::

   Prefer the hosted docs theme (shibuya). This page is the **front door**;
   deep topics live in the toctree sections below.

Install
-------

Rust (CON I/O only)
~~~~~~~~~~~~~~~~~~~

.. code:: shell

    cargo add readcon-core

Python lean (stubs for chemfiles APIs)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code:: shell

    pip install 'readcon==0.13.1'

Python full (convert XYZ/PDB/… → CON + selection)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code:: shell

    pip install 'readcon-chemfiles==0.13.1'
    # do not also install lean `readcon` in the same venv

Rust with chemfiles
~~~~~~~~~~~~~~~~~~~

.. code:: shell

    cargo add readcon-core --features chemfiles
    # or in this repo: cargo build --features chemfiles

Read a CON file
---------------

.. code:: python

    import readcon
    frame = readcon.read_first_frame("structure.con")
    print(frame.cell, len(frame.atoms))

.. code:: rust

    use readcon_core::iterators::read_first_frame;
    let frame = read_first_frame(std::path::Path::new("structure.con"))?;

Convert a foreign format into CON
---------------------------------

.. code:: python

    import readcon
    assert readcon.has_chemfiles_support()  # need readcon-chemfiles
    frame = readcon.read_chemfiles_first("water.xyz")
    frame.write_con("water.con")

Full walkthrough: :doc:\`chemfiles-tutorial\`. Executable Org notebook:
:doc:\`chemfiles-notebook\` (``scripts/run-chemfiles-notebook.sh``).

Where to go next
----------------

.. table::

    +---------------------------------+-------------------------------------------------+
    | Goal                            | Page                                            |
    +=================================+=================================================+
    | Learn CON I/O patterns          | :doc:\`tutorials\`                              |
    +---------------------------------+-------------------------------------------------+
    | Convert XYZ/PDB/GRO → CON       | :doc:\`chemfiles-tutorial\`                     |
    +---------------------------------+-------------------------------------------------+
    | Run the literate notebook       | :doc:\`chemfiles-notebook\`                     |
    +---------------------------------+-------------------------------------------------+
    | Task recipes                    | :doc:\`chemfiles-howto\`                        |
    +---------------------------------+-------------------------------------------------+
    | Why chemfiles / bonds / indices | :doc:\`chemfiles-explain\`                      |
    +---------------------------------+-------------------------------------------------+
    | API tables                      | :doc:\`chemfiles-reference\`, :doc:\`bindings\` |
    +---------------------------------+-------------------------------------------------+
    | On-disk format                  | :doc:\`spec\`                                   |
    +---------------------------------+-------------------------------------------------+
    | Release / contribute            | :doc:\`contributing\`                           |
    +---------------------------------+-------------------------------------------------+
