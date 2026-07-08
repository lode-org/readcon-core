
.. raw:: html

   <div class="rc-hero">
     <img class="light-only rc-hero-logo" src="_static/logo-light.svg" width="400" height="102" alt="readcon-core" />
     <img class="dark-only rc-hero-logo" src="_static/logo-dark.svg" width="400" height="102" alt="readcon-core" />
     <p class="rc-hero-tagline">Put CON everywhere: multi-language checkpoints with constraints, forces, and atom identity.</p>
   </div>

================
``readcon-core``
================

Reference implementation of versioned ``.con`` / ``.convel``. Spec v2–v3 frames
(cell, type-grouped coordinates, per-direction constraints, ``atom_id``,
optional sections such as velocities, forces, energies, charges, spins, and
magmoms, plus JSON metadata). Hourglass ABI so Fortran, C, C++, Python, Julia,
and Rust share one file; chemfiles to land foreign structures in CON; DLPack /
metatensor for ML and device hand-off; ``readcon-db`` for campaigns that still
store CON text.

Spec: :doc:`spec`. FAQ: :doc:`faq`. Numbers: :doc:`benchmarks`. Start:
:doc:`getting-started`.

.. important::

   *New here?* → :doc:`getting-started` then :doc:`tutorial`

   *Import into CON?* → :doc:`chemfiles-tutorial`
   · Org notebook :doc:`chemfiles-notebook`

   *Format rules?* → :doc:`spec` · *APIs?* → :doc:`bindings`

.. figure:: /_static/figures/conversion-pipeline.svg
   :alt: Convert XYZ PDB or GRO into a CON frame
   :align: center
   :width: 92%

   *Conversion path* — common structure formats into CON.

.. grid:: 1 1 2 2
   :gutter: 2

   .. grid-item-card:: Tutorial — first CON checkpoint
      :link: tutorial
      :link-type: doc

      One Good Tutorial: read, inspect, write, build a frame (Python).

   .. grid-item-card:: How-to by language
      :link: howto
      :link-type: doc

      Task recipes for Rust, Python, C, C++, Julia, Fortran.

   .. grid-item-card:: Convert formats
      :link: chemfiles-tutorial
      :link-type: doc

      XYZ, PDB, GRO → CON without writing a reader per format.

   .. grid-item-card:: Spec & bindings
      :link: spec
      :link-type: doc

      On-disk CON/convel rules and multi-language APIs.

Site map
--------

.. toctree::
   :maxdepth: 1
   :caption: Tutorials

   getting-started
   tutorial
   chemfiles-tutorial
   chemfiles-notebook

.. toctree::
   :maxdepth: 1
   :caption: How-to guides

   howto
   chemfiles-howto

.. toctree::
   :maxdepth: 1
   :caption: Explanation

   faq
   evolution
   architecture
   benchmarks
   chemfiles-explain

.. toctree::
   :maxdepth: 1
   :caption: Reference

   spec
   bindings
   chemfiles-reference
   rpc
   Rust API (docs.rs) <https://docs.rs/readcon-core>

.. toctree::
   :maxdepth: 1
   :caption: Project meta

   contributing
   changelog
   issue-status
