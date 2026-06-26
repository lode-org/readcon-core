===================
``mod compression``
===================


.. rust:module:: readcon_core::compression
   :index: 0
   :vis: pub


   .. rust:use:: readcon_core::compression
      :used_name: self


   .. rust:use:: readcon_core
      :used_name: crate


   .. rust:use:: std::io::Read
      :used_name: Read


   .. rust:use:: std::io
      :used_name: io


   .. rust:use:: std::path::Path
      :used_name: Path


   .. rubric:: Functions


   .. rust:function:: readcon_core::compression::detect_compression
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"detect_compression"},{"type":"punctuation","value":"("},{"type":"name","value":"bytes"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"&"},{"type":"punctuation","value":"["},{"type":"link","value":"u8","target":"u8"},{"type":"punctuation","value":"]"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"Compression","target":"Compression"}]

      Detect compression format from the first bytes of a file.
      
      - ``1f 8b`` = gzip
      - Otherwise = uncompressed

   .. rust:function:: readcon_core::compression::detect_compression_from_extension
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"detect_compression_from_extension"},{"type":"punctuation","value":"("},{"type":"name","value":"path"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"&"},{"type":"link","value":"Path","target":"Path"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"Compression","target":"Compression"}]

      Detect compression format from a file extension.
      
      Returns ``Compression::Gzip`` for ``.gz`` extension, ``Compression::None`` otherwise.

   .. rust:function:: readcon_core::compression::gzip_writer
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"gzip_writer"},{"type":"punctuation","value":"("},{"type":"name","value":"path"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"&"},{"type":"link","value":"Path","target":"Path"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"io","target":"io"},{"type":"punctuation","value":"::"},{"type":"name","value":"Result"},{"type":"punctuation","value":"<"},{"type":"link","value":"flate2","target":"flate2"},{"type":"punctuation","value":"::"},{"type":"name","value":"write"},{"type":"punctuation","value":"::"},{"type":"name","value":"GzEncoder"},{"type":"punctuation","value":"<"},{"type":"link","value":"std","target":"std"},{"type":"punctuation","value":"::"},{"type":"name","value":"fs"},{"type":"punctuation","value":"::"},{"type":"name","value":"File"},{"type":"punctuation","value":">"},{"type":"punctuation","value":">"}]

      Creates a gzip-compressed writer wrapping a file at the given path.

   .. rust:function:: readcon_core::compression::read_file_contents
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"read_file_contents"},{"type":"punctuation","value":"("},{"type":"name","value":"path"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"&"},{"type":"link","value":"Path","target":"Path"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"Result","target":"Result"},{"type":"punctuation","value":"<"},{"type":"link","value":"FileContents","target":"FileContents"},{"type":"punctuation","value":", "},{"type":"link","value":"Box","target":"Box"},{"type":"punctuation","value":"<"},{"type":"keyword","value":"dyn"},{"type":"space"},{"type":"link","value":"std","target":"std"},{"type":"punctuation","value":"::"},{"type":"name","value":"error"},{"type":"punctuation","value":"::"},{"type":"name","value":"Error"},{"type":"punctuation","value":">"},{"type":"punctuation","value":">"}]

      Reads file contents, decompressing if needed.
      
      Detection strategy:
      1. Read first 2 bytes to check magic bytes.
      2. If gzip: decompress entire file to a String.
      3. If uncompressed and < 64 KiB: ``read_to_string``.
      4. If uncompressed and >= 64 KiB: memory-mapped I/O.

   .. rubric:: Enums


   .. rust:enum:: readcon_core::compression::Compression
      :index: 1
      :vis: pub
      :layout: [{"type":"keyword","value":"enum"},{"type":"space"},{"type":"name","value":"Compression"}]

      Detected compression format based on magic bytes.

      .. rust:struct:: readcon_core::compression::Compression::None
         :index: 2
         :vis: pub
         :toc: None
         :layout: [{"type":"name","value":"None"}]


      .. rust:struct:: readcon_core::compression::Compression::Gzip
         :index: 2
         :vis: pub
         :toc: Gzip
         :layout: [{"type":"name","value":"Gzip"}]


   .. rust:enum:: readcon_core::compression::FileContents
      :index: 1
      :vis: pub
      :layout: [{"type":"keyword","value":"enum"},{"type":"space"},{"type":"name","value":"FileContents"}]

      Holds file contents either as an owned String or a memory-mapped region.

      .. rust:struct:: readcon_core::compression::FileContents::Owned
         :index: 2
         :vis: pub
         :toc: Owned
         :layout: [{"type":"name","value":"Owned"},{"type":"punctuation","value":"("},{"type":"link","value":"String","target":"String"},{"type":"punctuation","value":")"}]


      .. rust:struct:: readcon_core::compression::FileContents::Mapped
         :index: 2
         :vis: pub
         :toc: Mapped
         :layout: [{"type":"name","value":"Mapped"},{"type":"punctuation","value":"("},{"type":"link","value":"memmap2","target":"memmap2"},{"type":"punctuation","value":"::"},{"type":"name","value":"Mmap"},{"type":"punctuation","value":")"}]


      .. rubric:: Implementations


      .. rust:impl:: readcon_core::compression::FileContents
         :index: -1
         :vis: pub
         :layout: [{"type":"keyword","value":"impl"},{"type":"space"},{"type":"link","value":"FileContents","target":"FileContents"}]
         :toc: impl FileContents


         .. rubric:: Functions


         .. rust:function:: readcon_core::compression::FileContents::as_str
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"as_str"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"self"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"Result","target":"Result"},{"type":"punctuation","value":"<"},{"type":"punctuation","value":"&"},{"type":"link","value":"str","target":"str"},{"type":"punctuation","value":", "},{"type":"link","value":"std","target":"std"},{"type":"punctuation","value":"::"},{"type":"name","value":"str"},{"type":"punctuation","value":"::"},{"type":"name","value":"Utf8Error"},{"type":"punctuation","value":">"}]

