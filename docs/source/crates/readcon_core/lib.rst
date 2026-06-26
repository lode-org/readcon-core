======================
Crate ``readcon_core``
======================


.. rust:crate:: readcon_core
   :index: 0


   .. rubric:: Modules
   .. toctree::
      :maxdepth: 1

      compression
      error
      ffi
      helpers
      iterators
      parser
      types
      writer
      rpc
      python


   .. rust:use:: readcon_core
      :used_name: self


   .. rust:use:: readcon_core
      :used_name: crate


   .. rust:use:: readcon_core::rpc::read_con_capnp
      :used_name: ReadCon_capnp
      :reexport: readcon_core

   .. rubric:: Re-exports

   * :rust:any:``readcon_core::rpc::read_con_capnp``

   .. rubric:: Variables


   .. rust:variable:: readcon_core::CON_SPEC_VERSION
      :index: 0
      :vis: pub
      :toc: const CON_SPEC_VERSION
      :layout: [{"type":"keyword","value":"const"},{"type":"space"},{"type":"name","value":"CON_SPEC_VERSION"},{"type":"punctuation","value":": "},{"type":"link","value":"u32","target":"u32"}]

      CON/convel format spec version implemented by this build.
      
      - Version 1: column 5 present but semantics undefined. Readers MAY
        ignore it. No JSON metadata line.
      - Version 2: column 5 is the original atom index before type-based
        grouping. Readers MUST parse and preserve it. Writers MUST write
        the stored value. Line 2 of the header carries a JSON object
        with at least ``{"con_spec_version": 2}``.
      
      See ``docs/orgmode/spec.org`` for the full specification.

   .. rust:variable:: readcon_core::VERSION
      :index: 0
      :vis: pub
      :toc: const VERSION
      :layout: [{"type":"keyword","value":"const"},{"type":"space"},{"type":"name","value":"VERSION"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"&"},{"type":"link","value":"str","target":"str"}]

      Library version string, injected from Cargo.toml at compile time.
