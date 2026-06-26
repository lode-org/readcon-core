
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
