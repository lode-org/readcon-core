
.. raw:: html

   <div class="rc-hero">
     <div class="rc-hero-rule" aria-hidden="true"></div>
     <div class="rc-hero-brand">
       <img class="rc-hero-mark" src="_static/mark.svg" width="56" height="56" alt="" />
       <div>
         <p class="rc-hero-name"><span class="rc-hero-read">read</span><span class="rc-hero-con">con</span></p>
         <p class="rc-hero-sub">core / CON I/O</p>
       </div>
     </div>
     <p class="rc-hero-tagline">Reference reader and writer for versioned CON checkpoints: cell, per-direction constraints, atom identity, optional forces.</p>
     <pre class="rc-hero-conline" aria-hidden="true">{"con_spec_version":2}&#10;15.345600  21.702000  100.000000</pre>
   </div>

================
``readcon-core``
================

Rare-event codes already checkpoint on CON. This library is the formal
spec and the shared ``rkr_*`` ABI so Fortran, C, C++, Python, Julia, and
Rust read and write the same file everywhere. Optional chemfiles conversion brings
XYZ, PDB, and GRO in; DLPack and metatensor export the same arrays out.
`readcon-db <https://lode-org.github.io/readcon-db/docs/>`_ indexes
CON corpora.

:doc:`getting-started` · :doc:`tutorial` · :doc:`migrate` · :doc:`spec` ·
:doc:`faq` · :doc:`benchmarks`

.. code-block:: shell

   pip install 'readcon==0.14.9'          # Python CON I/O
   # pip install 'readcon-chemfiles==0.14.9'  # + foreign -> CON
   cargo add readcon-core@0.14.9          # Rust
   # cargo add readcon-db / pip install readcon-db

Full matrix (Julia, C/Fortran, packages): :doc:`getting-started`.

.. important::

   *New here?* :doc:`getting-started` then :doc:`tutorial`

   *Migrate a stack onto CON?* :doc:`migrate`

   *Import into CON?* :doc:`chemfiles-tutorial`
   · Org notebook :doc:`chemfiles-notebook`

   *Format rules?* :doc:`spec` · *APIs?* :doc:`bindings`

.. figure:: /_static/figures/conversion-pipeline.svg
   :alt: Convert XYZ, PDB, or GRO into a CON frame
   :align: center
   :width: 92%

   Conversion path: XYZ, PDB, or GRO into a CON frame.

.. grid:: 1 1 2 2
   :gutter: 2

   .. grid-item-card:: Tutorial: first CON checkpoint
      :link: tutorial
      :link-type: doc

      Read a fixture, inspect the cell, write a frame (Python).

   .. grid-item-card:: How-to by language
      :link: howto
      :link-type: doc

      Task recipes for Rust, Python, C, C++, Julia, Fortran.

   .. grid-item-card:: Convert formats
      :link: chemfiles-tutorial
      :link-type: doc

      XYZ, PDB, GRO to CON without writing a reader per format.

   .. grid-item-card:: Spec and bindings
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
   migrate
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

.. toctree::
   :maxdepth: 1
   :caption: Project meta

   contributing
   changelog
   issue-status
