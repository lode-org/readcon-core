===============
Getting started
===============


.. contents::

.. tip::

   This is the **front door**. Use the sidebar for the full map; the links
   below are proper Sphinx references (not raw ``:doc:`` text).

Install
-------

Rust (CON I/O only)
~~~~~~~~~~~~~~~~~~~

.. code:: shell

    cargo add readcon-core

Python lean (chemfiles APIs present but disabled)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code:: shell

    pip install 'readcon==0.13.1'

Python full (XYZ/PDB/… → CON + selection)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code:: shell

    pip install 'readcon-chemfiles==0.13.1'
    # do not also install lean readcon in the same venv

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

See the full walkthrough in :doc:`chemfiles-tutorial`. Run the literate Org
notebook (:doc:`chemfiles-notebook`) with::

   scripts/run-chemfiles-notebook.sh

Where to go next
----------------

.. list-table::
   :header-rows: 1
   :widths: 45 55
   :class: next-steps

   * - Goal
     - Page
   * - Learn CON I/O patterns
     - :doc:`tutorials`
   * - Convert XYZ / PDB / GRO → CON
     - :doc:`chemfiles-tutorial`
   * - Run the literate Org notebook
     - :doc:`chemfiles-notebook`
   * - Task recipes (how-to)
     - :doc:`chemfiles-howto`
   * - Why chemfiles, bonds, indices
     - :doc:`chemfiles-explain`
   * - API tables
     - :doc:`chemfiles-reference`, :doc:`bindings`
   * - On-disk format
     - :doc:`spec`
   * - Release / contribute
     - :doc:`contributing`
