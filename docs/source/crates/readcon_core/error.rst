=============
``mod error``
=============


.. rust:module:: readcon_core::error
   :index: 0
   :vis: pub


   .. rust:use:: readcon_core::error
      :used_name: self


   .. rust:use:: readcon_core
      :used_name: crate


   .. rust:use:: std::fmt
      :used_name: fmt


   .. rust:use:: std::num::ParseFloatError
      :used_name: ParseFloatError


   .. rust:use:: std::num::ParseIntError
      :used_name: ParseIntError


   .. rubric:: Enums


   .. rust:enum:: readcon_core::error::ParseError
      :index: 1
      :vis: pub
      :layout: [{"type":"keyword","value":"enum"},{"type":"space"},{"type":"name","value":"ParseError"}]


      .. rust:struct:: readcon_core::error::ParseError::IncompleteHeader
         :index: 2
         :vis: pub
         :toc: IncompleteHeader
         :layout: [{"type":"name","value":"IncompleteHeader"}]


      .. rust:struct:: readcon_core::error::ParseError::IncompleteFrame
         :index: 2
         :vis: pub
         :toc: IncompleteFrame
         :layout: [{"type":"name","value":"IncompleteFrame"}]


      .. rust:struct:: readcon_core::error::ParseError::IncompleteVelocitySection
         :index: 2
         :vis: pub
         :toc: IncompleteVelocitySection
         :layout: [{"type":"name","value":"IncompleteVelocitySection"}]


      .. rust:struct:: readcon_core::error::ParseError::InvalidVectorLength
         :index: 2
         :vis: pub
         :toc: InvalidVectorLength
         :layout: [{"type":"name","value":"InvalidVectorLength"}]


         .. rust:variable:: readcon_core::error::ParseError::InvalidVectorLength::expected
            :index: -1
            :vis: pub
            :toc: expected
            :layout: [{"type":"name","value":"expected"},{"type":"punctuation","value":": "},{"type":"link","value":"usize","target":"usize"}]


         .. rust:variable:: readcon_core::error::ParseError::InvalidVectorLength::found
            :index: -1
            :vis: pub
            :toc: found
            :layout: [{"type":"name","value":"found"},{"type":"punctuation","value":": "},{"type":"link","value":"usize","target":"usize"}]


      .. rust:struct:: readcon_core::error::ParseError::InvalidNumberFormat
         :index: 2
         :vis: pub
         :toc: InvalidNumberFormat
         :layout: [{"type":"name","value":"InvalidNumberFormat"},{"type":"punctuation","value":"("},{"type":"link","value":"String","target":"String"},{"type":"punctuation","value":")"}]


      .. rust:struct:: readcon_core::error::ParseError::MissingSpecVersion
         :index: 2
         :vis: pub
         :toc: MissingSpecVersion
         :layout: [{"type":"name","value":"MissingSpecVersion"}]


      .. rust:struct:: readcon_core::error::ParseError::UnsupportedSpecVersion
         :index: 2
         :vis: pub
         :toc: UnsupportedSpecVersion
         :layout: [{"type":"name","value":"UnsupportedSpecVersion"},{"type":"punctuation","value":"("},{"type":"link","value":"u32","target":"u32"},{"type":"punctuation","value":")"}]


      .. rust:struct:: readcon_core::error::ParseError::InvalidMetadataJson
         :index: 2
         :vis: pub
         :toc: InvalidMetadataJson
         :layout: [{"type":"name","value":"InvalidMetadataJson"},{"type":"punctuation","value":"("},{"type":"link","value":"String","target":"String"},{"type":"punctuation","value":")"}]


      .. rust:struct:: readcon_core::error::ParseError::IncompleteForceSection
         :index: 2
         :vis: pub
         :toc: IncompleteForceSection
         :layout: [{"type":"name","value":"IncompleteForceSection"}]


      .. rust:struct:: readcon_core::error::ParseError::UnknownSection
         :index: 2
         :vis: pub
         :toc: UnknownSection
         :layout: [{"type":"name","value":"UnknownSection"},{"type":"punctuation","value":"("},{"type":"link","value":"String","target":"String"},{"type":"punctuation","value":")"}]


      .. rust:struct:: readcon_core::error::ParseError::ValidationError
         :index: 2
         :vis: pub
         :toc: ValidationError
         :layout: [{"type":"name","value":"ValidationError"},{"type":"punctuation","value":"("},{"type":"link","value":"String","target":"String"},{"type":"punctuation","value":")"}]


      .. rubric:: Traits implemented


      .. rust:impl:: readcon_core::error::ParseError::Display
         :index: -1
         :vis: pub
         :layout: [{"type":"keyword","value":"impl"},{"type":"space"},{"type":"link","value":"fmt","target":"fmt"},{"type":"punctuation","value":"::"},{"type":"name","value":"Display"},{"type":"space"},{"type":"keyword","value":"for"},{"type":"space"},{"type":"link","value":"ParseError","target":"ParseError"}]
         :toc: impl Display for ParseError


      .. rust:impl:: readcon_core::error::ParseError::Error
         :index: -1
         :vis: pub
         :layout: [{"type":"keyword","value":"impl"},{"type":"space"},{"type":"link","value":"std","target":"std"},{"type":"punctuation","value":"::"},{"type":"name","value":"error"},{"type":"punctuation","value":"::"},{"type":"name","value":"Error"},{"type":"space"},{"type":"keyword","value":"for"},{"type":"space"},{"type":"link","value":"ParseError","target":"ParseError"}]
         :toc: impl Error for ParseError


      .. rust:impl:: readcon_core::error::ParseError::From
         :index: -1
         :vis: pub
         :layout: [{"type":"keyword","value":"impl"},{"type":"space"},{"type":"link","value":"From","target":"From"},{"type":"punctuation","value":"<"},{"type":"link","value":"ParseFloatError","target":"ParseFloatError"},{"type":"punctuation","value":">"},{"type":"space"},{"type":"keyword","value":"for"},{"type":"space"},{"type":"link","value":"ParseError","target":"ParseError"}]
         :toc: impl From for ParseError


      .. rust:impl:: readcon_core::error::ParseError::From
         :index: -1
         :vis: pub
         :layout: [{"type":"keyword","value":"impl"},{"type":"space"},{"type":"link","value":"From","target":"From"},{"type":"punctuation","value":"<"},{"type":"link","value":"ParseIntError","target":"ParseIntError"},{"type":"punctuation","value":">"},{"type":"space"},{"type":"keyword","value":"for"},{"type":"space"},{"type":"link","value":"ParseError","target":"ParseError"}]
         :toc: impl From for ParseError

