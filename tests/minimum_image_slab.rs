//! Near-flat slab minimum image, plus ordinary cells that already agreed.
//!
//! `resources/test/near_flat_slab.con` is the reported pair: lengths
//! 13, 13, 23.3, angles 86.892, 16.892, 70, periodic in a and b only.
//! Wrapping through the full inverse turns a sub-angstrom step into
//! about 5.15e7 Å. The closest image in the periodic plane stays near
//! 0.335 Å.

use readcon_core::correspondence::IdentityCheck;
#[cfg(feature = "capi")]
use readcon_core::ffi::{
    RKRConFrame, RKRStatus, free_rkr_frame, rkr_frame_minimum_image_displacements,
};
use readcon_core::iterators::ConFrameIterator;
use readcon_core::minimum_image_displacements;
use readcon_core::types::{ConFrame, ConFrameBuilder, cell_vectors};

fn read_fixture() -> Vec<ConFrame> {
    let path =
        std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("resources/test/near_flat_slab.con");
    let text = std::fs::read_to_string(&path).expect("near_flat_slab.con");
    ConFrameIterator::new(&text)
        .map(|frame| frame.expect("frame parses"))
        .collect()
}

fn dot(a: [f64; 3], b: [f64; 3]) -> f64 {
    a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
}

fn axpy(y: [f64; 3], alpha: f64, x: [f64; 3]) -> [f64; 3] {
    [
        y[0] + alpha * x[0],
        y[1] + alpha * x[1],
        y[2] + alpha * x[2],
    ]
}

fn add(a: [f64; 3], b: [f64; 3]) -> [f64; 3] {
    [a[0] + b[0], a[1] + b[1], a[2] + b[2]]
}

