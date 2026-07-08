
.. raw:: html

   <div class="rc-hero">
     <img class="light-only rc-hero-logo" src="_static/logo-light.svg" width="400" height="102" alt="readcon-core" />
     <img class="dark-only rc-hero-logo" src="_static/logo-dark.svg" width="400" height="102" alt="readcon-core" />
     <p class="rc-hero-tagline">Versioned CON / convel for eOn and LODE: multi-language hourglass ABI, full section fidelity, optional chemfiles ingress.</p>
   </div>

================
``readcon-core``
================

Reads and writes versioned ``.con`` / ``.convel`` for eOn / LODE so optimizers
and drivers in Rust, C, C++, Python, Julia, and Fortran share one semantics
surface. Spec-v2 JSON metadata, three-axis constraints, forces / velocities,
and ``atom_id`` round-trip. Chemfiles maps XYZ / PDB / GRO into CON.
Campaign corpora use companion ``readcon-db`` with UTF-8 CON text as authority.

Parse path: CI Cachegrind I-refs and equal-geometry multi-frame comparisons
(ASE CON, C sscanf peers). See :doc:`benchmarks`, :doc:`architecture`,
:doc:`faq`.

.. important::

   *New here?* → :doc:`getting-started`

   *Bring XYZ/PDB/GRO into CON?* → :doc:`chemfiles-tutorial`
   · run the Org notebook :doc:`chemfiles-notebook`
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
