//! Clauses added with specification 4.0.4.

use readcon_core::error::ParseError;
use readcon_core::iterators::ConFrameIterator;
use readcon_core::units::{
    HISTORICAL_NATURAL_TIME, NATURAL_TIME_UNIT, unit_conversion_factor,
    unit_conversion_factor_for_version, validate_unit_for_quantity,
};

fn class_of(text: &str) -> String {
    match ConFrameIterator::new(text).next() {
        Some(Err(err)) => err.class_name().to_string(),
        Some(Ok(_)) => "ok".into(),
        None => "empty".into(),
    }
}

fn frame(line2: &str, row: &str) -> String {
    format!("t\n{line2}\n10 10 10\n90 90 90\n\n\n1\n1\n1\nH\nCoordinates of Component 1\n{row}\n")
}

/// CON-mask.8. Bit 0 is x, bit 1 is y, and bit 2 is z.
#[test]
fn con_mask_8_bit_order() {
    let text = frame(
        r#"{"con_spec_version":4,"units":{"length":"angstrom","energy":"eV"}}"#,
        "0 0 0 1 0",
    );
    let parsed = ConFrameIterator::new(&text).next().unwrap().unwrap();
    assert_eq!(parsed.atom_data[0].fixed(), [true, false, false]);
    let y = frame(
        r#"{"con_spec_version":4,"units":{"length":"angstrom","energy":"eV"}}"#,
        "0 0 0 2 0",
    );
    let parsed = ConFrameIterator::new(&y).next().unwrap().unwrap();
    assert_eq!(parsed.atom_data[0].fixed(), [false, true, false]);
    let z = frame(
        r#"{"con_spec_version":4,"units":{"length":"angstrom","energy":"eV"}}"#,
        "0 0 0 4 0",
    );
    let parsed = ConFrameIterator::new(&z).next().unwrap().unwrap();
    assert_eq!(parsed.atom_data[0].fixed(), [false, false, true]);
}

/// CON-coord.2. A coordinate block is a symbol, the label, and one row.
#[test]
fn con_coord_2_block_shape() {
    let text = frame(
        r#"{"con_spec_version":4,"units":{"length":"angstrom","energy":"eV"}}"#,
        "0 0 0 0 0",
    );
    assert_eq!(class_of(&text), "ok");
    let missing = "t\n{\"con_spec_version\":4,\"units\":{\"length\":\"angstrom\",\"energy\":\"eV\"}}\n10 10 10\n90 90 90\n\n\n1\n1\n1\nH\n0 0 0 0 0\n";
    assert_ne!(class_of(missing), "ok");
}

/// CON-section.25. The reserved names are the section table.
#[test]
fn con_section_25_reserved_table() {
    let spec = include_str!("../docs/orgmode/spec.org");
    let clause = spec
        .lines()
        .find(|line| line.starts_with("- CON-section.25"))
        .expect("clause");
    for name in [
        "velocities",
        "forces",
        "energies",
        "charges",
        "spins",
        "magmoms",
        "displacements",
        "spreads",
    ] {
        assert!(clause.contains(name), "{name}");
    }
}

/// CON-bonds.4. The index is the coordinate-block position, not column 5.
#[test]
fn con_bonds_4_index_is_not_the_column_id() {
    let text = "\
t
{\"con_spec_version\":3,\"units\":{\"length\":\"angstrom\",\"energy\":\"eV\"},\"bonds\":[[0,0]]}
10 10 10
90 90 90


1
1
1
H
Coordinates of Component 1
0 0 0 0 7
";
    let parsed = ConFrameIterator::new(text).next().unwrap().unwrap();
    let bonds = parsed.header.bonds();
    assert_eq!(bonds.len(), 1);
    assert_eq!((bonds[0].i, bonds[0].j), (0, 0));
    assert_eq!(parsed.atom_data[0].atom_id, 7);
}

/// CON-units.21. units.velocity follows the time the version assigns.
#[test]
fn con_units_21_velocity_follows_the_assigned_time() {
    let consistent = frame(
        r#"{"con_spec_version":4,"units":{"length":"nm","energy":"eV","time":"ps","velocity":"nm/ps"},"sections":["velocities"]}"#,
        "0 0 0 0 0",
    );
    let with_velocity = format!("{consistent}\nH\nVelocities of Component 1\n0.1 0.2 0.3 0 0\n");
    assert_eq!(class_of(&with_velocity), "ok");
    let disagree = frame(
        r#"{"con_spec_version":4,"units":{"length":"angstrom","energy":"eV","time":"ps","velocity":"angstrom/fs"},"sections":["velocities"]}"#,
        "0 0 0 0 0",
    );
    let disagree = format!("{disagree}\nH\nVelocities of Component 1\n0.1 0.2 0.3 0 0\n");
    assert_eq!(class_of(&disagree), "InvalidUnits");
    let lying = frame(
        r#"{"con_spec_version":3,"units":{"length":"angstrom","energy":"eV","time":"fs","velocity":"angstrom/fs"},"sections":["velocities"]}"#,
        "0 0 0 0 0",
    );
    let lying = format!("{lying}\nH\nVelocities of Component 1\n0.1 0.2 0.3 0 0\n");
    assert_eq!(class_of(&lying), "InvalidUnits");
    let con3 = frame(
        r#"{"con_spec_version":3,"units":{"length":"angstrom","energy":"eV","time":"fs","velocity":"angstrom/(amu*angstrom^2/eV)^0.5"},"sections":["velocities"]}"#,
        "0 0 0 0 0",
    );
    let con3 = format!("{con3}\nH\nVelocities of Component 1\n0.1 0.2 0.3 0 0\n");
    assert_eq!(class_of(&con3), "ok");
}

/// CON-units.5 and CON-units.16. The two natural spellings match, and a, ha, da do not fold.
#[test]
fn con_units_16_symbols_are_case_sensitive() {
    let symbol = unit_conversion_factor(NATURAL_TIME_UNIT, "fs").unwrap();
    let historical = unit_conversion_factor(HISTORICAL_NATURAL_TIME, "fs").unwrap();
    assert!((symbol - historical).abs() < 1e-12);
    assert!(validate_unit_for_quantity("mass", "Da").is_ok());
    assert!(validate_unit_for_quantity("length", "a").is_err());
    assert!(validate_unit_for_quantity("energy", "ha").is_err());
    assert!(validate_unit_for_quantity("mass", "da").is_err());
    let _ = ParseError::InvalidUnits("marker".into());
}

/// CON-units.16. SI prefixes remain case-sensitive in every major.
#[test]
fn con_units_16_con3_mev_spellings_are_case_sensitive() {
    let mega = unit_conversion_factor_for_version(3, "MeV", "eV").unwrap();
    assert!((mega - 1.0e6).abs() < 1.0e-6);
    let milli = unit_conversion_factor_for_version(3, "mev", "eV").unwrap();
    assert!((milli - 1.0e-3).abs() < 1.0e-12);
    for unknown in ["MEV", "Mev", "mEV"] {
        assert!(
            unit_conversion_factor_for_version(3, unknown, "eV").is_err(),
            "{unknown}"
        );
    }
}

/// CON-status.8. Requirement words are uppercase, and RFC 8174 is cited.
#[test]
fn con_status_8_uppercase_keywords() {
    let spec = include_str!("../docs/orgmode/spec.org");
    assert!(spec.contains("CON-status.8"));
    assert!(spec.contains("RFC 8174"));
}
