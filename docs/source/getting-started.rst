===============
Getting started
===============


.. figure:: /_static/figures/conversion-pipeline.svg
   :alt: XYZ, PDB, or GRO converted into a CON frame
   :align: center
   :width: 100%

   *Format conversion* — common structure files become a CON frame for any
   language binding. Needs the *with conversions* install below.

.. figure:: /_static/figures/lean-vs-conversion.svg
   :alt: Default CON-only install versus install that also converts other formats
   :align: center
   :width: 100%

   *Two installs* — default package is CON I/O only; the conversion package
   adds XYZ / PDB / GRO (and similar) → CON. Same CON APIs either way.

.. tip::

   Start here for install and the shortest paths. Top nav *Convert* is the
   conversion tutorial and recipes.

Scope
-----

readcon-core implements CON / convel: cell, type-grouped atoms, per-direction
fixed masks, ``atom_id``, velocity / force sections, JSON line-2 metadata. One
``rkr_*`` hourglass ABI for Fortran, C, C++, Python, Julia, and Rust. That stack
is the point: many languages and tools, one on-disk contract.

.. table::

    +---------------------------------+-----------------------------------------+
    | Task                            | Path                                    |
    +=================================+=========================================+
    | Read / write CON                | ``readcon`` / ``readcon-core``          |
    +---------------------------------+-----------------------------------------+
    | Link from Fortran / C / C++     | Hourglass ABI; lean features by default |
    +---------------------------------+-----------------------------------------+
    | Many trajectories, multi-reader | ``readcon-db`` (CON text authoritative) |
    +---------------------------------+-----------------------------------------+
    | Foreign structure file → CON    | Optional chemfiles build                |
    +---------------------------------+-----------------------------------------+
    | ASE calculator                  | Optional ``to_ase`` / ``from_ase``      |
    +---------------------------------+-----------------------------------------+

Why CON looks this way: :doc:`faq`, :doc:`evolution`.
Rules: :doc:`spec`. Layout of the library:
:doc:`architecture`. Numbers:
:doc:`benchmarks`.

Install
-------

.. tab-set::

   .. tab-item:: Rust

      .. code-block:: shell

         cargo add readcon-core

   .. tab-item:: Python

      .. code-block:: shell

         pip install 'readcon==0.13.1'
         # conversions: pip install 'readcon-chemfiles==0.13.1'

   .. tab-item:: Fortran

      .. code-block:: shell

         cargo build --release
         cd fortran/ReadCon && fpm test --flag "-L../../target/release" \
           --link-flag "-L../../target/release -lreadcon_core -ldl -lpthread -lm"

   .. tab-item:: C / C++

      .. code-block:: shell

         # Meson or CMake (Corrosion) — see bindings page
         # Header: include/readcon-core.h

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

The PyPI name ``readcon-chemfiles`` is historical (multi-format read is linked
in that wheel). You do not need a separate chemfiles tutorial to convert a
file—call the helpers on ``readcon`` as below.

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

Needs the **with conversions** install.

.. code:: python

    import readcon
    assert readcon.has_chemfiles_support()  # False on the CON-only wheel
    frame = readcon.read_chemfiles_first("water.xyz")
    frame.write_con("water.con")

Full walkthrough: :doc:`chemfiles-tutorial`. Executable notebook:
:doc:`chemfiles-notebook` via ``scripts/run-chemfiles-notebook.sh``.

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
