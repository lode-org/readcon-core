//! Atom-id correspondence: a Claisen-like regrouping and a renumbered band.
//!
//! Positional zip is the wrong displacement. Matching column 5 is the
//! right one. The band check names the first frame that breaks the ids.

use readcon_core::correspondence::IdentityCheck;
use readcon_core::ffi::{
    RKRConFrame, RKRStatus, free_rkr_frame, rkr_frame_atom_id_permutation,
    rkr_frame_minimum_image_displacements, rkr_frame_reorder_like, rkr_frames_check_atom_ids,
    rkr_last_error_message,
};
use readcon_core::iterators::ConFrameIterator;
use readcon_core::storage_dtype::{FloatArray1, FloatArray2};
use readcon_core::types::{Bond, ConFrame, ConFrameBuilder};
use readcon_core::writer::write_frames_to_string;
use readcon_core::{
    CorrespondenceError, atom_id_permutation, check_atom_id_consistency, minimum_image_delta,
    minimum_image_displacements, reorder_like,
};
use std::ffi::CStr;

const CELL: f64 = 18.0;
const MASS_C: f64 = 12.011;
const MASS_O: f64 = 15.999;
const MASS_H: f64 = 1.008;

fn add(a: [f64; 3], b: [f64; 3]) -> [f64; 3] {
    [a[0] + b[0], a[1] + b[1], a[2] + b[2]]
}

fn sub(a: [f64; 3], b: [f64; 3]) -> [f64; 3] {
    [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
}

fn scale(a: [f64; 3], s: f64) -> [f64; 3] {
    [a[0] * s, a[1] * s, a[2] * s]
}

fn norm(a: [f64; 3]) -> f64 {
    (a[0] * a[0] + a[1] * a[1] + a[2] * a[2]).sqrt()
}

fn unit(a: [f64; 3]) -> [f64; 3] {
    scale(a, 1.0 / norm(a))
}

fn rot_z(v: [f64; 3], deg: f64) -> [f64; 3] {
    let (s, c) = deg.to_radians().sin_cos();
    [c * v[0] - s * v[1], s * v[0] + c * v[1], v[2]]
}

fn dist(a: [f64; 3], b: [f64; 3]) -> f64 {
    norm(sub(a, b))
}

fn h_at(origin: [f64; 3], dir: [f64; 3]) -> [f64; 3] {
    add(origin, scale(unit(dir), 1.09))
}

#[derive(Clone)]
struct Placed {
    symbol: &'static str,
    id: u64,
    pos: [f64; 3],
    mass: f64,
}

/// Allyl vinyl ether, C5H8O, and the 4-pentenal product of a Claisen
/// rearrangement. The product writer emits oxygen before carbon. C5 is
/// stored one cell along +x from the geometry the bonds describe.
struct Claisen {
    reactant: Vec<Placed>,
    product: Vec<Placed>,
    /// Product coordinates before the periodic image of C5.
    product_unwrapped: Vec<Placed>,
    c5_reactant: [f64; 3],
    c5_true: [f64; 3],
    oxygen_shift: f64,
}

fn claisen() -> Claisen {
    let c1 = [3.0, 4.0, 4.0];
    let c2 = add(c1, [1.336, 0.0, 0.0]);
    let o = add(c2, scale(rot_z([1.0, 0.0, 0.0], 60.0), 1.360));
    let c3 = add(o, scale(rot_z(unit(sub(o, c2)), 65.0), 1.430));
    let c4 = add(c3, scale(rot_z(unit(sub(c3, o)), -70.0), 1.504));
    let c5 = add(c4, scale(rot_z(unit(sub(c4, c3)), 56.0), 1.336));

    let c2_p = c2;
    let o_p = add(c2_p, scale(unit(sub(o, c2)), 1.210));
    let c1_p = add(c1, [0.04, 0.02, 0.0]);
    let c5_true = add(c1_p, scale(rot_z(unit(sub(c1, c2)), -80.0), 1.540));
    let c5_stored = add(c5_true, [CELL, 0.0, 0.0]);
    let c4_p = add(c5_true, scale(rot_z(unit(sub(c5_true, c1_p)), 70.0), 1.504));
    let c3_p = add(c4_p, scale(rot_z(unit(sub(c4_p, c5_true)), 60.0), 1.336));

    let reactant_h = hydrogens([c1, c2, c3, c4, c5]);
    let product_h = hydrogens([c1_p, c2_p, c3_p, c4_p, c5_true]);

    let heavy = |id: u64, symbol: &'static str, pos: [f64; 3], mass: f64| Placed {
        symbol,
        id,
        pos,
        mass,
    };
    let reactant_heavy = [
        heavy(0, "C", c1, MASS_C),
        heavy(1, "C", c2, MASS_C),
        heavy(3, "C", c3, MASS_C),
        heavy(4, "C", c4, MASS_C),
        heavy(5, "C", c5, MASS_C),
        heavy(2, "O", o, MASS_O),
    ];
    let product_heavy_true = [
        heavy(2, "O", o_p, MASS_O),
        heavy(0, "C", c1_p, MASS_C),
        heavy(1, "C", c2_p, MASS_C),
        heavy(3, "C", c3_p, MASS_C),
        heavy(4, "C", c4_p, MASS_C),
        heavy(5, "C", c5_true, MASS_C),
    ];
    let mut product_heavy = product_heavy_true.clone();
    product_heavy[5].pos = c5_stored;

    let mut reactant = reactant_heavy.to_vec();
    reactant.extend(reactant_h);
    let mut product = product_heavy.to_vec();
    product.extend(product_h.clone());
    let mut product_unwrapped = product_heavy_true.to_vec();
    product_unwrapped.extend(product_h);

    Claisen {
        reactant,
        product,
        product_unwrapped,
        c5_reactant: c5,
        c5_true,
        oxygen_shift: 1.360 - 1.210,
    }
}

