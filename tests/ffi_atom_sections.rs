//! Charges, spins, and magmoms through the C ABI.
//!
//! A binding that copies a frame out through the C accessors and rebuilds
//! it with the C builder must write the same bytes as the Rust rewrite.

use readcon_core::ffi::*;
use readcon_core::iterators::read_all_frames;
use readcon_core::types::ConFrame;
use readcon_core::writer::{ConFrameWriter, binding_rewrite_frame};
use std::ffi::{CStr, CString};
use std::path::{Path, PathBuf};
use std::ptr;

const SECTION_FIXTURES: [&str; 3] = [
    "tiny_cuh2_charges_spins_magmoms.con",
    "tiny_cuh2_displacements.con",
    "tiny_cuh2_spreads.con",
];

fn fixture(name: &str) -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("resources/test")
        .join(name)
}

fn handle(frame: &ConFrame) -> *const RKRConFrame {
    (frame as *const ConFrame) as *const RKRConFrame
}

fn write_bytes(frames: &[&ConFrame]) -> Vec<u8> {
    let mut buf = Vec::new();
    ConFrameWriter::new(&mut buf)
        .extend(frames.iter().copied())
        .unwrap();
    buf
}

type CopyFn = unsafe extern "C" fn(*const RKRConFrame, *mut f64, usize) -> RKRStatus;

fn copied(frame: *const RKRConFrame, width: usize, copy: CopyFn) -> Option<Vec<f64>> {
    let n = unsafe { rkr_frame_atom_count(frame) };
    let mut out = vec![0.0; n * width];
    match unsafe { copy(frame, out.as_mut_ptr(), out.len()) } {
        RKRStatus::RKR_STATUS_SUCCESS => Some(out),
        RKRStatus::RKR_STATUS_SECTION_ABSENT => None,
        status => panic!("copy failed: {status:?}"),
    }
}

unsafe fn header_line(frame: *const RKRConFrame, prebox: bool, index: usize) -> CString {
    let raw = unsafe { rkr_frame_get_header_line_cpp(frame, prebox, index) };
    assert!(!raw.is_null());
    let line = unsafe { CStr::from_ptr(raw) }.to_owned();
    unsafe { rkr_free_string(raw) };
    line
}

/// Rebuild `frame` using only the C accessors and the C builder.
unsafe fn rebuild_through_c(frame: &ConFrame) -> *mut RKRConFrame {
    let h = handle(frame);
    let n = unsafe { rkr_frame_atom_count(h) };
    let positions = copied(h, 3, rkr_frame_copy_positions).unwrap();
    let masses = copied(h, 1, rkr_frame_copy_masses).unwrap();
    let charges = copied(h, 1, rkr_frame_copy_charges);
    let spins = copied(h, 1, rkr_frame_copy_spins);
    let magmoms = copied(h, 3, rkr_frame_copy_magmoms);
    let displacements = copied(h, 3, rkr_frame_copy_displacements);
    let spreads = copied(h, 3, rkr_frame_copy_spreads);
    let mut ids = vec![0u64; n];
    assert_eq!(
        unsafe { rkr_frame_copy_atom_ids(h, ids.as_mut_ptr(), n) },
        RKRStatus::RKR_STATUS_SUCCESS
    );

    let headers = unsafe {
        [
            header_line(h, true, 0),
            header_line(h, true, 1),
            header_line(h, false, 0),
            header_line(h, false, 1),
        ]
    };
    let mut builder = unsafe {
        rkr_frame_new(
            frame.header.boxl.as_ptr(),
            frame.header.angles.as_ptr(),
            headers[0].as_ptr(),
            headers[1].as_ptr(),
            headers[2].as_ptr(),
            headers[3].as_ptr(),
        )
    };
    assert!(!builder.is_null());
    let metadata = unsafe { rkr_frame_metadata_json(h) };
    assert_eq!(
        unsafe { rkr_frame_builder_set_metadata_json(builder, metadata) },
        RKRStatus::RKR_STATUS_SUCCESS
    );
    unsafe { rkr_free_string(metadata) };
    for (i, atom) in frame.atom_data.iter().enumerate() {
        let symbol = CString::new(atom.symbol.as_ref()).unwrap();
        let [fx, fy, fz] = atom.fixed();
        let ok = RKRStatus::RKR_STATUS_SUCCESS;
        unsafe {
            assert_eq!(
                rkr_frame_add_atom_with_fixed_mask(
                    builder,
                    symbol.as_ptr(),
                    positions[3 * i],
                    positions[3 * i + 1],
                    positions[3 * i + 2],
                    fx,
                    fy,
                    fz,
                    ids[i],
                    masses[i],
                ),
                ok
            );
            if let Some(c) = &charges {
                assert_eq!(rkr_frame_builder_set_last_charge(builder, c[i]), ok);
            }
            if let Some(s) = &spins {
                assert_eq!(rkr_frame_builder_set_last_spin(builder, s[i]), ok);
            }
            if let Some(m) = &magmoms {
                assert_eq!(
                    rkr_frame_builder_set_last_magmom(builder, m[3 * i..].as_ptr()),
                    ok
                );
            }
            if let Some(d) = &displacements {
                assert_eq!(
                    rkr_frame_builder_set_last_displacement(builder, d[3 * i..].as_ptr()),
                    ok
                );
            }
            if let Some(s) = &spreads {
                assert_eq!(
                    rkr_frame_builder_set_last_spread(builder, s[3 * i..].as_ptr()),
                    ok
                );
            }
        }
    }
    let built = unsafe { rkr_frame_builder_build(&mut builder) };
    assert!(!built.is_null());
    built
}

