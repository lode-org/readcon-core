
.. raw:: html

   <div class="rc-hero">
     <img class="light-only rc-hero-logo" src="_static/logo-light.svg" width="400" height="102" alt="readcon-core" />
     <img class="dark-only rc-hero-logo" src="_static/logo-dark.svg" width="400" height="102" alt="readcon-core" />
     <p class="rc-hero-tagline">CON / convel: full checkpoints for eOn and LODE. Constraints, forces, atom identity, multi-language ABI.</p>
   </div>

================
``readcon-core``
================

Reference library for ``.con`` / ``.convel``: versioned frames with cell,
type-grouped coordinates, per-direction constraints, ``atom_id``, optional
velocities and forces, and JSON metadata. Lazy iterators; C / C++ / Python /
Julia / Fortran via one hourglass ABI. Optional chemfiles import lands foreign
structures in CON without weakening the on-disk contract.

Spec: :doc:`spec`. Measurements: :doc:`benchmarks`. Start: :doc:`getting-started`.

.. important::

   *New here?* → :doc:`getting-started`

   *Import into CON?* → :doc:`chemfiles-tutorial`
   · Org notebook :doc:`chemfiles-notebook`
   (``scripts/run-chemfiles-notebook.sh``)

   *Format rules?* → :doc:`spec` · *APIs?* → :doc:`bindings` ·
   :doc:`chemfiles-reference`

.. figure:: /_static/figures/conversion-pipeline.svg
   :alt: Convert XYZ PDB or GRO into CON for eOn and LODE
   :align: center
   :width: 92%

   *Conversion path* — common structure formats into CON for eOn / LODE.

.. grid:: 1 1 2 2
   :gutter: 2

   .. grid-item-card:: Get started
      :link: getting-started
      :link-type: doc

      Install, read a CON file, convert XYZ/PDB/GRO when you need it.

   .. grid-item-card:: Convert formats
      :link: chemfiles-tutorial
      :link-type: doc

      XYZ, PDB, GRO → CON without writing a reader per format.

   .. grid-item-card:: Why conversion is optional
      :link: chemfiles-explain
      :link-type: doc

      Background on optional conversion, bonds, and atom indices.

   .. grid-item-card:: Spec & bindings
      :link: spec
      :link-type: doc

      On-disk CON/convel rules, C/Python/Julia/Rust APIs.

Site map
--------

.. toctree::
   :maxdepth: 1
   :caption: Tutorials & start

   getting-started
   tutorials
   faq

.. toctree::
   :maxdepth: 1
   :caption: Convert other formats

   chemfiles-tutorial
   chemfiles-notebook
   chemfiles-howto
   chemfiles-explain
   chemfiles-reference

.. toctree::
   :maxdepth: 1
   :caption: Explanation & design

   spec
   evolution
   architecture
   benchmarks

.. toctree::
   :maxdepth: 1
   :caption: Reference (API)

   bindings
   rpc
   Rust API (docs.rs) <https://docs.rs/readcon-core>

.. toctree::
   :maxdepth: 1
   :caption: Project meta

   contributing
   changelog
   issue-status
