//! A NaN or infinite cell is refused on every Cap'n Proto path: the frame
//! converters, the client, and the server.

#![cfg(all(feature = "rpc", unix))]

use std::path::Path;
use std::time::{Duration, Instant};

use capnp::message::Builder;
use capnp_rpc::{RpcSystem, rpc_twoparty_capnp, twoparty};
use futures::AsyncReadExt;
use readcon_core::error::{ConvertError, ParseError};
use readcon_core::iterators::ConFrameIterator;
use readcon_core::rpc::client::RpcClient;
use readcon_core::rpc::convert::{fill_frame_builder, frame_from_reader};
use readcon_core::rpc::read_con_capnp::{con_frame_data, read_con_service};
use readcon_core::rpc::server::start_server;
use readcon_core::rpc::set_compatibility_stamp;
use readcon_core::types::ConFrame;

const MINIMAL: &str = include_str!("../resources/conformance/valid/v2_minimal.con");

/// NaN, +Inf, and -Inf, with the spelling a cell error gives each.
const NON_FINITE: [(f64, &str); 3] = [
    (f64::NAN, "NaN"),
    (f64::INFINITY, "inf"),
    (f64::NEG_INFINITY, "-inf"),
];

/// A cell slot: its field name and a way to set it.
type Slot = (&'static str, fn(&mut ConFrame, f64));

fn cell_slots() -> [Slot; 6] {
    [
        ("boxl[0]", |f, v| f.header.boxl[0] = v),
        ("boxl[1]", |f, v| f.header.boxl[1] = v),
        ("boxl[2]", |f, v| f.header.boxl[2] = v),
        ("angles[0]", |f, v| f.header.angles[0] = v),
        ("angles[1]", |f, v| f.header.angles[1] = v),
        ("angles[2]", |f, v| f.header.angles[2] = v),
    ]
}

/// Every cell slot with every non-finite value.
fn cell_cases() -> impl Iterator<Item = (&'static str, fn(&mut ConFrame, f64), f64, &'static str)> {
    cell_slots().into_iter().flat_map(|(field, set)| {
        NON_FINITE
            .into_iter()
            .map(move |(value, token)| (field, set, value, token))
    })
}

/// The typed cell error, with its text.
fn assert_typed_cell(error: &ConvertError, expected: &str) {
    let parse = error
        .parse_error()
        .unwrap_or_else(|| panic!("not a typed error: {error:?}"));
    assert!(matches!(parse, ParseError::NonFiniteValue(_)), "{parse:?}");
    assert!(parse.is_non_finite_cell(), "{parse}");
    assert_eq!(error.to_string(), expected);
}

/// The [`ConvertError`] in a client's boxed error.
fn convert_error<'a>(error: &'a (dyn std::error::Error + 'static)) -> &'a ConvertError {
    error
        .downcast_ref::<ConvertError>()
        .unwrap_or_else(|| panic!("not a ConvertError: {error}"))
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
    for (field, set, value, token) in cell_cases() {
        let mut frame = finite_frame();
        set(&mut frame, value);
        let mut message = Builder::new_default();
        let error = fill_frame_builder(message.init_root::<con_frame_data::Builder>(), &frame)
            .expect_err("a non-finite cell must be refused");
        assert_typed_cell(
            &error,
            &format!("non-finite value: cell field {field} is {token}"),
        );
        assert_typed_cell(
            &error.in_frame(4),
            &format!("non-finite value: cell field {field} of frame 4 is {token}"),
        );
    }
}

#[test]
fn the_frame_reader_refuses_each_non_finite_cell_slot_on_the_wire() {
    for (field, _, value, token) in cell_cases() {
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
        assert_typed_cell(
            &error,
            &format!("non-finite value: cell field {field} is {token}"),
        );
    }
}

#[test]
fn a_malformed_wire_frame_is_a_message() {
    let mut message = Builder::new_default();
    {
        let mut root = message.init_root::<con_frame_data::Builder>();
        root.reborrow().init_cell(2);
        root.init_angles(3);
    }
    let reader = message
        .get_root_as_reader::<con_frame_data::Reader>()
        .expect("reader");
    let error = frame_from_reader(reader).expect_err("a short cell must be refused");
    assert!(error.parse_error().is_none(), "{error:?}");
    assert_eq!(error, "cell/angles must have length 3");
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
fn in_frame_names_a_cell_error_once_and_leaves_messages_alone() {
    let error = ConvertError::from(ParseError::non_finite_cell("boxl[2]", f64::INFINITY));
    let named = error.in_frame(3);
    assert_typed_cell(
        &named,
        "non-finite value: cell field boxl[2] of frame 3 is inf",
    );
    assert_typed_cell(
        &named.in_frame(9),
        "non-finite value: cell field boxl[2] of frame 3 is inf",
    );
    assert_eq!(ConvertError::from("unrelated").in_frame(3), "unrelated");
}

#[test]
fn the_client_refuses_a_non_finite_cell_before_it_sends_and_names_the_frame() {
    let scratch = tempfile::tempdir().expect("tempdir");
    let client = RpcClient::new(&serve(scratch.path())).expect("client");
    for (field, set, value, token) in cell_cases() {
        let mut bad = finite_frame();
        set(&mut bad, value);
        let frames = [finite_frame(), bad];
        let error = client
            .write_frames(&frames)
            .expect_err("a non-finite cell must be refused");
        assert_typed_cell(
            convert_error(error.as_ref()),
            &format!("non-finite value: cell field {field} of frame 1 is {token}"),
        );
    }
    let ok = client
        .write_frames(&[finite_frame()])
        .expect("a finite frame still writes");
    assert!(!ok.is_empty());
}

/// `MINIMAL` with line `line` (0-based) replaced.
fn minimal_with(line: usize, text: &str) -> String {
    let mut lines: Vec<&str> = MINIMAL.lines().collect();
    lines[line] = text;
    lines.join("\n") + "\n"
}

#[test]
fn the_client_returns_the_typed_error_for_a_file_the_server_refuses() {
    let scratch = tempfile::tempdir().expect("tempdir");
    let client = RpcClient::new(&serve(scratch.path())).expect("client");
    for (spelling, shown) in [("NaN", "NaN"), ("inf", "inf"), ("-inf", "-inf")] {
        for slot in 0..3 {
            for (line, field) in [(2usize, "boxl"), (3, "angles")] {
                let mut values = if line == 2 {
                    ["10.0", "10.0", "10.0"]
                } else {
                    ["90.0", "90.0", "90.0"]
                };
                values[slot] = spelling;
                let text = format!("{MINIMAL}{}", minimal_with(line, &values.join(" ")));
                let error = client
                    .parse_bytes(text.as_bytes())
                    .expect_err("a non-finite cell must be refused");
                assert_typed_cell(
                    convert_error(error.as_ref()),
                    &format!("non-finite value: cell field {field}[{slot}] of frame 1 is {shown}"),
                );
            }
            let mut position = ["0.0", "0.0", "0.0"];
            position[slot] = spelling;
            let row = format!("{} 7 0", position.join(" "));
            let error = client
                .parse_bytes(minimal_with(11, &row).as_bytes())
                .expect_err("a non-finite position must be refused");
            let error = convert_error(error.as_ref());
            let parse = error.parse_error().expect("typed");
            assert!(matches!(parse, ParseError::NonFiniteValue(_)), "{parse:?}");
            assert!(!parse.is_non_finite_cell(), "{parse}");
            assert!(error.to_string().contains(spelling), "{error}");
        }
    }
    assert_eq!(
        client
            .parse_bytes(MINIMAL.as_bytes())
            .expect("finite")
            .len(),
        1
    );
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
    let refused = runtime.block_on(local.run_until(async move {
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

        let mut refused = Vec::new();
        for (field, _, value, token) in cell_cases() {
            let index = field[field.find('[').unwrap() + 1..field.len() - 1]
                .parse::<u32>()
                .unwrap();
            let mut request = service.write_frames_request();
            {
                let mut write = request.get().init_req();
                set_compatibility_stamp(write.reborrow().init_compatibility());
                let mut list = write.reborrow().init_frames(2);
                for i in 0..2 {
                    fill_frame_builder(list.reborrow().get(i), &finite_frame()).expect("fill");
                }
                let bad = list.reborrow().get(1);
                if field.starts_with("boxl") {
                    bad.get_cell().expect("cell").set(index, value);
                } else {
                    bad.get_angles().expect("angles").set(index, value);
                }
            }
            let error = match request.send().promise.await {
                Ok(_) => panic!("the server accepted a non-finite {field}"),
                Err(error) => error,
            };
            refused.push((field, token, error.to_string()));
        }
        refused
    }));
    assert_eq!(refused.len(), 18);
    for (field, token, message) in refused {
        assert!(
            message.contains(&format!(
                "non-finite value: cell field {field} of frame 1 is {token}"
            )),
            "{message}"
        );
    }

    let client = RpcClient::new(&spec).expect("client");
    assert!(client.write_frames(&[finite_frame()]).is_ok());
}
