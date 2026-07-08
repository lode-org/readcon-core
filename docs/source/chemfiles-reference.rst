==============================================
Reference — Chemfiles conversion and selection
==============================================


.. note::

   Diátaxis *reference*. Learning path: :doc:`chemfiles-tutorial`.
   Executable Org: :doc:`chemfiles-notebook` (``scripts/run-chemfiles-notebook.sh``).

`tutorial <chemfiles-tutorial.rst>`_; for tasks see `how-to <chemfiles-howto.rst>`_; for rationale see
`explanation <chemfiles-explain.rst>`_. Binding-wide matrices live in `bindings <bindings.rst>`_; on-disk ``bonds``
key in `spec <spec.rst>`_.

Feature and install matrix
--------------------------

.. table::

    +---------------+-------------------------------------------------+-----------------------+-------------------------------------------------------+
    | Build         | Cargo                                           | PyPI                  | ``chemfiles_enabled()`` / ``has_chemfiles_support()`` |
    +===============+=================================================+=======================+=======================================================+
    | Lean          | default features                                | ``readcon``           | false (stubs)                                         |
    +---------------+-------------------------------------------------+-----------------------+-------------------------------------------------------+
    | Full          | ``--features chemfiles``                        | ``readcon-chemfiles`` | true                                                  |
    +---------------+-------------------------------------------------+-----------------------+-------------------------------------------------------+
    | Full editable | ``maturin develop --features python,chemfiles`` | n/a                   | true                                                  |
    +---------------+-------------------------------------------------+-----------------------+-------------------------------------------------------+

Optional extra on lean package: ``readcon[chemfiles]`` → depends on
``readcon-chemfiles==X.Y.Z`` (same version; avoid installing both modules).

Rust modules
------------

.. table::

    +---------------------------------------+-----------------------------------+
    | Module                                | Role                              |
    +=======================================+===================================+
    | ``readcon_core::chemfiles_import``    | Foreign format → ``ConFrame``     |
    +---------------------------------------+-----------------------------------+
    | ``readcon_core::chemfiles_selection`` | Selection grammar on ``ConFrame`` |
    +---------------------------------------+-----------------------------------+

**Import (full feature)**

.. table::

    +-------------------------------------------+-------------------------------------+
    | Function                                  | Purpose                             |
    +===========================================+=====================================+
    | ``con_frame_from_chemfiles(&Frame)``      | Single chemfiles frame              |
    +-------------------------------------------+-------------------------------------+
    | ``con_frame_from_trajectory_path(path)``  | First step of a file                |
    +-------------------------------------------+-------------------------------------+
    | ``con_frames_from_trajectory_path(path)`` | All steps                           |
    +-------------------------------------------+-------------------------------------+
    | ``con_frames_from_memory(data, format)``  | Buffer + format name (``"XYZ"``, …) |
    +-------------------------------------------+-------------------------------------+
    | ``bonds_from_chemfiles_frame``            | Topology → ``Vec<Bond>``            |
    +-------------------------------------------+-------------------------------------+
    | ``chemfiles_enabled()``                   | ``const fn`` probe                  |
    +-------------------------------------------+-------------------------------------+

**Import (stubs without feature):** path/memory helpers return
``ChemfilesImportError::FeatureDisabled``. ``con_frame_from_chemfiles`` is only
available with the feature (needs ``chemfiles::Frame`` in the signature).

**Selection (always available; stubs error without feature)**

.. table::

    +-------------------------------------------------+--------------------------------------+
    | Item                                            | Purpose                              |
    +=================================================+======================================+
    | ``SelectionMatch`` / ``SelectionResult``        | Match payload                        |
    +-------------------------------------------------+--------------------------------------+
    | ``evaluate_selection_on_con_frame(sel, frame)`` | Full result                          |
    +-------------------------------------------------+--------------------------------------+
    | ``select_atom_indices(sel, frame)``             | Atom context → sorted unique indices |
    +-------------------------------------------------+--------------------------------------+
    | ``parse_selection_string(sel)``                 | Context size only                    |
    +-------------------------------------------------+--------------------------------------+

Constants: ``CHEMFILES_EXTRA_PREFIX``, ``CHEMFILES_ATOM_PROPS_KEY``,
``CHEMFILES_ATOM_NAMES_KEY``, ``CHEMFILES_ATOM_TYPES_KEY``.

Error: ``ChemfilesImportError`` (``Chemfiles`` / ``InvalidFrame`` / ``Io`` /
``FeatureDisabled``; ``Chemfiles`` variant only in full builds).

Python (``import readcon``)
---------------------------

.. table::

    +-------------------------------------------------------------------+------------------+--------------------------------+
    | API                                                               | Lean wheel       | ``readcon-chemfiles``          |
    +===================================================================+==================+================================+
    | ``has_chemfiles_support()``                                       | ``False``        | ``True``                       |
    +-------------------------------------------------------------------+------------------+--------------------------------+
    | ``read_chemfiles(path)``                                          | ``RuntimeError`` | ``list[ConFrame]`` (all steps) |
    +-------------------------------------------------------------------+------------------+--------------------------------+
    | ``read_chemfiles_first(path)``                                    | ``RuntimeError`` | ``ConFrame``                   |
    +-------------------------------------------------------------------+------------------+--------------------------------+
    | ``read_chemfiles_memory(data, format)``                           | ``RuntimeError`` | ``list[ConFrame]``             |
    +-------------------------------------------------------------------+------------------+--------------------------------+
    | ``select_on_frame(frame, sel)`` / ``frame.select(sel)``           | error            | dict                           |
    +-------------------------------------------------------------------+------------------+--------------------------------+
    | ``select_atom_indices(frame, sel)`` / ``frame.select_atoms(sel)`` | error            | ``list[int]``                  |
    +-------------------------------------------------------------------+------------------+--------------------------------+
    | ``frame.write_con(path)``                                         | yes              | yes                            |
    +-------------------------------------------------------------------+------------------+--------------------------------+
    | ``PyConFrame.bonds`` / ``has_bonds``                              | yes              | yes                            |
    +-------------------------------------------------------------------+------------------+--------------------------------+