fn hydrogens(c: [[f64; 3]; 5]) -> Vec<Placed> {
    // Two on C1, one on C2, two on C3, one on C4, two on C5. Ids 6..13.
    let sites = [
        (6, c[0], [-0.4, 0.6, 0.7]),
        (7, c[0], [-0.4, -0.7, 0.5]),
        (8, c[1], [0.2, 0.3, -1.0]),
        (9, c[2], [0.2, 0.2, 1.0]),
        (10, c[2], [0.3, -0.4, -0.8]),
        (11, c[3], [-0.2, 0.5, 0.9]),
        (12, c[4], [0.4, 0.4, 0.8]),
        (13, c[4], [0.5, -0.5, -0.6]),
    ];
    sites
        .into_iter()
        .map(|(id, origin, dir)| Placed {
            symbol: "H",
            id,
            pos: h_at(origin, dir),
            mass: MASS_H,
        })
        .collect()
}

fn build(
    atoms: &[Placed],
    velocity_on: Option<(u64, [f64; 3])>,
    force_on: Option<(u64, [f64; 3])>,
) -> ConFrame {
    let mut builder = ConFrameBuilder::new([CELL, CELL, CELL], [90.0, 90.0, 90.0]);
    for atom in atoms {
        builder.add_atom(
            atom.symbol,
            atom.pos[0],
            atom.pos[1],
            atom.pos[2],
            [false, false, false],
            atom.id,
            atom.mass,
        );
        if velocity_on.is_some_and(|(id, _)| id == atom.id) {
            builder.with_velocity(velocity_on.unwrap().1);
        }
        if force_on.is_some_and(|(id, _)| id == atom.id) {
            builder.with_force(force_on.unwrap().1);
        }
    }
    builder.build().expect("frame")
}

fn by_id(frame: &ConFrame, id: u64) -> usize {
    frame.atom_index_by_id(id).unwrap()
}

fn pos(frame: &ConFrame, i: usize) -> [f64; 3] {
    let atom = &frame.atom_data[i];
    [atom.x, atom.y, atom.z]
}

