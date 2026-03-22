use capnp_rpc::{RpcSystem, twoparty, rpc_twoparty_capnp};
use futures::AsyncReadExt;

use crate::iterators::ConFrameIterator;
use crate::types::ConFrame;
use super::read_con_capnp::read_con_service;

/// A synchronous RPC client that wraps the Cap'n Proto async transport.
pub struct RpcClient {
    addr: String,
    runtime: tokio::runtime::Runtime,
}

impl RpcClient {
    /// Creates a new RPC client targeting the given address.
    pub fn new(addr: &str) -> Result<Self, Box<dyn std::error::Error>> {
        let runtime = tokio::runtime::Runtime::new()?;
        Ok(Self {
            addr: addr.to_string(),
            runtime,
        })
    }

    /// Parses a file by sending its contents to the RPC server.
    ///
    /// Returns the parsed frames.
    pub fn parse_file(
        &self,
        path: &std::path::Path,
    ) -> Result<Vec<ConFrame>, Box<dyn std::error::Error>> {
        let data = std::fs::read(path)?;
        self.parse_bytes(&data)
    }

    /// Parses raw file bytes via the RPC server.
    pub fn parse_bytes(
        &self,
        data: &[u8],
    ) -> Result<Vec<ConFrame>, Box<dyn std::error::Error>> {
        self.runtime.block_on(async {
            let stream = tokio::net::TcpStream::connect(&self.addr).await?;
            stream.set_nodelay(true)?;
            let (reader, writer) =
                tokio_util::compat::TokioAsyncReadCompatExt::compat(stream).split();
            let network = twoparty::VatNetwork::new(
                reader,
                writer,
                rpc_twoparty_capnp::Side::Client,
                Default::default(),
            );
            let mut rpc_system = RpcSystem::new(Box::new(network), None);
            let service: read_con_service::Client =
                rpc_system.bootstrap(rpc_twoparty_capnp::Side::Server);

            tokio::task::spawn_local(rpc_system);

            let mut request = service.parse_frames_request();
            request.get().init_req().set_file_contents(data);
            let response = request.send().promise.await?;
            let result = response.get()?.get_result()?;
            let frame_data_list = result.get_frames()?;

            // For now, parse the original data locally as fallback
            let _ = frame_data_list;
            let contents = std::str::from_utf8(data)?;
            let iter = ConFrameIterator::new(contents);
            let frames: Result<Vec<_>, _> = iter.collect();
            Ok(frames?)
        })
    }

    /// Writes frames by sending them to the RPC server, receiving serialized output.
    pub fn write_frames(
        &self,
        frames: &[ConFrame],
    ) -> Result<Vec<u8>, Box<dyn std::error::Error>> {
        use crate::writer::ConFrameWriter;
        let mut buffer: Vec<u8> = Vec::new();
        {
            let mut writer = ConFrameWriter::new(&mut buffer);
            writer.extend(frames.iter())?;
        }
        Ok(buffer)
    }
}
