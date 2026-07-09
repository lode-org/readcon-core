
.. raw:: html

   <div class="rc-hero">
     <div class="rc-hero-brand">
       <img class="rc-hero-mark" src="_static/mark.svg" width="56" height="56" alt="" />
       <div>
         <p class="rc-hero-name">readcon</p>
         <p class="rc-hero-sub">core · CON I/O</p>
       </div>
     </div>
     <p class="rc-hero-tagline">Put CON everywhere: multi-language checkpoints with constraints, forces, and atom identity.</p>
     <div class="rc-hero-pills">
       <span>Spec v2–v3</span>
       <span>Hourglass ABI</span>
       <span>chemfiles → CON</span>
       <span>readcon-db</span>
       <span>ASV + Cachegrind</span>
     </div>
     <p class="rc-hero-flow">foreign file → ConFrame → .con · campaigns · optimizers</p>
   </div>

================
``readcon-core``
================

Versioned ``.con`` / ``.convel`` with a shared hourglass API (Fortran, C, C++,
Python, Julia, Rust). Chemfiles lands foreign structures as CON; DLPack /
metatensor hand off to ML; `readcon-db
<https://lode-org.github.io/readcon-db/>`_ stores campaign corpora as CON text
(`docs.rs <https://docs.rs/readcon-db>`_).

:doc:`getting-started` · :doc:`tutorial` · :doc:`migrate` · :doc:`spec` ·
:doc:`faq` · :doc:`benchmarks`

.. code-block:: shell

   pip install 'readcon==0.14.0'          # Python CON I/O
   # pip install 'readcon-chemfiles==0.14.0'  # + foreign → CON
   cargo add readcon-core                 # Rust
   # cargo add readcon-db / pip install readcon-db  # campaigns

Full matrix (Julia, C/Fortran, packages): :doc:`getting-started`.

.. important::

   *New here?* → :doc:`getting-started` then :doc:`tutorial`

   *Migrate a stack onto CON?* → :doc:`migrate`

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
   Rust API (docs.rs) <https://docs.rs/readcon-core>

.. toctree::
   :maxdepth: 1
   :caption: Project meta

   contributing
   changelog
   issue-status
