
.. image:: /_static/logo-light.svg
   :class: light-only
   :width: 420
   :align: center
   :alt: readcon-core

.. image:: /_static/logo-dark.svg
   :class: dark-only
   :width: 420
   :align: center
   :alt: readcon-core

================
``readcon-core``
================

readcon-core is a Rust library for reading and writing CON and convel
simulation configuration files, with FFI bindings for C/C++, Python,
and Julia. From v0.13 you can ****convert foreign trajectories**** (XYZ, PDB,
GRO, … via chemfiles) into CON.

****Chemfiles (Diátaxis + executable Org):**** start at
`chemfiles-tutorial <chemfiles-tutorial.rst>`_, run
`chemfiles-notebook <chemfiles-notebook.rst>`_ with
``scripts/run-chemfiles-notebook.sh`` (Org Babel — not a committed ``.ipynb``).

Contents
--------

.. toctree::
   :maxdepth: 2
   :caption: Contents

   spec
   evolution
   faq
   benchmarks
   tutorials
   chemfiles-tutorial
   chemfiles-notebook
   chemfiles-howto
   chemfiles-explain
   chemfiles-reference
   architecture
   bindings
   crates/readcon_core/lib
   rpc
   contributing
   changelog
