//! Property and clause checks for the conformance corpus.
//!
//! Arbitrary frames written with round-trip floats parse back to the same
//! frame. A legacy file becomes byte-stable after one read-write cycle.

use proptest::prelude::*;
use readcon_core::iterators::ConFrameIterator;
use readcon_core::types::ConFrameBuilder;
use readcon_core::units::NATURAL_TIME_UNIT;
use readcon_core::writer::{ConFrameWriter, FloatFormat};
use std::fs;
use std::path::PathBuf;

fn corpus(rel: &str) -> String {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("resources/conformance")
        .join(rel);
    let contents = readcon_core::compression::read_file_contents(&path)
        .unwrap_or_else(|e| panic!("read {}: {e}", path.display()));
    contents
        .as_str()
        .unwrap_or_else(|e| panic!("utf-8 {}: {e}", path.display()))
        .to_string()
}

fn write_round_trip(frame: &readcon_core::types::ConFrame) -> String {
    let mut buffer = Vec::new();
    {
        let mut writer = ConFrameWriter::with_float_format(&mut buffer, FloatFormat::RoundTrip);
        writer.write_frame(frame).expect("write");
    }
    String::from_utf8(buffer).unwrap()
}

fn read_one(text: &str) -> readcon_core::types::ConFrame {
    let mut iter = ConFrameIterator::new(text);
    let frame = iter.next().unwrap().unwrap();
    assert!(iter.next().is_none());
    frame
}

fn read_all(text: &str) -> Vec<readcon_core::types::ConFrame> {
    ConFrameIterator::new(text)
        .collect::<Result<Vec<_>, _>>()
        .unwrap()
}

proptest! {
    #![proptest_config(ProptestConfig { cases: 32, .. ProptestConfig::default() })]

    #[test]
    fn round_trip_arbitrary_frame(
        n_h in 0usize..3,
        n_cu in 1usize..3,
        length in 6.0f64..24.0,
        angle in 40.0f64..140.0,
        mask_bits in prop::collection::vec(0u8..8, 4),
        ids in prop::collection::vec(any::<u64>(), 4),
        with_velocity in proptest::bool::ANY,
        with_force in proptest::bool::ANY,
        with_energy in proptest::bool::ANY,
        with_charge in proptest::bool::ANY,
        with_spin in proptest::bool::ANY,
        with_magmom in proptest::bool::ANY,
        with_displacement in proptest::bool::ANY,
        with_spread in proptest::bool::ANY,
        with_lattice in proptest::bool::ANY,
        coords in prop::collection::vec(-4.0f64..4.0, 12),
    ) {
        let n = n_h + n_cu;
        prop_assume!(n >= 1);
        let mut meta = serde_json::json!({
            "units": {"length": "angstrom", "energy": "eV", "mass": "amu"},
        });
        if with_velocity {
            meta["units"]["time"] = serde_json::json!(NATURAL_TIME_UNIT);
        }
        if with_lattice {
            meta["pbc"] = serde_json::json!([true, false, true]);
            meta["lattice_vectors"] = serde_json::json!([
                [length, 0.0, 0.0],
                [0.0, length + 1.0, 0.0],
                [0.0, 0.0, length + 2.0],
            ]);
        }
        // A stored lattice wins, and the writer rewrites lines 3-4 from it.
        let angles = if with_lattice {
            [90.0, 90.0, 90.0]
        } else {
            [angle, 90.0, 90.0]
        };
        let mut builder = ConFrameBuilder::new(
            [length, length + 1.0, length + 2.0],
            angles,
        );
        builder.set_metadata_json(&meta.to_string()).unwrap();
        builder.set_con_spec_minor(1);
        for i in 0..n {
            let symbol = if i < n_cu { "Cu" } else { "H" };
            let mass = if symbol == "Cu" { 63.546 } else { 1.00794 };
            let base = i * 3;
            let bits = mask_bits[i];
            let spread = coords[base].abs();
            builder.add_atom(
                symbol,
                coords[base],
                coords[base + 1],
                coords[base + 2],
                [bits & 1 != 0, bits & 2 != 0, bits & 4 != 0],
                ids[i],
                mass,
            );
            if with_velocity {
                builder.with_velocity([coords[base] * 0.01, 0.0, 0.0]);
            }
            if with_force {
                builder.with_force([0.0, coords[base + 1] * 0.01, 0.0]);
            }
            if with_energy {
                builder.with_energy(coords[base]);
            }
            if with_charge {
                builder.with_charge(coords[base + 1] * 0.1);
            }
            if with_spin {
                builder.with_spin(coords[base + 2] * 0.1);
            }
            if with_magmom {
                builder.with_magmom([0.0, coords[base], 0.0]);
            }
            if with_displacement {
                builder.with_displacement([coords[base] * 0.01, 0.0, 0.0]);
            }
            if with_spread {
                builder.with_spread([spread, spread * 0.5, 0.0]);
            }
        }
        let frame = builder.build().unwrap();
        let text = write_round_trip(&frame);
        let again = read_one(&text);
        prop_assert_eq!(again, frame);
    }
}

#[test]
fn legacy_file_is_byte_stable_after_one_rewrite() {
    let original = corpus("valid/v1_plain.con");
    let first = read_all(&original);
    let written = write_round_trip(&first[0]);
    let second = read_all(&written);
    let rewritten = write_round_trip(&second[0]);
    assert_eq!(written.as_bytes(), rewritten.as_bytes());
    assert_eq!(first, second);
}

