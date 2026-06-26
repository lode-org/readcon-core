==============
``mod parser``
==============


.. rust:module:: readcon_core::parser
   :index: 0
   :vis: pub


   .. rust:use:: readcon_core::parser
      :used_name: self


   .. rust:use:: readcon_core
      :used_name: crate


   .. rust:use:: readcon_core::error::ParseError
      :used_name: ParseError


   .. rust:use:: readcon_core::helpers::symbol_to_atomic_number
      :used_name: symbol_to_atomic_number


   .. rust:use:: readcon_core::types::AtomDatum
      :used_name: AtomDatum


   .. rust:use:: readcon_core::types::ConFrame
      :used_name: ConFrame


   .. rust:use:: readcon_core::types::FrameHeader
      :used_name: FrameHeader


   .. rust:use:: readcon_core::types::decode_fixed_bitmask
      :used_name: decode_fixed_bitmask


   .. rust:use:: serde_json::Value
      :used_name: Value


   .. rust:use:: std::collections::BTreeMap
      :used_name: BTreeMap


   .. rust:use:: std::iter::Peekable
      :used_name: Peekable


   .. rust:use:: std::sync::Arc
      :used_name: Arc


   .. rubric:: Functions


   .. rust:function:: readcon_core::parser::parse_declared_sections
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"parse_declared_sections"},{"type":"punctuation","value":"<"},{"type":"lifetime","value":"'a"},{"type":"punctuation","value":", "},{"type":"name","value":"I"},{"type":"punctuation","value":">"},{"type":"punctuation","value":"("},{"type":"name","value":"lines"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"&"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"Peekable","target":"Peekable"},{"type":"punctuation","value":"<"},{"type":"link","value":"I","target":"I"},{"type":"punctuation","value":">"},{"type":"punctuation","value":", "},{"type":"name","value":"header"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"&"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"FrameHeader","target":"FrameHeader"},{"type":"punctuation","value":", "},{"type":"name","value":"atom_data"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"&"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"punctuation","value":"["},{"type":"link","value":"AtomDatum","target":"AtomDatum"},{"type":"punctuation","value":"]"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"Result","target":"Result"},{"type":"punctuation","value":"<"},{"type":"punctuation","value":"("},{"type":"punctuation","value":")"},{"type":"punctuation","value":", "},{"type":"link","value":"ParseError","target":"ParseError"},{"type":"punctuation","value":">"},{"type":"newline"},{"type":"keyword","value":"where"},{"type":"newline"},{"type":"indent"},{"type":"link","value":"I","target":"I"},{"type":"punctuation","value":": "},{"type":"link","value":"Iterator","target":"Iterator"},{"type":"punctuation","value":"<"},{"type":"name","value":"Item"},{"type":"punctuation","value":" = "},{"type":"punctuation","value":"&"},{"type":"lifetime","value":"'a"},{"type":"space"},{"type":"link","value":"str","target":"str"},{"type":"punctuation","value":">"}]

      Parses declared sections from a frame's header metadata.
      
      If ``header.sections`` is non-empty (v2 file with ``"sections"`` key in JSON),
      parses each declared section in order. Otherwise falls back to legacy
      blank-separator velocity detection.

   .. rust:function:: readcon_core::parser::parse_force_section
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"parse_force_section"},{"type":"punctuation","value":"<"},{"type":"lifetime","value":"'a"},{"type":"punctuation","value":", "},{"type":"name","value":"I"},{"type":"punctuation","value":">"},{"type":"punctuation","value":"("},{"type":"name","value":"lines"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"&"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"Peekable","target":"Peekable"},{"type":"punctuation","value":"<"},{"type":"link","value":"I","target":"I"},{"type":"punctuation","value":">"},{"type":"punctuation","value":", "},{"type":"name","value":"header"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"&"},{"type":"link","value":"FrameHeader","target":"FrameHeader"},{"type":"punctuation","value":", "},{"type":"name","value":"atom_data"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"&"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"punctuation","value":"["},{"type":"link","value":"AtomDatum","target":"AtomDatum"},{"type":"punctuation","value":"]"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"Result","target":"Result"},{"type":"punctuation","value":"<"},{"type":"link","value":"bool","target":"bool"},{"type":"punctuation","value":", "},{"type":"link","value":"ParseError","target":"ParseError"},{"type":"punctuation","value":">"},{"type":"newline"},{"type":"keyword","value":"where"},{"type":"newline"},{"type":"indent"},{"type":"link","value":"I","target":"I"},{"type":"punctuation","value":": "},{"type":"link","value":"Iterator","target":"Iterator"},{"type":"punctuation","value":"<"},{"type":"name","value":"Item"},{"type":"punctuation","value":" = "},{"type":"punctuation","value":"&"},{"type":"lifetime","value":"'a"},{"type":"space"},{"type":"link","value":"str","target":"str"},{"type":"punctuation","value":">"}]

      Attempts to parse a force section following coordinate (and optional velocity) blocks.
      
      Force sections mirror velocity sections: a blank separator line followed by per-component
      force blocks (symbol line, "Forces of Component N" line, then atom lines with
      ``fx fy fz fixed_flag atom_id``).
      
      Returns ``Ok(true)`` if forces were found and parsed, ``Ok(false)`` otherwise.

   .. rust:function:: readcon_core::parser::parse_frame_header
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"parse_frame_header"},{"type":"punctuation","value":"<"},{"type":"lifetime","value":"'a"},{"type":"punctuation","value":">"},{"type":"punctuation","value":"("},{"type":"name","value":"lines"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"&"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"keyword","value":"impl"},{"type":"space"},{"type":"link","value":"Iterator","target":"Iterator"},{"type":"punctuation","value":"<"},{"type":"name","value":"Item"},{"type":"punctuation","value":" = "},{"type":"punctuation","value":"&"},{"type":"lifetime","value":"'a"},{"type":"space"},{"type":"link","value":"str","target":"str"},{"type":"punctuation","value":">"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"Result","target":"Result"},{"type":"punctuation","value":"<"},{"type":"link","value":"FrameHeader","target":"FrameHeader"},{"type":"punctuation","value":", "},{"type":"link","value":"ParseError","target":"ParseError"},{"type":"punctuation","value":">"}]

      Parses the 9-line header of a ``.con`` file frame from an iterator.
      
      This function consumes the next 9 lines from the given line iterator to
      construct a ``FrameHeader``. The iterator is advanced by 9 lines on success.
      
      **Arguments**
      
      * ``lines`` - A mutable reference to an iterator that yields string slices.
      
      **Errors**
      
      * ``ParseError::IncompleteHeader`` if the iterator has fewer than 9 lines remaining.
      * Propagates any errors from ``parse_line_of_n`` if the numeric data within
        the header is malformed.
      
      **Panics**
      
      This function will panic if the intermediate vectors for box dimensions or angles,
      after being successfully parsed, cannot be converted into fixed-size arrays.
      This should not happen if ``parse_line_of_n`` is used correctly with ``n=3``.

   .. rust:function:: readcon_core::parser::parse_line_of_n
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"parse_line_of_n"},{"type":"punctuation","value":"<"},{"type":"name","value":"T"},{"type":"punctuation","value":": "},{"type":"link","value":"std","target":"std"},{"type":"punctuation","value":"::"},{"type":"name","value":"str"},{"type":"punctuation","value":"::"},{"type":"name","value":"FromStr"},{"type":"punctuation","value":">"},{"type":"punctuation","value":"("},{"type":"name","value":"line"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"&"},{"type":"link","value":"str","target":"str"},{"type":"punctuation","value":", "},{"type":"name","value":"n"},{"type":"punctuation","value":": "},{"type":"link","value":"usize","target":"usize"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"Result","target":"Result"},{"type":"punctuation","value":"<"},{"type":"link","value":"Vec","target":"Vec"},{"type":"punctuation","value":"<"},{"type":"link","value":"T","target":"T"},{"type":"punctuation","value":">"},{"type":"punctuation","value":", "},{"type":"link","value":"ParseError","target":"ParseError"},{"type":"punctuation","value":">"},{"type":"newline"},{"type":"keyword","value":"where"},{"type":"newline"},{"type":"indent"},{"type":"link","value":"ParseError","target":"ParseError"},{"type":"punctuation","value":": "},{"type":"link","value":"From","target":"From"},{"type":"punctuation","value":"<"},{"type":"link","value":"std","target":"std"},{"type":"punctuation","value":"::"},{"type":"name","value":"str"},{"type":"punctuation","value":"::"},{"type":"name","value":"FromStr"},{"type":"punctuation","value":"::"},{"type":"name","value":"Err"},{"type":"punctuation","value":">"}]

      Parses a line of whitespace-separated values into a vector of a specific type.
      
      This generic helper function takes a string slice, splits it by whitespace,
      and attempts to parse each substring into the target type ``T``. The type ``T``
      must implement ``std::str::FromStr``.
      
      **Arguments**
      
      * ``line`` - A string slice representing a single line of data.
      * ``n`` - The exact number of values expected on the line.
      
      **Errors**
      
      * ``ParseError::InvalidVectorLength`` if the number of parsed values is not equal to ``n``.
      * Propagates any error from the ``parse()`` method of the target type ``T``.
      
      **Example**
      
      .. code-block:: none

         use readcon_core::parser::parse_line_of_n;
         let line = "10.5 20.0 30.5";
         let values: Vec<f64> = parse_line_of_n(line, 3).unwrap();
         assert_eq!(values, vec![10.5, 20.0, 30.5]);

         let result = parse_line_of_n::<i32>(line, 2);
         assert!(result.is_err());


   .. rust:function:: readcon_core::parser::parse_line_of_n_f64
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"parse_line_of_n_f64"},{"type":"punctuation","value":"("},{"type":"name","value":"line"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"&"},{"type":"link","value":"str","target":"str"},{"type":"punctuation","value":", "},{"type":"name","value":"n"},{"type":"punctuation","value":": "},{"type":"link","value":"usize","target":"usize"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"Result","target":"Result"},{"type":"punctuation","value":"<"},{"type":"link","value":"Vec","target":"Vec"},{"type":"punctuation","value":"<"},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":">"},{"type":"punctuation","value":", "},{"type":"link","value":"ParseError","target":"ParseError"},{"type":"punctuation","value":">"}]

      Parses a line of whitespace-separated f64 values using fast-float2.
      
      This is the hot-path parser for coordinate and velocity lines. It uses
      ``fast_float2::parse`` instead of `str::parse::<f64>()` for better throughput
      on the numeric-heavy atom data lines.
      
      **Arguments**
      
      * ``line`` - A string slice representing a single line of data.
      * ``n`` - The exact number of f64 values expected on the line.

   .. rust:function:: readcon_core::parser::parse_line_of_range_f64
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"parse_line_of_range_f64"},{"type":"punctuation","value":"("},{"type":"name","value":"line"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"&"},{"type":"link","value":"str","target":"str"},{"type":"punctuation","value":", "},{"type":"name","value":"min"},{"type":"punctuation","value":": "},{"type":"link","value":"usize","target":"usize"},{"type":"punctuation","value":", "},{"type":"name","value":"max"},{"type":"punctuation","value":": "},{"type":"link","value":"usize","target":"usize"},{"type":"punctuation","value":", "},{"type":"name","value":"defaults"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"&"},{"type":"punctuation","value":"["},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":"]"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"Result","target":"Result"},{"type":"punctuation","value":"<"},{"type":"link","value":"Vec","target":"Vec"},{"type":"punctuation","value":"<"},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":">"},{"type":"punctuation","value":", "},{"type":"link","value":"ParseError","target":"ParseError"},{"type":"punctuation","value":">"}]

      Parses a line of whitespace-separated f64 values, accepting between ``min``
      and ``max`` values (inclusive). Returns a vector of exactly ``max`` elements,
      padding with values from ``defaults`` when fewer than ``max`` are present.
      
      Used for atom lines where column 5 (atom_index) is optional.

   .. rust:function:: readcon_core::parser::parse_single_frame
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"parse_single_frame"},{"type":"punctuation","value":"<"},{"type":"lifetime","value":"'a"},{"type":"punctuation","value":">"},{"type":"punctuation","value":"("},{"type":"name","value":"lines"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"&"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"keyword","value":"impl"},{"type":"space"},{"type":"link","value":"Iterator","target":"Iterator"},{"type":"punctuation","value":"<"},{"type":"name","value":"Item"},{"type":"punctuation","value":" = "},{"type":"punctuation","value":"&"},{"type":"lifetime","value":"'a"},{"type":"space"},{"type":"link","value":"str","target":"str"},{"type":"punctuation","value":">"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"Result","target":"Result"},{"type":"punctuation","value":"<"},{"type":"link","value":"ConFrame","target":"ConFrame"},{"type":"punctuation","value":", "},{"type":"link","value":"ParseError","target":"ParseError"},{"type":"punctuation","value":">"}]

      Parses a complete frame from a ``.con`` file, including its header and atomic data.
      
      This function first parses the complete frame header and then uses the information within it
      (specifically the number of atom types and atoms per type) to parse the subsequent
      atom coordinate blocks.
      
      **Arguments**
      
      * ``lines`` - A mutable reference to an iterator that yields string slices for the frame.
      
      **Errors**
      
      * ``ParseError::IncompleteFrame`` if the iterator ends before all expected
        atomic data has been read.
      * Propagates any errors from the underlying calls to ``parse_frame_header`` and
        ``parse_line_of_n``.
      
      **Example**
      
      .. code-block:: none

         use readcon_core::parser::parse_single_frame;

         let frame_text = r#"
         Generated by test
         {"con_spec_version":2}
         10.0 10.0 10.0
         90.0 90.0 90.0
         POSTBOX LINE 1
         POSTBOX LINE 2
         2
         1 1
         12.011 1.008
         C
         Coordinates of Component 1
         1.0 1.0 1.0 0.0 1
         H
         Coordinates of Component 2
         2.0 2.0 2.0 0.0 2
         "#;

         let mut lines = frame_text.trim().lines();
         let con_frame = parse_single_frame(&mut lines).unwrap();

         assert_eq!(con_frame.header.natm_types, 2);
         assert_eq!(con_frame.atom_data.len(), 2);
         assert_eq!(&*con_frame.atom_data[0].symbol, "C");
         assert_eq!(con_frame.atom_data[1].atom_id, 2);


   .. rust:function:: readcon_core::parser::parse_velocity_section
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"parse_velocity_section"},{"type":"punctuation","value":"<"},{"type":"lifetime","value":"'a"},{"type":"punctuation","value":", "},{"type":"name","value":"I"},{"type":"punctuation","value":">"},{"type":"punctuation","value":"("},{"type":"name","value":"lines"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"&"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"Peekable","target":"Peekable"},{"type":"punctuation","value":"<"},{"type":"link","value":"I","target":"I"},{"type":"punctuation","value":">"},{"type":"punctuation","value":", "},{"type":"name","value":"header"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"&"},{"type":"link","value":"FrameHeader","target":"FrameHeader"},{"type":"punctuation","value":", "},{"type":"name","value":"atom_data"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"&"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"punctuation","value":"["},{"type":"link","value":"AtomDatum","target":"AtomDatum"},{"type":"punctuation","value":"]"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"Result","target":"Result"},{"type":"punctuation","value":"<"},{"type":"link","value":"bool","target":"bool"},{"type":"punctuation","value":", "},{"type":"link","value":"ParseError","target":"ParseError"},{"type":"punctuation","value":">"},{"type":"newline"},{"type":"keyword","value":"where"},{"type":"newline"},{"type":"indent"},{"type":"link","value":"I","target":"I"},{"type":"punctuation","value":": "},{"type":"link","value":"Iterator","target":"Iterator"},{"type":"punctuation","value":"<"},{"type":"name","value":"Item"},{"type":"punctuation","value":" = "},{"type":"punctuation","value":"&"},{"type":"lifetime","value":"'a"},{"type":"space"},{"type":"link","value":"str","target":"str"},{"type":"punctuation","value":">"}]

      Attempts to parse an optional velocity section following coordinate blocks.
      
      In ``.convel`` files, after all coordinate blocks there is a blank separator line
      followed by per-component velocity blocks with the same structure as coordinate
      blocks (symbol line, "Velocities of Component N" line, then atom lines with
      ``vx vy vz fixed atomID``).
      
      This function peeks at the next line. If it is blank (or contains only whitespace),
      it consumes the blank line and parses velocity data into the existing ``atom_data``.
      If the next line is not blank (or is absent), no velocities are parsed.
      
      Returns ``Ok(true)`` if velocities were found and parsed, ``Ok(false)`` otherwise.
