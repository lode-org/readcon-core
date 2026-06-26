===============
Getting started
===============


.. contents::

.. figure:: /_static/figures/ingress-with-structure.png
   :alt: XYZ/PDB/GRO through chemfiles into ConFrame and .con for eOn/LODE
   :align: center
   :width: 100%

   **Ingress with structure** — foreign formats → chemfiles → ``ConFrame``
   (bonds optional) → ``.con`` for eOn / LODE. Same geometry chemparseplot and
   rgpycrumbs render with WBO-style bonds and xyzrender strips.

.. figure:: /_static/figures/lean-vs-full.svg
   :alt: Lean default build versus chemfiles-linked full ingress build
   :align: center
   :width: 100%

   **Lean vs full** — same Python/Rust API surface; only full builds link
   libchemfiles (``readcon-chemfiles`` / ``--features chemfiles``).

.. tip::

   This is the **front door**. Use the **right sidebar** for the on-page TOC,
   repo stats, and **Edit this page**. Top nav has Chemfiles + Ecosystem
   (eOn, rgpot, chemparseplot, rgpycrumbs, pychum).

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

.. figure:: /_static/figures/structures-wbo-style.png
   :alt: sulfolene and CuH2 CON frames as ball-stick with WBO-colored bonds
   :align: center
   :width: 100%

   **Sample frames** from ``resources/test/`` — ball–stick with pseudo-WBO bond
   coloring (chemparseplot / rgpycrumbs aesthetic). Real WBO from QM goes through
   those tools; here geometry alone drives the scalar for docs.

Convert a foreign format into CON
---------------------------------

.. code:: python

    import readcon
    assert readcon.has_chemfiles_support()  # need readcon-chemfiles
    frame = readcon.read_chemfiles_first("water.xyz")
    frame.write_con("water.con")

See the full walkthrough in :doc:`chemfiles-tutorial`. Run the literate Org
notebook (:doc:`chemfiles-notebook`) with:

.. code:: shell

    scripts/run-chemfiles-notebook.sh

Downstream visualization
------------------------

CON is the **exchange format**. Publication figures (NEB profiles, structure
strips, Wiberg bond-order views, 2D reaction valleys) live in the sibling tools:

- `chemparseplot <https://chemparseplot.rgoswami.me>`_ — NEB / optimization landscapes, structure strips (\`\`xyzrender\`\` / ASE / solvis backends)

- `rgpycrumbs <https://rgpycrumbs.rgoswami.me>`_ — CLI wrappers (\`\`plt\ :sub:`neb`\\`\`, \`\`plt\ :sub:`min`\\`\`, \`\`plt\ :sub:`saddle`\\`\`), fragment WBO viz

- `pychum <https://github.com/HaoZeke/pychum>`_ — ORCA / NWChem inputs when you need fresh energies on a CON geometry

.. figure:: /_static/figures/profile-structure-strip.png
   :alt: Energy profile with structure strip thumbnails
   :align: center
   :width: 100%

   **Profile + structure strip** layout used by chemparseplot NEB plots and
   rgpycrumbs ``plt_neb`` (docs figure uses test ``sulfolene.con`` as a stand-in).

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
