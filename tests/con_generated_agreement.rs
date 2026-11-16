//! Generated `.con` and convel frames, checked through the public readers
//! and writers.
//!
//! A write followed by a read must return the same frames. A damaged
//! buffer must name the problem. Serial and threaded reads must agree.

use readcon_core::error::ParseError;
use readcon_core::iterators::{frames_from_bytes, frames_from_text, read_all_frames};
use readcon_core::types::{ConFrame, ConFrameBuilder};
use readcon_core::writer::{write_frames_to_vec, WriteError};

fn bits(value: f64) -> u64 {
    value.to_bits()
}

fn same_row(got: Option<[f64; 3]>, expect: Option<[f64; 3]>) {
    match (got, expect) {
        (Some(got), Some(expect)) => {
            for index in 0..3 {
                assert_eq!(
                    bits(got[index]),
                    bits(expect[index]),
                    "{got:?} vs {expect:?}"
                );
            }
        }
        (None, None) => {}
        (got, expect) => panic!("section {got:?} vs {expect:?}"),
    }
}

fn same_frames(got: &[ConFrame], expect: &[ConFrame]) {
    assert_eq!(got.len(), expect.len());
    for (got, expect) in got.iter().zip(expect.iter()) {
        assert_eq!(got.header.natm_types, expect.header.natm_types);
        assert_eq!(got.header.natms_per_type, expect.header.natms_per_type);
        for index in 0..3 {
            assert_eq!(
                bits(got.header.boxl[index]),
                bits(expect.header.boxl[index])
            );
            assert_eq!(
                bits(got.header.angles[index]),
                bits(expect.header.angles[index])
            );
        }
        assert_eq!(
            got.header.masses_per_type.len(),
            expect.header.masses_per_type.len()
        );
        for (got_mass, expect_mass) in got
            .header
            .masses_per_type
            .iter()
            .zip(expect.header.masses_per_type.iter())
        {
            assert_eq!(bits(*got_mass), bits(*expect_mass));
        }
        assert_eq!(got.atom_data.len(), expect.atom_data.len());
        for (got_atom, expect_atom) in got.atom_data.iter().zip(expect.atom_data.iter()) {
            assert_eq!(got_atom.symbol.as_ref(), expect_atom.symbol.as_ref());
            assert_eq!(bits(got_atom.x()), bits(expect_atom.x()));
            assert_eq!(bits(got_atom.y()), bits(expect_atom.y()));
            assert_eq!(bits(got_atom.z()), bits(expect_atom.z()));
            assert_eq!(got_atom.fixed(), expect_atom.fixed());
            assert_eq!(got_atom.atom_id, expect_atom.atom_id);
            same_row(got_atom.velocity(), expect_atom.velocity());
            same_row(got_atom.force(), expect_atom.force());
        }
    }
}

fn read_both(bytes: &[u8]) -> Vec<ConFrame> {
    let serial = frames_from_bytes(bytes, Some(1)).expect("serial read");
    let threaded = frames_from_bytes(bytes, Some(4)).expect("threaded read");
    same_frames(&threaded, &serial);
    serial
}

fn round_trip(frames: &[ConFrame]) -> Vec<u8> {
    let bytes = write_frames_to_vec(frames).expect("write");
    let got = read_both(&bytes);
    same_frames(&got, frames);
    bytes
}

fn geometry() -> ConFrame {
    let mut builder = ConFrameBuilder::new([10.5, 11.0, 12.25], [90.0, 90.0, 120.0]);
    builder
        .set_units(serde_json::json!({
            "length": "angstrom",
            "energy": "eV",
            "mass": "amu",
            "time": readcon_core::units::NATURAL_TIME_UNIT,
        }))
        .expect("units");
    let species = ["Cu", "H", "O", "Cu"];
    let coords = [
        [0.0, -0.0, 1.0],
        [f64::MIN_POSITIVE, -f64::MIN_POSITIVE, 1.25e-10],
        [f64::MAX, -f64::MAX, f64::from_bits(1)],
        [-0.0, 2.5, -3.5],
    ];
    let fixed = [
        [true, false, false],
        [false, true, false],
        [false, false, true],
        [true, true, true],
    ];
    let masses = [63.546, 1.008, 15.999, 63.546];
    let velocities = [
        [-0.0, 0.1, -0.2],
        [1.0e-20, -1.0e20, 0.0],
        [f64::MIN_POSITIVE, f64::MAX, -0.0],
        [0.5, -0.5, 0.25],
    ];
    let forces = [
        [0.0, -0.0, 1.5],
        [-2.0, 3.0, -4.0],
        [1.0e-8, -1.0e8, 9.0],
        [f64::from_bits(0x8000_0000_0000_0001), 0.0, 1.0],
    ];
    for index in 0..species.len() {
        builder.add_atom(
            species[index],
            coords[index][0],
            coords[index][1],
            coords[index][2],
            fixed[index],
            10 + index as u64,
            masses[index],
        );
        builder.with_velocity(velocities[index]);
        builder.with_force(forces[index]);
    }
    builder.build().expect("geometry")
}

