//! A NaN or infinite cell is refused on every Cap'n Proto path: the frame
//! converters, the client, and the server.

#![cfg(all(feature = "rpc", unix))]

use std::path::Path;
use std::time::{Duration, Instant};

use capnp::message::Builder;
use capnp_rpc::{RpcSystem, rpc_twoparty_capnp, twoparty};
use futures::AsyncReadExt;
use readcon_core::iterators::ConFrameIterator;
use readcon_core::rpc::client::RpcClient;
use readcon_core::rpc::convert::{fill_frame_builder, frame_from_reader, name_frame};
use readcon_core::rpc::read_con_capnp::{con_frame_data, read_con_service};
use readcon_core::rpc::server::start_server;
use readcon_core::rpc::set_compatibility_stamp;
use readcon_core::types::ConFrame;

const MINIMAL: &str = include_str!("../resources/conformance/valid/v2_minimal.con");

/// A cell slot: its field name, the token its error carries, a way to set it,
/// and the non-finite value to set.
type Slot = (&'static str, &'static str, fn(&mut ConFrame, f64), f64);

fn cell_slots() -> Vec<Slot> {
    fn boxl(i: usize) -> fn(&mut ConFrame, f64) {
        match i {
            0 => |f, v| f.header.boxl[0] = v,
            1 => |f, v| f.header.boxl[1] = v,
            _ => |f, v| f.header.boxl[2] = v,
        }
    }
    fn angles(i: usize) -> fn(&mut ConFrame, f64) {
        match i {
            0 => |f, v| f.header.angles[0] = v,
            1 => |f, v| f.header.angles[1] = v,
            _ => |f, v| f.header.angles[2] = v,
        }
    }
    vec![
        ("boxl[0]", "NaN", boxl(0), f64::NAN),
        ("boxl[1]", "inf", boxl(1), f64::INFINITY),
        ("boxl[2]", "-inf", boxl(2), f64::NEG_INFINITY),
        ("angles[0]", "NaN", angles(0), f64::NAN),
        ("angles[1]", "inf", angles(1), f64::INFINITY),
        ("angles[2]", "-inf", angles(2), f64::NEG_INFINITY),
    ]
}

fn finite_frame() -> ConFrame {
    ConFrameIterator::new(MINIMAL)
        .next()
        .expect("a frame")
        .expect("parses")
}

fn wait_for_socket(path: &Path) {
    let start = Instant::now();
    while !path.exists() {
        assert!(
            start.elapsed() < Duration::from_secs(10),
            "server did not bind {}",
            path.display()
        );
        std::thread::sleep(Duration::from_millis(10));
    }
}

fn serve(dir: &Path) -> String {
    let sock = dir.join("readcon-cell-finite.sock");
    let spec = format!("unix:{}", sock.display());
    let spec_server = spec.clone();
    std::thread::spawn(move || {
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .expect("runtime");
        let local = tokio::task::LocalSet::new();
        let _ = runtime.block_on(local.run_until(start_server(&spec_server)));
    });
    wait_for_socket(&sock);
    spec
}

#[test]
fn the_frame_builder_refuses_each_non_finite_cell_slot_and_names_it() {
    for (field, token, set, value) in cell_slots() {
        let mut frame = finite_frame();
        set(&mut frame, value);
        let mut message = Builder::new_default();
        let error = fill_frame_builder(message.init_root::<con_frame_data::Builder>(), &frame)
            .expect_err("a non-finite cell must be refused");
        assert_eq!(
            error,
            format!("non-finite value: cell field {field} is {token}")
        );
    }
}

#[test]
fn the_frame_reader_refuses_each_non_finite_cell_slot_on_the_wire() {
    for (field, token, _, value) in cell_slots() {
        let mut message = Builder::new_default();
        {
            let root = message.init_root::<con_frame_data::Builder>();
            fill_frame_builder(root, &finite_frame()).expect("finite frame");
        }
        {
            let root = message.get_root::<con_frame_data::Builder>().expect("root");
            let index = field[field.find('[').unwrap() + 1..field.len() - 1]
                .parse::<u32>()
                .unwrap();
            if field.starts_with("boxl") {
                root.get_cell().expect("cell").set(index, value);
            } else {
                root.get_angles().expect("angles").set(index, value);
            }
        }
        let reader = message
            .get_root_as_reader::<con_frame_data::Reader>()
            .expect("reader");
        let error = frame_from_reader(reader).expect_err("a non-finite cell must be refused");
        assert_eq!(
            error,
            format!("non-finite value: cell field {field} is {token}")
        );
    }
}