#[test]
fn claisen_positional_zip_is_the_wrong_displacement() {
    let mol = claisen();
    assert_eq!(mol.reactant.len(), 14);
    assert_eq!(mol.product.len(), 14);
    let reactant_bonds = [
        (0, 1, 1.336),
        (1, 2, 1.360),
        (2, 3, 1.430),
        (3, 4, 1.504),
        (4, 5, 1.336),
    ];
    let xyz = |atoms: &[Placed], id: u64| atoms.iter().find(|a| a.id == id).unwrap().pos;
    for (i, j, length) in reactant_bonds {
        let d = dist(xyz(&mol.reactant, i), xyz(&mol.reactant, j));
        assert!((d - length).abs() < 1e-9, "reactant {i}-{j} is {d}");
    }
    let carbonyl = dist(
        xyz(&mol.product_unwrapped, 1),
        xyz(&mol.product_unwrapped, 2),
    );
    assert!((carbonyl - 1.210).abs() < 1e-9);
    let formed = dist(
        xyz(&mol.product_unwrapped, 0),
        xyz(&mol.product_unwrapped, 5),
    );
    assert!((formed - 1.540).abs() < 1e-9);
    let broken = dist(
        xyz(&mol.product_unwrapped, 2),
        xyz(&mol.product_unwrapped, 3),
    );
    assert!(broken > 2.2, "O–C3 still looks bonded: {broken}");

    let reactant = build(&mol.reactant, None, None);
    let mut product = build(
        &mol.product,
        Some((5, [0.2, -0.1, 0.05])),
        Some((2, [0.4, 0.0, -0.2])),
    );
    // Carbonyl, in the product's oxygen-first order.
    product.header.set_bonds(&[Bond::new(0, 2).with_order(2)]);

    let oxygen = by_id(&reactant, 2);
    let c5 = by_id(&reactant, 5);
    let raw_zip_o = sub(pos(&product, oxygen), pos(&reactant, oxygen));
    assert!(
        norm(raw_zip_o) > 5.0,
        "positional zip at the oxygen slot should be a different atom, got {}",
        norm(raw_zip_o)
    );

    let disp = minimum_image_displacements(&reactant, &product, IdentityCheck::Strict).unwrap();
    let oxygen_mic = disp[oxygen];
    assert!(
        (norm(oxygen_mic) - mol.oxygen_shift).abs() < 1e-8,
        "oxygen moved {}",
        norm(oxygen_mic)
    );
    let raw_c5 = sub(pos(&product, by_id(&product, 5)), mol.c5_reactant);
    assert!((raw_c5[0] - CELL).abs() > 1.0 || raw_c5[0].abs() > CELL / 2.0);
    assert!(raw_c5[0].abs() > 10.0, "unwrapped C5 step is {}", raw_c5[0]);
    let c5_mic = disp[c5];
    let chemical = sub(mol.c5_true, mol.c5_reactant);
    for k in 0..3 {
        assert!((c5_mic[k] - chemical[k]).abs() < 1e-8);
    }
    let zip_c5 = sub(pos(&product, c5), pos(&reactant, c5));
    assert!(
        norm(sub(zip_c5, c5_mic)) > 1.0,
        "positional zip of C5 matched the id displacement"
    );

    let mut ordered = reorder_like(&reactant, &product, IdentityCheck::Strict).unwrap();
    assert_eq!(
        ordered
            .atom_data
            .iter()
            .map(|a| a.atom_id)
            .collect::<Vec<_>>(),
        reactant
            .atom_data
            .iter()
            .map(|a| a.atom_id)
            .collect::<Vec<_>>()
    );
    assert_eq!(ordered.atom_data[c5].velocity(), Some([0.2, -0.1, 0.05]));
    assert_eq!(ordered.atom_data[oxygen].force(), Some([0.4, 0.0, -0.2]));
    let bonds = ordered.bonds();
    assert_eq!(bonds.len(), 1);
    assert_eq!(bonds[0].i, oxygen as u32);
    assert_eq!(bonds[0].j, by_id(&reactant, 1) as u32);
    assert_eq!(bonds[0].order, Some(2));
    assert_eq!(
        ordered.header.natms_per_type,
        reactant.header.natms_per_type
    );

    let mut units = ordered
        .header
        .metadata
        .get("units")
        .cloned()
        .expect("v3 units");
    units
        .as_object_mut()
        .unwrap()
        .insert("time".into(), serde_json::json!("fs"));
    ordered.header.set_units(units);
    let text = write_frames_to_string(&[ordered]).unwrap();
    let back = ConFrameIterator::from_bytes(text.as_bytes())
        .next()
        .unwrap()
        .unwrap();
    assert_eq!(back.atom_data[c5].atom_id, 5);
    assert_eq!(back.atom_data[c5].symbol.as_ref(), "C");
    assert!((back.atom_data[c5].velocity().unwrap()[0] - 0.2).abs() < 1e-6);
}

