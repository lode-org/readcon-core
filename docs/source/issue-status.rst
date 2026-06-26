============================================
Tracker issue status (lode-org/readcon-core)
============================================


Maps historical GitHub issues to current tree. Prefer closing via PR ``Closes #N``.

.. table::

    +-------+--------------------------------------+--------+-------------------------------------------------------------------------+
    | Issue | Title                                | Status | Evidence                                                                |
    +=======+======================================+========+=========================================================================+
    | #4    | DOC: User facing details             | Done   | Sphinx + Shibuya site, Org→RST Diátaxis                                 |
    +-------+--------------------------------------+--------+-------------------------------------------------------------------------+
    | #5    | ENH: Python bindings                 | Done   | ``python`` feature, maturin wheels, ``readcon`` / ``readcon-chemfiles`` |
    +-------+--------------------------------------+--------+-------------------------------------------------------------------------+
    | #6    | ENH: Fortran bindings                | Done   | ``fortran/ReadCon/src/readcon.f90`` ISO\ :sub:`C`\ \ :sub:`BINDING`\    |
    +-------+--------------------------------------+--------+-------------------------------------------------------------------------+
    | #7    | DOC: cmake integration               | Done   | Root ``CMakeLists.txt`` (Corrosion) + bindings CMake subsection         |
    +-------+--------------------------------------+--------+-------------------------------------------------------------------------+
    | #8    | REL: Explain release process         | Done   | ``docs/orgmode/contributing.org`` release + cog/cargo-dist/PyPI         |
    +-------+--------------------------------------+--------+-------------------------------------------------------------------------+
    | #10   | ENH: Support convel                  | Done   | ``.convel`` iterators/writers, tests, docs                              |
    +-------+--------------------------------------+--------+-------------------------------------------------------------------------+
    | #11   | TST: Coverage and metrics            | Done   | ``.github/workflows/coverage.yml``                                      |
    +-------+--------------------------------------+--------+-------------------------------------------------------------------------+
    | #12   | EXT: Integrate with chemfiles        | Done   | ``--features chemfiles``, ingress APIs, Cachegrind scenarios            |
    +-------+--------------------------------------+--------+-------------------------------------------------------------------------+
    | #19   | ENH: 3-component fixed\ :sub:`flag`\ | Done   | ``AtomData.fixed: [bool; 3]``, C ``fixed_x/y/z``, bitmask 0–7           |
    +-------+--------------------------------------+--------+-------------------------------------------------------------------------+

Chemfiles conversion and Cachegrind I-refs are on the benchmarks page include.
