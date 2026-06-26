
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
simulation configuration files, with FFI bindings for C/C++, Python, and Julia.
From v0.13 you can convert foreign trajectories (XYZ, PDB, GRO, … via chemfiles)
into CON.

Contents
--------

.. toctree::
   :maxdepth: 2
   :caption: Guide

   tutorials
   chemfiles-tutorial
   chemfiles-notebook
   chemfiles-howto
   chemfiles-explain
   chemfiles-reference
   faq
   contributing

.. toctree::
   :maxdepth: 2
   :caption: Specification

   spec
   evolution
   architecture
   bindings
   rpc
   benchmarks

.. toctree::
   :maxdepth: 2
   :caption: API & project

   crates/readcon_core/lib
   changelog
