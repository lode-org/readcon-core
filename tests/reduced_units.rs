use std::collections::BTreeMap;

use readcon_core::iterators::ConFrameIterator;
use readcon_core::types::ConFrameBuilder;
use readcon_core::units::{
    Dimension, canonicalize_units_metadata, parse_unit_expression, unit_conversion_factor,
    validate_unit_for_quantity, validate_v3_units_metadata,
};
use readcon_core::writer::ConFrameWriter;

#[test]
fn reduced_units_keep_their_declared_dimensions() {
    for (quantity, unit) in [
        ("length", "sigma"),
        ("energy", "epsilon"),
        ("force", "epsilon / sigma"),
        ("time", "(amu * sigma^2 / epsilon)^0.5"),
    ] {
        validate_unit_for_quantity(quantity, unit).unwrap();
    }
    assert!(validate_unit_for_quantity("length", "epsilon").is_err());
    assert!(validate_unit_for_quantity("energy", "sigma").is_err());
    assert!(validate_unit_for_quantity("time", "epsilon / sigma").is_err());
    let units = serde_json::json!({"length": "sigma", "energy": "epsilon"});
    validate_v3_units_metadata(&units).unwrap();
    assert_eq!(canonicalize_units_metadata(&units).unwrap(), units);
}

#[test]
fn reduced_conversions_require_matching_reference_scales() {
    for (from, to) in [
        ("sigma", "sigma"),
        ("epsilon", "epsilon"),
        ("EPSILON / SIGMA", "epsilon / sigma"),
        ("epsilon * sigma / sigma", "epsilon"),
        ("(epsilon / sigma)^2", "epsilon^2 / sigma^2"),
        ("sigma^0.1 * sigma^0.2", "sigma^0.3"),
    ] {
        assert_eq!(unit_conversion_factor(from, to).unwrap(), 1.0);
    }
    let length_factor = unit_conversion_factor("sigma * nm / angstrom", "sigma").unwrap();
    assert!((length_factor - 10.0).abs() < 1e-12);
    let energy_factor = unit_conversion_factor("epsilon * meV / eV", "epsilon").unwrap();
    assert!((energy_factor - 0.001).abs() < 1e-15);
}

#[test]
fn reduced_scales_cannot_be_assigned_physical_values() {
    for (reduced, physical) in [
        ("sigma", "angstrom"),
        ("epsilon", "eV"),
        ("epsilon / sigma", "eV / angstrom"),
        ("(amu * sigma^2 / epsilon)^0.5", "fs"),
        ("sigma^0.000000000001", "angstrom^0.000000000001"),
    ] {
        assert!(unit_conversion_factor(reduced, physical).is_err());
        assert!(unit_conversion_factor(physical, reduced).is_err());
        assert!(parse_unit_expression(reduced).is_err());
    }
}

#[test]
fn cancelled_references_have_a_physical_factor() {
    let (factor, dimension) = parse_unit_expression("sigma / sigma * angstrom").unwrap();
    assert_eq!(factor, 1e-10);
    assert_eq!(dimension, Dimension::LENGTH);
}

#[test]
fn con_roundtrip_preserves_reduced_units_and_values() {
    let units = serde_json::json!({"length": "sigma", "energy": "epsilon"});
    let mut builder = ConFrameBuilder::new([10.0; 3], [90.0; 3]);
    builder.metadata(BTreeMap::from([("units".into(), units.clone())]));
    builder.set_energy(-1.25);
    builder.add_atom("H", 1.5, 2.5, 3.5, [false; 3], 0, 1.0);
    let original = builder.build().unwrap();
    let mut bytes = Vec::new();
    ConFrameWriter::new(&mut bytes).write_frame(&original).unwrap();
    let text = String::from_utf8(bytes).unwrap();
    let mut frames = ConFrameIterator::new(&text);
    let restored = frames.next().unwrap().unwrap();
    assert!(frames.next().is_none());
    assert_eq!(restored.header.metadata.get("units"), Some(&units));
    assert_eq!(restored.header.energy().unwrap().to_bits(), (-1.25_f64).to_bits());
    assert_eq!(restored.atom_data[0].x.to_bits(), 1.5_f64.to_bits());
    assert_eq!(restored.atom_data[0].y.to_bits(), 2.5_f64.to_bits());
    assert_eq!(restored.atom_data[0].z.to_bits(), 3.5_f64.to_bits());
}