fn one_atom() -> ConFrame {
    let mut builder = ConFrameBuilder::new([1.0, 2.0, 3.0], [90.0, 80.0, 70.0]);
    builder.add_atom(
        "He",
        -0.0,
        f64::MIN_POSITIVE,
        -1.5e-7,
        [false, false, true],
        7,
        4.0026,
    );
    builder.build().expect("one atom")
}

fn zero_atoms() -> ConFrame {
    ConFrameBuilder::new([4.0, 5.0, 6.0], [90.0, 90.0, 90.0])
        .build()
        .expect("zero atoms")
}

fn expect_parse_error(bytes: &[u8]) -> String {
    let serial = frames_from_bytes(bytes, Some(1)).expect_err("serial accepted damaged input");
    let threaded = frames_from_bytes(bytes, Some(4)).expect_err("threads accepted damaged input");
    let serial_text = serial.to_string();
    let threaded_text = threaded.to_string();
    assert!(!serial_text.is_empty(), "{serial:?}");
    assert!(!threaded_text.is_empty(), "{threaded:?}");
    assert_eq!(
        serial.class_name(),
        threaded.class_name(),
        "{serial_text} vs {threaded_text}"
    );
    let text = std::str::from_utf8(bytes).expect("utf-8");
    let from_text =
        frames_from_text(text, Some(1)).expect_err("text reader accepted damaged input");
    assert_eq!(from_text.class_name(), serial.class_name());
    serial_text
}

#[test]
fn generated_frames_round_trip_across_readers() {
    let frames = vec![geometry(), one_atom(), zero_atoms(), geometry()];
    let bytes = round_trip(&frames);
    let crlf = bytes
        .iter()
        .flat_map(|byte| {
            if *byte == b'\n' {
                vec![b'\r', b'\n']
            } else {
                vec![*byte]
            }
        })
        .collect::<Vec<_>>();
    same_frames(&read_both(&crlf), &frames);

    assert_eq!(*bytes.last().unwrap(), b'\n');
    let mut bare = bytes.clone();
    bare.pop();
    same_frames(&read_both(&bare), &frames);

    let dir = tempfile::tempdir().expect("tempdir");
    let path = dir.path().join("generated.con");
    std::fs::write(&path, &crlf).unwrap();
    let from_file = read_all_frames(&path).expect("path read");
    same_frames(&from_file, &frames);

    let bare_path = dir.path().join("bare.convel");
    std::fs::write(&bare_path, &bare).unwrap();
    let from_bare = read_all_frames(&bare_path).expect("bare path");
    same_frames(&from_bare, &frames);
}

#[test]
fn scientific_notation_and_signed_zero_match_binary64() {
    let frames = vec![one_atom()];
    let bytes = write_frames_to_vec(&frames).unwrap();
    let text = String::from_utf8(bytes).unwrap();
    let marker = "Coordinates of Component 1\n";
    let at = text.find(marker).expect("coordinate label") + marker.len();
    let line_end = text[at..].find('\n').unwrap() + at;
    let mut parts = text[at..line_end]
        .split_whitespace()
        .map(str::to_string)
        .collect::<Vec<_>>();
    assert!(parts.len() >= 5);
    parts[0] = "-0.0e0".into();
    parts[1] = "1.25e-10".into();
    parts[2] = "-1.0E+2".into();
    let rewritten = format!("{}{}{}", &text[..at], parts.join(" "), &text[line_end..]);
    let got = read_both(rewritten.as_bytes());
    assert_eq!(bits(got[0].atom_data[0].x()), (-0.0f64).to_bits());
    assert_eq!(bits(got[0].atom_data[0].y()), bits(1.25e-10));
    assert_eq!(bits(got[0].atom_data[0].z()), bits(-100.0));

    let overflow = rewritten.replacen("-1.0E+2", "1e309", 1);
    let message = expect_parse_error(overflow.as_bytes());
    assert!(
        message.contains("non-finite") || message.contains("invalid"),
        "{message}"
    );
}