#[test]
fn unknown_key_survives_rewrite() {
    let text = corpus("valid/unknown_key.con");
    let frame = read_one(&text);
    assert_eq!(
        frame
            .header
            .metadata
            .get("campaign")
            .and_then(|v| v.as_str()),
        Some("slab-42")
    );
    let again = read_one(&write_round_trip(&frame));
    assert_eq!(
        again
            .header
            .metadata
            .get("campaign")
            .and_then(|v| v.as_str()),
        Some("slab-42")
    );
}

#[test]
fn pbc_and_lattice_follow_the_cell_clauses() {
    let missing = read_one(&corpus("valid/header_lines.con"));
    assert_eq!(missing.header.pbc_effective(), [true, true, true]);
    let partial = read_one(&corpus("valid/pbc_partial.con"));
    assert_eq!(partial.header.pbc(), Some([false, true, false]));

    let lattice = read_one(&corpus("valid/lattice_vectors.con"));
    let matrix = lattice.header.cell_matrix();
    assert_eq!(matrix[1][1], 12.0);
    assert_eq!(matrix[2][2], 14.0);
    let from_lengths = read_one(&corpus("valid/cell_angles.con"));
    assert!(from_lengths.header.lattice_vectors().is_none());
    let built = from_lengths.header.cell_matrix();
    assert!(built[0][0] > 0.0 && built[2][2] > 0.0);
}

#[test]
fn spec1_column_four_rejects_two_through_six() {
    let template = corpus("invalid/spec1_mask_2.con");
    for value in 2..=6 {
        let text = template.replacen(" 2 0\n", &format!(" {value} 0\n"), 1);
        let err = ConFrameIterator::new(&text).next().unwrap().unwrap_err();
        assert_eq!(err.class_name(), "InvalidFixedFlag", "{text}");
    }
}

#[test]
fn big_id_is_not_read_through_binary64() {
    let frame = read_one(&corpus("valid/big_id.con"));
    assert_eq!(frame.atom_data[0].atom_id, 9_007_199_254_740_993);
}

#[test]
fn repeated_ids_keep_file_order() {
    let frame = read_one(&corpus("valid/repeated_ids.con"));
    let ids: Vec<u64> = frame.atom_data.iter().map(|a| a.atom_id).collect();
    assert_eq!(ids, vec![5, 5]);
    let positions: Vec<f64> = frame.atom_data.iter().map(|a| a.x).collect();
    assert_eq!(positions, vec![0.0, 1.0]);
}

#[test]
fn unique_ids_define_pregrouping_order() {
    let frame = read_one(&corpus("valid/two_types.con"));
    let mut order: Vec<(u64, f64)> = frame
        .atom_data
        .iter()
        .map(|atom| (atom.atom_id, atom.x))
        .collect();
    order.sort_by_key(|row| row.0);
    let ids: Vec<u64> = order.iter().map(|row| row.0).collect();
    assert_eq!(ids, vec![0, 1, 2]);
}

#[test]
fn blank_line_at_eof_is_not_a_velocity_block() {
    let frames = read_all(&corpus("valid/blank_then_eof.con"));
    assert_eq!(frames.len(), 1);
    assert!(frames[0].atom_data[0].velocity.is_none());
}

#[test]
fn eon_convel_kinetic_energy_matches_the_natural_unit() {
    let text = fs::read_to_string(
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("resources/conformance/foreign/producers.toml"),
    )
    .unwrap();
    let recorded = text
        .lines()
        .find_map(|line| line.trim().strip_prefix("kinetic_energy_ev = "))
        .unwrap()
        .parse::<f64>()
        .unwrap();
    let frame = read_one(&corpus("valid/eon_slab.convel"));
    assert_eq!(frame.header.spec_version, 3);
    assert!(frame.header.metadata.get("con_spec_minor").is_none());
    let mut kinetic = 0.0;
    let mut bound = 0.0;
    let dv = 5e-7;
    let mass = 195.084;
    for atom in &frame.atom_data {
        let vel = atom.velocity.expect("convel velocity");
        for component in vel {
            kinetic += 0.5 * mass * component * component;
            bound += mass * (component.abs() + dv) * dv;
        }
    }
    assert!(
        (kinetic - recorded).abs() <= bound,
        "read {kinetic} eV, eOn printed {recorded} eV, bound {bound}"
    );
    let inflated = kinetic * 10.180505710759414_f64.powi(2);
    assert!((inflated - recorded).abs() > 1.0);
}

#[test]
fn writer_refuses_minor1_velocities_without_time() {
    let frame = read_one(&corpus("valid/v31_velocities.con"));
    let mut stripped = frame.clone();
    if let Some(units) = stripped
        .header
        .metadata
        .get_mut("units")
        .and_then(|value| value.as_object_mut())
    {
        units.remove("time");
    }
    let mut buffer = Vec::new();
    let mut writer = ConFrameWriter::with_float_format(&mut buffer, FloatFormat::RoundTrip);
    let err = writer.write_frame(&stripped).unwrap_err();
    let message = err.to_string();
    assert!(
        message.contains("InvalidUnits") || message.to_ascii_lowercase().contains("time"),
        "{message}"
    );
}
