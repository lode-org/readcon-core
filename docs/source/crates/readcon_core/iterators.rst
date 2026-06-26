=================
``mod iterators``
=================


.. rust:module:: readcon_core::iterators
   :index: 0
   :vis: pub


   .. rust:use:: readcon_core::iterators
      :used_name: self


   .. rust:use:: readcon_core
      :used_name: crate


   .. rust:use:: readcon_core::parser::parse_declared_sections
      :used_name: parse_declared_sections


   .. rust:use:: readcon_core::parser::parse_single_frame
      :used_name: parse_single_frame


   .. rust:use:: readcon_core::error
      :used_name: error


   .. rust:use:: readcon_core::types
      :used_name: types


   .. rust:use:: std::iter::Peekable
      :used_name: Peekable


   .. rust:use:: std::path::Path
      :used_name: Path


   .. rubric:: Functions


   .. rust:function:: readcon_core::iterators::parse_frames_parallel
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"parse_frames_parallel"},{"type":"punctuation","value":"("},{"type":"name","value":"file_contents"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"&"},{"type":"link","value":"str","target":"str"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"Vec","target":"Vec"},{"type":"punctuation","value":"<"},{"type":"link","value":"Result","target":"Result"},{"type":"punctuation","value":"<"},{"type":"link","value":"types","target":"types"},{"type":"punctuation","value":"::"},{"type":"name","value":"ConFrame"},{"type":"punctuation","value":", "},{"type":"link","value":"error","target":"error"},{"type":"punctuation","value":"::"},{"type":"name","value":"ParseError"},{"type":"punctuation","value":">"},{"type":"punctuation","value":">"}]

      Parses frames in parallel using rayon, splitting on frame boundaries.
      
      Phase 1: sequential scan to find byte offsets of each frame's start.
      Phase 2: parallel parse of each frame slice using rayon.
      
      Requires the ``parallel`` feature.

   .. rust:function:: readcon_core::iterators::read_all_frames
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"read_all_frames"},{"type":"punctuation","value":"("},{"type":"name","value":"path"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"&"},{"type":"link","value":"Path","target":"Path"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"Result","target":"Result"},{"type":"punctuation","value":"<"},{"type":"link","value":"Vec","target":"Vec"},{"type":"punctuation","value":"<"},{"type":"link","value":"types","target":"types"},{"type":"punctuation","value":"::"},{"type":"name","value":"ConFrame"},{"type":"punctuation","value":">"},{"type":"punctuation","value":", "},{"type":"link","value":"Box","target":"Box"},{"type":"punctuation","value":"<"},{"type":"keyword","value":"dyn"},{"type":"space"},{"type":"link","value":"std","target":"std"},{"type":"punctuation","value":"::"},{"type":"name","value":"error"},{"type":"punctuation","value":"::"},{"type":"name","value":"Error"},{"type":"punctuation","value":">"},{"type":"punctuation","value":">"}]

      Reads all frames from a file.
      
      For files smaller than 64 KiB, uses a simple ``read_to_string`` to avoid
      the fixed overhead of mmap (VMA creation, page fault, munmap). For larger
      trajectory files, uses memory-mapped I/O to let the OS page cache handle
      the data.

   .. rust:function:: readcon_core::iterators::read_first_frame
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"read_first_frame"},{"type":"punctuation","value":"("},{"type":"name","value":"path"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"&"},{"type":"link","value":"Path","target":"Path"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"Result","target":"Result"},{"type":"punctuation","value":"<"},{"type":"link","value":"types","target":"types"},{"type":"punctuation","value":"::"},{"type":"name","value":"ConFrame"},{"type":"punctuation","value":", "},{"type":"link","value":"Box","target":"Box"},{"type":"punctuation","value":"<"},{"type":"keyword","value":"dyn"},{"type":"space"},{"type":"link","value":"std","target":"std"},{"type":"punctuation","value":"::"},{"type":"name","value":"error"},{"type":"punctuation","value":"::"},{"type":"name","value":"Error"},{"type":"punctuation","value":">"},{"type":"punctuation","value":">"}]

      Reads only the first frame from a file.
      
      More efficient than ``read_all_frames`` for single-frame access because it
      stops parsing after the first frame rather than collecting all of them.

   .. rubric:: Structs and Unions


   .. rust:struct:: readcon_core::iterators::ConFrameIterator
      :index: 1
      :vis: pub
      :toc: struct ConFrameIterator
      :layout: [{"type":"keyword","value":"struct"},{"type":"space"},{"type":"name","value":"ConFrameIterator"},{"type":"punctuation","value":"<"},{"type":"lifetime","value":"'a"},{"type":"punctuation","value":">"}]

      An iterator that lazily parses simulation frames from a ``.con`` or ``.convel``
      file's contents.
      
      This struct wraps an iterator over the lines of a string and, upon each iteration,
      attempts to parse a complete ``ConFrame``. Velocity sections are detected
      automatically: if a blank line follows the coordinate blocks, the velocity
      data is parsed into the atoms.
      
      The iterator yields items of type `Result<ConFrame, ParseError>`, allowing for
      robust error handling for each frame.

      .. rubric:: Implementations


      .. rust:impl:: readcon_core::iterators::ConFrameIterator
         :index: -1
         :vis: pub
         :layout: [{"type":"keyword","value":"impl"},{"type":"punctuation","value":"<"},{"type":"lifetime","value":"'a"},{"type":"punctuation","value":">"},{"type":"space"},{"type":"link","value":"ConFrameIterator","target":"ConFrameIterator"},{"type":"punctuation","value":"<"},{"type":"lifetime","value":"'a"},{"type":"punctuation","value":">"}]
         :toc: impl ConFrameIterator


         .. rubric:: Functions


         .. rust:function:: readcon_core::iterators::ConFrameIterator::forward
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"forward"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"mut"},{"type":"space"},{"type":"keyword","value":"self"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"Option","target":"Option"},{"type":"punctuation","value":"<"},{"type":"link","value":"Result","target":"Result"},{"type":"punctuation","value":"<"},{"type":"punctuation","value":"("},{"type":"punctuation","value":")"},{"type":"punctuation","value":", "},{"type":"link","value":"error","target":"error"},{"type":"punctuation","value":"::"},{"type":"name","value":"ParseError"},{"type":"punctuation","value":">"},{"type":"punctuation","value":">"}]

            Skips the next frame without fully parsing its atomic data.
            
            This is more efficient than ``next()`` if you only need to advance the
            iterator. It reads the frame's header to determine how many lines to skip,
            including any velocity section if present.
            
            **Returns**
            
            * ``Some(Ok(()))`` on a successful skip.
            * ``Some(Err(ParseError::...))`` if there's an error parsing the header.
            * ``None`` if the iterator is already at the end.

         .. rust:function:: readcon_core::iterators::ConFrameIterator::new
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"new"},{"type":"punctuation","value":"("},{"type":"name","value":"file_contents"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"&"},{"type":"lifetime","value":"'a"},{"type":"space"},{"type":"link","value":"str","target":"str"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"Self","target":"Self"}]

            Creates a new ``ConFrameIterator`` from a string slice of the entire file.
            
            **Arguments**
            
            * ``file_contents`` - A string slice containing the text of one or more ``.con`` frames.

      .. rubric:: Traits implemented


      .. rust:impl:: readcon_core::iterators::ConFrameIterator::Iterator
         :index: -1
         :vis: pub
         :layout: [{"type":"keyword","value":"impl"},{"type":"punctuation","value":"<"},{"type":"lifetime","value":"'a"},{"type":"punctuation","value":">"},{"type":"space"},{"type":"link","value":"Iterator","target":"Iterator"},{"type":"space"},{"type":"keyword","value":"for"},{"type":"space"},{"type":"link","value":"ConFrameIterator","target":"ConFrameIterator"},{"type":"punctuation","value":"<"},{"type":"lifetime","value":"'a"},{"type":"punctuation","value":">"}]
         :toc: impl Iterator for ConFrameIterator

