//! Property round trip, separator contract, truncated frames, and huge counts.
//!
//! CON-token.3: separators inside a line are spaces or tabs.
//! A carriage return ends a line. It is not a field break.
//! A form feed is neither.
//! The frame skip and the full parse agree on a form-feed line before
//! velocities. A per-type count sum that does not fit in `usize` is
//! `InvalidCount` on the skip path as well as the read path.

use readcon_core::error::ParseError;
use readcon_core::iterators::{ConFrameIterator, count_frames, read_all_frames};
use readcon_core::types::ConFrameBuilder;
use readcon_core::units::NATURAL_TIME_UNIT;
use readcon_core::writer::ConFrameWriter;
use std::io::Cursor;

fn header(body: &str) -> String {
    format!(
        "property\n{{\"con_spec_version\":3,\"con_spec_minor\":1,\"units\":{{\"length\":\"angstrom\",\"energy\":\"eV\",\"mass\":\"amu\",\"time\":\"{NATURAL_TIME_UNIT}\"}}}}\n10.0 10.0 10.0\n90.0 90.0 90.0\npost\npost\n1\n1\n1.0\nH\nCoordinates of Component 1\n{body}\n"
    )
}

fn assert_number_error(text: &str) {
    let err = ConFrameIterator::new(text)
        .next()
        .expect("a frame was started")
        .expect_err("separator is not legal");
    assert!(matches!(err, ParseError::InvalidNumberFormat(_)), "{err:?}");
}

#[test]
fn spaces_and_tabs_separate_fields_and_crlf_is_a_line_ending() {
    let spaced = header("1.5 2.5 3.5 0 4");
    let tabbed = header("1.5\t2.5\t3.5\t0\t4");
    let crlf = header("1.5 2.5 3.5 0 4").replace('\n', "\r\n");
    for text in [spaced, tabbed, crlf] {
        let frame = ConFrameIterator::new(&text)
            .next()
            .expect("frame")
            .expect("parse");
        assert_eq!(frame.atom_data.len(), 1);
        assert_eq!(frame.atom_data[0].x.to_bits(), 1.5f64.to_bits());
        assert_eq!(frame.atom_data[0].y.to_bits(), 2.5f64.to_bits());
        assert_eq!(frame.atom_data[0].z.to_bits(), 3.5f64.to_bits());
        assert_eq!(frame.atom_data[0].atom_id, 4);
    }
}

#[test]
fn form_feed_carriage_return_and_vertical_tab_are_not_separators() {
    assert_number_error(&header("1.0\u{000c}2.0 3.0 0 0"));
    assert_number_error(&header("1.0\r2.0 3.0 0 0"));
    assert_number_error(&header("1.0\u{000b}2.0 3.0 0 0"));
    assert_number_error(&header("1.0 2.0 3.0 0 0\u{00a0}"));
}

#[test]
fn form_feed_line_before_velocities_is_one_frame() {
    let text = format!(
        "property\n{{\"con_spec_version\":2}}\n10.0 10.0 10.0\n90.0 90.0 90.0\npost\npost\n1\n1\n1.0\nH\nCoordinates of Component 1\n1.0 2.0 3.0 0 0\n\u{000c}\nH\nVelocities of Component 1\n4.0 5.0 6.0 0 0\n"
    );
    let frames: Vec<_> = ConFrameIterator::new(&text).collect();
    assert_eq!(frames.len(), 1, "{frames:?}");
    let frame = frames[0].as_ref().expect("parse");
    assert_eq!(
        frame.atom_data[0].velocity().map(|v| v.map(f64::to_bits)),
        Some([4.0, 5.0, 6.0].map(f64::to_bits))
    );
    let dir = tempfile::tempdir().expect("tempdir");
    let path = dir.path().join("ff-blank.convel");
    std::fs::write(&path, &text).expect("write");
    assert_eq!(count_frames(&path).expect("count"), 1);
}

