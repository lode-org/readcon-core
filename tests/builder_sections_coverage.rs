//! Displacement and spread sections on the frame builder, and the
//! positions-reusing frame constructor with every optional section set.

use readcon_core::error::ParseError;
use readcon_core::storage_dtype::FloatArray2;
use readcon_core::types::{
    AtomDatum, ConFrameBuilder, con_frame_from_atom_data, con_frame_from_atom_data_with_positions,
};

fn builder(n: usize) -> ConFrameBuilder {
    let mut b = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
    for i in 0..n {
        b.add_atom("Cu", i as f64, 0.5, 1.5, [false; 3], i as u64, 63.546);
    }
    b
}

#[test]
fn displacements_set_read_and_build() {
    let mut b = builder(3);
    assert_eq!(b.get_atom_displacement(1).unwrap(), None);
    assert!(b.displacements().is_empty());
    assert!(matches!(
        b.set_displacements_from_flat(&[0.0; 5]),
        Err(ParseError::InvalidVectorLength { expected: 9, found: 5 })
    ));
    let flat = [0.1, 0.2, 0.3, 1.1, 1.2, 1.3, 2.1, 2.2, 2.3];
    b.set_displacements_from_flat(&flat).unwrap();
    assert_eq!(b.displacements(), &flat);
    assert_eq!(b.get_atom_displacement(2).unwrap(), Some([2.1, 2.2, 2.3]));
    assert!(matches!(
        b.get_atom_displacement(3),
        Err(ParseError::IndexOutOfBounds { index: 3, len: 3 })
    ));
    b.displacements_mut()[0] = 9.0;
    assert_eq!(b.get_atom_displacement(0).unwrap(), Some([9.0, 0.2, 0.3]));
    assert_eq!(b.displacements_view().shape(), &[3, 3]);
    let frame = b.build().unwrap();
    assert_eq!(frame.displacements.nrows(), 3);
}

#[test]
fn displacements_mut_allocates_the_section() {
    let mut b = builder(2);
    assert_eq!(b.displacements_mut().len(), 6);
    assert_eq!(b.get_atom_displacement(1).unwrap(), Some([0.0; 3]));
}

#[test]
fn spreads_validate_set_read_and_build() {
    let mut b = builder(2);
    assert_eq!(b.get_atom_spread(0).unwrap(), None);
    assert!(b.spreads().is_empty());
    assert!(matches!(
        b.set_spreads_from_flat(&[0.0; 4]),
        Err(ParseError::InvalidVectorLength { expected: 6, found: 4 })
    ));
    // A negative or non-finite spread is refused before any write.
    assert!(matches!(
        b.set_spreads_from_flat(&[0.1, 0.1, 0.1, 0.1, -0.1, 0.1]),
        Err(ParseError::ValidationError(_))
    ));
    assert!(b.set_spreads_from_flat(&[0.1, 0.1, f64::NAN, 0.1, 0.1, 0.1]).is_err());
    assert!(b.spreads().is_empty());
    let flat = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6];
    b.set_spreads_from_flat(&flat).unwrap();
    assert_eq!(b.spreads(), &flat);
    assert_eq!(b.get_atom_spread(1).unwrap(), Some([0.4, 0.5, 0.6]));
    assert!(matches!(
        b.get_atom_spread(2),
        Err(ParseError::IndexOutOfBounds { index: 2, len: 2 })
    ));
    b.spreads_mut()[5] = 0.7;
    assert_eq!(b.get_atom_spread(1).unwrap(), Some([0.4, 0.5, 0.7]));
    assert_eq!(b.spreads_view().shape(), &[2, 3]);
    let frame = b.build().unwrap();
    assert_eq!(frame.spreads.nrows(), 2);
}

#[test]
fn spreads_mut_allocates_the_section() {
    let mut b = builder(1);
    assert_eq!(b.spreads_mut().len(), 3);
    assert_eq!(b.get_atom_spread(0).unwrap(), Some([0.0; 3]));
}

fn sectioned_atoms(n: usize) -> Vec<AtomDatum> {
    (0..n)
        .map(|i| {
            let f = i as f64;
            let mut a = AtomDatum::coords("Cu", f, 0.5, 1.5, [false; 3], i as u64);
            a.set_velocity(Some([f, 1.0, 2.0]));
            a.set_force(Some([-f, -1.0, -2.0]));
            a.set_energy(Some(0.25 * f));
            a.set_charge(Some(0.5 * f));
            a.set_spin(Some(-0.5 * f));
            a.set_magmom(Some([0.0, 0.0, f]));
            a.set_displacement(Some([0.1 * f, 0.0, 0.0]));
            a.set_spread(Some([0.2, 0.2, 0.2 + f]));
            a
        })
        .collect()
}

#[test]
fn positions_reusing_constructor_fills_every_section() {
    let template = builder(3).build().unwrap();
    let atoms = sectioned_atoms(3);
    let positions = FloatArray2::from_f64_row_major(
        3,
        3,
        atoms.iter().flat_map(|a| [a.x, a.y, a.z]).collect(),
    );
    let frame =
        con_frame_from_atom_data_with_positions(template.header.clone(), atoms.clone(), positions);
    assert_eq!(frame.positions.as_f64_row(2), [2.0, 0.5, 1.5]);
    assert_eq!(frame.velocities.as_f64_row(1), [1.0, 1.0, 2.0]);
    assert_eq!(frame.forces.as_f64_row(2), [-2.0, -1.0, -2.0]);
    assert_eq!(frame.atom_energies.get_f64(2), 0.5);
    assert_eq!(frame.charges.get_f64(1), 0.5);
    assert_eq!(frame.spins.get_f64(2), -1.0);
    assert_eq!(frame.magmoms.as_f64_row(2), [0.0, 0.0, 2.0]);
    assert_eq!(frame.displacements.as_f64_row(1), [0.1, 0.0, 0.0]);
    assert_eq!(frame.spreads.as_f64_row(2), [0.2, 0.2, 2.2]);
    assert_eq!(frame.masses.get_f64(0), 63.546);
    assert_eq!(frame.atom_ids.to_vec(), vec![0, 1, 2]);

    // The AoS constructor agrees section for section.
    let reference = con_frame_from_atom_data(template.header.clone(), atoms);
    for i in 0..3 {
        assert_eq!(frame.velocities.as_f64_row(i), reference.velocities.as_f64_row(i));
        assert_eq!(frame.spreads.as_f64_row(i), reference.spreads.as_f64_row(i));
        assert_eq!(frame.atom_energies.get_f64(i), reference.atom_energies.get_f64(i));
    }
}

#[test]
fn positions_reusing_constructor_without_sections() {
    let template = builder(2).build().unwrap();
    let atoms: Vec<AtomDatum> = (0..2)
        .map(|i| AtomDatum::coords("Cu", i as f64, 0.5, 1.5, [false; 3], i as u64))
        .collect();
    let positions = FloatArray2::from_f64_row_major(2, 3, vec![0.0, 0.5, 1.5, 1.0, 0.5, 1.5]);
    let frame = con_frame_from_atom_data_with_positions(template.header.clone(), atoms, positions);
    assert_eq!(frame.velocities.nrows(), 0);
    assert_eq!(frame.spreads.nrows(), 0);
    assert_eq!(frame.positions.as_f64_row(1), [1.0, 0.5, 1.5]);
}
