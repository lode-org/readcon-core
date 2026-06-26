==============
``mod server``
==============


.. rust:module:: readcon_core::rpc::server
   :index: 0
   :vis: pub


   .. rust:use:: readcon_core::rpc::server
      :used_name: self


   .. rust:use:: readcon_core
      :used_name: crate


   .. rust:use:: capnp::capability::Promise
      :used_name: Promise


   .. rust:use:: capnp_rpc::RpcSystem
      :used_name: RpcSystem


   .. rust:use:: capnp_rpc::pry
      :used_name: pry


   .. rust:use:: capnp_rpc::rpc_twoparty_capnp
      :used_name: rpc_twoparty_capnp


   .. rust:use:: capnp_rpc::twoparty
      :used_name: twoparty


   .. rust:use:: futures::AsyncReadExt
      :used_name: AsyncReadExt


   .. rust:use:: readcon_core::iterators::ConFrameIterator
      :used_name: ConFrameIterator


   .. rust:use:: readcon_core::writer::ConFrameWriter
      :used_name: ConFrameWriter


   .. rust:use:: super::read_con_capnp::read_con_service
      :used_name: read_con_service


   .. rubric:: Functions


   .. rust:function:: readcon_core::rpc::server::start_server
      :index: 0
      :vis: pub
      :layout: [{"type":"keyword","value":"async"},{"type":"space"},{"type":"keyword","value":"fn"},{"type":"space"},{"type":"name","value":"start_server"},{"type":"punctuation","value":"("},{"type":"name","value":"addr"},{"type":"punctuation","value":": "},{"type":"punctuation","value":"&"},{"type":"link","value":"str","target":"str"},{"type":"punctuation","value":")"},{"type":"space"},{"type":"returns"},{"type":"space"},{"type":"link","value":"Result","target":"Result"},{"type":"punctuation","value":"<"},{"type":"punctuation","value":"("},{"type":"punctuation","value":")"},{"type":"punctuation","value":", "},{"type":"link","value":"Box","target":"Box"},{"type":"punctuation","value":"<"},{"type":"keyword","value":"dyn"},{"type":"space"},{"type":"link","value":"std","target":"std"},{"type":"punctuation","value":"::"},{"type":"name","value":"error"},{"type":"punctuation","value":"::"},{"type":"name","value":"Error"},{"type":"punctuation","value":">"},{"type":"punctuation","value":">"}]

      Starts an RPC server on the given address.
      
      This function blocks until the server is shut down.
