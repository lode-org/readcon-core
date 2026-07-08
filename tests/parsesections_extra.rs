//! Parse/write optional charges, spins, magmoms sections on the v2 surface.
mod common;
use readcon_core::iterators::ConFrameIterator;
use readcon_core::writer::ConFrameWriter;
use std::fs;
use std::path::Path;

#[test]
fn parse_charges_spins_magmoms() {
    let fdat = fs::read_to_string(test_case!("tiny_cuh2_charges_spins_magmoms.con"))
        .expect("fixture");
    let frames: Vec<_> = ConFrameIterator::new(&fdat)
        .map(|r| r.expect("parse"))
        .collect();
    assert_eq!(frames.len(), 1);
    let frame = &frames[0];
    assert!(!frame.has_velocities());
    assert!(!frame.has_forces());
    assert!(!frame.has_energies());
    assert!(frame.has_charges());
    assert!(frame.has_spins());
    assert!(frame.has_magmoms());
    assert_eq!(
        frame.header.sections,
        vec!["charges", "spins", "magmoms"]
    );
    assert_eq!(frame.atom_data[0].charge, Some(0.5));
    assert_eq!(frame.atom_data[1].charge, Some(-0.25));
    assert_eq!(frame.atom_data[2].charge, Some(0.1));
    assert_eq!(frame.atom_data[0].spin, Some(0.5));
    assert_eq!(frame.atom_data[2].spin, Some(0.0));
    assert_eq!(frame.atom_data[0].magmom, Some([0.0, 0.0, 1.0]));
    assert_eq!(frame.atom_data[1].magmom, Some([0.0, 0.0, -1.0]));
    // SoA sync on iterator path
    assert_eq!(frame.charges.len(), 4);
    assert_eq!(frame.spins.len(), 4);
    assert_eq!(frame.magmoms.nrows(), 4);
    assert!((frame.charges.get_f64(0) - 0.5).abs() < 1e-12);
}

#[test]
fn charges_spins_magmoms_roundtrip() {
    let fdat = fs::read_to_string(test_case!("tiny_cuh2_charges_spins_magmoms.con"))
        .expect("fixture");
    let original: Vec<_> = ConFrameIterator::new(&fdat)
        .map(|r| r.expect("parse"))
        .collect();

    let mut buffer: Vec<u8> = Vec::new();
    {
        let mut writer = ConFrameWriter::with_precision(&mut buffer, 17);
        writer.extend(original.iter()).expect("write");
    }
    let rt = String::from_utf8(buffer).unwrap();
    let round: Vec<_> = ConFrameIterator::new(&rt)
        .map(|r| r.expect("reparse"))
        .collect();
    assert_eq!(original.len(), round.len());
    assert_eq!(original, round);
}

#[test]
fn coords_only_still_ok_without_new_sections() {
    let fdat = fs::read_to_string(test_case!("tiny_cuh2.con")).expect("fixture");
    let frames: Vec<_> = ConFrameIterator::new(&fdat)
        .map(|r| r.expect("parse"))
        .collect();
    assert_eq!(frames.len(), 1);
    let f = &frames[0];
    assert!(!f.has_charges());
    assert!(!f.has_spins());
    assert!(!f.has_magmoms());
    assert!(f.atom_data.iter().all(|a| a.charge.is_none()));
}

#[test]
fn unknown_section_still_errors() {
    let bad = r#"Random Number Seed
{"con_spec_version":2,"sections":["not_a_real_section"]}
10.0 10.0 10.0
90.0 90.0 90.0
0 0
0 0
1
1
1.0
H
Coordinates of Component 1
0.0 0.0 0.0 0 0
"#;
    let err = ConFrameIterator::new(bad)
        .next()
        .expect("one result")
        .expect_err("unknown section");
    assert!(
        err.to_string().contains("unknown section")
            || err.to_string().contains("not_a_real_section"),
        "got: {err}"
    );
}
