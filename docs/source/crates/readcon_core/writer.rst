==============
``mod writer``
==============


.. rust:module:: readcon_core::writer
   :index: 0
   :vis: pub


   .. rust:use:: readcon_core::writer
      :used_name: self


   .. rust:use:: readcon_core
      :used_name: crate


   .. rust:use:: readcon_core::types::ConFrame
      :used_name: ConFrame


   .. rust:use:: readcon_core::types::encode_fixed_bitmask
      :used_name: encode_fixed_bitmask


   .. rust:use:: serde_json::json
      :used_name: json


   .. rust:use:: std::fs::File
      :used_name: File


   .. rust:use:: std::io::BufWriter
      :used_name: BufWriter


   .. rust:use:: std::io::Write
      :used_name: Write


   .. rust:use:: std::io
      :used_name: io


   .. rust:use:: std::path::Path
      :used_name: Path


   .. rubric:: Structs and Unions


   .. rust:struct:: readcon_core::writer::ConFrameWriter
      :index: 1
      :vis: pub
      :toc: struct ConFrameWriter
      :layout: [{"type":"keyword","value":"struct"},{"type":"space"},{"type":"name","value":"ConFrameWriter"},{"type":"punctuation","value":"<"},{"type":"name","value":"W"},{"type":"punctuation","value":": "},{"type":"link","value":"Write","target":"Write"},{"type":"punctuation","value":">"}]

      A writer that can serialize and write ``ConFrame`` objects to any output stream.
      
      This struct encapsulates a writer (like a file) and provides a high-level API
      for writing simulation frames in the ``.con`` format.
      
      **Example**
      .. code-block:: no_run

         **use std::fs::File;**
         **use readcon_core::types::ConFrame;**
         **use readcon_core::writer::ConFrameWriter;**
         **let frames: Vec<ConFrame> = Vec::new();**
         let mut writer = ConFrameWriter::from_path("output.con").unwrap();
         writer.extend(frames.iter()).unwrap();


      .. rubric:: Implementations


      .. rust:impl:: readcon_core::writer::ConFrameWriter
         :index: -1
         :vis: pub
         :layout: [{"type":"keyword","value":"impl"},{"type":"punctuation","value":"<"},{"type":"name","value":"W"},{"type":"punctuation","value":": "},{"type":"link","value":"Write","target":"Write"},{"type":"punctuation","value":">"},{"type":"space"},{"type":"link","value":"ConFrameWriter","target":"ConFrameWriter"},{"type":"punctuation","value":"<"},{"type":"link","value":"W","target":"W"},{"type":"punctuation","value":">"}]
         :toc: impl ConFrameWriter


         .. rubric:: Functions


         .. rust:function:: readcon_core::writer::ConFrameWriter::extend
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"extend"},{"type":"punctuation","value":"<"},{"type":"lifetime","value":"'a"},{"type":"punctuation","value":">"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"keyword","value":"self"},{"type":"punctuation","value":", "},{"type":"name","value":"frames"},{"type":"punctuation","value":": "},{"type":"keyword","value":"impl"},{"type":"space"},{"type":"link","value":"Iterator","target":"Iterator"},{"type":"punctuation","value":"<"},{"type":"name","value":"Item"},{"type":"punctuation","value":" = "},{"type":"punctuation","value":"&"},{"type":"lifetime","value":"'a"},{"type":"space"},{"type":"link","value":"ConFrame","target":"ConFrame"},{"type":"punctuation","value":">"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"io","target":"io"},{"type":"punctuation","value":"::"},{"type":"name","value":"Result"},{"type":"punctuation","value":"<"},{"type":"punctuation","value":"("},{"type":"punctuation","value":")"},{"type":"punctuation","value":">"}]

            Writes all frames from an iterator to the output stream.
            
            This is the most convenient way to write a multi-frame file.

         .. rust:function:: readcon_core::writer::ConFrameWriter::new
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"new"},{"type":"punctuation","value":"("},{"type":"name","value":"writer"},{"type":"punctuation","value":": "},{"type":"link","value":"W","target":"W"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"Self","target":"Self"}]

            Creates a new ``ConFrameWriter`` that wraps a given writer.
            
            **Arguments**
            
            * ``writer`` - Any type that implements ``std::io::Write``, e.g., a ``File``.

         .. rust:function:: readcon_core::writer::ConFrameWriter::with_precision
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"with_precision"},{"type":"punctuation","value":"("},{"type":"name","value":"writer"},{"type":"punctuation","value":": "},{"type":"link","value":"W","target":"W"},{"type":"punctuation","value":", "},{"type":"name","value":"precision"},{"type":"punctuation","value":": "},{"type":"link","value":"usize","target":"usize"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"Self","target":"Self"}]

            Creates a new ``ConFrameWriter`` with a custom floating-point precision.
            
            **Arguments**
            
            * ``writer`` - Any type that implements ``std::io::Write``.
            * ``precision`` - Number of decimal places for floating-point output.

         .. rust:function:: readcon_core::writer::ConFrameWriter::write_frame
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"write_frame"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"keyword","value":"self"},{"type":"punctuation","value":", "},{"type":"name","value":"frame"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"&"},{"type":"link","value":"ConFrame","target":"ConFrame"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"io","target":"io"},{"type":"punctuation","value":"::"},{"type":"name","value":"Result"},{"type":"punctuation","value":"<"},{"type":"punctuation","value":"("},{"type":"punctuation","value":")"},{"type":"punctuation","value":">"}]

            Writes a single ``ConFrame`` to the output stream.

      .. rust:impl:: readcon_core::writer::ConFrameWriter
         :index: -1
         :vis: pub
         :layout: [{"type":"keyword","value":"impl"},{"type":"space"},{"type":"link","value":"ConFrameWriter","target":"ConFrameWriter"},{"type":"punctuation","value":"<"},{"type":"link","value":"File","target":"File"},{"type":"punctuation","value":">"}]
         :toc: impl ConFrameWriter


         .. rubric:: Functions


         .. rust:function:: readcon_core::writer::ConFrameWriter::from_path
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"from_path"},{"type":"punctuation","value":"<"},{"type":"name","value":"P"},{"type":"punctuation","value":": "},{"type":"link","value":"AsRef","target":"AsRef"},{"type":"punctuation","value":"<"},{"type":"link","value":"Path","target":"Path"},{"type":"punctuation","value":">"},{"type":"punctuation","value":">"},{"type":"punctuation","value":"("},{"type":"name","value":"path"},{"type":"punctuation","value":": "},{"type":"link","value":"P","target":"P"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"io","target":"io"},{"type":"punctuation","value":"::"},{"type":"name","value":"Result"},{"type":"punctuation","value":"<"},{"type":"link","value":"Self","target":"Self"},{"type":"punctuation","value":">"}]

            Creates a new ``ConFrameWriter`` that writes to a file at the given path.
            
            This is a convenience function that creates the file and wraps it.

         .. rust:function:: readcon_core::writer::ConFrameWriter::from_path_with_precision
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"from_path_with_precision"},{"type":"punctuation","value":"<"},{"type":"name","value":"P"},{"type":"punctuation","value":": "},{"type":"link","value":"AsRef","target":"AsRef"},{"type":"punctuation","value":"<"},{"type":"link","value":"Path","target":"Path"},{"type":"punctuation","value":">"},{"type":"punctuation","value":">"},{"type":"punctuation","value":"("},{"type":"name","value":"path"},{"type":"punctuation","value":": "},{"type":"link","value":"P","target":"P"},{"type":"punctuation","value":", "},{"type":"name","value":"precision"},{"type":"punctuation","value":": "},{"type":"link","value":"usize","target":"usize"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"io","target":"io"},{"type":"punctuation","value":"::"},{"type":"name","value":"Result"},{"type":"punctuation","value":"<"},{"type":"link","value":"Self","target":"Self"},{"type":"punctuation","value":">"}]

            Creates a new ``ConFrameWriter`` that writes to a file with a custom precision.

      .. rust:impl:: readcon_core::writer::ConFrameWriter
         :index: -1
         :vis: pub
         :layout: [{"type":"keyword","value":"impl"},{"type":"space"},{"type":"link","value":"ConFrameWriter","target":"ConFrameWriter"},{"type":"punctuation","value":"<"},{"type":"link","value":"flate2","target":"flate2"},{"type":"punctuation","value":"::"},{"type":"name","value":"write"},{"type":"punctuation","value":"::"},{"type":"name","value":"GzEncoder"},{"type":"punctuation","value":"<"},{"type":"link","value":"File","target":"File"},{"type":"punctuation","value":">"},{"type":"punctuation","value":">"}]
         :toc: impl ConFrameWriter


         .. rubric:: Functions


         .. rust:function:: readcon_core::writer::ConFrameWriter::from_path_gzip
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"from_path_gzip"},{"type":"punctuation","value":"<"},{"type":"name","value":"P"},{"type":"punctuation","value":": "},{"type":"link","value":"AsRef","target":"AsRef"},{"type":"punctuation","value":"<"},{"type":"link","value":"Path","target":"Path"},{"type":"punctuation","value":">"},{"type":"punctuation","value":">"},{"type":"punctuation","value":"("},{"type":"name","value":"path"},{"type":"punctuation","value":": "},{"type":"link","value":"P","target":"P"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"io","target":"io"},{"type":"punctuation","value":"::"},{"type":"name","value":"Result"},{"type":"punctuation","value":"<"},{"type":"link","value":"Self","target":"Self"},{"type":"punctuation","value":">"}]

            Creates a gzip-compressed writer for the given path.

         .. rust:function:: readcon_core::writer::ConFrameWriter::from_path_gzip_with_precision
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"from_path_gzip_with_precision"},{"type":"punctuation","value":"<"},{"type":"name","value":"P"},{"type":"punctuation","value":": "},{"type":"link","value":"AsRef","target":"AsRef"},{"type":"punctuation","value":"<"},{"type":"link","value":"Path","target":"Path"},{"type":"punctuation","value":">"},{"type":"punctuation","value":">"},{"type":"punctuation","value":"("},{"type":"name","value":"path"},{"type":"punctuation","value":": "},{"type":"link","value":"P","target":"P"},{"type":"punctuation","value":", "},{"type":"name","value":"precision"},{"type":"punctuation","value":": "},{"type":"link","value":"usize","target":"usize"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"io","target":"io"},{"type":"punctuation","value":"::"},{"type":"name","value":"Result"},{"type":"punctuation","value":"<"},{"type":"link","value":"Self","target":"Self"},{"type":"punctuation","value":">"}]

            Creates a gzip-compressed writer with custom precision.
