=============
``mod types``
=============


.. rust:module:: readcon_core::types
   :index: 0
   :vis: pub


   .. rust:use:: readcon_core::types
      :used_name: self


   .. rust:use:: readcon_core
      :used_name: crate


   .. rust:use:: std::collections::BTreeMap
      :used_name: BTreeMap


   .. rust:use:: std::sync::Arc
      :used_name: Arc


   .. rubric:: Functions


   .. rust:function:: readcon_core::types::decode_fixed_bitmask
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"decode_fixed_bitmask"},{"type":"punctuation","value":"("},{"type":"name","value":"val"},{"type":"punctuation","value":": "},{"type":"link","value":"u8","target":"u8"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"punctuation","value":"["},{"type":"link","value":"bool","target":"bool"},{"type":"punctuation","value":"; "},{"type":"literal","value":"3"},{"type":"punctuation","value":"]"}]

      Decode a column-4 bitmask value to per-direction fixed flags.
      
      - 0 = free
      - 1 = all-fixed (legacy, treated as [true, true, true])
      - 2-7 = bitmask (bit 0 = x, bit 1 = y, bit 2 = z)

   .. rust:function:: readcon_core::types::encode_fixed_bitmask
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"encode_fixed_bitmask"},{"type":"punctuation","value":"("},{"type":"name","value":"fixed"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"["},{"type":"link","value":"bool","target":"bool"},{"type":"punctuation","value":"; "},{"type":"literal","value":"3"},{"type":"punctuation","value":"]"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"u8","target":"u8"}]

      Encode per-direction fixed flags to a column-4 bitmask value.
      
      Always emits 7 for all-fixed (never legacy value 1).

   .. rubric:: Structs and Unions


   .. rust:struct:: readcon_core::types::AtomDatum
      :index: 1
      :vis: pub
      :toc: struct AtomDatum
      :layout: [{"type":"keyword","value":"struct"},{"type":"space"},{"type":"name","value":"AtomDatum"}]

      Represents the data for a single atom in a frame.

      .. rust:variable:: readcon_core::types::AtomDatum::symbol
         :index: 2
         :vis: pub
         :toc: symbol
         :layout: [{"type":"name","value":"symbol"},{"type":"punctuation","value":": "},{"type":"link","value":"Arc","target":"Arc"},{"type":"punctuation","value":"<"},{"type":"link","value":"str","target":"str"},{"type":"punctuation","value":">"}]

         The chemical symbol of the atom (e.g., "C", "H", "O").
         Using Arc<str> to avoid expensive clones for each atom of the same type.

      .. rust:variable:: readcon_core::types::AtomDatum::x
         :index: 2
         :vis: pub
         :toc: x
         :layout: [{"type":"name","value":"x"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"}]

         The Cartesian x-coordinate.

      .. rust:variable:: readcon_core::types::AtomDatum::y
         :index: 2
         :vis: pub
         :toc: y
         :layout: [{"type":"name","value":"y"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"}]

         The Cartesian y-coordinate.

      .. rust:variable:: readcon_core::types::AtomDatum::z
         :index: 2
         :vis: pub
         :toc: z
         :layout: [{"type":"name","value":"z"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"}]

         The Cartesian z-coordinate.

      .. rust:variable:: readcon_core::types::AtomDatum::fixed
         :index: 2
         :vis: pub
         :toc: fixed
         :layout: [{"type":"name","value":"fixed"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"["},{"type":"link","value":"bool","target":"bool"},{"type":"punctuation","value":"; "},{"type":"literal","value":"3"},{"type":"punctuation","value":"]"}]

         Per-direction constraint flags: [fixed_x, fixed_y, fixed_z].
         
         Encoded as a bitmask in column 4 of the file format:
         - 0 = free (all false)
         - 1 = all-fixed (legacy, treated as [true, true, true])
         - 2-6 = per-direction combinations (bit 0=y, bit 1=x+y, bit 2=z, ...)
         - 7 = all-fixed (canonical)

      .. rust:variable:: readcon_core::types::AtomDatum::atom_id
         :index: 2
         :vis: pub
         :toc: atom_id
         :layout: [{"type":"name","value":"atom_id"},{"type":"punctuation","value":": "},{"type":"link","value":"u64","target":"u64"}]

         The original atom index (column 5 in .con format).
         
         The .con format groups atoms by element type, which reorders them
         relative to their original input ordering. This field preserves the
         pre-grouping index so the original sequence can be reconstructed
         after any number of read/write cycles.
         
         When column 5 is absent from the input, defaults to the sequential
         position within the frame (0, 1, 2, ...).

      .. rust:variable:: readcon_core::types::AtomDatum::vx
         :index: 2
         :vis: pub
         :toc: vx
         :layout: [{"type":"name","value":"vx"},{"type":"punctuation","value":": "},{"type":"link","value":"Option","target":"Option"},{"type":"punctuation","value":"<"},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":">"}]

         The x-component of velocity (present only in ``.convel`` files).

      .. rust:variable:: readcon_core::types::AtomDatum::vy
         :index: 2
         :vis: pub
         :toc: vy
         :layout: [{"type":"name","value":"vy"},{"type":"punctuation","value":": "},{"type":"link","value":"Option","target":"Option"},{"type":"punctuation","value":"<"},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":">"}]

         The y-component of velocity (present only in ``.convel`` files).

      .. rust:variable:: readcon_core::types::AtomDatum::vz
         :index: 2
         :vis: pub
         :toc: vz
         :layout: [{"type":"name","value":"vz"},{"type":"punctuation","value":": "},{"type":"link","value":"Option","target":"Option"},{"type":"punctuation","value":"<"},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":">"}]

         The z-component of velocity (present only in ``.convel`` files).

      .. rust:variable:: readcon_core::types::AtomDatum::fx
         :index: 2
         :vis: pub
         :toc: fx
         :layout: [{"type":"name","value":"fx"},{"type":"punctuation","value":": "},{"type":"link","value":"Option","target":"Option"},{"type":"punctuation","value":"<"},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":">"}]

         The x-component of force (present when ``"forces"`` section declared).

      .. rust:variable:: readcon_core::types::AtomDatum::fy
         :index: 2
         :vis: pub
         :toc: fy
         :layout: [{"type":"name","value":"fy"},{"type":"punctuation","value":": "},{"type":"link","value":"Option","target":"Option"},{"type":"punctuation","value":"<"},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":">"}]

         The y-component of force (present when ``"forces"`` section declared).

      .. rust:variable:: readcon_core::types::AtomDatum::fz
         :index: 2
         :vis: pub
         :toc: fz
         :layout: [{"type":"name","value":"fz"},{"type":"punctuation","value":": "},{"type":"link","value":"Option","target":"Option"},{"type":"punctuation","value":"<"},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":">"}]

         The z-component of force (present when ``"forces"`` section declared).

      .. rubric:: Implementations


      .. rust:impl:: readcon_core::types::AtomDatum
         :index: -1
         :vis: pub
         :layout: [{"type":"keyword","value":"impl"},{"type":"space"},{"type":"link","value":"AtomDatum","target":"AtomDatum"}]
         :toc: impl AtomDatum


         .. rubric:: Functions


         .. rust:function:: readcon_core::types::AtomDatum::has_forces
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"has_forces"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"self"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"bool","target":"bool"}]

            Returns ``true`` if this atom has force data.

         .. rust:function:: readcon_core::types::AtomDatum::has_velocity
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"has_velocity"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"self"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"bool","target":"bool"}]

            Returns ``true`` if this atom has velocity data.

         .. rust:function:: readcon_core::types::AtomDatum::is_fixed
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"is_fixed"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"self"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"bool","target":"bool"}]

            Returns ``true`` if any direction is fixed.

         .. rust:function:: readcon_core::types::AtomDatum::is_fully_fixed
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"is_fully_fixed"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"self"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"bool","target":"bool"}]

            Returns ``true`` if all three directions are fixed.

      .. rubric:: Traits implemented


      .. rust:impl:: readcon_core::types::AtomDatum::PartialEq
         :index: -1
         :vis: pub
         :layout: [{"type":"keyword","value":"impl"},{"type":"space"},{"type":"link","value":"PartialEq","target":"PartialEq"},{"type":"space"},{"type":"keyword","value":"for"},{"type":"space"},{"type":"link","value":"AtomDatum","target":"AtomDatum"}]
         :toc: impl PartialEq for AtomDatum


   .. rust:struct:: readcon_core::types::ConFrame
      :index: 1
      :vis: pub
      :toc: struct ConFrame
      :layout: [{"type":"keyword","value":"struct"},{"type":"space"},{"type":"name","value":"ConFrame"}]

      Represents a single, complete simulation frame, including header and all atomic data.

      .. rust:variable:: readcon_core::types::ConFrame::header
         :index: 2
         :vis: pub
         :toc: header
         :layout: [{"type":"name","value":"header"},{"type":"punctuation","value":": "},{"type":"link","value":"FrameHeader","target":"FrameHeader"}]

         The ``FrameHeader`` containing the frame's metadata.

      .. rust:variable:: readcon_core::types::ConFrame::atom_data
         :index: 2
         :vis: pub
         :toc: atom_data
         :layout: [{"type":"name","value":"atom_data"},{"type":"punctuation","value":": "},{"type":"link","value":"Vec","target":"Vec"},{"type":"punctuation","value":"<"},{"type":"link","value":"AtomDatum","target":"AtomDatum"},{"type":"punctuation","value":">"}]

         A vector holding all atomic data for the frame.

      .. rubric:: Implementations


      .. rust:impl:: readcon_core::types::ConFrame
         :index: -1
         :vis: pub
         :layout: [{"type":"keyword","value":"impl"},{"type":"space"},{"type":"link","value":"ConFrame","target":"ConFrame"}]
         :toc: impl ConFrame


         .. rubric:: Functions


         .. rust:function:: readcon_core::types::ConFrame::has_forces
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"has_forces"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"self"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"bool","target":"bool"}]

            Returns ``true`` if any atom in this frame has force data.

         .. rust:function:: readcon_core::types::ConFrame::has_velocities
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"has_velocities"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"self"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"bool","target":"bool"}]

            Returns ``true`` if any atom in this frame has velocity data.

      .. rust:impl:: readcon_core::types::ConFrame
         :index: -1
         :vis: pub
         :layout: [{"type":"keyword","value":"impl"},{"type":"space"},{"type":"link","value":"ConFrame","target":"ConFrame"}]
         :toc: impl ConFrame


         .. rubric:: Functions


         .. rust:function:: readcon_core::types::ConFrame::builder
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"builder"},{"type":"punctuation","value":"("},{"type":"name","value":"cell"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"["},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":"; "},{"type":"literal","value":"3"},{"type":"punctuation","value":"]"},{"type":"punctuation","value":", "},{"type":"name","value":"angles"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"["},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":"; "},{"type":"literal","value":"3"},{"type":"punctuation","value":"]"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"ConFrameBuilder","target":"ConFrameBuilder"}]

            Creates a new builder for constructing a ``ConFrame``.

      .. rubric:: Traits implemented


      .. rust:impl:: readcon_core::types::ConFrame::PartialEq
         :index: -1
         :vis: pub
         :layout: [{"type":"keyword","value":"impl"},{"type":"space"},{"type":"link","value":"PartialEq","target":"PartialEq"},{"type":"space"},{"type":"keyword","value":"for"},{"type":"space"},{"type":"link","value":"ConFrame","target":"ConFrame"}]
         :toc: impl PartialEq for ConFrame


   .. rust:struct:: readcon_core::types::ConFrameBuilder
      :index: 1
      :vis: pub
      :toc: struct ConFrameBuilder
      :layout: [{"type":"keyword","value":"struct"},{"type":"space"},{"type":"name","value":"ConFrameBuilder"}]

      A builder for constructing ``ConFrame`` objects from in-memory data.
      
      Atoms are accumulated and grouped by symbol on ``build()`` to compute the
      header fields (``natm_types``, ``natms_per_type``, ``masses_per_type``).
      
      **Example**
      
      .. code-block:: none

         use readcon_core::types::ConFrameBuilder;

         let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
         builder.add_atom("Cu", 0.0, 0.0, 0.0, [true, true, true], 0, 63.546);
         builder.add_atom("H", 1.0, 2.0, 3.0, [false, false, false], 1, 1.008);
         let frame = builder.build();
         assert_eq!(frame.header.natm_types, 2);
         assert_eq!(frame.atom_data.len(), 2);


      .. rubric:: Implementations


      .. rust:impl:: readcon_core::types::ConFrameBuilder
         :index: -1
         :vis: pub
         :layout: [{"type":"keyword","value":"impl"},{"type":"space"},{"type":"link","value":"ConFrameBuilder","target":"ConFrameBuilder"}]
         :toc: impl ConFrameBuilder


         .. rubric:: Functions


         .. rust:function:: readcon_core::types::ConFrameBuilder::add_atom
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"add_atom"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"keyword","value":"self"},{"type":"punctuation","value":", "},{"type":"name","value":"symbol"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"&"},{"type":"link","value":"str","target":"str"},{"type":"punctuation","value":", "},{"type":"name","value":"x"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"y"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"z"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"fixed"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"["},{"type":"link","value":"bool","target":"bool"},{"type":"punctuation","value":"; "},{"type":"literal","value":"3"},{"type":"punctuation","value":"]"},{"type":"punctuation","value":", "},{"type":"name","value":"atom_id"},{"type":"punctuation","value":": "},{"type":"link","value":"u64","target":"u64"},{"type":"punctuation","value":", "},{"type":"name","value":"mass"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":")"}]

            Adds an atom without velocity data.

         .. rust:function:: readcon_core::types::ConFrameBuilder::add_atom_with_forces
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"add_atom_with_forces"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"keyword","value":"self"},{"type":"punctuation","value":", "},{"type":"name","value":"symbol"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"&"},{"type":"link","value":"str","target":"str"},{"type":"punctuation","value":", "},{"type":"name","value":"x"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"y"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"z"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"fixed"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"["},{"type":"link","value":"bool","target":"bool"},{"type":"punctuation","value":"; "},{"type":"literal","value":"3"},{"type":"punctuation","value":"]"},{"type":"punctuation","value":", "},{"type":"name","value":"atom_id"},{"type":"punctuation","value":": "},{"type":"link","value":"u64","target":"u64"},{"type":"punctuation","value":", "},{"type":"name","value":"mass"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"fx"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"fy"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"fz"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":")"}]

            Adds an atom with force data.

         .. rust:function:: readcon_core::types::ConFrameBuilder::add_atom_with_velocity
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"add_atom_with_velocity"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"keyword","value":"self"},{"type":"punctuation","value":", "},{"type":"name","value":"symbol"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"&"},{"type":"link","value":"str","target":"str"},{"type":"punctuation","value":", "},{"type":"name","value":"x"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"y"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"z"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"fixed"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"["},{"type":"link","value":"bool","target":"bool"},{"type":"punctuation","value":"; "},{"type":"literal","value":"3"},{"type":"punctuation","value":"]"},{"type":"punctuation","value":", "},{"type":"name","value":"atom_id"},{"type":"punctuation","value":": "},{"type":"link","value":"u64","target":"u64"},{"type":"punctuation","value":", "},{"type":"name","value":"mass"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"vx"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"vy"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"vz"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":")"}]

            Adds an atom with velocity data (for .convel output).

         .. rust:function:: readcon_core::types::ConFrameBuilder::add_atom_with_velocity_and_forces
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"add_atom_with_velocity_and_forces"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"keyword","value":"self"},{"type":"punctuation","value":", "},{"type":"name","value":"symbol"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"&"},{"type":"link","value":"str","target":"str"},{"type":"punctuation","value":", "},{"type":"name","value":"x"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"y"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"z"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"fixed"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"["},{"type":"link","value":"bool","target":"bool"},{"type":"punctuation","value":"; "},{"type":"literal","value":"3"},{"type":"punctuation","value":"]"},{"type":"punctuation","value":", "},{"type":"name","value":"atom_id"},{"type":"punctuation","value":": "},{"type":"link","value":"u64","target":"u64"},{"type":"punctuation","value":", "},{"type":"name","value":"mass"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"vx"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"vy"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"vz"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"fx"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"fy"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"fz"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":")"}]

            Adds an atom with both velocity and force data.

         .. rust:function:: readcon_core::types::ConFrameBuilder::build
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"build"},{"type":"punctuation","value":"("},{"type":"keyword","value":"self"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"ConFrame","target":"ConFrame"}]

            Consumes the builder and produces a ``ConFrame``.
            
            Atoms are grouped by symbol (in encounter order) to compute
            ``natm_types``, ``natms_per_type``, and ``masses_per_type``.

         .. rust:function:: readcon_core::types::ConFrameBuilder::metadata
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"metadata"},{"type":"punctuation","value":"("},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"keyword","value":"self"},{"type":"punctuation","value":", "},{"type":"name","value":"m"},{"type":"punctuation","value":": "},{"type":"link","value":"BTreeMap","target":"BTreeMap"},{"type":"punctuation","value":"<"},{"type":"link","value":"String","target":"String"},{"type":"punctuation","value":", "},{"type":"link","value":"serde_json","target":"serde_json"},{"type":"punctuation","value":"::"},{"type":"name","value":"Value"},{"type":"punctuation","value":">"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"Self","target":"Self"}]

            Adds extra key-value pairs to the JSON metadata line.
            The ``con_spec_version`` key is always set automatically.

         .. rust:function:: readcon_core::types::ConFrameBuilder::new
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"new"},{"type":"punctuation","value":"("},{"type":"name","value":"cell"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"["},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":"; "},{"type":"literal","value":"3"},{"type":"punctuation","value":"]"},{"type":"punctuation","value":", "},{"type":"name","value":"angles"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"["},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":"; "},{"type":"literal","value":"3"},{"type":"punctuation","value":"]"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"Self","target":"Self"}]

            Creates a new builder with the given cell dimensions and angles.

         .. rust:function:: readcon_core::types::ConFrameBuilder::postbox_header
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"postbox_header"},{"type":"punctuation","value":"("},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"keyword","value":"self"},{"type":"punctuation","value":", "},{"type":"name","value":"h"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"["},{"type":"link","value":"String","target":"String"},{"type":"punctuation","value":"; "},{"type":"literal","value":"2"},{"type":"punctuation","value":"]"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"Self","target":"Self"}]

            Sets the two post-box header lines.

         .. rust:function:: readcon_core::types::ConFrameBuilder::prebox_header
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"prebox_header"},{"type":"punctuation","value":"("},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"keyword","value":"self"},{"type":"punctuation","value":", "},{"type":"name","value":"h"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"["},{"type":"link","value":"String","target":"String"},{"type":"punctuation","value":"; "},{"type":"literal","value":"2"},{"type":"punctuation","value":"]"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"Self","target":"Self"}]

            Sets the two pre-box header lines.

         .. rust:function:: readcon_core::types::ConFrameBuilder::set_energy
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"set_energy"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"keyword","value":"self"},{"type":"punctuation","value":", "},{"type":"name","value":"energy"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":")"}]

            Sets the per-frame total energy metadata.

         .. rust:function:: readcon_core::types::ConFrameBuilder::set_frame_index
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"set_frame_index"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"keyword","value":"self"},{"type":"punctuation","value":", "},{"type":"name","value":"idx"},{"type":"punctuation","value":": "},{"type":"link","value":"u64","target":"u64"},{"type":"punctuation","value":")"}]

            Sets the zero-based frame index metadata.

         .. rust:function:: readcon_core::types::ConFrameBuilder::set_metadata_json
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"set_metadata_json"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"keyword","value":"self"},{"type":"punctuation","value":", "},{"type":"name","value":"metadata_json"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"&"},{"type":"link","value":"str","target":"str"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"Result","target":"Result"},{"type":"punctuation","value":"<"},{"type":"punctuation","value":"("},{"type":"punctuation","value":")"},{"type":"punctuation","value":", "},{"type":"link","value":"serde_json","target":"serde_json"},{"type":"punctuation","value":"::"},{"type":"name","value":"Error"},{"type":"punctuation","value":">"}]

            Parses and sets JSON metadata for the frame header.
            
            The input must be a JSON object. The ``con_spec_version`` and
            ``sections`` keys are ignored because they are managed by the
            builder/writer.

         .. rust:function:: readcon_core::types::ConFrameBuilder::set_neb_band
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"set_neb_band"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"keyword","value":"self"},{"type":"punctuation","value":", "},{"type":"name","value":"band"},{"type":"punctuation","value":": "},{"type":"link","value":"u64","target":"u64"},{"type":"punctuation","value":")"}]

            Sets the NEB band index metadata.

         .. rust:function:: readcon_core::types::ConFrameBuilder::set_neb_bead
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"set_neb_bead"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"keyword","value":"self"},{"type":"punctuation","value":", "},{"type":"name","value":"bead"},{"type":"punctuation","value":": "},{"type":"link","value":"u64","target":"u64"},{"type":"punctuation","value":")"}]

            Sets the NEB bead index metadata.

         .. rust:function:: readcon_core::types::ConFrameBuilder::set_scalar_metadata
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"set_scalar_metadata"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"keyword","value":"self"},{"type":"punctuation","value":", "},{"type":"name","value":"key"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"&"},{"type":"link","value":"str","target":"str"},{"type":"punctuation","value":", "},{"type":"name","value":"value"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":")"}]

            Sets a numeric metadata key.

         .. rust:function:: readcon_core::types::ConFrameBuilder::set_string_metadata
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"set_string_metadata"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"keyword","value":"self"},{"type":"punctuation","value":", "},{"type":"name","value":"key"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"&"},{"type":"link","value":"str","target":"str"},{"type":"punctuation","value":", "},{"type":"name","value":"value"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"&"},{"type":"link","value":"str","target":"str"},{"type":"punctuation","value":")"}]

            Sets a string metadata key.

         .. rust:function:: readcon_core::types::ConFrameBuilder::set_time
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"set_time"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"keyword","value":"self"},{"type":"punctuation","value":", "},{"type":"name","value":"time"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":")"}]

            Sets the simulation time metadata.

         .. rust:function:: readcon_core::types::ConFrameBuilder::set_timestep
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"set_timestep"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"keyword","value":"self"},{"type":"punctuation","value":", "},{"type":"name","value":"dt"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":")"}]

            Sets the timestep metadata.

   .. rust:struct:: readcon_core::types::FrameHeader
      :index: 1
      :vis: pub
      :toc: struct FrameHeader
      :layout: [{"type":"keyword","value":"struct"},{"type":"space"},{"type":"name","value":"FrameHeader"}]

      Holds all metadata from the 9-line header of a simulation frame.

      .. rust:variable:: readcon_core::types::FrameHeader::prebox_header
         :index: 2
         :vis: pub
         :toc: prebox_header
         :layout: [{"type":"name","value":"prebox_header"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"["},{"type":"link","value":"String","target":"String"},{"type":"punctuation","value":"; "},{"type":"literal","value":"2"},{"type":"punctuation","value":"]"}]

         The two text lines preceding the box dimension data.
         Line 0 is free-form text (e.g. "Generated by eOn").
         Line 1 is reserved for machine-readable JSON metadata and is
         managed automatically by the parser/writer -- do not set directly.

      .. rust:variable:: readcon_core::types::FrameHeader::boxl
         :index: 2
         :vis: pub
         :toc: boxl
         :layout: [{"type":"name","value":"boxl"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"["},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":"; "},{"type":"literal","value":"3"},{"type":"punctuation","value":"]"}]

         The three box dimensions, typically Lx, Ly, and Lz.

      .. rust:variable:: readcon_core::types::FrameHeader::angles
         :index: 2
         :vis: pub
         :toc: angles
         :layout: [{"type":"name","value":"angles"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"["},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":"; "},{"type":"literal","value":"3"},{"type":"punctuation","value":"]"}]

         The three box angles, typically alpha, beta, and gamma.

      .. rust:variable:: readcon_core::types::FrameHeader::postbox_header
         :index: 2
         :vis: pub
         :toc: postbox_header
         :layout: [{"type":"name","value":"postbox_header"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"["},{"type":"link","value":"String","target":"String"},{"type":"punctuation","value":"; "},{"type":"literal","value":"2"},{"type":"punctuation","value":"]"}]

         The two text lines following the box angle data.

      .. rust:variable:: readcon_core::types::FrameHeader::natm_types
         :index: 2
         :vis: pub
         :toc: natm_types
         :layout: [{"type":"name","value":"natm_types"},{"type":"punctuation","value":": "},{"type":"link","value":"usize","target":"usize"}]

         The number of distinct atom types in the frame.

      .. rust:variable:: readcon_core::types::FrameHeader::natms_per_type
         :index: 2
         :vis: pub
         :toc: natms_per_type
         :layout: [{"type":"name","value":"natms_per_type"},{"type":"punctuation","value":": "},{"type":"link","value":"Vec","target":"Vec"},{"type":"punctuation","value":"<"},{"type":"link","value":"usize","target":"usize"},{"type":"punctuation","value":">"}]

         A vector containing the count of atoms for each respective type.

      .. rust:variable:: readcon_core::types::FrameHeader::masses_per_type
         :index: 2
         :vis: pub
         :toc: masses_per_type
         :layout: [{"type":"name","value":"masses_per_type"},{"type":"punctuation","value":": "},{"type":"link","value":"Vec","target":"Vec"},{"type":"punctuation","value":"<"},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":">"}]

         A vector containing the mass for each respective atom type.

      .. rust:variable:: readcon_core::types::FrameHeader::spec_version
         :index: 2
         :vis: pub
         :toc: spec_version
         :layout: [{"type":"name","value":"spec_version"},{"type":"punctuation","value":": "},{"type":"link","value":"u32","target":"u32"}]

         CON spec version parsed from the JSON metadata line.

      .. rust:variable:: readcon_core::types::FrameHeader::metadata
         :index: 2
         :vis: pub
         :toc: metadata
         :layout: [{"type":"name","value":"metadata"},{"type":"punctuation","value":": "},{"type":"link","value":"BTreeMap","target":"BTreeMap"},{"type":"punctuation","value":"<"},{"type":"link","value":"String","target":"String"},{"type":"punctuation","value":", "},{"type":"link","value":"serde_json","target":"serde_json"},{"type":"punctuation","value":"::"},{"type":"name","value":"Value"},{"type":"punctuation","value":">"}]

         Additional key-value metadata from the JSON metadata line.
         Keys other than ``con_spec_version`` are preserved here for round-tripping.

      .. rust:variable:: readcon_core::types::FrameHeader::sections
         :index: 2
         :vis: pub
         :toc: sections
         :layout: [{"type":"name","value":"sections"},{"type":"punctuation","value":": "},{"type":"link","value":"Vec","target":"Vec"},{"type":"punctuation","value":"<"},{"type":"link","value":"String","target":"String"},{"type":"punctuation","value":">"}]

         Declared data sections from JSON metadata or detected from data presence. (e.g. ``["velocities", "forces"]``).
         Empty for legacy files (parser falls back to blank-separator velocity detection).

      .. rubric:: Implementations


      .. rust:impl:: readcon_core::types::FrameHeader
         :index: -1
         :vis: pub
         :layout: [{"type":"keyword","value":"impl"},{"type":"space"},{"type":"link","value":"FrameHeader","target":"FrameHeader"}]
         :toc: impl FrameHeader

            Typed accessors for recommended JSON metadata keys.
            
            All getters read from ``self.metadata``; all setters write to it.
            The underlying ``BTreeMap`` is the source of truth -- these helpers
            provide ergonomic typed access without changing storage.

         .. rubric:: Functions


         .. rust:function:: readcon_core::types::FrameHeader::energy
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"energy"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"self"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"Option","target":"Option"},{"type":"punctuation","value":"<"},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":">"}]

            Per-frame total energy (in the units declared by the ``units`` key).

         .. rust:function:: readcon_core::types::FrameHeader::frame_index
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"frame_index"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"self"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"Option","target":"Option"},{"type":"punctuation","value":"<"},{"type":"link","value":"u64","target":"u64"},{"type":"punctuation","value":">"}]

            Zero-based frame index within a trajectory.

         .. rust:function:: readcon_core::types::FrameHeader::lattice_vectors
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"lattice_vectors"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"self"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"Option","target":"Option"},{"type":"punctuation","value":"<"},{"type":"punctuation","value":"["},{"type":"punctuation","value":"["},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":"; "},{"type":"literal","value":"3"},{"type":"punctuation","value":"]"},{"type":"punctuation","value":"; "},{"type":"literal","value":"3"},{"type":"punctuation","value":"]"},{"type":"punctuation","value":">"}]

            Exact 3x3 lattice vector matrix (row-major, angstroms).
            When present, takes precedence over the length/angle values on lines 3-4.

         .. rust:function:: readcon_core::types::FrameHeader::neb_band
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"neb_band"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"self"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"Option","target":"Option"},{"type":"punctuation","value":"<"},{"type":"link","value":"u64","target":"u64"},{"type":"punctuation","value":">"}]

            NEB band index.

         .. rust:function:: readcon_core::types::FrameHeader::neb_bead
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"neb_bead"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"self"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"Option","target":"Option"},{"type":"punctuation","value":"<"},{"type":"link","value":"u64","target":"u64"},{"type":"punctuation","value":">"}]

            NEB bead (image) index.

         .. rust:function:: readcon_core::types::FrameHeader::pbc
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"pbc"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"self"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"Option","target":"Option"},{"type":"punctuation","value":"<"},{"type":"punctuation","value":"["},{"type":"link","value":"bool","target":"bool"},{"type":"punctuation","value":"; "},{"type":"literal","value":"3"},{"type":"punctuation","value":"]"},{"type":"punctuation","value":">"}]

            Periodic boundary conditions as ``[pbc_x, pbc_y, pbc_z]``.
            Returns ``None`` if not set (callers should default to ``[true, true, true]``).

         .. rust:function:: readcon_core::types::FrameHeader::potential_params
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"potential_params"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"self"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"Option","target":"Option"},{"type":"punctuation","value":"<"},{"type":"punctuation","value":"&"},{"type":"link","value":"serde_json","target":"serde_json"},{"type":"punctuation","value":"::"},{"type":"name","value":"Value"},{"type":"punctuation","value":">"}]

            Potential parameters as a JSON value.

         .. rust:function:: readcon_core::types::FrameHeader::potential_type
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"potential_type"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"self"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"Option","target":"Option"},{"type":"punctuation","value":"<"},{"type":"punctuation","value":"&"},{"type":"link","value":"str","target":"str"},{"type":"punctuation","value":">"}]

            Potential type string (e.g. "EMT", "LJ").

         .. rust:function:: readcon_core::types::FrameHeader::set_energy
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"set_energy"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"keyword","value":"self"},{"type":"punctuation","value":", "},{"type":"name","value":"e"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":")"}]

            Sets the per-frame total energy.

         .. rust:function:: readcon_core::types::FrameHeader::set_frame_index
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"set_frame_index"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"keyword","value":"self"},{"type":"punctuation","value":", "},{"type":"name","value":"idx"},{"type":"punctuation","value":": "},{"type":"link","value":"u64","target":"u64"},{"type":"punctuation","value":")"}]

            Sets the frame index.

         .. rust:function:: readcon_core::types::FrameHeader::set_lattice_vectors
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"set_lattice_vectors"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"keyword","value":"self"},{"type":"punctuation","value":", "},{"type":"name","value":"vecs"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"["},{"type":"punctuation","value":"["},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":"; "},{"type":"literal","value":"3"},{"type":"punctuation","value":"]"},{"type":"punctuation","value":"; "},{"type":"literal","value":"3"},{"type":"punctuation","value":"]"},{"type":"punctuation","value":")"}]

            Sets the exact lattice vector matrix.

         .. rust:function:: readcon_core::types::FrameHeader::set_neb_band
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"set_neb_band"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"keyword","value":"self"},{"type":"punctuation","value":", "},{"type":"name","value":"band"},{"type":"punctuation","value":": "},{"type":"link","value":"u64","target":"u64"},{"type":"punctuation","value":")"}]

            Sets the NEB band index.

         .. rust:function:: readcon_core::types::FrameHeader::set_neb_bead
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"set_neb_bead"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"keyword","value":"self"},{"type":"punctuation","value":", "},{"type":"name","value":"bead"},{"type":"punctuation","value":": "},{"type":"link","value":"u64","target":"u64"},{"type":"punctuation","value":")"}]

            Sets the NEB bead index.

         .. rust:function:: readcon_core::types::FrameHeader::set_pbc
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"set_pbc"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"keyword","value":"self"},{"type":"punctuation","value":", "},{"type":"name","value":"pbc"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"["},{"type":"link","value":"bool","target":"bool"},{"type":"punctuation","value":"; "},{"type":"literal","value":"3"},{"type":"punctuation","value":"]"},{"type":"punctuation","value":")"}]

            Sets the periodic boundary conditions.

         .. rust:function:: readcon_core::types::FrameHeader::set_potential
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"set_potential"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"keyword","value":"self"},{"type":"punctuation","value":", "},{"type":"name","value":"pot_type"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"&"},{"type":"link","value":"str","target":"str"},{"type":"punctuation","value":", "},{"type":"name","value":"params"},{"type":"punctuation","value":": "},{"type":"link","value":"serde_json","target":"serde_json"},{"type":"punctuation","value":"::"},{"type":"name","value":"Value"},{"type":"punctuation","value":")"}]

            Sets the potential type and parameters.

         .. rust:function:: readcon_core::types::FrameHeader::set_time
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"set_time"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"keyword","value":"self"},{"type":"punctuation","value":", "},{"type":"name","value":"t"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":")"}]

            Sets the simulation time.

         .. rust:function:: readcon_core::types::FrameHeader::set_timestep
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"set_timestep"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"keyword","value":"self"},{"type":"punctuation","value":", "},{"type":"name","value":"dt"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":")"}]

            Sets the integration timestep.

         .. rust:function:: readcon_core::types::FrameHeader::set_units
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"set_units"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"keyword","value":"self"},{"type":"punctuation","value":", "},{"type":"name","value":"units"},{"type":"punctuation","value":": "},{"type":"link","value":"serde_json","target":"serde_json"},{"type":"punctuation","value":"::"},{"type":"name","value":"Value"},{"type":"punctuation","value":")"}]

            Sets the unit system.

         .. rust:function:: readcon_core::types::FrameHeader::time
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"time"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"self"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"Option","target":"Option"},{"type":"punctuation","value":"<"},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":">"}]

            Simulation time of this frame (in the declared time unit).

         .. rust:function:: readcon_core::types::FrameHeader::timestep
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"timestep"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"self"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"Option","target":"Option"},{"type":"punctuation","value":"<"},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":">"}]

            Integration timestep (in the declared time unit).

         .. rust:function:: readcon_core::types::FrameHeader::units
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"units"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"self"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"Option","target":"Option"},{"type":"punctuation","value":"<"},{"type":"punctuation","value":"&"},{"type":"link","value":"serde_json","target":"serde_json"},{"type":"punctuation","value":"::"},{"type":"name","value":"Value"},{"type":"punctuation","value":">"}]

            Unit system as a JSON object (e.g. ``{"length":"angstrom","energy":"eV"}``).

      .. rubric:: Traits implemented


      .. rust:impl:: readcon_core::types::FrameHeader::PartialEq
         :index: -1
         :vis: pub
         :layout: [{"type":"keyword","value":"impl"},{"type":"space"},{"type":"link","value":"PartialEq","target":"PartialEq"},{"type":"space"},{"type":"keyword","value":"for"},{"type":"space"},{"type":"link","value":"FrameHeader","target":"FrameHeader"}]
         :toc: impl PartialEq for FrameHeader