#[test]
fn c_accessors_report_charges_spins_and_magmoms() {
    let frames = read_all_frames(&fixture("tiny_cuh2_charges_spins_magmoms.con")).unwrap();
    let frame = &frames[0];
    let h = handle(frame);
    unsafe {
        assert!(rkr_frame_has_charges(h));
        assert!(rkr_frame_has_spins(h));
        assert!(rkr_frame_has_magmoms(h));
    }
    let charges = copied(h, 1, rkr_frame_copy_charges).unwrap();
    let spins = copied(h, 1, rkr_frame_copy_spins).unwrap();
    let magmoms = copied(h, 3, rkr_frame_copy_magmoms).unwrap();
    for (i, atom) in frame.atom_data.iter().enumerate() {
        assert_eq!(Some(charges[i]), atom.charge());
        assert_eq!(Some(spins[i]), atom.spin());
        assert_eq!(
            Some([magmoms[3 * i], magmoms[3 * i + 1], magmoms[3 * i + 2]]),
            atom.magmom()
        );
    }

    let plain = read_all_frames(&fixture("tiny_cuh2.con")).unwrap();
    let p = handle(&plain[0]);
    unsafe {
        assert!(!rkr_frame_has_charges(p));
        assert!(!rkr_frame_has_spins(p));
        assert!(!rkr_frame_has_magmoms(p));
        assert!(!rkr_frame_has_charges(ptr::null()));
        assert!(!rkr_frame_has_spins(ptr::null()));
        assert!(!rkr_frame_has_magmoms(ptr::null()));
    }
    assert!(copied(p, 1, rkr_frame_copy_charges).is_none());
    assert!(copied(p, 1, rkr_frame_copy_spins).is_none());
    assert!(copied(p, 3, rkr_frame_copy_magmoms).is_none());

    let mut short = [0.0; 1];
    unsafe {
        assert_eq!(
            rkr_frame_copy_magmoms(h, short.as_mut_ptr(), short.len()),
            RKRStatus::RKR_STATUS_BUFFER_TOO_SMALL
        );
        assert_eq!(
            rkr_frame_copy_charges(ptr::null(), short.as_mut_ptr(), 1),
            RKRStatus::RKR_STATUS_NULL_POINTER
        );
        assert_eq!(
            rkr_frame_builder_set_last_charge(ptr::null_mut(), 1.0),
            RKRStatus::RKR_STATUS_NULL_POINTER
        );
        assert_eq!(
            rkr_frame_builder_set_last_spin(ptr::null_mut(), 1.0),
            RKRStatus::RKR_STATUS_NULL_POINTER
        );
        assert_eq!(
            rkr_frame_builder_set_last_magmom(ptr::null_mut(), short.as_ptr()),
            RKRStatus::RKR_STATUS_NULL_POINTER
        );
    }
}

#[test]
fn c_rebuild_of_section_fixtures_matches_rust_rewrite() {
    for name in SECTION_FIXTURES {
        let frames = read_all_frames(&fixture(name)).unwrap();
        let expected: Vec<_> = frames
            .iter()
            .map(|frame| binding_rewrite_frame(frame).unwrap())
            .collect();
        let rebuilt: Vec<_> = frames
            .iter()
            .map(|frame| unsafe { rebuild_through_c(frame) })
            .collect();
        let rebuilt_refs: Vec<&ConFrame> = rebuilt
            .iter()
            .map(|&h| unsafe { &*(h as *const ConFrame) })
            .collect();
        let want = write_bytes(&expected.iter().collect::<Vec<_>>());
        let got = write_bytes(&rebuilt_refs);
        assert_eq!(
            String::from_utf8_lossy(&got),
            String::from_utf8_lossy(&want),
            "{name}"
        );
        for h in rebuilt {
            unsafe { free_rkr_frame(h) };
        }
    }
}
