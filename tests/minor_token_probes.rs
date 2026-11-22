//! con_spec_minor token probes shared by the Rust, C, RPC, Python, and Julia
//! tests. Cases and expected results are in
//! `tests/fixtures/minor_token_probes.json`, written by
//! `tests/fixtures/generate_minor_token_probes.py`.

use readcon_core::iterators::frames_from_text;
use readcon_core::types::ConFrameBuilder;
use readcon_core::writer::ConFrameWriter;
use serde_json::Value;

const VELOCITY_BODY: &str = "\n10 10 10\n90 90 90\n\n\n1\n1\n1.0\nH\nCoordinates of Component 1\n0 0 0 0 0\n\nH\nVelocities of Component 1\n0.1 0.2 0.3 0 0\n";

fn probes() -> Vec<Value> {
    let text = include_str!("fixtures/minor_token_probes.json");
    let root: Value = serde_json::from_str(text).unwrap();
    root["cases"].as_array().unwrap().clone()
}

fn velocity_text(line2: &str) -> String {
    format!(
        "gen\n{},\"sections\":[\"velocities\"]}}{VELOCITY_BODY}",
        &line2[..line2.len() - 1]
    )
}

fn check_error(name: &str, tag: &str, class: &str, message: &str) {
    match tag {
        "dup" => {
            assert_eq!(class, "InvalidMetadataJson", "{name}: {message}");
            assert!(
                message.contains("duplicate con_spec_minor key"),
                "{name}: {message}"
            );
        }
        "invalid" => {
            assert_eq!(class, "InvalidMetadataJson", "{name}: {message}");
            assert!(!message.contains("duplicate"), "{name}: {message}");
        }
        "units" => assert!(message.contains("units.time"), "{name}: {message}"),
        other => panic!("{name}: unexpected tag {other}"),
    }
}

#[test]
fn rust_reader_matches_probe_table() {
    let cases = probes();
    assert_eq!(cases.len(), 59);
    for case in &cases {
        let name = case["name"].as_str().unwrap();
        for (line_key, op) in [("line2_w", "read_w"), ("line2_n", "read_n")] {
            let line2 = case[line_key].as_str().unwrap();
            let expected = case[op].as_str().unwrap();
            match frames_from_text(&velocity_text(line2), None) {
                Ok(frames) => {
                    assert_eq!(expected, "ok", "{name} {op}");
                    assert_eq!(frames.len(), 1, "{name} {op}");
                }
                Err(err) => {
                    assert_ne!(expected, "ok", "{name} {op}: {err}");
                    if expected == "units" {
                        assert_eq!(err.class_name(), "InvalidUnits", "{name} {op}: {err}");
                    } else {
                        check_error(name, expected, err.class_name(), &err.to_string());
                    }
                }
            }
        }
    }
}

#[test]
fn rust_builder_matches_probe_table() {
    for case in &probes() {
        let name = case["name"].as_str().unwrap();
        for (line_key, op) in [("line2_w", "raw_w"), ("line2_n", "raw_n")] {
            let line2 = case[line_key].as_str().unwrap();
            let expected = case[op].as_str().unwrap();
            let mut builder = ConFrameBuilder::new([10.0; 3], [90.0; 3]);
            if let Err(err) = builder.set_metadata_json(line2) {
                check_error(name, expected, err.class_name(), &err.to_string());
                continue;
            }
            builder.add_atom("H", 0.0, 0.0, 0.0, [false; 3], 0, 1.0);
            builder.with_velocity([0.1, 0.2, 0.3]);
            let frame = builder.build().unwrap();
            let mut out = Vec::new();
            let result = ConFrameWriter::new(&mut out).write_frame(&frame);
            match result {
                Ok(()) => {
                    let text = String::from_utf8(out).unwrap();
                    assert_eq!(text.lines().nth(1).unwrap(), expected, "{name} {op}");
                    assert_eq!(frames_from_text(&text, None).unwrap().len(), 1, "{name}");
                }
                Err(err) => check_error(name, expected, "", &err.to_string()),
            }
        }
    }
}
