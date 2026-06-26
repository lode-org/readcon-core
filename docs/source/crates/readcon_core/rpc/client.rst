==============
``mod client``
==============


.. rust:module:: readcon_core::rpc::client
   :index: 0
   :vis: pub


   .. rust:use:: readcon_core::rpc::client
      :used_name: self


   .. rust:use:: readcon_core
      :used_name: crate


   .. rust:use:: capnp_rpc::RpcSystem
      :used_name: RpcSystem


   .. rust:use:: capnp_rpc::rpc_twoparty_capnp
      :used_name: rpc_twoparty_capnp


   .. rust:use:: capnp_rpc::twoparty
      :used_name: twoparty


   .. rust:use:: futures::AsyncReadExt
      :used_name: AsyncReadExt


   .. rust:use:: super::read_con_capnp::read_con_service
      :used_name: read_con_service


   .. rust:use:: readcon_core::iterators::ConFrameIterator
      :used_name: ConFrameIterator


   .. rust:use:: readcon_core::types::ConFrame
      :used_name: ConFrame


   .. rubric:: Structs and Unions


   .. rust:struct:: readcon_core::rpc::client::RpcClient
      :index: 1
      :vis: pub
      :toc: struct RpcClient
      :layout: [{"type":"keyword","value":"struct"},{"type":"space"},{"type":"name","value":"RpcClient"}]

      A synchronous RPC client that wraps the Cap'n Proto async transport.

      .. rubric:: Implementations


      .. rust:impl:: readcon_core::rpc::client::RpcClient
         :index: -1
         :vis: pub
         :layout: [{"type":"keyword","value":"impl"},{"type":"space"},{"type":"link","value":"RpcClient","target":"RpcClient"}]
         :toc: impl RpcClient


         .. rubric:: Functions


         .. rust:function:: readcon_core::rpc::client::RpcClient::new
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"new"},{"type":"punctuation","value":"("},{"type":"name","value":"addr"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"&"},{"type":"link","value":"str","target":"str"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"Result","target":"Result"},{"type":"punctuation","value":"<"},{"type":"link","value":"Self","target":"Self"},{"type":"punctuation","value":", "},{"type":"link","value":"Box","target":"Box"},{"type":"punctuation","value":"<"},{"type":"keyword","value":"dyn"},{"type":"space"},{"type":"link","value":"std","target":"std"},{"type":"punctuation","value":"::"},{"type":"name","value":"error"},{"type":"punctuation","value":"::"},{"type":"name","value":"Error"},{"type":"punctuation","value":">"},{"type":"punctuation","value":">"}]

            Creates a new RPC client targeting the given address.

         .. rust:function:: readcon_core::rpc::client::RpcClient::parse_bytes
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"parse_bytes"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"self"},{"type":"punctuation","value":", "},{"type":"name","value":"data"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"&"},{"type":"punctuation","value":"["},{"type":"link","value":"u8","target":"u8"},{"type":"punctuation","value":"]"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"Result","target":"Result"},{"type":"punctuation","value":"<"},{"type":"link","value":"Vec","target":"Vec"},{"type":"punctuation","value":"<"},{"type":"link","value":"ConFrame","target":"ConFrame"},{"type":"punctuation","value":">"},{"type":"punctuation","value":", "},{"type":"link","value":"Box","target":"Box"},{"type":"punctuation","value":"<"},{"type":"keyword","value":"dyn"},{"type":"space"},{"type":"link","value":"std","target":"std"},{"type":"punctuation","value":"::"},{"type":"name","value":"error"},{"type":"punctuation","value":"::"},{"type":"name","value":"Error"},{"type":"punctuation","value":">"},{"type":"punctuation","value":">"}]

            Parses raw file bytes via the RPC server.

         .. rust:function:: readcon_core::rpc::client::RpcClient::parse_file
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"parse_file"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"self"},{"type":"punctuation","value":", "},{"type":"name","value":"path"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"&"},{"type":"link","value":"std","target":"std"},{"type":"punctuation","value":"::"},{"type":"name","value":"path"},{"type":"punctuation","value":"::"},{"type":"name","value":"Path"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"Result","target":"Result"},{"type":"punctuation","value":"<"},{"type":"link","value":"Vec","target":"Vec"},{"type":"punctuation","value":"<"},{"type":"link","value":"ConFrame","target":"ConFrame"},{"type":"punctuation","value":">"},{"type":"punctuation","value":", "},{"type":"link","value":"Box","target":"Box"},{"type":"punctuation","value":"<"},{"type":"keyword","value":"dyn"},{"type":"space"},{"type":"link","value":"std","target":"std"},{"type":"punctuation","value":"::"},{"type":"name","value":"error"},{"type":"punctuation","value":"::"},{"type":"name","value":"Error"},{"type":"punctuation","value":">"},{"type":"punctuation","value":">"}]

            Parses a file by sending its contents to the RPC server.
            
            Returns the parsed frames.

         .. rust:function:: readcon_core::rpc::client::RpcClient::write_frames
            :index: -1
            :vis: pub
            :layout: [{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"write_frames"},{"type":"punctuation","value":"("},{"type":"punctuation","value":"&"},{"type":"keyword","value":"self"},{"type":"punctuation","value":", "},{"type":"name","value":"frames"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"&"},{"type":"punctuation","value":"["},{"type":"link","value":"ConFrame","target":"ConFrame"},{"type":"punctuation","value":"]"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"Result","target":"Result"},{"type":"punctuation","value":"<"},{"type":"link","value":"Vec","target":"Vec"},{"type":"punctuation","value":"<"},{"type":"link","value":"u8","target":"u8"},{"type":"punctuation","value":">"},{"type":"punctuation","value":", "},{"type":"link","value":"Box","target":"Box"},{"type":"punctuation","value":"<"},{"type":"keyword","value":"dyn"},{"type":"space"},{"type":"link","value":"std","target":"std"},{"type":"punctuation","value":"::"},{"type":"name","value":"error"},{"type":"punctuation","value":"::"},{"type":"name","value":"Error"},{"type":"punctuation","value":">"},{"type":"punctuation","value":">"}]

            Writes frames by sending them to the RPC server, receiving serialized output.