fn sub(a: [f64; 3], b: [f64; 3]) -> [f64; 3] {
    [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
}

/// Shortest image that adds integer combinations of the periodic rows.
fn brute(cell: [[f64; 3]; 3], pbc: [bool; 3], delta: [f64; 3], lim: i32) -> [f64; 3] {
    let mut best = delta;
    let mut best_n2 = dot(delta, delta);
    for i in -lim..=lim {
        if !pbc[0] && i != 0 {
            continue;
        }
        for j in -lim..=lim {
            if !pbc[1] && j != 0 {
                continue;
            }
            for k in -lim..=lim {
                if !pbc[2] && k != 0 {
                    continue;
                }
                let cand = axpy(
                    axpy(axpy(delta, -f64::from(i), cell[0]), -f64::from(j), cell[1]),
                    -f64::from(k),
                    cell[2],
                );
                let n2 = dot(cand, cand);
                if n2 < best_n2 {
                    best = cand;
                    best_n2 = n2;
                }
            }
        }
    }
    best
}

fn close(got: [f64; 3], want: [f64; 3]) {
    for k in 0..3 {
        assert!(
            (got[k] - want[k]).abs() < 1e-8,
            "component {k}: {got:?} vs {want:?}"
        );
    }
}

fn assert_matches_brute(reference: &ConFrame, other: &ConFrame, lim: i32) {
    let cell = reference.header.cell_matrix();
    let pbc = reference.header.pbc_effective();
    let perm = readcon_core::atom_id_permutation(reference, other, IdentityCheck::Strict)
        .expect("atom ids");
    let disp = minimum_image_displacements(reference, other, IdentityCheck::Strict).expect("wrap");
    assert_eq!(disp.len(), perm.len());
    for (i, row) in disp.iter().enumerate() {
        let delta = sub(other.xyz_at(perm[i]), reference.xyz_at(i));
        close(*row, brute(cell, pbc, delta, lim));
    }
}

fn frame_with(
    lengths: [f64; 3],
    angles: [f64; 3],
    pbc: [bool; 3],
    lattice: Option<[[f64; 3]; 3]>,
    positions: &[[f64; 3]],
) -> ConFrame {
    let mut builder = ConFrameBuilder::new(lengths, angles);
    for (i, pos) in positions.iter().enumerate() {
        builder.add_atom(
            "Cu",
            pos[0],
            pos[1],
            pos[2],
            [false; 3],
            (i + 1) as u64,
            63.546,
        );
    }
    let mut frame = builder.build().expect("frame");
    if let Some(vecs) = lattice {
        frame.header.set_lattice_vectors(vecs).expect("lattice");
    }
    frame.header.set_pbc(pbc);
    frame
}

fn pair(
    lengths: [f64; 3],
    angles: [f64; 3],
    pbc: [bool; 3],
    lattice: Option<[[f64; 3]; 3]>,
    reference: &[[f64; 3]],
    deltas: &[[f64; 3]],
) -> (ConFrame, ConFrame) {
    let other: Vec<[f64; 3]> = reference
        .iter()
        .zip(deltas)
        .map(|(pos, delta)| add(*pos, *delta))
        .collect();
    (
        frame_with(lengths, angles, pbc, lattice, reference),
        frame_with(lengths, angles, pbc, lattice, &other),
    )
}

#[test]
fn near_flat_slab_fixture_stays_near_a_third_of_an_angstrom() {
    let frames = read_fixture();
    assert_eq!(frames.len(), 2);
    assert_eq!(frames[0].atom_data.len(), 24);
    assert_eq!(frames[1].atom_data.len(), 24);
    assert_eq!(frames[0].header.boxl, [13.0, 13.0, 23.3]);
    assert_eq!(frames[0].header.angles, [86.892, 16.892, 70.0]);
    assert_eq!(frames[1].header.boxl, frames[0].header.boxl);
    assert_eq!(frames[1].header.angles, frames[0].header.angles);
    assert_eq!(frames[0].header.pbc_effective(), [true, true, false]);
    let cz = frames[0].header.cell_matrix()[2][2];
    assert!((cz - 1.227526962879789e-7).abs() < 1e-16, "c_z {cz}");

    let disp =
        minimum_image_displacements(&frames[0], &frames[1], IdentityCheck::Strict).expect("wrap");
    assert_eq!(disp.len(), 24);
    let max = disp
        .iter()
        .flat_map(|row| row.iter().map(|component| component.abs()))
        .fold(0.0_f64, f64::max);
    assert!(
        (max - 0.335).abs() < 1e-3,
        "max abs component {max}; the full-inverse wrap is about 5.15e7"
    );
    assert_matches_brute(&frames[0], &frames[1], 8);

    #[cfg(feature = "capi")]
    {
        let a = Box::into_raw(Box::new(frames[0].clone())) as *mut RKRConFrame;
        let b = Box::into_raw(Box::new(frames[1].clone())) as *mut RKRConFrame;
        let mut raw = vec![0.0; disp.len() * 3];
        let status =
            unsafe { rkr_frame_minimum_image_displacements(a, b, 1, raw.as_mut_ptr(), raw.len()) };
        assert_eq!(status, RKRStatus::RKR_STATUS_SUCCESS);
        for (i, row) in disp.iter().enumerate() {
            close([raw[i * 3], raw[i * 3 + 1], raw[i * 3 + 2]], *row);
        }
        unsafe {
            free_rkr_frame(a);
            free_rkr_frame(b);
        }
    }
}

#[test]
fn a_synthetic_near_flat_slab_matches_a_periodic_search() {
    let lengths = [5.0, 5.0, 3.0];
    let angles = [86.892, 16.892, 70.0];
    let cell = cell_vectors(lengths, angles);
    assert!(cell[2][2].abs() < 1e-6, "c_z {}", cell[2][2]);
    let reference = [[0.0, 0.0, 0.0], [1.2, 0.4, 0.0], [2.0, 1.5, 0.01]];
    let deltas = [
        [0.02, -0.01, 0.275],
        add(cell[0], [0.0, 0.0, -0.02]),
        [0.1, -0.05, 1.0e-4],
    ];
    let (reference_frame, other) = pair(
        lengths,
        angles,
        [true, true, false],
        None,
        &reference,
        &deltas,
    );
    assert_matches_brute(&reference_frame, &other, 8);
    let disp =
        minimum_image_displacements(&reference_frame, &other, IdentityCheck::Strict).unwrap();
    close(disp[0], deltas[0]);
    assert!(disp.iter().flatten().all(|component| component.abs() < 6.0));
}

#[test]
fn an_orthorhombic_cell_matches_a_periodic_search() {
    let lengths = [10.0, 12.0, 14.0];
    let angles = [90.0, 90.0, 90.0];
    let origin = [[0.0, 0.0, 0.0]];
    let (reference, other) = pair(
        lengths,
        angles,
        [true, true, true],
        None,
        &origin,
        &[[9.0, 9.0, 3.0]],
    );
    let disp = minimum_image_displacements(&reference, &other, IdentityCheck::Strict).unwrap();
    close(disp[0], [-1.0, -3.0, 3.0]);
    assert_matches_brute(&reference, &other, 4);

    let (reference, other) = pair(
        lengths,
        angles,
        [true, true, false],
        None,
        &origin,
        &[[9.0, 9.0, 4.0]],
    );
    let disp = minimum_image_displacements(&reference, &other, IdentityCheck::Strict).unwrap();
    close(disp[0], [-1.0, -3.0, 4.0]);

    let (reference, other) = pair(
        lengths,
        angles,
        [false, true, true],
        None,
        &origin,
        &[[9.0, 9.0, 0.0]],
    );
    let disp = minimum_image_displacements(&reference, &other, IdentityCheck::Strict).unwrap();
    close(disp[0], [9.0, -3.0, 0.0]);
}

#[test]
fn a_mild_triclinic_fraction_is_already_the_shortest_image() {
    let lengths = [10.0, 12.0, 14.0];
    let angles = [80.0, 90.0, 70.0];
    let cell = cell_vectors(lengths, angles);
    let frac = [0.2, -0.3, 0.25];
    let delta = axpy(
        axpy(axpy([0.0; 3], frac[0], cell[0]), frac[1], cell[1]),
        frac[2],
        cell[2],
    );
    let shifted = add(delta, cell[0]);
    let (reference, other) = pair(
        lengths,
        angles,
        [true, true, true],
        None,
        &[[1.0, 2.0, 3.0], [1.0, 2.0, 3.0]],
        &[delta, shifted],
    );
    let disp = minimum_image_displacements(&reference, &other, IdentityCheck::Strict).unwrap();
    close(disp[0], delta);
    close(disp[1], delta);
    assert_matches_brute(&reference, &other, 4);

    let along = minimum_image_displacements(
        &frame_with(lengths, angles, [true; 3], None, &[[0.0; 3]]),
        &frame_with(lengths, angles, [true; 3], None, &[cell[0]]),
        IdentityCheck::Strict,
    )
    .unwrap();
    close(along[0], [0.0; 3]);
}

#[test]
fn a_sheared_slab_is_not_the_unreduced_rounding() {
    // Naive rounding in this basis misses the shorter image. The
    // unreduced coefficients are about (-4, 1), ( -5, 2) and (4, -1).
    let lattice = [[6.0, 0.0, 0.0], [17.5, 2.0, 0.0], [0.0, 0.0, 12.0]];
    let deltas = [
        [-6.288849, 1.061501, -0.26009],
        [2.494081, 3.017287, -0.868942],
        [8.075075, -0.567523, 0.278136],
    ];
    let (reference, other) = pair(
        [1.0, 1.0, 1.0],
        [90.0, 90.0, 90.0],
        [true, true, false],
        Some(lattice),
        &[[0.0; 3]; 3],
        &deltas,
    );
    assert_eq!(reference.header.cell_matrix(), lattice);
    assert_matches_brute(&reference, &other, 12);
    let disp = minimum_image_displacements(&reference, &other, IdentityCheck::Strict).unwrap();
    let lengths: Vec<f64> = disp.iter().map(|row| dot(*row, *row).sqrt()).collect();
    assert!(lengths[0] < 1.1, "{}", lengths[0]);
    assert!(lengths[1] < 3.0, "{}", lengths[1]);
    assert!(lengths[2] < 2.2, "{}", lengths[2]);
    close(
        [disp[0][2], disp[1][2], disp[2][2]],
        [-0.26009, -0.868942, 0.278136],
    );
}