#[test]
fn a_renumbered_band_image_keeps_its_ids() {
    let mol = claisen();
    let reactant = build(&mol.reactant, None, None);
    let product = build(&mol.product, None, None);
    let mut mid_atoms = mol.reactant.clone();
    for atom in &mut mid_atoms {
        let there = mol
            .product_unwrapped
            .iter()
            .find(|p| p.id == atom.id)
            .unwrap()
            .pos;
        atom.pos = add(atom.pos, scale(sub(there, atom.pos), 0.4));
    }
    // Swap C1 and C5 in storage. The ids move with the atoms.
    let i_c1 = mid_atoms.iter().position(|a| a.id == 0).unwrap();
    let i_c5 = mid_atoms.iter().position(|a| a.id == 5).unwrap();
    mid_atoms.swap(i_c1, i_c5);
    let image1 = build(&mid_atoms, None, None);

    check_atom_id_consistency(
        &[reactant.clone(), image1.clone(), product.clone()],
        IdentityCheck::Strict,
    )
    .unwrap();

    let zip = sub(pos(&image1, 0), pos(&reactant, 0));
    let disp = minimum_image_displacements(&reactant, &image1, IdentityCheck::Strict).unwrap();
    assert!(
        norm(zip) > 1.5,
        "swapped image looks aligned: {}",
        norm(zip)
    );
    assert!(
        norm(disp[0]) < 0.1,
        "C1 only relaxes, moved {}",
        norm(disp[0])
    );
    assert_ne!(image1.atom_data[0].atom_id, reactant.atom_data[0].atom_id);

    let mut broken = product.clone();
    let duplicated = broken.atom_data[0].atom_id;
    broken.atom_data[3].atom_id = duplicated;
    let err =
        check_atom_id_consistency(&[reactant, image1, broken], IdentityCheck::Strict).unwrap_err();
    assert_eq!(err.frame_index(), Some(2));
    assert_eq!(err.atom_id(), Some(duplicated));
    assert_eq!(err.atom_index(), Some(3));
    let text = err.to_string();
    assert!(text.contains("frame 2"), "{text}");
    assert!(text.contains(&format!("atom_id {duplicated}")), "{text}");
}

#[test]
fn strict_mass_and_fixed_mask_are_optional() {
    let reference = build(
        &[
            Placed {
                symbol: "Cu",
                id: 0,
                pos: [0.0, 0.0, 0.0],
                mass: 63.546,
            },
            Placed {
                symbol: "H",
                id: 1,
                pos: [1.0, 0.0, 0.0],
                mass: 1.008,
            },
        ],
        None,
        None,
    );
    let mut other = reference.clone();
    other.masses.set_f64(1, 2.014);
    other.atom_data[1].fixed = [true, false, false];
    let strict = atom_id_permutation(&reference, &other, IdentityCheck::Strict).unwrap_err();
    assert!(matches!(
        strict,
        CorrespondenceError::Mass { atom_id: 1, .. }
    ));
    assert!(strict.to_string().contains("mass"));
    assert_eq!(strict.frame_index(), Some(1));
    assert_eq!(strict.atom_id(), Some(1));
    assert_eq!(strict.atom_index(), Some(1));
    // Mass is checked before the mask, so a mask-only frame is separate.
    let mut mask_only = reference.clone();
    mask_only.atom_data[1].fixed = [true, false, false];
    let mask = atom_id_permutation(&reference, &mask_only, IdentityCheck::Strict).unwrap_err();
    assert!(matches!(
        mask,
        CorrespondenceError::Fixed { atom_id: 1, .. }
    ));
    assert!(mask.to_string().contains("fixed mask"));
    assert_eq!(mask.frame_index(), Some(1));
    assert_eq!(mask.atom_id(), Some(1));
    assert_eq!(mask.atom_index(), Some(1));
    assert!(atom_id_permutation(&reference, &other, IdentityCheck::Lenient).is_ok());

    let mut symbol = reference.clone();
    symbol.atom_data[1].symbol = "D".into();
    let err = atom_id_permutation(&reference, &symbol, IdentityCheck::Lenient).unwrap_err();
    assert!(matches!(
        err,
        CorrespondenceError::Symbol { atom_id: 1, .. }
    ));
    assert!(err.to_string().contains("symbol"));
    assert_eq!(err.frame_index(), Some(1));
    assert_eq!(err.atom_id(), Some(1));
    assert_eq!(err.atom_index(), Some(1));

    let missing = build(
        &[Placed {
            symbol: "Cu",
            id: 0,
            pos: [0.0, 0.0, 0.0],
            mass: 63.546,
        }],
        None,
        None,
    );
    let err = atom_id_permutation(&reference, &missing, IdentityCheck::Lenient).unwrap_err();
    assert!(matches!(
        err,
        CorrespondenceError::Missing {
            atom_id: 1,
            reference_index: 1,
            ..
        }
    ));
    assert!(err.to_string().contains("missing atom_id 1"));
    assert_eq!(err.frame_index(), Some(1));
    assert_eq!(err.atom_id(), Some(1));
    assert_eq!(err.atom_index(), Some(1));
}

