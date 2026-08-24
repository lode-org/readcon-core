use capnp::capability::Promise;
use capnp_rpc::{pry, rpc_twoparty_capnp, twoparty, RpcSystem};
use futures::AsyncReadExt;

use crate::iterators::ConFrameIterator;
use crate::writer::ConFrameWriter;

use super::convert::{fill_frame_builder, frame_from_reader};
use super::read_con_capnp::read_con_service;
use super::{set_compatibility_stamp, validate_compatibility_stamp};

struct ReadConServiceImpl;

impl read_con_service::Server for ReadConServiceImpl {
    fn parse_frames(
        &mut self,
        params: read_con_service::ParseFramesParams,
        mut results: read_con_service::ParseFramesResults,
    ) -> Promise<(), capnp::Error> {
        let req = pry!(params.get());
        let parse_request = pry!(req.get_req());
        if let Err(e) = validate_compatibility_stamp(pry!(parse_request.get_compatibility())) {
            return Promise::err(capnp::Error::failed(e));
        }
        let file_bytes = pry!(parse_request.get_file_contents());
        let file_str = match std::str::from_utf8(file_bytes) {
            Ok(s) => s,
            Err(e) => return Promise::err(capnp::Error::failed(e.to_string())),
        };

        let frames: Result<Vec<_>, _> = ConFrameIterator::new(file_str).collect();
        let frames = match frames {
            Ok(f) => f,
            Err(e) => return Promise::err(capnp::Error::failed(e.to_string())),
        };

        let mut result_builder = results.get().init_result();
        set_compatibility_stamp(result_builder.reborrow().init_compatibility());
        let mut frames_builder = result_builder.reborrow().init_frames(frames.len() as u32);

        for (i, frame) in frames.iter().enumerate() {
            let fb = frames_builder.reborrow().get(i as u32);
            if let Err(e) = fill_frame_builder(fb, frame) {
                return Promise::err(capnp::Error::failed(e));
            }
        }

        Promise::ok(())
    }

    fn write_frames(
        &mut self,
        params: read_con_service::WriteFramesParams,
        mut results: read_con_service::WriteFramesResults,
    ) -> Promise<(), capnp::Error> {
        let req = pry!(params.get());
        let write_request = pry!(req.get_req());
        if let Err(e) = validate_compatibility_stamp(pry!(write_request.get_compatibility())) {
            return Promise::err(capnp::Error::failed(e));
        }
        let frame_data_list = pry!(write_request.get_frames());

        let mut frames = Vec::with_capacity(frame_data_list.len() as usize);
        for i in 0..frame_data_list.len() {
            let fd = frame_data_list.get(i);
            match frame_from_reader(fd) {
                Ok(f) => frames.push(f),
                Err(e) => return Promise::err(capnp::Error::failed(e)),
            }
        }

        let mut buffer: Vec<u8> = Vec::new();
        {
            let mut writer = ConFrameWriter::new(&mut buffer);
            if let Err(e) = writer.extend(frames.iter()) {
                return Promise::err(capnp::Error::failed(e.to_string()));
            }
        }

        let mut result = results.get().init_result();
        result.set_file_contents(&buffer);
        set_compatibility_stamp(result.reborrow().init_compatibility());

        Promise::ok(())
    }
}

fn spawn_server_vat<S>(stream: S, service: read_con_service::Client)
where
    S: tokio::io::AsyncRead + tokio::io::AsyncWrite + Unpin + 'static,
{
    let (reader, writer) = tokio_util::compat::TokioAsyncReadCompatExt::compat(stream).split();
    let network = twoparty::VatNetwork::new(
        reader,
        writer,
        rpc_twoparty_capnp::Side::Server,
        Default::default(),
    );
    let rpc_system = RpcSystem::new(Box::new(network), Some(service.client));
    tokio::task::spawn_local(rpc_system);
}

/// Starts an RPC server on a TCP `host:port` or Unix `unix:/path` endpoint.
///
/// Blocks until the process is stopped. A pre-existing Unix socket file is
/// removed before bind.
pub async fn start_server(addr: &str) -> Result<(), Box<dyn std::error::Error>> {
    let ep = super::endpoint::Endpoint::parse(addr)?;
    let service: read_con_service::Client = capnp_rpc::new_client(ReadConServiceImpl);
    match ep {
        super::endpoint::Endpoint::Tcp(bind) => {
            let listener = tokio::net::TcpListener::bind(&bind).await?;
            loop {
                let (stream, _) = listener.accept().await?;
                stream.set_nodelay(true)?;
                spawn_server_vat(stream, service.clone());
            }
        }
        #[cfg(unix)]
        super::endpoint::Endpoint::Unix(path) => {
            let _ = std::fs::remove_file(&path);
            let listener = tokio::net::UnixListener::bind(&path)?;
            loop {
                let (stream, _) = listener.accept().await?;
                spawn_server_vat(stream, service.clone());
            }
        }
    }
}
