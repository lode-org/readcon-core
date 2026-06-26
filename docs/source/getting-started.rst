===============
Getting started
===============


.. contents::

.. figure:: /_static/figures/conversion-pipeline.svg
   :alt: XYZ, PDB, or GRO converted into a CON frame and written for eOn or LODE
   :align: center
   :width: 100%

   **Format conversion** — common structure files become a CON frame, then a
   ``.con`` for eOn / LODE (or any language binding). Needs the *with
   conversions* install below.

.. figure:: /_static/figures/lean-vs-conversion.svg
   :alt: Default CON-only install versus install that also converts other formats
   :align: center
   :width: 100%

   **Two installs** — default package is CON I/O only; the conversion package
   adds XYZ / PDB / GRO (and similar) → CON. Same CON APIs either way.

.. tip::

   Start here for install and the shortest paths. Use the right sidebar for
   this page’s sections; top nav **Convert** is the conversion tutorial and
   recipes.

Install
-------

Rust — CON I/O only
~~~~~~~~~~~~~~~~~~~

.. code:: shell

    cargo add readcon-core

Python — CON I/O only
~~~~~~~~~~~~~~~~~~~~~

.. code:: shell

    pip install 'readcon==0.13.1'

Python — CON I/O plus format conversion
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code:: shell

    pip install 'readcon-chemfiles==0.13.1'
    # do not also install lean readcon in the same venv

The package name still contains ``chemfiles`` (the library used under the hood
for multi-format read). You do not need to learn that library to convert
files—use the ``read_chemfiles_*`` helpers on ``readcon`` as in the next section.

Rust — CON I/O plus format conversion
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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

Convert XYZ (or PDB / GRO) into CON
-----------------------------------

Needs the ****with conversions**** install.

.. code:: python

    import readcon
    assert readcon.has_chemfiles_support()  # False on the CON-only wheel
    frame = readcon.read_chemfiles_first("water.xyz")
    frame.write_con("water.con")

Full walkthrough: `convert formats tutorial <chemfiles-tutorial.rst>`_. Runnable Org notebook:
`executable notebook <chemfiles-notebook.rst>`_ via:

.. code:: shell

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
   * - Run the executable conversion notebook
     - :doc:`chemfiles-notebook`
   * - Task recipes (batch convert, C API)
     - :doc:`chemfiles-howto`
   * - Why conversion is optional; bonds & indices
     - :doc:`chemfiles-explain`
   * - API tables
     - :doc:`chemfiles-reference`, :doc:`bindings`
   * - On-disk format
     - :doc:`spec`
   * - Release / contribute
     - :doc:`contributing`