#[test]
fn the_first_bad_frame_is_the_one_reported() {
    let mol = claisen();
    let good = build(&mol.reactant, None, None);
    let mut later = good.clone();
    later.atom_data[4].atom_id = later.atom_data[0].atom_id;
    let mut earlier = good.clone();
    earlier.atom_data[2].symbol = "N".into();
    let err = check_atom_id_consistency(&[good.clone(), earlier, later], IdentityCheck::Lenient)
        .unwrap_err();
    assert_eq!(err.frame_index(), Some(1));
    assert_eq!(err.atom_id(), Some(good.atom_data[2].atom_id));
    let empty = check_atom_id_consistency(&[], IdentityCheck::Strict).unwrap_err();
    assert!(matches!(empty, CorrespondenceError::EmptySequence));
    assert!(empty.to_string().contains("at least one frame"));
    assert_eq!(empty.frame_index(), None);
    assert_eq!(empty.atom_id(), None);
    assert_eq!(empty.atom_index(), None);
    check_atom_id_consistency(&[good], IdentityCheck::Strict).unwrap();
}

#[test]
fn c_abi_reports_the_permutation_and_the_offender() {
    let reference = build(
        &[
            Placed {
                symbol: "O",
                id: 2,
                pos: [0.0, 0.0, 0.0],
                mass: MASS_O,
            },
            Placed {
                symbol: "C",
                id: 0,
                pos: [1.2, 0.0, 0.0],
                mass: MASS_C,
            },
        ],
        None,
        None,
    );
    let other = build(
        &[
            Placed {
                symbol: "C",
                id: 0,
                pos: [1.3, 0.1, 0.0],
                mass: MASS_C,
            },
            Placed {
                symbol: "O",
                id: 2,
                pos: [0.1, 0.0, 0.0],
                mass: MASS_O,
            },
        ],
        None,
        None,
    );
    let a = Box::into_raw(Box::new(reference)) as *mut RKRConFrame;
    let b = Box::into_raw(Box::new(other)) as *mut RKRConFrame;
    let mut perm = [0u64; 2];
    let status = unsafe { rkr_frame_atom_id_permutation(a, b, 1, perm.as_mut_ptr(), perm.len()) };
    assert_eq!(status, RKRStatus::RKR_STATUS_SUCCESS);
    assert_eq!(perm, [1, 0]);
    let ordered = unsafe { rkr_frame_reorder_like(a, b, 1) };
    assert!(!ordered.is_null());
    let ordered_frame = unsafe { &*(ordered as *const ConFrame) };
    assert_eq!(ordered_frame.atom_data[0].atom_id, 2);
    assert_eq!(ordered_frame.atom_data[1].atom_id, 0);
    let mut disp = [0.0; 6];
    let status =
        unsafe { rkr_frame_minimum_image_displacements(a, b, 1, disp.as_mut_ptr(), disp.len()) };
    assert_eq!(status, RKRStatus::RKR_STATUS_SUCCESS);
    assert!((disp[0] - 0.1).abs() < 1e-12);

    let mut broken = ordered_frame.clone();
    broken.atom_data[1].atom_id = 2;
    let bad = Box::into_raw(Box::new(broken)) as *mut RKRConFrame;
    let frames = [a as *const RKRConFrame, bad as *const RKRConFrame];
    let mut frame_index = 0u64;
    let mut atom_id = 0u64;
    let status = unsafe {
        rkr_frames_check_atom_ids(
            frames.as_ptr(),
            frames.len(),
            1,
            &mut frame_index,
            &mut atom_id,
        )
    };
    assert_eq!(status, RKRStatus::RKR_STATUS_VALIDATION_ERROR);
    assert_eq!(frame_index, 1);
    assert_eq!(atom_id, 2);
    let message = unsafe { CStr::from_ptr(rkr_last_error_message()) };
    assert!(message.to_string_lossy().contains("duplicate atom_id 2"));
    unsafe {
        free_rkr_frame(ordered);
        free_rkr_frame(bad);
        free_rkr_frame(a);
        free_rkr_frame(b);
    }
}

