use capnp::capability::Promise;
use capnp_rpc::{RpcSystem, twoparty, rpc_twoparty_capnp};

use crate::iterators::ConFrameIterator;
use crate::writer::ConFrameWriter;

use super::read_con_capnp::read_con_service;

struct ReadConServiceImpl;

impl read_con_service::Server for ReadConServiceImpl {
    fn parse_frames(
        &mut self,
        params: read_con_service::ParseFramesParams,
        mut results: read_con_service::ParseFramesResults,
    ) -> Promise<(), capnp::Error> {
        let req = pry!(params.get());
        let file_bytes = pry!(pry!(req.get_req()).get_file_contents());
        let file_str = match std::str::from_utf8(file_bytes) {
            Ok(s) => s,
            Err(e) => return Promise::err(capnp::Error::failed(e.to_string())),
        };

        let iter = ConFrameIterator::new(file_str);
        let frames: Vec<_> = iter.filter_map(|r| r.ok()).collect();

        let mut result_builder = results.get().init_result();
        let mut frames_builder = result_builder.reborrow().init_frames(frames.len() as u32);

        for (i, frame) in frames.iter().enumerate() {
            let mut fb = frames_builder.reborrow().get(i as u32);

            // Cell
            let mut cell = fb.reborrow().init_cell(3);
            for (j, &v) in frame.header.boxl.iter().enumerate() {
                cell.set(j as u32, v);
            }

            // Angles
            let mut angles = fb.reborrow().init_angles(3);
            for (j, &v) in frame.header.angles.iter().enumerate() {
                angles.set(j as u32, v);
            }

            // Headers
            let mut prebox = fb.reborrow().init_prebox_header(2);
            prebox.set(0, &frame.header.prebox_header[0]);
            prebox.set(1, &frame.header.prebox_header[1]);

            let mut postbox = fb.reborrow().init_postbox_header(2);
            postbox.set(0, &frame.header.postbox_header[0]);
            postbox.set(1, &frame.header.postbox_header[1]);

            fb.set_has_velocities(frame.has_velocities());

            // Atoms
            let mut atoms_builder = fb.reborrow().init_atoms(frame.atom_data.len() as u32);
            for (k, atom) in frame.atom_data.iter().enumerate() {
                let mut ab = atoms_builder.reborrow().get(k as u32);
                ab.set_symbol(&atom.symbol);
                ab.set_x(atom.x);
                ab.set_y(atom.y);
                ab.set_z(atom.z);
                ab.set_is_fixed(atom.is_fixed);
                ab.set_atom_id(atom.atom_id);
                ab.set_vx(atom.vx.unwrap_or(0.0));
                ab.set_vy(atom.vy.unwrap_or(0.0));
                ab.set_vz(atom.vz.unwrap_or(0.0));
                ab.set_has_velocity(atom.has_velocity());
            }
        }

        Promise::ok(())
    }

    fn write_frames(
        &mut self,
        params: read_con_service::WriteFramesParams,
        mut results: read_con_service::WriteFramesResults,
    ) -> Promise<(), capnp::Error> {
        use crate::types::{AtomDatum, ConFrame, FrameHeader};
        use std::rc::Rc;

        let req = pry!(params.get());
        let frame_data_list = pry!(pry!(req.get_req()).get_frames());

        let mut frames = Vec::new();
        for i in 0..frame_data_list.len() {
            let fd = pry!(frame_data_list.get(i));

            let cell_list = pry!(fd.get_cell());
            let angles_list = pry!(fd.get_angles());
            let prebox_list = pry!(fd.get_prebox_header());
            let postbox_list = pry!(fd.get_postbox_header());
            let atoms_list = pry!(fd.get_atoms());

            let boxl = [
                cell_list.get(0),
                cell_list.get(1),
                cell_list.get(2),
            ];
            let angles = [
                angles_list.get(0),
                angles_list.get(1),
                angles_list.get(2),
            ];

            let prebox_header = [
                pry!(prebox_list.get(0)).to_string(),
                pry!(prebox_list.get(1)).to_string(),
            ];
            let postbox_header = [
                pry!(postbox_list.get(0)).to_string(),
                pry!(postbox_list.get(1)).to_string(),
            ];

            // Reconstruct atom data
            let mut atom_data = Vec::with_capacity(atoms_list.len() as usize);
            let mut natms_per_type: Vec<usize> = Vec::new();
            let mut masses_per_type: Vec<f64> = Vec::new();
            let mut current_symbol = String::new();
            let mut current_count: usize = 0;

            for j in 0..atoms_list.len() {
                let a = pry!(atoms_list.get(j));
                let sym = pry!(a.get_symbol()).to_string();

                if sym != current_symbol {
                    if current_count > 0 {
                        natms_per_type.push(current_count);
                    }
                    current_symbol = sym.clone();
                    current_count = 0;
                    masses_per_type.push(0.0); // mass not in schema atoms
                }
                current_count += 1;

                let has_vel = a.get_has_velocity();
                atom_data.push(AtomDatum {
                    symbol: Rc::new(sym),
                    x: a.get_x(),
                    y: a.get_y(),
                    z: a.get_z(),
                    is_fixed: a.get_is_fixed(),
                    atom_id: a.get_atom_id(),
                    vx: if has_vel { Some(a.get_vx()) } else { None },
                    vy: if has_vel { Some(a.get_vy()) } else { None },
                    vz: if has_vel { Some(a.get_vz()) } else { None },
                });
            }
            if current_count > 0 {
                natms_per_type.push(current_count);
            }

            let header = FrameHeader {
                prebox_header,
                boxl,
                angles,
                postbox_header,
                natm_types: natms_per_type.len(),
                natms_per_type,
                masses_per_type,
            };

            frames.push(ConFrame { header, atom_data });
        }

        let mut buffer: Vec<u8> = Vec::new();
        {
            let mut writer = ConFrameWriter::new(&mut buffer);
            if let Err(e) = writer.extend(frames.iter()) {
                return Promise::err(capnp::Error::failed(e.to_string()));
            }
        }

        results
            .get()
            .init_result()
            .set_file_contents(&buffer);

        Promise::ok(())
    }
}

/// Starts an RPC server on the given address.
///
/// This function blocks until the server is shut down.
pub async fn start_server(addr: &str) -> Result<(), Box<dyn std::error::Error>> {
    let listener = tokio::net::TcpListener::bind(addr).await?;
    let service = read_con_service::ToClient::new(ReadConServiceImpl)
        .into_client::<capnp_rpc::Server>();

    loop {
        let (stream, _) = listener.accept().await?;
        stream.set_nodelay(true)?;
        let (reader, writer) = tokio_util::compat::TokioAsyncReadCompatExt::compat(stream).split();
        let network = twoparty::VatNetwork::new(
            reader,
            writer,
            rpc_twoparty_capnp::Side::Server,
            Default::default(),
        );
        let rpc_system = RpcSystem::new(Box::new(network), Some(service.clone().client));
        tokio::task::spawn_local(rpc_system);
    }
}
