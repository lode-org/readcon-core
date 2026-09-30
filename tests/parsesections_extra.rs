//! Parse/write optional charges, spins, magmoms, displacements sections on the v2 surface.
mod common;
use readcon_core::iterators::ConFrameIterator;
use readcon_core::writer::ConFrameWriter;
use std::fs;
use std::path::Path;

#[test]
fn parse_charges_spins_magmoms() {
    let fdat =
        fs::read_to_string(test_case!("tiny_cuh2_charges_spins_magmoms.con")).expect("fixture");
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
    assert_eq!(frame.header.sections, vec!["charges", "spins", "magmoms"]);
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
    let fdat =
        fs::read_to_string(test_case!("tiny_cuh2_charges_spins_magmoms.con")).expect("fixture");
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
    assert!(!f.has_displacements());
    assert!(f.atom_data.iter().all(|a| a.charge.is_none()));
}

#[test]
fn builder_authors_charges_spins_magmoms() {
    use readcon_core::types::ConFrameBuilder;
    let mut b = ConFrameBuilder::new([10.0; 3], [90.0; 3]);
    b.add_atom("Cu", 0.0, 0.0, 0.0, [false; 3], 0, 63.546)
        .with_charge(0.5)
        .with_spin(1.0)
        .with_magmom([0.0, 0.0, 1.0]);
    let frame = b.build().expect("build");
    assert!(frame.has_charges());
    assert!(frame.has_spins());
    assert!(frame.has_magmoms());
    assert_eq!(frame.header.sections, vec!["charges", "spins", "magmoms"]);
    assert_eq!(frame.atom_data[0].charge, Some(0.5));
    assert_eq!(frame.atom_data[0].spin, Some(1.0));
    assert_eq!(frame.atom_data[0].magmom, Some([0.0, 0.0, 1.0]));
}

#[test]
fn parse_displacements() {
    let fdat = fs::read_to_string(test_case!("tiny_cuh2_displacements.con")).expect("fixture");
    let frames: Vec<_> = ConFrameIterator::new(&fdat)
        .map(|r| r.expect("parse"))
        .collect();
    assert_eq!(frames.len(), 1);
    let frame = &frames[0];
    assert!(!frame.has_magmoms());
    assert!(frame.has_displacements());
    assert_eq!(frame.header.sections, vec!["displacements"]);
    assert_eq!(frame.atom_data[0].displacement, Some([0.0, 0.0, 0.0]));
    assert_eq!(frame.atom_data[2].displacement, Some([0.125, -0.25, 0.0]));
    assert_eq!(frame.atom_data[3].displacement, Some([-0.125, 0.25, 0.0]));
    assert!(frame.atom_data.iter().all(|a| a.magmom.is_none()));
    // SoA sync on iterator path
    assert_eq!(frame.displacements.nrows(), 4);
    assert_eq!(frame.displacements.as_f64_row(2), [0.125, -0.25, 0.0]);
}

#[test]
fn displacements_roundtrip() {
    let fdat = fs::read_to_string(test_case!("tiny_cuh2_displacements.con")).expect("fixture");
    let original: Vec<_> = ConFrameIterator::new(&fdat)
        .map(|r| r.expect("parse"))
        .collect();

    let mut buffer: Vec<u8> = Vec::new();
    {
        let mut writer = ConFrameWriter::with_precision(&mut buffer, 17);
        writer.extend(original.iter()).expect("write");
    }
    let rt = String::from_utf8(buffer).unwrap();
    assert!(rt.contains("Displacements of Component 2"));
    let round: Vec<_> = ConFrameIterator::new(&rt)
        .map(|r| r.expect("reparse"))
        .collect();
    assert_eq!(original.len(), round.len());
    assert_eq!(original, round);
}

#[test]
fn builder_authors_displacements_after_magmoms() {
    use readcon_core::types::ConFrameBuilder;
    let mut b = ConFrameBuilder::new([10.0; 3], [90.0; 3]);
    b.add_atom("Cu", 0.0, 0.0, 0.0, [false; 3], 0, 63.546)
        .with_magmom([0.0, 0.0, 1.0])
        .with_displacement([0.1, -0.2, 0.3]);
    b.add_atom("Cu", 1.0, 0.0, 0.0, [false; 3], 1, 63.546);
    let frame = b.build().expect("build");
    assert!(frame.has_magmoms());
    assert!(frame.has_displacements());
    assert_eq!(frame.header.sections, vec!["magmoms", "displacements"]);
    assert_eq!(frame.atom_data[0].displacement, Some([0.1, -0.2, 0.3]));
    // Later atoms are zero-filled so the section stays length-coherent.
    assert_eq!(frame.atom_data[1].displacement, Some([0.0, 0.0, 0.0]));
}

/// Drops the final data row; the last declared section then has one row
/// fewer than the header's atom count.
fn drop_last_row(text: &str) -> String {
    let mut lines: Vec<&str> = text.lines().collect();
    lines.pop();
    let mut out = lines.join("\n");
    out.push('\n');
    out
}

#[test]
fn short_magmoms_and_displacements_sections_reject_alike() {
    for (fixture, section) in [
        ("tiny_cuh2_charges_spins_magmoms.con", "magmoms"),
        ("tiny_cuh2_displacements.con", "displacements"),
    ] {
        let fdat = fs::read_to_string(test_case!(fixture)).expect("fixture");
        let short = drop_last_row(&fdat);
        let err = ConFrameIterator::new(&short)
            .next()
            .expect("one result")
            .expect_err("short section must be rejected");
        assert!(
            matches!(
                &err,
                readcon_core::error::ParseError::IncompleteSection(name) if name == section
            ),
            "{fixture}: got {err:?}"
        );
    }
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
