===============
``mod helpers``
===============


.. rust:module:: readcon_core::helpers
   :index: 0
   :vis: pub


   .. rust:use:: readcon_core::helpers
      :used_name: self


   .. rust:use:: readcon_core
      :used_name: crate


   .. rubric:: Functions


   .. rust:function:: readcon_core::helpers::atomic_number_to_symbol
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"atomic_number_to_symbol"},{"type":"punctuation","value":"("},{"type":"name","value":"atomic_number"},{"type":"punctuation","value":": "},{"type":"link","value":"u64","target":"u64"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"punctuation","value":"&"},{"type":"lifetime","value":"'static"},{"type":"space"},{"type":"link","value":"str","target":"str"}]

      Converts an atomic number to its corresponding chemical symbol.

   .. rust:function:: readcon_core::helpers::symbol_to_atomic_number
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"symbol_to_atomic_number"},{"type":"punctuation","value":"("},{"type":"name","value":"symbol"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"&"},{"type":"link","value":"str","target":"str"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"u64","target":"u64"}]

