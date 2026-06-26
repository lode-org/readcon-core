
.. raw:: html

   <div class="rc-hero">
     <img class="light-only rc-hero-logo" src="_static/logo-light.svg" width="400" height="102" alt="readcon-core" />
     <img class="dark-only rc-hero-logo" src="_static/logo-dark.svg" width="400" height="102" alt="readcon-core" />
     <p class="rc-hero-tagline">CON and convel I/O for LODE and eOn — fast, typed metadata, multi-language bindings, optional chemfiles ingress.</p>
   </div>

================
``readcon-core``
================

Rust library for **reading and writing** ``.con`` / ``.convel`` simulation
frames (eOn, LODE). Lazy iterators, spec-v2 JSON metadata, C/C++/Python/Julia
bindings. From v0.13, convert **XYZ, PDB, GRO,** and other chemfiles formats
into CON without inventing another reader for each format.

.. important::

   **New here?** → :doc:`getting-started`

   **Bring XYZ/PDB/GRO into CON?** → :doc:`chemfiles-tutorial`
   · run the Org notebook :doc:`chemfiles-notebook`
   (``scripts/run-chemfiles-notebook.sh``)

   **Format rules?** → :doc:`spec` · **APIs?** → :doc:`bindings` ·
   :doc:`chemfiles-reference`


.. figure:: /_static/figures/ecosystem-full.png
   :alt: readcon-core linked to eOn, rgpot, LODE, chemparseplot, rgpycrumbs, pychum
   :align: center
   :width: 92%

   **Ecosystem** — CON I/O at the center; consumers (eOn, rgpot, LODE) and the
   viz/input layer (chemparseplot, rgpycrumbs, pychum).

.. grid:: 1 1 2 2
   :gutter: 2

   .. grid-item-card:: WBO-style structures
      :link: getting-started
      :link-type: doc

      Ball–stick CON frames with bond scalars (chemparseplot / rgpycrumbs look).

   .. grid-item-card:: Chemfiles ingress
      :link: chemfiles-tutorial
      :link-type: doc

      XYZ, PDB, GRO → ``ConFrame`` → ``.con`` without a bespoke reader per format.

   .. grid-item-card:: 2D landscapes
      :link: chemfiles-explain
      :link-type: doc

      Reaction-valley figures are the viz layer — link out to chemparseplot.

   .. grid-item-card:: Spec & bindings
      :link: spec
      :link-type: doc

      On-disk CON/convel rules, C/Python/Julia/Rust APIs.

Site map
--------

.. toctree::
   :maxdepth: 1
   :caption: Start

   getting-started
   tutorials
   faq

.. toctree::
   :maxdepth: 1
   :caption: Chemfiles ingress

   chemfiles-tutorial
   chemfiles-notebook
   chemfiles-howto
   chemfiles-explain
   chemfiles-reference

.. toctree::
   :maxdepth: 1
   :caption: Format & design

   spec
   evolution
   architecture
   benchmarks

.. toctree::
   :maxdepth: 1
   :caption: Bindings & API

   bindings
   rpc
   crates/readcon_core/lib

.. toctree::
   :maxdepth: 1
   :caption: Project

   contributing
   changelog