#[test]
fn zero_atoms_per_species_is_an_error() {
    let mut frame = one_atom();
    frame.header.natm_types = 2;
    frame.header.natms_per_type = vec![1, 0];
    frame.header.masses_per_type.push(12.0);
    let error =
        write_frames_to_vec(std::slice::from_ref(&frame)).expect_err("writer stored a zero count");
    match error {
        WriteError::Format(ParseError::InvalidCount(message)) => {
            assert!(message.contains(">= 1"), "{message}");
        }
        other => panic!("expected a count error, got {other}"),
    }

    let text = "\
zero count
{\"con_spec_version\":3,\"con_spec_minor\":1,\"units\":{\"length\":\"angstrom\",\"energy\":\"eV\",\"mass\":\"amu\",\"time\":\"fs\"}}
1.0 1.0 1.0
90.0 90.0 90.0
0 0
0 0 0
2
1 0
4.0 12.0
He
Coordinates of Component 1
0.0 0.0 0.0 0 1
";
    let message = expect_parse_error(text.as_bytes());
    assert!(message.contains("count"), "{message}");
}

#[test]
fn truncated_last_frame_is_not_dropped() {
    let first = write_frames_to_vec(&[geometry()]).unwrap();
    let bytes = write_frames_to_vec(&[geometry(), one_atom()]).unwrap();
    assert!(bytes.starts_with(&first));
    let text = std::str::from_utf8(&bytes).unwrap();

    let json_at = text[first.len()..].find('{').expect("second metadata") + first.len();
    let message = expect_parse_error(&bytes[..json_at + 1]);
    assert!(
        message.contains("JSON") || message.contains("ended unexpectedly"),
        "{message}"
    );

    let label = "Coordinates of Component 1\n";
    let coord = text.rfind(label).expect("second coordinates") + label.len();
    let message = expect_parse_error(&bytes[..coord]);
    assert!(message.contains("ended unexpectedly"), "{message}");

    let forces = text.find("Forces of Component 1").expect("forces");
    let message = expect_parse_error(&bytes[..forces]);
    assert!(
        message.contains("force") || message.contains("ended unexpectedly"),
        "{message}"
    );

    let mut torn = bytes.clone();
    torn.extend_from_slice(b"partial frame\n{\"con_spec_version\":3}\n1.0");
    let message = expect_parse_error(&torn);
    assert!(
        message.contains("ended unexpectedly")
            || message.contains("JSON")
            || message.contains("invalid")
            || message.contains("units"),
        "{message}"
    );
}

#[test]
fn same_symbol_components_fixed_flags_and_missing_id_agree() {
    let text = "\
two copper
{\"con_spec_version\":3,\"con_spec_minor\":1,\"units\":{\"length\":\"angstrom\",\"energy\":\"eV\",\"mass\":\"amu\",\"time\":\"fs\"},\"sections\":[\"velocities\",\"forces\"]}
8.0 9.0 10.0
90.0 90.0 90.0
0 0
0 0 0
2
1 1
63.546 63.546
Cu
Coordinates of Component 1
1.5 -2.5 3.5 5
Cu
Coordinates of Component 2
-4.0 0.5 6.0 2 9
\nCu
Velocities of Component 1
0.1 -0.0 0.2 5 0
Cu
Velocities of Component 2
-1.0e-3 2.0e-3 -3.0e-3 2 9
\nCu
Forces of Component 1
1.0 0.0 -1.0 5 0
Cu
Forces of Component 2
-0.0 4.0 -5.0 2 9
";
    let got = read_both(text.as_bytes());
    assert_eq!(got[0].header.natms_per_type, vec![1, 1]);
    assert_eq!(got[0].atom_data[0].symbol.as_ref(), "Cu");
    assert_eq!(got[0].atom_data[1].symbol.as_ref(), "Cu");
    assert_eq!(got[0].atom_data[0].fixed(), [true, false, true]);
    assert_eq!(got[0].atom_data[0].atom_id, 0);
    assert_eq!(got[0].atom_data[1].fixed(), [false, true, false]);
    assert_eq!(got[0].atom_data[1].atom_id, 9);
    assert_eq!(
        bits(got[0].atom_data[0].velocity().unwrap()[1]),
        (-0.0f64).to_bits()
    );
    assert_eq!(
        bits(got[0].atom_data[1].velocity().unwrap()[0]),
        bits(-1.0e-3)
    );
    assert_eq!(
        bits(got[0].atom_data[1].force().unwrap()[0]),
        (-0.0f64).to_bits()
    );
    let again = round_trip(&got);
    assert!(!again.is_empty());
}

#[test]
fn bad_tokens_name_the_problem() {
    let base = write_frames_to_vec(&[one_atom()]).unwrap();
    let text = String::from_utf8(base).unwrap();
    let cases = [
        ("0.0 0.0 0.0 8 1", "fixed"),
        ("nan 0.0 0.0 0 1", "non-finite"),
        ("0.0 1e 0.0 0 1", "invalid"),
        ("0.0 0.0 0.0 +1 1", "fixed"),
    ];
    for (row, needle) in cases {
        let marker = "Coordinates of Component 1\n";
        let at = text.find(marker).unwrap() + marker.len();
        let line_end = text[at..].find('\n').unwrap() + at;
        let damaged = format!("{}{row}{}", &text[..at], &text[line_end..]);
        let message = expect_parse_error(damaged.as_bytes());
        assert!(
            message.to_ascii_lowercase().contains(needle),
            "{row} -> {message}"
        );
    }
}