``select`` / ``select_on_frame`` dict keys: ``selection``, ``context_size``, ``matches``
(``list[list[int]]``), ``primary_indices``. ``format`` for memory import is a
chemfiles name (``"XYZ"``, ``"PDB"``, ``"GRO"``, …).

C / C++
-------

.. table::

    +-------------------------------------------------------------------------------------------------------------+-----------------------------------------------------------------------+
    | Symbol                                                                                                      | Notes                                                                 |
    +=============================================================================================================+=======================================================================+
    | ``rkr_has_chemfiles_support``                                                                               | 0 or 1                                                                |
    +-------------------------------------------------------------------------------------------------------------+-----------------------------------------------------------------------+
    | ``rkr_frame_select``                                                                                        | Fills ``RKRSelectionResult*``; stubs → ``RKR_STATUS_SELECTION_ERROR`` |
    +-------------------------------------------------------------------------------------------------------------+-----------------------------------------------------------------------+
    | ``rkr_selection_result_match_count`` / ``_context_size`` / ``_match_at`` / ``_primary_indices`` / ``_free`` | Always declared                                                       |
    +-------------------------------------------------------------------------------------------------------------+-----------------------------------------------------------------------+
    | ``readcon::ConFrame::select``                                                                               | C++ RAII; throws if support is 0                                      |
    +-------------------------------------------------------------------------------------------------------------+-----------------------------------------------------------------------+
    | ``readcon::has_chemfiles_support``                                                                          | C++                                                                   |
    +-------------------------------------------------------------------------------------------------------------+-----------------------------------------------------------------------+

CON metadata keys (topology / sidecars)
---------------------------------------

.. table::

    +-------------------------------+-----------------------------------------------------------------------+
    | Key                           | Meaning                                                               |
    +===============================+=======================================================================+
    | ``bonds``                     | Array of ``[i,j]`` or ``{i,j,order?}``; 0-based ``atom_data`` indices |
    +-------------------------------+-----------------------------------------------------------------------+
    | ``chemfiles_atom_names``      | Display names, chemfiles/=atom\_id= order                             |
    +-------------------------------+-----------------------------------------------------------------------+
    | ``chemfiles_atom_types``      | Atomic types, parallel to names                                       |
    +-------------------------------+-----------------------------------------------------------------------+
    | ``chemfiles_atom_properties`` | Per-atom property bags                                                |
    +-------------------------------+-----------------------------------------------------------------------+
    | ``chemfiles::…``              | Unmapped frame properties                                             |
    +-------------------------------+-----------------------------------------------------------------------+

See `spec <spec.rst>`_ § frame topology for normative wording.

Selection grammar (implemented on CON frames)
---------------------------------------------

.. table::

    +------------------------------------------------+--------------------------+--------------+
    | Pattern                                        | Needs ``bonds``?         | Context size |
    +================================================+==========================+==============+
    | ``name X`` / ``type Y`` / ``all`` / ``none``   | no                       |            1 |
    +------------------------------------------------+--------------------------+--------------+
    | ``bonds: …`` / ``pairs: …`` / ``two: …``       | yes for topology filters |            2 |
    +------------------------------------------------+--------------------------+--------------+
    | ``angles: …`` / ``three: …``                   | yes (derived)            |            3 |
    +------------------------------------------------+--------------------------+--------------+
    | ``dihedrals: …`` / ``four: …``                 | yes (derived)            |            4 |
    +------------------------------------------------+--------------------------+--------------+
    | ``is_bonded`` / ``is_angle`` / ``is_dihedral`` | yes                      |    2 / 3 / 4 |
    +------------------------------------------------+--------------------------+--------------+

These patterns are what CON selection implements (tests under
``chemfiles_selection_cpp_regression`` for topology cases). Format limits
(``resname``, properties, impropers, geometry thresholds) are CON limits—see
``chemfiles-explain.org`` (**What selection cannot see on CON**). The optional
conversion stack may reuse a third-party grammar engine; that is an
implementation detail, not a second public API surface.

CI / release artifacts
----------------------

.. table::

    +--------------------------------------------+---------------------------------------------------------------+
    | Workflow                                   | Produces                                                      |
    +============================================+===============================================================+
    | ``python_wheels.yml`` matrix ``default``   | PyPI ``readcon``                                              |
    +--------------------------------------------+---------------------------------------------------------------+
    | ``python_wheels.yml`` matrix ``chemfiles`` | PyPI ``readcon-chemfiles`` (no Windows chemfiles row)         |
    +--------------------------------------------+---------------------------------------------------------------+
    | ``crates_publish.yml``                     | crates.io ``readcon-core`` (chemfiles still optional feature) |
    +--------------------------------------------+---------------------------------------------------------------+

Pending/active trusted publishers must use **exact** PyPI names ``readcon`` and
``readcon-chemfiles``.