fn cu_h() -> ConFrame {
    build(
        &[
            Placed {
                symbol: "Cu",
                id: 10,
                pos: [0.0, 0.0, 0.0],
                mass: 63.546,
            },
            Placed {
                symbol: "H",
                id: 11,
                pos: [1.2, 0.0, 0.0],
                mass: 1.008,
            },
        ],
        None,
        None,
    )
}

fn expect_section(err: &CorrespondenceError, section: &str, rows: usize, atoms: usize) {
    match err {
        CorrespondenceError::SectionLength {
            section: got,
            rows: got_rows,
            atoms: got_atoms,
        } => {
            assert_eq!(*got, section);
            assert_eq!(*got_rows, rows);
            assert_eq!(*got_atoms, atoms);
        }
        other => panic!("expected a {section} length error, got {other}"),
    }
    let text = err.to_string();
    assert!(text.contains(section), "{text}");
    assert!(text.contains(&format!("{rows} rows")), "{text}");
    assert!(text.contains(&format!("{atoms} atoms")), "{text}");
    assert_eq!(err.frame_index(), None);
    assert_eq!(err.atom_id(), None);
    assert_eq!(err.atom_index(), None);
}

#[test]
fn an_extra_atom_is_named() {
    let reference = cu_h();
    let extra = build(
        &[
            Placed {
                symbol: "Cu",
                id: 10,
                pos: [0.0, 0.0, 0.0],
                mass: 63.546,
            },
            Placed {
                symbol: "H",
                id: 11,
                pos: [1.2, 0.0, 0.0],
                mass: 1.008,
            },
            Placed {
                symbol: "O",
                id: 12,
                pos: [2.0, 0.0, 0.0],
                mass: 15.999,
            },
        ],
        None,
        None,
    );
    let err = atom_id_permutation(&reference, &extra, IdentityCheck::Strict).unwrap_err();
    assert!(matches!(
        err,
        CorrespondenceError::Extra {
            frame_index: 1,
            atom_id: 12,
            atom_index: 2,
        }
    ));
    assert_eq!(err.frame_index(), Some(1));
    assert_eq!(err.atom_id(), Some(12));
    assert_eq!(err.atom_index(), Some(2));
    assert!(err.to_string().contains("not in the reference frame"));
}

#[test]
fn a_short_section_is_rejected() {
    let reference = cu_h();
    let sections = [
        "masses",
        "positions",
        "velocities",
        "forces",
        "energies",
        "charges",
        "spins",
        "magmoms",
        "displacements",
        "spreads",
    ];
    for section in sections {
        let mut other = reference.clone();
        match section {
            "masses" => other.masses = FloatArray1::zeros(other.masses.kind(), 1),
            "positions" => other.positions = FloatArray2::zeros(other.positions.kind(), 1, 3),
            "velocities" => other.velocities = FloatArray2::zeros(other.velocities.kind(), 1, 3),
            "forces" => other.forces = FloatArray2::zeros(other.forces.kind(), 1, 3),
            "energies" => other.atom_energies = FloatArray1::zeros(other.atom_energies.kind(), 1),
            "charges" => other.charges = FloatArray1::zeros(other.charges.kind(), 1),
            "spins" => other.spins = FloatArray1::zeros(other.spins.kind(), 1),
            "magmoms" => other.magmoms = FloatArray2::zeros(other.magmoms.kind(), 1, 3),
            "displacements" => {
                other.displacements = FloatArray2::zeros(other.displacements.kind(), 1, 3);
            }
            "spreads" => other.spreads = FloatArray2::zeros(other.spreads.kind(), 1, 3),
            _ => unreachable!(),
        }
        let err = reorder_like(&reference, &other, IdentityCheck::Strict).unwrap_err();
        expect_section(&err, section, 1, 2);
    }
}