#[test]
fn a_finite_cell_survives_the_wire_bit_for_bit() {
    let mut frame = finite_frame();
    frame.header.boxl = [10.123456789012345, 11.5, 12.25];
    frame.header.angles = [80.5, 95.25, 100.125];
    let mut message = Builder::new_default();
    fill_frame_builder(message.init_root::<con_frame_data::Builder>(), &frame).expect("fill");
    let reader = message
        .get_root_as_reader::<con_frame_data::Reader>()
        .expect("reader");
    let back = frame_from_reader(reader).expect("read back");
    assert_eq!(
        back.header.boxl.map(f64::to_bits),
        frame.header.boxl.map(f64::to_bits)
    );
    assert_eq!(
        back.header.angles.map(f64::to_bits),
        frame.header.angles.map(f64::to_bits)
    );
}

#[test]
fn name_frame_names_a_cell_error_and_leaves_other_messages_alone() {
    assert_eq!(
        name_frame("non-finite value: cell field boxl[2] is inf".into(), 3),
        "non-finite value: cell field boxl[2] of frame 3 is inf"
    );
    assert_eq!(
        name_frame(
            "non-finite value: cell field boxl[2] of frame 1 is inf".into(),
            3
        ),
        "non-finite value: cell field boxl[2] of frame 1 is inf"
    );
    assert_eq!(name_frame("unrelated".into(), 3), "unrelated");
}

#[test]
fn the_client_refuses_a_non_finite_cell_before_it_sends_and_names_the_frame() {
    let scratch = tempfile::tempdir().expect("tempdir");
    let client = RpcClient::new(&serve(scratch.path())).expect("client");
    for (field, token, set, value) in cell_slots() {
        let mut bad = finite_frame();
        set(&mut bad, value);
        let frames = [finite_frame(), bad];
        let error = client
            .write_frames(&frames)
            .expect_err("a non-finite cell must be refused");
        assert_eq!(
            error.to_string(),
            format!("non-finite value: cell field {field} of frame 1 is {token}")
        );
    }
    let ok = client
        .write_frames(&[finite_frame()])
        .expect("a finite frame still writes");
    assert!(!ok.is_empty());
}

#[test]
fn the_server_refuses_a_non_finite_cell_that_arrives_on_the_wire() {
    let scratch = tempfile::tempdir().expect("tempdir");
    let spec = serve(scratch.path());
    let sock = spec.strip_prefix("unix:").unwrap().to_string();
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .expect("runtime");
    let local = tokio::task::LocalSet::new();
    let (field, message) = runtime.block_on(local.run_until(async move {
        let stream = tokio::net::UnixStream::connect(&sock)
            .await
            .expect("connect");
        let (reader, writer) = tokio_util::compat::TokioAsyncReadCompatExt::compat(stream).split();
        let network = twoparty::VatNetwork::new(
            reader,
            writer,
            rpc_twoparty_capnp::Side::Client,
            Default::default(),
        );
        let mut system = RpcSystem::new(Box::new(network), None);
        let service: read_con_service::Client = system.bootstrap(rpc_twoparty_capnp::Side::Server);
        tokio::task::spawn_local(system);

        let mut request = service.write_frames_request();
        {
            let mut write = request.get().init_req();
            set_compatibility_stamp(write.reborrow().init_compatibility());
            let mut list = write.reborrow().init_frames(2);
            for i in 0..2 {
                fill_frame_builder(list.reborrow().get(i), &finite_frame()).expect("fill");
            }
            list.reborrow()
                .get(1)
                .get_angles()
                .expect("angles")
                .set(2, f64::NAN);
        }
        let error = match request.send().promise.await {
            Ok(_) => panic!("the server accepted a NaN angle"),
            Err(error) => error,
        };
        ("angles[2]", error.to_string())
    }));
    assert!(
        message.contains(&format!(
            "non-finite value: cell field {field} of frame 1 is NaN"
        )),
        "{message}"
    );

    let client = RpcClient::new(&spec).expect("client");
    assert!(client.write_frames(&[finite_frame()]).is_ok());
}
