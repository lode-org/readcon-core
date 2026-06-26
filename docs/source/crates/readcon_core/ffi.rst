===========
``mod ffi``
===========


.. rust:module:: readcon_core::ffi
   :index: 0
   :vis: pub


   .. rust:use:: readcon_core::ffi
      :used_name: self


   .. rust:use:: readcon_core
      :used_name: crate


   .. rust:use:: readcon_core::helpers::symbol_to_atomic_number
      :used_name: symbol_to_atomic_number


   .. rust:use:: readcon_core::iterators::ConFrameIterator
      :used_name: ConFrameIterator


   .. rust:use:: readcon_core::iterators
      :used_name: iterators


   .. rust:use:: readcon_core::types::ConFrame
      :used_name: ConFrame


   .. rust:use:: readcon_core::types::ConFrameBuilder
      :used_name: ConFrameBuilder


   .. rust:use:: readcon_core::writer::ConFrameWriter
      :used_name: ConFrameWriter


   .. rust:use:: std::ffi::CStr
      :used_name: CStr


   .. rust:use:: std::ffi::CString
      :used_name: CString


   .. rust:use:: std::ffi::c_char
      :used_name: c_char


   .. rust:use:: std::fs::File
      :used_name: File


   .. rust:use:: std::fs
      :used_name: fs


   .. rust:use:: std::path::Path
      :used_name: Path


   .. rust:use:: std::ptr
      :used_name: ptr


   .. rubric:: Variables


   .. rust:variable:: readcon_core::ffi::RKR_CON_SPEC_VERSION
      :index: 0
      :vis: pub
      :toc: const RKR_CON_SPEC_VERSION
      :layout: [{"type":"keyword","value":"const"},{"type":"space"},{"type":"name","value":"RKR_CON_SPEC_VERSION"},{"type":"punctuation","value":": "},{"type":"link","value":"u32","target":"u32"}]

      CON/convel format spec version. Use `#if RKR_CON_SPEC_VERSION >= 2` in C/C++
      to gate code that depends on atom_index semantics.

   .. rubric:: Functions


   .. rust:function:: readcon_core::ffi::con_frame_iterator_next
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"unsafe"},{"type":"space"},{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"con_frame_iterator_next"},{"type":"punctuation","value":"("},{"type":"name","value":"iterator"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"CConFrameIterator","target":"CConFrameIterator"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"operator","value":"*"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"RKRConFrame","target":"RKRConFrame"}]

      Reads the next frame from the iterator, returning an opaque handle.
      The caller OWNS the returned handle and must free it with ``free_rkr_frame``.
      
      **Safety**
      iterator must be valid. The caller takes ownership of the returned frame.

   .. rust:function:: readcon_core::ffi::create_writer_from_path_c
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"unsafe"},{"type":"space"},{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"create_writer_from_path_c"},{"type":"punctuation","value":"("},{"type":"name","value":"filename_c"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"const"},{"type":"space"},{"type":"link","value":"c_char","target":"c_char"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"operator","value":"*"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"RKRConFrameWriter","target":"RKRConFrameWriter"}]

      Creates a new frame writer for the specified file.
      The caller OWNS the returned pointer and MUST call ``free_rkr_writer``.
      
      **Safety**
      filename_c must be valid. The caller takes ownership of the returned writer.

   .. rust:function:: readcon_core::ffi::create_writer_from_path_with_precision_c
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"unsafe"},{"type":"space"},{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"create_writer_from_path_with_precision_c"},{"type":"punctuation","value":"("},{"type":"name","value":"filename_c"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"const"},{"type":"space"},{"type":"link","value":"c_char","target":"c_char"},{"type":"punctuation","value":", "},{"type":"name","value":"precision"},{"type":"punctuation","value":": "},{"type":"link","value":"u8","target":"u8"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"operator","value":"*"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"RKRConFrameWriter","target":"RKRConFrameWriter"}]

      Creates a new frame writer with custom floating-point precision.
      The caller OWNS the returned pointer and MUST call ``free_rkr_writer``.
      
      **Safety**
      filename_c must be valid. The caller takes ownership of the returned writer.

   .. rust:function:: readcon_core::ffi::create_writer_gzip_c
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"unsafe"},{"type":"space"},{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"create_writer_gzip_c"},{"type":"punctuation","value":"("},{"type":"name","value":"filename_c"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"const"},{"type":"space"},{"type":"link","value":"c_char","target":"c_char"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"operator","value":"*"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"RKRConFrameWriter","target":"RKRConFrameWriter"}]

      Creates a new gzip-compressed frame writer for the specified file.
      The caller OWNS the returned pointer and MUST call ``free_rkr_writer``.
      
      **Safety**
      filename_c must be valid. The caller takes ownership of the returned writer.

   .. rust:function:: readcon_core::ffi::free_c_frame
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"unsafe"},{"type":"space"},{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"free_c_frame"},{"type":"punctuation","value":"("},{"type":"name","value":"frame"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"CFrame","target":"CFrame"},{"type":"punctuation","value":")"}]

      Frees the memory of a ``CFrame`` struct, including its internal atoms array.
      
      **Safety**
      frame must be valid or null.

   .. rust:function:: readcon_core::ffi::free_con_frame_iterator
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"unsafe"},{"type":"space"},{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"free_con_frame_iterator"},{"type":"punctuation","value":"("},{"type":"name","value":"iterator"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"CConFrameIterator","target":"CConFrameIterator"},{"type":"punctuation","value":")"}]

      Frees the memory for a ``CConFrameIterator``.
      
      **Safety**
      iterator must be valid or null.

   .. rust:function:: readcon_core::ffi::free_rkr_frame
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"unsafe"},{"type":"space"},{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"free_rkr_frame"},{"type":"punctuation","value":"("},{"type":"name","value":"frame_handle"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"RKRConFrame","target":"RKRConFrame"},{"type":"punctuation","value":")"}]

      Frees the memory for an opaque ``RKRConFrame`` handle.
      
      **Safety**
      frame_handle must be valid or null.

   .. rust:function:: readcon_core::ffi::free_rkr_frame_array
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"unsafe"},{"type":"space"},{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"free_rkr_frame_array"},{"type":"punctuation","value":"("},{"type":"name","value":"frames"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"operator","value":"*"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"RKRConFrame","target":"RKRConFrame"},{"type":"punctuation","value":", "},{"type":"name","value":"num_frames"},{"type":"punctuation","value":": "},{"type":"link","value":"usize","target":"usize"},{"type":"punctuation","value":")"}]

      Frees an array of frame handles returned by ``rkr_read_all_frames``.
      Each frame is freed individually, then the array itself.
      
      **Safety**
      frames must be valid or null.

   .. rust:function:: readcon_core::ffi::free_rkr_frame_builder
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"unsafe"},{"type":"space"},{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"free_rkr_frame_builder"},{"type":"punctuation","value":"("},{"type":"name","value":"builder_handle"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"RKRConFrameBuilder","target":"RKRConFrameBuilder"},{"type":"punctuation","value":")"}]

      Frees a frame builder without building.
      
      **Safety**
      builder_handle must be valid or null.

   .. rust:function:: readcon_core::ffi::free_rkr_writer
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"unsafe"},{"type":"space"},{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"free_rkr_writer"},{"type":"punctuation","value":"("},{"type":"name","value":"writer_handle"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"RKRConFrameWriter","target":"RKRConFrameWriter"},{"type":"punctuation","value":")"}]

      Frees the memory for an ``RKRConFrameWriter``, closing the associated file.
      
      **Safety**
      writer_handle must be valid or null.

   .. rust:function:: readcon_core::ffi::read_con_file_iterator
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"unsafe"},{"type":"space"},{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"read_con_file_iterator"},{"type":"punctuation","value":"("},{"type":"name","value":"filename_c"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"const"},{"type":"space"},{"type":"link","value":"c_char","target":"c_char"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"operator","value":"*"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"CConFrameIterator","target":"CConFrameIterator"}]

      Creates a new iterator for a .con file.
      The caller OWNS the returned pointer and MUST call ``free_con_frame_iterator``.
      Returns NULL if there are no more frames or on error.
      
      **Safety**
      filename_c must be valid. The caller takes ownership of the returned iterator.

   .. rust:function:: readcon_core::ffi::rkr_con_spec_version
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"rkr_con_spec_version"},{"type":"punctuation","value":"("},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"u32","target":"u32"}]

      Returns the spec version at runtime (for dynamically linked consumers).

   .. rust:function:: readcon_core::ffi::rkr_frame_add_atom
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"unsafe"},{"type":"space"},{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"rkr_frame_add_atom"},{"type":"punctuation","value":"("},{"type":"name","value":"builder_handle"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"RKRConFrameBuilder","target":"RKRConFrameBuilder"},{"type":"punctuation","value":", "},{"type":"name","value":"symbol"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"const"},{"type":"space"},{"type":"link","value":"c_char","target":"c_char"},{"type":"punctuation","value":", "},{"type":"name","value":"x"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"y"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"z"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"is_fixed"},{"type":"punctuation","value":": "},{"type":"link","value":"bool","target":"bool"},{"type":"punctuation","value":", "},{"type":"name","value":"atom_id"},{"type":"punctuation","value":": "},{"type":"link","value":"u64","target":"u64"},{"type":"punctuation","value":", "},{"type":"name","value":"mass"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"RKRStatus","target":"RKRStatus"}]

      Adds an atom (without velocity) to the frame builder.
      Returns ``RKR_STATUS_SUCCESS`` on success, or an error code.
      
      **Safety**
      builder_handle and symbol must be valid.

   .. rust:function:: readcon_core::ffi::rkr_frame_add_atom_with_fixed_mask
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"unsafe"},{"type":"space"},{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"rkr_frame_add_atom_with_fixed_mask"},{"type":"punctuation","value":"("},{"type":"name","value":"builder_handle"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"RKRConFrameBuilder","target":"RKRConFrameBuilder"},{"type":"punctuation","value":", "},{"type":"name","value":"symbol"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"const"},{"type":"space"},{"type":"link","value":"c_char","target":"c_char"},{"type":"punctuation","value":", "},{"type":"name","value":"x"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"y"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"z"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"fixed_x"},{"type":"punctuation","value":": "},{"type":"link","value":"bool","target":"bool"},{"type":"punctuation","value":", "},{"type":"name","value":"fixed_y"},{"type":"punctuation","value":": "},{"type":"link","value":"bool","target":"bool"},{"type":"punctuation","value":", "},{"type":"name","value":"fixed_z"},{"type":"punctuation","value":": "},{"type":"link","value":"bool","target":"bool"},{"type":"punctuation","value":", "},{"type":"name","value":"atom_id"},{"type":"punctuation","value":": "},{"type":"link","value":"u64","target":"u64"},{"type":"punctuation","value":", "},{"type":"name","value":"mass"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"RKRStatus","target":"RKRStatus"}]

      Adds an atom (without velocity) to the frame builder using per-axis fixed flags.
      Returns ``RKR_STATUS_SUCCESS`` on success, or an error code.
      
      **Safety**
      builder_handle and symbol must be valid.

   .. rust:function:: readcon_core::ffi::rkr_frame_add_atom_with_forces
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"unsafe"},{"type":"space"},{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"rkr_frame_add_atom_with_forces"},{"type":"punctuation","value":"("},{"type":"name","value":"builder_handle"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"RKRConFrameBuilder","target":"RKRConFrameBuilder"},{"type":"punctuation","value":", "},{"type":"name","value":"symbol"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"const"},{"type":"space"},{"type":"link","value":"c_char","target":"c_char"},{"type":"punctuation","value":", "},{"type":"name","value":"x"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"y"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"z"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"is_fixed"},{"type":"punctuation","value":": "},{"type":"link","value":"bool","target":"bool"},{"type":"punctuation","value":", "},{"type":"name","value":"atom_id"},{"type":"punctuation","value":": "},{"type":"link","value":"u64","target":"u64"},{"type":"punctuation","value":", "},{"type":"name","value":"mass"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"fx"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"fy"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"fz"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"RKRStatus","target":"RKRStatus"}]

      Adds an atom with force data to the frame builder.
      Returns ``RKR_STATUS_SUCCESS`` on success, or an error code.
      
      **Safety**
      builder_handle and symbol must be valid.

   .. rust:function:: readcon_core::ffi::rkr_frame_add_atom_with_forces_fixed_mask
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"unsafe"},{"type":"space"},{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"rkr_frame_add_atom_with_forces_fixed_mask"},{"type":"punctuation","value":"("},{"type":"name","value":"builder_handle"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"RKRConFrameBuilder","target":"RKRConFrameBuilder"},{"type":"punctuation","value":", "},{"type":"name","value":"symbol"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"const"},{"type":"space"},{"type":"link","value":"c_char","target":"c_char"},{"type":"punctuation","value":", "},{"type":"name","value":"x"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"y"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"z"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"fixed_x"},{"type":"punctuation","value":": "},{"type":"link","value":"bool","target":"bool"},{"type":"punctuation","value":", "},{"type":"name","value":"fixed_y"},{"type":"punctuation","value":": "},{"type":"link","value":"bool","target":"bool"},{"type":"punctuation","value":", "},{"type":"name","value":"fixed_z"},{"type":"punctuation","value":": "},{"type":"link","value":"bool","target":"bool"},{"type":"punctuation","value":", "},{"type":"name","value":"atom_id"},{"type":"punctuation","value":": "},{"type":"link","value":"u64","target":"u64"},{"type":"punctuation","value":", "},{"type":"name","value":"mass"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"fx"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"fy"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"fz"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"RKRStatus","target":"RKRStatus"}]

      Adds an atom with force data to the frame builder using per-axis fixed flags.
      Returns ``RKR_STATUS_SUCCESS`` on success, or an error code.
      
      **Safety**
      builder_handle and symbol must be valid.

   .. rust:function:: readcon_core::ffi::rkr_frame_add_atom_with_velocity
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"unsafe"},{"type":"space"},{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"rkr_frame_add_atom_with_velocity"},{"type":"punctuation","value":"("},{"type":"name","value":"builder_handle"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"RKRConFrameBuilder","target":"RKRConFrameBuilder"},{"type":"punctuation","value":", "},{"type":"name","value":"symbol"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"const"},{"type":"space"},{"type":"link","value":"c_char","target":"c_char"},{"type":"punctuation","value":", "},{"type":"name","value":"x"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"y"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"z"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"is_fixed"},{"type":"punctuation","value":": "},{"type":"link","value":"bool","target":"bool"},{"type":"punctuation","value":", "},{"type":"name","value":"atom_id"},{"type":"punctuation","value":": "},{"type":"link","value":"u64","target":"u64"},{"type":"punctuation","value":", "},{"type":"name","value":"mass"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"vx"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"vy"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"vz"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"RKRStatus","target":"RKRStatus"}]

      Adds an atom with velocity data to the frame builder.
      Returns ``RKR_STATUS_SUCCESS`` on success, or an error code.
      
      **Safety**
      builder_handle and symbol must be valid.

   .. rust:function:: readcon_core::ffi::rkr_frame_add_atom_with_velocity_and_forces
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"unsafe"},{"type":"space"},{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"rkr_frame_add_atom_with_velocity_and_forces"},{"type":"punctuation","value":"("},{"type":"name","value":"builder_handle"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"RKRConFrameBuilder","target":"RKRConFrameBuilder"},{"type":"punctuation","value":", "},{"type":"name","value":"symbol"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"const"},{"type":"space"},{"type":"link","value":"c_char","target":"c_char"},{"type":"punctuation","value":", "},{"type":"name","value":"x"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"y"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"z"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"is_fixed"},{"type":"punctuation","value":": "},{"type":"link","value":"bool","target":"bool"},{"type":"punctuation","value":", "},{"type":"name","value":"atom_id"},{"type":"punctuation","value":": "},{"type":"link","value":"u64","target":"u64"},{"type":"punctuation","value":", "},{"type":"name","value":"mass"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"vx"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"vy"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"vz"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"fx"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"fy"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"fz"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"RKRStatus","target":"RKRStatus"}]

      Adds an atom with velocity and force data to the frame builder.
      Returns ``RKR_STATUS_SUCCESS`` on success, or an error code.
      
      **Safety**
      builder_handle and symbol must be valid.

   .. rust:function:: readcon_core::ffi::rkr_frame_add_atom_with_velocity_and_forces_fixed_mask
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"unsafe"},{"type":"space"},{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"rkr_frame_add_atom_with_velocity_and_forces_fixed_mask"},{"type":"punctuation","value":"("},{"type":"name","value":"builder_handle"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"RKRConFrameBuilder","target":"RKRConFrameBuilder"},{"type":"punctuation","value":", "},{"type":"name","value":"symbol"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"const"},{"type":"space"},{"type":"link","value":"c_char","target":"c_char"},{"type":"punctuation","value":", "},{"type":"name","value":"x"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"y"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"z"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"fixed_x"},{"type":"punctuation","value":": "},{"type":"link","value":"bool","target":"bool"},{"type":"punctuation","value":", "},{"type":"name","value":"fixed_y"},{"type":"punctuation","value":": "},{"type":"link","value":"bool","target":"bool"},{"type":"punctuation","value":", "},{"type":"name","value":"fixed_z"},{"type":"punctuation","value":": "},{"type":"link","value":"bool","target":"bool"},{"type":"punctuation","value":", "},{"type":"name","value":"atom_id"},{"type":"punctuation","value":": "},{"type":"link","value":"u64","target":"u64"},{"type":"punctuation","value":", "},{"type":"name","value":"mass"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"vx"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"vy"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"vz"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"fx"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"fy"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"fz"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"RKRStatus","target":"RKRStatus"}]

      Adds an atom with velocity and force data using per-axis fixed flags.
      Returns ``RKR_STATUS_SUCCESS`` on success, or an error code.
      
      **Safety**
      builder_handle and symbol must be valid.

   .. rust:function:: readcon_core::ffi::rkr_frame_add_atom_with_velocity_fixed_mask
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"unsafe"},{"type":"space"},{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"rkr_frame_add_atom_with_velocity_fixed_mask"},{"type":"punctuation","value":"("},{"type":"name","value":"builder_handle"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"RKRConFrameBuilder","target":"RKRConFrameBuilder"},{"type":"punctuation","value":", "},{"type":"name","value":"symbol"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"const"},{"type":"space"},{"type":"link","value":"c_char","target":"c_char"},{"type":"punctuation","value":", "},{"type":"name","value":"x"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"y"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"z"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"fixed_x"},{"type":"punctuation","value":": "},{"type":"link","value":"bool","target":"bool"},{"type":"punctuation","value":", "},{"type":"name","value":"fixed_y"},{"type":"punctuation","value":": "},{"type":"link","value":"bool","target":"bool"},{"type":"punctuation","value":", "},{"type":"name","value":"fixed_z"},{"type":"punctuation","value":": "},{"type":"link","value":"bool","target":"bool"},{"type":"punctuation","value":", "},{"type":"name","value":"atom_id"},{"type":"punctuation","value":": "},{"type":"link","value":"u64","target":"u64"},{"type":"punctuation","value":", "},{"type":"name","value":"mass"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"vx"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"vy"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"vz"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"RKRStatus","target":"RKRStatus"}]

      Adds an atom with velocity data to the frame builder using per-axis fixed flags.
      Returns ``RKR_STATUS_SUCCESS`` on success, or an error code.
      
      **Safety**
      builder_handle and symbol must be valid.

   .. rust:function:: readcon_core::ffi::rkr_frame_builder_build
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"unsafe"},{"type":"space"},{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"rkr_frame_builder_build"},{"type":"punctuation","value":"("},{"type":"name","value":"builder_handle"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"RKRConFrameBuilder","target":"RKRConFrameBuilder"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"operator","value":"*"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"RKRConFrame","target":"RKRConFrame"}]

      Consumes the builder and returns a finalized RKRConFrame handle.
      The builder handle is invalidated after this call.
      The caller OWNS the returned frame and MUST call ``free_rkr_frame``.
      Returns NULL on error.
      
      **Safety**
      builder_handle must be valid. The caller takes ownership of the returned frame.

   .. rust:function:: readcon_core::ffi::rkr_frame_builder_set_energy
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"unsafe"},{"type":"space"},{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"rkr_frame_builder_set_energy"},{"type":"punctuation","value":"("},{"type":"name","value":"builder_handle"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"RKRConFrameBuilder","target":"RKRConFrameBuilder"},{"type":"punctuation","value":", "},{"type":"name","value":"energy"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"RKRStatus","target":"RKRStatus"}]

      Sets the per-frame total energy metadata on an existing frame builder.
      Returns ``RKR_STATUS_SUCCESS`` on success, or an error code.
      
      **Safety**
      builder_handle must be valid.

   .. rust:function:: readcon_core::ffi::rkr_frame_builder_set_frame_index
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"unsafe"},{"type":"space"},{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"rkr_frame_builder_set_frame_index"},{"type":"punctuation","value":"("},{"type":"name","value":"builder_handle"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"RKRConFrameBuilder","target":"RKRConFrameBuilder"},{"type":"punctuation","value":", "},{"type":"name","value":"idx"},{"type":"punctuation","value":": "},{"type":"link","value":"u64","target":"u64"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"RKRStatus","target":"RKRStatus"}]

      Sets the zero-based frame index metadata on an existing frame builder.
      Returns ``RKR_STATUS_SUCCESS`` on success, or an error code.
      
      **Safety**
      builder_handle must be valid.

   .. rust:function:: readcon_core::ffi::rkr_frame_builder_set_metadata_json
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"unsafe"},{"type":"space"},{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"rkr_frame_builder_set_metadata_json"},{"type":"punctuation","value":"("},{"type":"name","value":"builder_handle"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"RKRConFrameBuilder","target":"RKRConFrameBuilder"},{"type":"punctuation","value":", "},{"type":"name","value":"metadata_json"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"const"},{"type":"space"},{"type":"link","value":"c_char","target":"c_char"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"RKRStatus","target":"RKRStatus"}]

      Parses and sets JSON metadata on an existing frame builder.
      Returns ``RKR_STATUS_SUCCESS`` on success, or an error code.
      
      **Safety**
      builder_handle and metadata_json must be valid.

   .. rust:function:: readcon_core::ffi::rkr_frame_builder_set_neb_band
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"unsafe"},{"type":"space"},{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"rkr_frame_builder_set_neb_band"},{"type":"punctuation","value":"("},{"type":"name","value":"builder_handle"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"RKRConFrameBuilder","target":"RKRConFrameBuilder"},{"type":"punctuation","value":", "},{"type":"name","value":"band"},{"type":"punctuation","value":": "},{"type":"link","value":"u64","target":"u64"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"RKRStatus","target":"RKRStatus"}]

      Sets the NEB band index metadata on an existing frame builder.
      Returns ``RKR_STATUS_SUCCESS`` on success, or an error code.
      
      **Safety**
      builder_handle must be valid.

   .. rust:function:: readcon_core::ffi::rkr_frame_builder_set_neb_bead
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"unsafe"},{"type":"space"},{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"rkr_frame_builder_set_neb_bead"},{"type":"punctuation","value":"("},{"type":"name","value":"builder_handle"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"RKRConFrameBuilder","target":"RKRConFrameBuilder"},{"type":"punctuation","value":", "},{"type":"name","value":"bead"},{"type":"punctuation","value":": "},{"type":"link","value":"u64","target":"u64"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"RKRStatus","target":"RKRStatus"}]

      Sets the NEB bead index metadata on an existing frame builder.
      Returns ``RKR_STATUS_SUCCESS`` on success, or an error code.
      
      **Safety**
      builder_handle must be valid.

   .. rust:function:: readcon_core::ffi::rkr_frame_builder_set_scalar_metadata
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"unsafe"},{"type":"space"},{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"rkr_frame_builder_set_scalar_metadata"},{"type":"punctuation","value":"("},{"type":"name","value":"builder_handle"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"RKRConFrameBuilder","target":"RKRConFrameBuilder"},{"type":"punctuation","value":", "},{"type":"name","value":"key"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"const"},{"type":"space"},{"type":"link","value":"c_char","target":"c_char"},{"type":"punctuation","value":", "},{"type":"name","value":"value"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"RKRStatus","target":"RKRStatus"}]

      Sets a numeric metadata key on an existing frame builder.
      Returns ``RKR_STATUS_SUCCESS`` on success, or an error code.
      
      **Safety**
      builder_handle and key must be valid.

   .. rust:function:: readcon_core::ffi::rkr_frame_builder_set_string_metadata
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"unsafe"},{"type":"space"},{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"rkr_frame_builder_set_string_metadata"},{"type":"punctuation","value":"("},{"type":"name","value":"builder_handle"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"RKRConFrameBuilder","target":"RKRConFrameBuilder"},{"type":"punctuation","value":", "},{"type":"name","value":"key"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"const"},{"type":"space"},{"type":"link","value":"c_char","target":"c_char"},{"type":"punctuation","value":", "},{"type":"name","value":"value"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"const"},{"type":"space"},{"type":"link","value":"c_char","target":"c_char"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"RKRStatus","target":"RKRStatus"}]

      Sets a string metadata key on an existing frame builder.
      Returns ``RKR_STATUS_SUCCESS`` on success, or an error code.
      
      **Safety**
      builder_handle, key, and value must be valid.

   .. rust:function:: readcon_core::ffi::rkr_frame_builder_set_time
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"unsafe"},{"type":"space"},{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"rkr_frame_builder_set_time"},{"type":"punctuation","value":"("},{"type":"name","value":"builder_handle"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"RKRConFrameBuilder","target":"RKRConFrameBuilder"},{"type":"punctuation","value":", "},{"type":"name","value":"time"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"RKRStatus","target":"RKRStatus"}]

      Sets the simulation time metadata on an existing frame builder.
      Returns ``RKR_STATUS_SUCCESS`` on success, or an error code.
      
      **Safety**
      builder_handle must be valid.

   .. rust:function:: readcon_core::ffi::rkr_frame_builder_set_timestep
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"unsafe"},{"type":"space"},{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"rkr_frame_builder_set_timestep"},{"type":"punctuation","value":"("},{"type":"name","value":"builder_handle"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"RKRConFrameBuilder","target":"RKRConFrameBuilder"},{"type":"punctuation","value":", "},{"type":"name","value":"dt"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"RKRStatus","target":"RKRStatus"}]

      Sets the timestep metadata on an existing frame builder.
      Returns ``RKR_STATUS_SUCCESS`` on success, or an error code.
      
      **Safety**
      builder_handle must be valid.

   .. rust:function:: readcon_core::ffi::rkr_frame_energy
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"rkr_frame_energy"},{"type":"punctuation","value":"("},{"type":"name","value":"frame_handle"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"const"},{"type":"space"},{"type":"link","value":"RKRConFrame","target":"RKRConFrame"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"f64","target":"f64"}]

      Returns the per-frame energy from metadata, or NaN if absent.

   .. rust:function:: readcon_core::ffi::rkr_frame_frame_index
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"rkr_frame_frame_index"},{"type":"punctuation","value":"("},{"type":"name","value":"frame_handle"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"const"},{"type":"space"},{"type":"link","value":"RKRConFrame","target":"RKRConFrame"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"u64","target":"u64"}]

      Returns the zero-based frame index from metadata, or UINT64_MAX if absent.

   .. rust:function:: readcon_core::ffi::rkr_frame_get_header_line
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"unsafe"},{"type":"space"},{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"rkr_frame_get_header_line"},{"type":"punctuation","value":"("},{"type":"name","value":"frame_handle"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"const"},{"type":"space"},{"type":"link","value":"RKRConFrame","target":"RKRConFrame"},{"type":"punctuation","value":", "},{"type":"name","value":"is_prebox"},{"type":"punctuation","value":": "},{"type":"link","value":"bool","target":"bool"},{"type":"punctuation","value":", "},{"type":"name","value":"line_index"},{"type":"punctuation","value":": "},{"type":"link","value":"usize","target":"usize"},{"type":"punctuation","value":", "},{"type":"name","value":"buffer"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"c_char","target":"c_char"},{"type":"punctuation","value":", "},{"type":"name","value":"buffer_len"},{"type":"punctuation","value":": "},{"type":"link","value":"usize","target":"usize"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"RKRStatus","target":"RKRStatus"}]

      Copies a header string line into a user-provided buffer.
      This is a C style helper... where the user explicitly sets the buffer.
      Returns ``RKR_STATUS_SUCCESS`` on success, or an error code.
      
      **Safety**
      frame_handle must be valid. buffer must be at least buffer_len bytes.

   .. rust:function:: readcon_core::ffi::rkr_frame_get_header_line_cpp
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"unsafe"},{"type":"space"},{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"rkr_frame_get_header_line_cpp"},{"type":"punctuation","value":"("},{"type":"name","value":"frame_handle"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"const"},{"type":"space"},{"type":"link","value":"RKRConFrame","target":"RKRConFrame"},{"type":"punctuation","value":", "},{"type":"name","value":"is_prebox"},{"type":"punctuation","value":": "},{"type":"link","value":"bool","target":"bool"},{"type":"punctuation","value":", "},{"type":"name","value":"line_index"},{"type":"punctuation","value":": "},{"type":"link","value":"usize","target":"usize"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"operator","value":"*"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"c_char","target":"c_char"}]

      Gets a header string line as a newly allocated, null-terminated C string.
      
      The caller OWNS the returned pointer and MUST call ``rkr_free_string`` on it
      to prevent a memory leak. Returns NULL on error or if the index is invalid.
      
      **Safety**
      frame_handle must be valid. The caller takes ownership of the returned string.

   .. rust:function:: readcon_core::ffi::rkr_frame_metadata_json
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"unsafe"},{"type":"space"},{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"rkr_frame_metadata_json"},{"type":"punctuation","value":"("},{"type":"name","value":"frame_handle"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"const"},{"type":"space"},{"type":"link","value":"RKRConFrame","target":"RKRConFrame"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"operator","value":"*"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"c_char","target":"c_char"}]

      Returns the JSON metadata line from a parsed frame as a heap-allocated
      null-terminated C string. The caller MUST free with ``rkr_free_string``.
      Returns NULL on error.
      
      **Safety**
      frame_handle must be valid. The caller takes ownership of the returned string.

   .. rust:function:: readcon_core::ffi::rkr_frame_neb_band
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"rkr_frame_neb_band"},{"type":"punctuation","value":"("},{"type":"name","value":"frame_handle"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"const"},{"type":"space"},{"type":"link","value":"RKRConFrame","target":"RKRConFrame"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"u64","target":"u64"}]

      Returns the NEB band index from metadata, or UINT64_MAX if absent.

   .. rust:function:: readcon_core::ffi::rkr_frame_neb_bead
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"rkr_frame_neb_bead"},{"type":"punctuation","value":"("},{"type":"name","value":"frame_handle"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"const"},{"type":"space"},{"type":"link","value":"RKRConFrame","target":"RKRConFrame"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"u64","target":"u64"}]

      Returns the NEB bead index from metadata, or UINT64_MAX if absent.

   .. rust:function:: readcon_core::ffi::rkr_frame_new
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"unsafe"},{"type":"space"},{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"rkr_frame_new"},{"type":"punctuation","value":"("},{"type":"name","value":"cell"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"const"},{"type":"space"},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"angles"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"const"},{"type":"space"},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":", "},{"type":"name","value":"prebox0"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"const"},{"type":"space"},{"type":"link","value":"c_char","target":"c_char"},{"type":"punctuation","value":", "},{"type":"name","value":"prebox1"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"const"},{"type":"space"},{"type":"link","value":"c_char","target":"c_char"},{"type":"punctuation","value":", "},{"type":"name","value":"postbox0"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"const"},{"type":"space"},{"type":"link","value":"c_char","target":"c_char"},{"type":"punctuation","value":", "},{"type":"name","value":"postbox1"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"const"},{"type":"space"},{"type":"link","value":"c_char","target":"c_char"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"operator","value":"*"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"RKRConFrameBuilder","target":"RKRConFrameBuilder"}]

      Creates a new frame builder with the given cell dimensions, angles, and header lines.
      The caller OWNS the returned pointer and MUST call ``free_rkr_frame_builder`` or
      ``rkr_frame_builder_build``.
      Returns NULL on error.
      
      **Safety**
      cell and angles must point to 3 doubles. prebox0, prebox1, postbox0, postbox1 must be valid.
      The caller takes ownership of the returned builder.

   .. rust:function:: readcon_core::ffi::rkr_frame_potential_type
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"unsafe"},{"type":"space"},{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"rkr_frame_potential_type"},{"type":"punctuation","value":"("},{"type":"name","value":"frame_handle"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"const"},{"type":"space"},{"type":"link","value":"RKRConFrame","target":"RKRConFrame"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"operator","value":"*"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"c_char","target":"c_char"}]

      Returns the potential type string from metadata as a heap-allocated
      null-terminated C string. The caller MUST free with ``rkr_free_string``.
      Returns NULL if absent or on error.
      
      **Safety**
      frame_handle must be valid. The caller takes ownership of the returned string.

   .. rust:function:: readcon_core::ffi::rkr_frame_spec_version
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"rkr_frame_spec_version"},{"type":"punctuation","value":"("},{"type":"name","value":"frame_handle"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"const"},{"type":"space"},{"type":"link","value":"RKRConFrame","target":"RKRConFrame"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"u32","target":"u32"}]

      Returns the spec version stored in a parsed frame's header.
      Returns 0 on error (null handle).

   .. rust:function:: readcon_core::ffi::rkr_frame_time
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"rkr_frame_time"},{"type":"punctuation","value":"("},{"type":"name","value":"frame_handle"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"const"},{"type":"space"},{"type":"link","value":"RKRConFrame","target":"RKRConFrame"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"f64","target":"f64"}]

      Returns the simulation time from metadata, or NaN if absent.

   .. rust:function:: readcon_core::ffi::rkr_frame_timestep
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"rkr_frame_timestep"},{"type":"punctuation","value":"("},{"type":"name","value":"frame_handle"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"const"},{"type":"space"},{"type":"link","value":"RKRConFrame","target":"RKRConFrame"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"f64","target":"f64"}]

      Returns the integration timestep from metadata, or NaN if absent.

   .. rust:function:: readcon_core::ffi::rkr_frame_to_c_frame
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"unsafe"},{"type":"space"},{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"rkr_frame_to_c_frame"},{"type":"punctuation","value":"("},{"type":"name","value":"frame_handle"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"const"},{"type":"space"},{"type":"link","value":"RKRConFrame","target":"RKRConFrame"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"operator","value":"*"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"CFrame","target":"CFrame"}]

      Extracts the core atomic data into a transparent ``CFrame`` struct.
      The caller OWNS the returned pointer and MUST call ``free_c_frame`` on it.
      
      **Safety**
      frame_handle must be valid. The caller takes ownership of the returned CFrame.

   .. rust:function:: readcon_core::ffi::rkr_free_string
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"unsafe"},{"type":"space"},{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"rkr_free_string"},{"type":"punctuation","value":"("},{"type":"name","value":"s"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"c_char","target":"c_char"},{"type":"punctuation","value":")"}]

      Frees a C string that was allocated by Rust (e.g., from ``rkr_frame_get_header_line``).
      
      **Safety**
      s must be valid or null.

   .. rust:function:: readcon_core::ffi::rkr_library_version
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"rkr_library_version"},{"type":"punctuation","value":"("},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"operator","value":"*"},{"type":"keyword","value":"const"},{"type":"space"},{"type":"link","value":"c_char","target":"c_char"}]

      Returns a pointer to a static, null-terminated library version string.
      The returned pointer is valid for the lifetime of the process. Do NOT free it.

   .. rust:function:: readcon_core::ffi::rkr_read_all_frames
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"unsafe"},{"type":"space"},{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"rkr_read_all_frames"},{"type":"punctuation","value":"("},{"type":"name","value":"filename_c"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"const"},{"type":"space"},{"type":"link","value":"c_char","target":"c_char"},{"type":"punctuation","value":", "},{"type":"name","value":"num_frames"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"usize","target":"usize"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"operator","value":"*"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"operator","value":"*"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"RKRConFrame","target":"RKRConFrame"}]

      Reads all frames from a .con file using mmap.
      Returns an array of frame handles and sets ``num_frames`` to the count.
      The caller OWNS both the array and each frame handle.
      Free frames with ``free_rkr_frame`` and the array with ``free_rkr_frame_array``.
      Returns NULL on error.
      
      **Safety**
      filename_c and num_frames must be valid. The caller takes ownership of the returned handles and array.

   .. rust:function:: readcon_core::ffi::rkr_read_first_frame
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"unsafe"},{"type":"space"},{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"rkr_read_first_frame"},{"type":"punctuation","value":"("},{"type":"name","value":"filename_c"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"const"},{"type":"space"},{"type":"link","value":"c_char","target":"c_char"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"operator","value":"*"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"RKRConFrame","target":"RKRConFrame"}]

      Reads the first frame from a .con file.
      Uses ``read_to_string`` for small files (< 64 KiB) and mmap for larger ones.
      Stops after the first frame rather than parsing the entire file.
      The caller OWNS the returned handle and MUST call ``free_rkr_frame``.
      Returns NULL on error.
      
      **Safety**
      filename_c must be valid. The caller takes ownership of the returned frame.

   .. rust:function:: readcon_core::ffi::rkr_status_message
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"rkr_status_message"},{"type":"punctuation","value":"("},{"type":"name","value":"status"},{"type":"punctuation","value":": "},{"type":"link","value":"RKRStatus","target":"RKRStatus"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"operator","value":"*"},{"type":"keyword","value":"const"},{"type":"space"},{"type":"link","value":"c_char","target":"c_char"}]

      Returns a stable, static message for a status code.
      The returned pointer is valid for the lifetime of the process. Do NOT free it.

   .. rust:function:: readcon_core::ffi::rkr_writer_extend
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"unsafe"},{"type":"space"},{"type":"keyword","value":"extern"},{"type":"space"},{"type":"literal","value":"C"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"rkr_writer_extend"},{"type":"punctuation","value":"("},{"type":"name","value":"writer_handle"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"RKRConFrameWriter","target":"RKRConFrameWriter"},{"type":"punctuation","value":", "},{"type":"name","value":"frame_handles"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"const"},{"type":"space"},{"type":"operator","value":"*"},{"type":"keyword","value":"const"},{"type":"space"},{"type":"link","value":"RKRConFrame","target":"RKRConFrame"},{"type":"punctuation","value":", "},{"type":"name","value":"num_frames"},{"type":"punctuation","value":": "},{"type":"link","value":"usize","target":"usize"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"RKRStatus","target":"RKRStatus"}]

      Writes multiple frames from an array of handles to the file managed by the writer.
      Returns ``RKR_STATUS_SUCCESS`` on success, or an error code.
      
      **Safety**
      writer_handle and frame_handles must be valid.

   .. rubric:: Enums


   .. rust:enum:: readcon_core::ffi::RKRStatus
      :index: 1
      :vis: pub
      :layout: [{"type":"keyword","value":"enum"},{"type":"space"},{"type":"name","value":"RKRStatus"}]

      Error codes for RKR functions.

      .. rust:struct:: readcon_core::ffi::RKRStatus::RKR_STATUS_SUCCESS
         :index: 2
         :vis: pub
         :toc: RKR_STATUS_SUCCESS
         :layout: [{"type":"name","value":"RKR_STATUS_SUCCESS"}]

         Function completed successfully.

      .. rust:struct:: readcon_core::ffi::RKRStatus::RKR_STATUS_NULL_POINTER
         :index: 2
         :vis: pub
         :toc: RKR_STATUS_NULL_POINTER
         :layout: [{"type":"name","value":"RKR_STATUS_NULL_POINTER"}]

         A null pointer was passed for a required argument.

      .. rust:struct:: readcon_core::ffi::RKRStatus::RKR_STATUS_INVALID_UTF8
         :index: 2
         :vis: pub
         :toc: RKR_STATUS_INVALID_UTF8
         :layout: [{"type":"name","value":"RKR_STATUS_INVALID_UTF8"}]

         An input string was not valid UTF-8.

      .. rust:struct:: readcon_core::ffi::RKRStatus::RKR_STATUS_INVALID_JSON
         :index: 2
         :vis: pub
         :toc: RKR_STATUS_INVALID_JSON
         :layout: [{"type":"name","value":"RKR_STATUS_INVALID_JSON"}]

         JSON parsing or serialization failed.

      .. rust:struct:: readcon_core::ffi::RKRStatus::RKR_STATUS_IO_ERROR
         :index: 2
         :vis: pub
         :toc: RKR_STATUS_IO_ERROR
         :layout: [{"type":"name","value":"RKR_STATUS_IO_ERROR"}]

         File I/O error.

      .. rust:struct:: readcon_core::ffi::RKRStatus::RKR_STATUS_INDEX_OUT_OF_BOUNDS
         :index: 2
         :vis: pub
         :toc: RKR_STATUS_INDEX_OUT_OF_BOUNDS
         :layout: [{"type":"name","value":"RKR_STATUS_INDEX_OUT_OF_BOUNDS"}]

         Index out of bounds.

      .. rust:struct:: readcon_core::ffi::RKRStatus::RKR_STATUS_BUFFER_TOO_SMALL
         :index: 2
         :vis: pub
         :toc: RKR_STATUS_BUFFER_TOO_SMALL
         :layout: [{"type":"name","value":"RKR_STATUS_BUFFER_TOO_SMALL"}]

         The destination buffer cannot hold a null-terminated string.

      .. rust:struct:: readcon_core::ffi::RKRStatus::RKR_STATUS_INTERNAL_ERROR
         :index: 2
         :vis: pub
         :toc: RKR_STATUS_INTERNAL_ERROR
         :layout: [{"type":"name","value":"RKR_STATUS_INTERNAL_ERROR"}]

         An internal logic error or unhandled state.

   .. rubric:: Structs and Unions


   .. rust:struct:: readcon_core::ffi::CAtom
      :index: 1
      :vis: pub
      :toc: struct CAtom
      :layout: [{"type":"keyword","value":"struct"},{"type":"space"},{"type":"name","value":"CAtom"}]


      .. rust:variable:: readcon_core::ffi::CAtom::atomic_number
         :index: 2
         :vis: pub
         :toc: atomic_number
         :layout: [{"type":"name","value":"atomic_number"},{"type":"punctuation","value":": "},{"type":"link","value":"u64","target":"u64"}]


      .. rust:variable:: readcon_core::ffi::CAtom::x
         :index: 2
         :vis: pub
         :toc: x
         :layout: [{"type":"name","value":"x"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"}]


      .. rust:variable:: readcon_core::ffi::CAtom::y
         :index: 2
         :vis: pub
         :toc: y
         :layout: [{"type":"name","value":"y"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"}]


      .. rust:variable:: readcon_core::ffi::CAtom::z
         :index: 2
         :vis: pub
         :toc: z
         :layout: [{"type":"name","value":"z"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"}]


      .. rust:variable:: readcon_core::ffi::CAtom::atom_id
         :index: 2
         :vis: pub
         :toc: atom_id
         :layout: [{"type":"name","value":"atom_id"},{"type":"punctuation","value":": "},{"type":"link","value":"u64","target":"u64"}]


      .. rust:variable:: readcon_core::ffi::CAtom::mass
         :index: 2
         :vis: pub
         :toc: mass
         :layout: [{"type":"name","value":"mass"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"}]


      .. rust:variable:: readcon_core::ffi::CAtom::is_fixed
         :index: 2
         :vis: pub
         :toc: is_fixed
         :layout: [{"type":"name","value":"is_fixed"},{"type":"punctuation","value":": "},{"type":"link","value":"bool","target":"bool"}]


      .. rust:variable:: readcon_core::ffi::CAtom::fixed_x
         :index: 2
         :vis: pub
         :toc: fixed_x
         :layout: [{"type":"name","value":"fixed_x"},{"type":"punctuation","value":": "},{"type":"link","value":"bool","target":"bool"}]


      .. rust:variable:: readcon_core::ffi::CAtom::fixed_y
         :index: 2
         :vis: pub
         :toc: fixed_y
         :layout: [{"type":"name","value":"fixed_y"},{"type":"punctuation","value":": "},{"type":"link","value":"bool","target":"bool"}]


      .. rust:variable:: readcon_core::ffi::CAtom::fixed_z
         :index: 2
         :vis: pub
         :toc: fixed_z
         :layout: [{"type":"name","value":"fixed_z"},{"type":"punctuation","value":": "},{"type":"link","value":"bool","target":"bool"}]


      .. rust:variable:: readcon_core::ffi::CAtom::vx
         :index: 2
         :vis: pub
         :toc: vx
         :layout: [{"type":"name","value":"vx"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"}]


      .. rust:variable:: readcon_core::ffi::CAtom::vy
         :index: 2
         :vis: pub
         :toc: vy
         :layout: [{"type":"name","value":"vy"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"}]


      .. rust:variable:: readcon_core::ffi::CAtom::vz
         :index: 2
         :vis: pub
         :toc: vz
         :layout: [{"type":"name","value":"vz"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"}]


      .. rust:variable:: readcon_core::ffi::CAtom::has_velocity
         :index: 2
         :vis: pub
         :toc: has_velocity
         :layout: [{"type":"name","value":"has_velocity"},{"type":"punctuation","value":": "},{"type":"link","value":"bool","target":"bool"}]


      .. rust:variable:: readcon_core::ffi::CAtom::fx
         :index: 2
         :vis: pub
         :toc: fx
         :layout: [{"type":"name","value":"fx"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"}]


      .. rust:variable:: readcon_core::ffi::CAtom::fy
         :index: 2
         :vis: pub
         :toc: fy
         :layout: [{"type":"name","value":"fy"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"}]


      .. rust:variable:: readcon_core::ffi::CAtom::fz
         :index: 2
         :vis: pub
         :toc: fz
         :layout: [{"type":"name","value":"fz"},{"type":"punctuation","value":": "},{"type":"link","value":"f64","target":"f64"}]


      .. rust:variable:: readcon_core::ffi::CAtom::has_forces
         :index: 2
         :vis: pub
         :toc: has_forces
         :layout: [{"type":"name","value":"has_forces"},{"type":"punctuation","value":": "},{"type":"link","value":"bool","target":"bool"}]


   .. rust:struct:: readcon_core::ffi::CConFrameIterator
      :index: 1
      :vis: pub
      :toc: struct CConFrameIterator
      :layout: [{"type":"keyword","value":"struct"},{"type":"space"},{"type":"name","value":"CConFrameIterator"}]


   .. rust:struct:: readcon_core::ffi::CFrame
      :index: 1
      :vis: pub
      :toc: struct CFrame
      :layout: [{"type":"keyword","value":"struct"},{"type":"space"},{"type":"name","value":"CFrame"}]

      A transparent, "lossy" C-struct containing only the core atomic data.
      This can be extracted from an ``RKRConFrame`` handle for direct data access.
      The caller is responsible for freeing the ``atoms`` array using ``free_c_frame``.

      .. rust:variable:: readcon_core::ffi::CFrame::atoms
         :index: 2
         :vis: pub
         :toc: atoms
         :layout: [{"type":"name","value":"atoms"},{"type":"punctuation","value":": "},{"type":"operator","value":"*"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"link","value":"CAtom","target":"CAtom"}]


      .. rust:variable:: readcon_core::ffi::CFrame::num_atoms
         :index: 2
         :vis: pub
         :toc: num_atoms
         :layout: [{"type":"name","value":"num_atoms"},{"type":"punctuation","value":": "},{"type":"link","value":"usize","target":"usize"}]


      .. rust:variable:: readcon_core::ffi::CFrame::cell
         :index: 2
         :vis: pub
         :toc: cell
         :layout: [{"type":"name","value":"cell"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"["},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":"; "},{"type":"literal","value":"3"},{"type":"punctuation","value":"]"}]


      .. rust:variable:: readcon_core::ffi::CFrame::angles
         :index: 2
         :vis: pub
         :toc: angles
         :layout: [{"type":"name","value":"angles"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"["},{"type":"link","value":"f64","target":"f64"},{"type":"punctuation","value":"; "},{"type":"literal","value":"3"},{"type":"punctuation","value":"]"}]


      .. rust:variable:: readcon_core::ffi::CFrame::has_velocities
         :index: 2
         :vis: pub
         :toc: has_velocities
         :layout: [{"type":"name","value":"has_velocities"},{"type":"punctuation","value":": "},{"type":"link","value":"bool","target":"bool"}]


      .. rust:variable:: readcon_core::ffi::CFrame::has_forces
         :index: 2
         :vis: pub
         :toc: has_forces
         :layout: [{"type":"name","value":"has_forces"},{"type":"punctuation","value":": "},{"type":"link","value":"bool","target":"bool"}]


   .. rust:struct:: readcon_core::ffi::RKRConFrame
      :index: 1
      :vis: pub
      :toc: struct RKRConFrame
      :layout: [{"type":"keyword","value":"struct"},{"type":"space"},{"type":"name","value":"RKRConFrame"}]

      An opaque handle to a full, lossless Rust ``ConFrame`` object.
      The C/C++ side needs to treat this as a void pointer

   .. rust:struct:: readcon_core::ffi::RKRConFrameBuilder
      :index: 1
      :vis: pub
      :toc: struct RKRConFrameBuilder
      :layout: [{"type":"keyword","value":"struct"},{"type":"space"},{"type":"name","value":"RKRConFrameBuilder"}]

      An opaque handle to a Rust ``ConFrameBuilder`` object.

   .. rust:struct:: readcon_core::ffi::RKRConFrameWriter
      :index: 1
      :vis: pub
      :toc: struct RKRConFrameWriter
      :layout: [{"type":"keyword","value":"struct"},{"type":"space"},{"type":"name","value":"RKRConFrameWriter"}]

      An opaque handle to a Rust ``ConFrameWriter`` object.
      The C/C++ side needs to treat this as a void pointer