#[test]
fn overflowing_atom_count_is_invalid_on_the_skip_path() {
    let text = "\
overflow
{\"con_spec_version\":2}
10.0 10.0 10.0
90.0 90.0 90.0
post
post
2
9223372036854775808 9223372036854775808
1.0 1.0
Cu
Coordinates of Component 1
0.0 0.0 0.0 0 0
H
";
    let dir = tempfile::tempdir().expect("tempdir");
    let path = dir.path().join("overflow.con");
    std::fs::write(&path, text).expect("write");
    let err = count_frames(&path).expect_err("sum wraps");
    assert!(
        err.to_string().contains("InvalidCount") || err.to_string().contains("does not fit"),
        "{err}"
    );
    let read_err = read_all_frames(&path).expect_err("full read");
    let message = read_err.to_string();
    assert!(
        message.contains("InvalidCount")
            || message.contains("does not fit")
            || message.contains("Incomplete")
            || message.contains("invalid"),
        "{message}"
    );
}

#[test]
fn truncated_frame_is_an_error() {
    let mut text = header("1.0 2.0 3.0 0 0");
    text.push_str(&header("4.0 5.0 6.0 0 1"));
    text.truncate(text.len() - 6);
    let parsed: Vec<_> = ConFrameIterator::new(&text).collect();
    assert!(parsed.len() >= 2, "{parsed:?}");
    assert!(parsed[0].is_ok(), "{:?}", parsed[0]);
    assert!(parsed.last().unwrap().is_err(), "{parsed:?}");
}

#[test]
fn two_frames_with_units_round_trip_bit_for_bit() {
    let mut builder = ConFrameBuilder::new([15.3456, 21.702, 100.0], [90.0, 90.0, 90.0]);
    builder
        .set_metadata_json(r#"{"units":{"length":"angstrom","energy":"eV","mass":"amu"}}"#)
        .expect("metadata");
    builder.add_atom("Cu", 0.6394, -0.0, 6.9753, [true, true, true], 0, 63.546);
    builder.add_atom(
        "H",
        8.6823,
        9.947,
        11.733,
        [false, false, false],
        1,
        1.00784,
    );
    let first = builder.build().expect("build");
    let mut second = first.clone();
    second.atom_data[0].x = -1.25;
    let mut buffer = Vec::new();
    {
        let mut writer = ConFrameWriter::new(Cursor::new(&mut buffer));
        writer.write_frame(&first).expect("write");
        writer.write_frame(&second).expect("write");
        writer.flush().expect("flush");
    }
    let text = String::from_utf8(buffer).expect("utf8");
    let parsed: Vec<_> = ConFrameIterator::new(&text).collect();
    assert_eq!(parsed.len(), 2);
    for (got, expect) in parsed.iter().zip([&first, &second]) {
        let got = got.as_ref().expect("parse");
        assert_eq!(
            got.header.boxl.map(f64::to_bits),
            expect.header.boxl.map(f64::to_bits)
        );
        assert_eq!(
            got.header
                .masses_per_type
                .iter()
                .map(|mass| mass.to_bits())
                .collect::<Vec<_>>(),
            expect
                .header
                .masses_per_type
                .iter()
                .map(|mass| mass.to_bits())
                .collect::<Vec<_>>()
        );
        for (atom, src) in got.atom_data.iter().zip(&expect.atom_data) {
            assert_eq!(atom.x.to_bits(), src.x.to_bits());
            assert_eq!(atom.y.to_bits(), src.y.to_bits());
            assert_eq!(atom.z.to_bits(), src.z.to_bits());
            assert_eq!(atom.fixed, src.fixed);
            assert_eq!(atom.atom_id, src.atom_id);
        }
    }
}

#[test]
fn coordinate_spellings_match_from_str_bits() {
    let rows = [
        ("-0.0", "0.0", "+0"),
        (".5", "5.", "+.5"),
        ("-.5", "+1.5", "1.50"),
        ("1.25e-1", "1e22", "9007199254740992"),
        ("9007199254740993", "1.0000000000000002", "-2.5e-23"),
        ("00.10", "1.", ".25"),
        ("-0.000", "2.5e+1", "1e-22"),
    ];
    for (index, (x, y, z)) in rows.iter().enumerate() {
        let text = header(&format!("{x} {y} {z} 0 {index}"));
        let frame = ConFrameIterator::new(&text)
            .next()
            .unwrap_or_else(|| panic!("no frame for {x} {y} {z}"))
            .unwrap_or_else(|err| panic!("parse {x} {y} {z}: {err}"));
        let atom = &frame.atom_data[0];
        let expect = |token: &str| -> f64 {
            let trimmed = token.trim_start_matches('+');
            trimmed.parse::<f64>().expect(token)
        };
        assert_eq!(atom.x.to_bits(), expect(x).to_bits(), "x={x}");
        assert_eq!(atom.y.to_bits(), expect(y).to_bits(), "y={y}");
        assert_eq!(atom.z.to_bits(), expect(z).to_bits(), "z={z}");
        assert_eq!(atom.atom_id, index as u64);
    }
}

fn xorshift(state: &mut u64) -> u64 {
    *state = state.wrapping_mul(0x9E37_79B9_7F4A_7C15).wrapping_add(1);
    *state
}

fn finite_value(state: &mut u64) -> f64 {
    for _ in 0..16 {
        let bits = xorshift(state);
        let value = f64::from_bits(bits);
        if value.is_finite() {
            return value;
        }
    }
    0.0
}

#[test]
fn random_frames_round_trip_coordinates_masses_and_velocities() {
    let mut state = 0x1234_5678_9abc_def0u64;
    for case in 0..40 {
        let n_types = 1 + (xorshift(&mut state) % 2) as usize;
        let mut builder = ConFrameBuilder::new([12.5, 8.0, 20.0], [90.0, 90.0, 90.0]);
        let with_velocity = case % 2 == 0;
        let time = if with_velocity {
            format!(",\"time\":\"{NATURAL_TIME_UNIT}\"")
        } else {
            String::new()
        };
        builder
            .set_metadata_json(&format!(
                "{{\"units\":{{\"length\":\"angstrom\",\"energy\":\"eV\",\"mass\":\"amu\"{time}}}}}"
            ))
            .expect("metadata");
        let symbols = ["Cu", "H"];
        let mut next_id = 0u64;
        for type_index in 0..n_types {
            let count = 1 + (xorshift(&mut state) % 3) as usize;
            let mass = (xorshift(&mut state) % 10_000) as f64 / 8.0 + 0.125;
            for _ in 0..count {
                let x = finite_value(&mut state);
                let y = finite_value(&mut state);
                let z = finite_value(&mut state);
                let flag = (xorshift(&mut state) % 8) as u8;
                let fixed = [flag & 1 != 0, flag & 2 != 0, flag & 4 != 0];
                builder.add_atom(symbols[type_index], x, y, z, fixed, next_id, mass);
                if with_velocity {
                    builder.with_velocity([
                        finite_value(&mut state),
                        finite_value(&mut state),
                        finite_value(&mut state),
                    ]);
                }
                next_id += 1;
            }
        }
        let frame = builder.build().expect("build");
        let mut buffer = Vec::new();
        {
            let mut writer = ConFrameWriter::new(Cursor::new(&mut buffer));
            writer.write_frame(&frame).expect("write");
            writer.flush().expect("flush");
        }
        let text = String::from_utf8(buffer).expect("utf8");
        let parsed = ConFrameIterator::new(&text)
            .next()
            .expect("frame")
            .expect("parse");
        assert_eq!(parsed.atom_data.len(), frame.atom_data.len());
        assert_eq!(
            parsed
                .header
                .masses_per_type
                .iter()
                .map(|mass| mass.to_bits())
                .collect::<Vec<_>>(),
            frame
                .header
                .masses_per_type
                .iter()
                .map(|mass| mass.to_bits())
                .collect::<Vec<_>>()
        );
        for (got, expect) in parsed.atom_data.iter().zip(&frame.atom_data) {
            assert_eq!(got.x.to_bits(), expect.x.to_bits());
            assert_eq!(got.y.to_bits(), expect.y.to_bits());
            assert_eq!(got.z.to_bits(), expect.z.to_bits());
            assert_eq!(got.atom_id, expect.atom_id);
            assert_eq!(got.fixed, expect.fixed);
            assert_eq!(
                got.velocity().map(|row| row.map(f64::to_bits)),
                expect.velocity().map(|row| row.map(f64::to_bits))
            );
        }
    }
}