#[test]
fn a_bond_endpoint_past_the_atom_list_is_rejected() {
    let reference = cu_h();
    let mut other = reference.clone();
    other.header.set_bonds(&[Bond::new(5, 0)]);
    let err = reorder_like(&reference, &other, IdentityCheck::Strict).unwrap_err();
    assert!(matches!(
        err,
        CorrespondenceError::BondEndpoint { index: 5, atoms: 2 }
    ));
    assert!(err.to_string().contains("bond endpoint 5"));
    assert_eq!(err.frame_index(), None);
    assert_eq!(err.atom_id(), None);
    assert_eq!(err.atom_index(), None);

    let mut other = reference.clone();
    other.header.set_bonds(&[Bond::new(0, 9)]);
    let err = reorder_like(&reference, &other, IdentityCheck::Strict).unwrap_err();
    assert!(matches!(
        err,
        CorrespondenceError::BondEndpoint { index: 9, atoms: 2 }
    ));
    assert!(err.to_string().contains("bond endpoint 9"));
}

#[test]
fn non_finite_coordinates_and_deltas_are_rejected() {
    let reference = cu_h();
    let mut moved = reference.clone();
    moved.positions.set_f64_row(0, [f64::NAN, 0.0, 0.0]);
    let err = minimum_image_displacements(&moved, &reference, IdentityCheck::Strict).unwrap_err();
    assert!(matches!(
        err,
        CorrespondenceError::NonFiniteCoordinate {
            frame_index: 0,
            atom_id: 10,
            atom_index: 0,
        }
    ));
    assert!(err.to_string().contains("non-finite coordinate"));
    assert_eq!(err.frame_index(), Some(0));
    assert_eq!(err.atom_id(), Some(10));
    assert_eq!(err.atom_index(), Some(0));

    let mut other = reference.clone();
    other.positions.set_f64_row(1, [0.0, f64::INFINITY, 0.0]);
    let err = minimum_image_displacements(&reference, &other, IdentityCheck::Strict).unwrap_err();
    assert!(matches!(
        err,
        CorrespondenceError::NonFiniteCoordinate {
            frame_index: 1,
            atom_id: 11,
            atom_index: 1,
        }
    ));
    assert_eq!(err.atom_index(), Some(1));
    assert!(err.to_string().contains("non-finite coordinate"));

    let err = minimum_image_delta(
        reference.header.cell_matrix(),
        [true; 3],
        [f64::NAN, 0.0, 1.0],
    )
    .unwrap_err();
    assert!(matches!(err, CorrespondenceError::NonFiniteDelta));
    assert!(err.to_string().contains("cartesian delta is non-finite"));
    assert_eq!(err.frame_index(), None);
    assert_eq!(err.atom_id(), None);
    assert_eq!(err.atom_index(), None);
}

#[test]
fn an_empty_frame_rebuilds_type_runs_and_rejects_a_stray_section() {
    let empty = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0])
        .build()
        .expect("zero atoms");
    let ordered = reorder_like(&empty, &empty, IdentityCheck::Strict).unwrap();
    assert_eq!(ordered.header.natm_types, 0);
    assert!(ordered.header.natms_per_type.is_empty());
    assert!(ordered.header.masses_per_type.is_empty());

    let mut stray_rows = empty.clone();
    stray_rows.velocities = FloatArray2::zeros(stray_rows.velocities.kind(), 1, 3);
    let err = reorder_like(&empty, &stray_rows, IdentityCheck::Strict).unwrap_err();
    expect_section(&err, "velocities", 1, 0);

    let mut stray_col = empty.clone();
    stray_col.charges = FloatArray1::zeros(stray_col.charges.kind(), 1);
    let err = reorder_like(&empty, &stray_col, IdentityCheck::Strict).unwrap_err();
    expect_section(&err, "charges", 1, 0);
}

#[test]
fn coordinates_on_the_atoms_are_used_when_the_position_block_is_empty() {
    let reference = cu_h();
    let mut other = reference.clone();
    other.atom_data[0].x += 0.3;
    let kind = reference.positions.kind();
    let mut reference = reference;
    reference.positions = FloatArray2::zeros(kind, 0, 3);
    other.positions = FloatArray2::zeros(kind, 0, 3);

    let disp = minimum_image_displacements(&reference, &other, IdentityCheck::Strict).unwrap();
    assert!((disp[0][0] - 0.3).abs() < 1e-12);
    assert!(disp[0][1].abs() < 1e-12);
    assert!(disp[1][0].abs() < 1e-12);

    let ordered = reorder_like(&reference, &other, IdentityCheck::Strict).unwrap();
    assert_eq!(ordered.positions.nrows(), 0);
    assert!((ordered.atom_data[0].x - other.atom_data[0].x).abs() < 1e-12);
    assert_eq!(ordered.atom_data[0].atom_id, 10);
}
