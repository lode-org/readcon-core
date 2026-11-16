//! C ABI against the Rust reader and writer.
//!
//! Frames built and read through `rkr_*` match `ConFrame`. Damaged input
//! returns a status code. Null handles are rejected. Every returned buffer
//! is freed with its documented function.

use readcon_core::ffi::*;
use readcon_core::iterators::{frames_from_bytes, frames_from_text};
use readcon_core::types::{ConFrame, ConFrameBuilder};
use readcon_core::units::NATURAL_TIME_UNIT;
use readcon_core::writer::write_frames_to_vec;
use std::ffi::{CStr, CString};
use std::ptr;

fn bits(value: f64) -> u64 {
    value.to_bits()
}

fn units_json() -> CString {
    CString::new(format!(
        r#"{{"length":"angstrom","energy":"eV","mass":"amu","time":"{NATURAL_TIME_UNIT}"}}"#
    ))
    .unwrap()
}

fn rust_geometry() -> ConFrame {
    let mut builder = ConFrameBuilder::new([10.5, 11.0, 12.25], [90.0, 90.0, 120.0]);
    builder
        .set_units(serde_json::json!({
            "length": "angstrom",
            "energy": "eV",
            "mass": "amu",
            "time": NATURAL_TIME_UNIT,
        }))
        .unwrap();
    let rows = [
        ("Cu", [0.0, -0.0, 1.0], [true, false, false], 10u64, 63.546, [-0.0, 0.1, -0.2], [0.0, -0.0, 1.5]),
        ("H", [1.25e-10, -1.0e20, 2.5], [false, true, false], 11, 1.008, [1.0e-20, 0.0, -0.0], [-2.0, 3.0, -4.0]),
        ("Cu", [-0.0, 2.5, -3.5], [true, true, true], 13, 63.546, [0.5, -0.5, 0.25], [f64::from_bits(1), 0.0, 1.0]),
        ("O", [f64::MAX, -f64::MAX, f64::MIN_POSITIVE], [false, false, true], 12, 15.999, [f64::MIN_POSITIVE, f64::MAX, -0.0], [1.0e-8, -1.0e8, 9.0]),
    ];
    for (symbol, xyz, fixed, id, mass, vel, force) in rows {
        builder.add_atom(symbol, xyz[0], xyz[1], xyz[2], fixed, id, mass);
        builder.with_velocity(vel);
        builder.with_force(force);
    }
    builder.build().unwrap()
}

fn rust_one() -> ConFrame {
    let mut builder = ConFrameBuilder::new([1.0, 2.0, 3.0], [90.0, 80.0, 70.0]);
    builder.add_atom("He", -0.0, f64::MIN_POSITIVE, -1.5e-7, [false, false, true], 7, 4.0026);
    builder.build().unwrap()
}

fn rust_empty() -> ConFrame {
    ConFrameBuilder::new([4.0, 5.0, 6.0], [90.0, 90.0, 90.0])
        .build()
        .unwrap()
}

fn masses_for(frame: &ConFrame, index: usize) -> f64 {
    let mut cursor = 0usize;
    for (slot, &count) in frame.header.natms_per_type.iter().enumerate() {
        if index < cursor + count {
            return frame.header.masses_per_type[slot];
        }
        cursor += count;
    }
    panic!("atom {index} is outside the species counts");
}

unsafe fn c_frame_matches_masses(handle: *const RKRConFrame, expect: &ConFrame) {
    let view = rkr_frame_to_c_frame(handle);
    assert!(!view.is_null());
    let view_ref = &*view;
    assert_eq!(view_ref.num_atoms, expect.atom_data.len());
    for index in 0..3 {
        assert_eq!(bits(view_ref.cell[index]), bits(expect.header.boxl[index]));
        assert_eq!(bits(view_ref.angles[index]), bits(expect.header.angles[index]));
    }
    assert_eq!(view_ref.has_velocities, expect.has_velocities());
    assert_eq!(view_ref.has_forces, expect.has_forces());
    for (index, atom) in expect.atom_data.iter().enumerate() {
        let got = &*view_ref.atoms.add(index);
        let symbol = CString::new(atom.symbol.as_ref()).unwrap();
        assert_eq!(got.atomic_number, rkr_symbol_to_z(symbol.as_ptr()));
        assert_eq!(bits(got.x), bits(atom.x()));
        assert_eq!(bits(got.y), bits(atom.y()));
        assert_eq!(bits(got.z), bits(atom.z()));
        assert_eq!(got.atom_id, atom.atom_id);
        assert_eq!(bits(got.mass), bits(masses_for(expect, index)));
        assert_eq!([got.fixed_x, got.fixed_y, got.fixed_z], atom.fixed());
        match (got.has_velocity, atom.velocity()) {
            (true, Some(value)) => {
                assert_eq!([bits(got.vx), bits(got.vy), bits(got.vz)], value.map(bits));
            }
            (false, None) => {}
            (flag, value) => panic!("velocity {flag} vs {value:?}"),
        }
        match (got.has_forces, atom.force()) {
            (true, Some(value)) => {
                assert_eq!([bits(got.fx), bits(got.fy), bits(got.fz)], value.map(bits));
            }
            (false, None) => {}
            (flag, value) => panic!("force {flag} vs {value:?}"),
        }
    }
    free_c_frame(view);
}

unsafe fn read_c(path: &CStr, threads: usize) -> (*mut *mut RKRConFrame, usize) {
    let mut count = usize::MAX;
    let handles = if threads == 0 {
        rkr_read_all_frames(path.as_ptr(), &mut count)
    } else {
        rkr_read_all_frames_n_threads(path.as_ptr(), &mut count, threads)
    };
    assert!(!handles.is_null(), "read failed: {}", last_message());
    (handles, count)
}

fn last_message() -> String {
    unsafe { CStr::from_ptr(rkr_last_error_message()).to_string_lossy().into_owned() }
}

fn last_code() -> i32 {
    unsafe { (*rkr_last_error()).code }
}

#[test]
fn c_builder_matches_rust_and_round_trips() {
    let expect = vec![rust_geometry(), rust_one(), rust_empty()];
    unsafe {
        let built = c_build_same();
        assert_eq!(built.len(), expect.len());
        for (handle, frame) in built.iter().zip(&expect) {
            c_frame_matches_masses(*handle, frame);
        }
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("generated.con");
        let name = CString::new(path.to_str().unwrap()).unwrap();
        let writer = create_writer_from_path_round_trip_c(name.as_ptr());
        assert!(!writer.is_null());
        let handles: Vec<*const RKRConFrame> = built.iter().map(|item| *item as *const _).collect();
        assert_eq!(
            rkr_writer_extend(writer, handles.as_ptr(), handles.len()),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_eq!(rkr_writer_flush(writer), RKRStatus::RKR_STATUS_SUCCESS);
        free_rkr_writer(writer);

        let bytes = std::fs::read(&path).unwrap();
        let rust_frames = frames_from_bytes(&bytes, Some(1)).unwrap();
        for (handle, frame) in built.iter().zip(&rust_frames) {
            c_frame_matches_masses(*handle, frame);
        }
        for threads in [0usize, 1, 4] {
            let (read, count) = read_c(&name, threads);
            assert_eq!(count, rust_frames.len());
            for index in 0..count {
                c_frame_matches_masses(*read.add(index), &rust_frames[index]);
            }
            free_rkr_frame_array(read, count);
        }

        let mut text = ptr::null_mut();
        let mut len = 0usize;
        assert_eq!(
            rkr_write_frames_to_string(handles.as_ptr(), handles.len(), &mut text, &mut len),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert!(!text.is_null());
        let written = std::slice::from_raw_parts(text.cast::<u8>(), len);
        let from_text = frames_from_text(std::str::from_utf8(written).unwrap(), Some(1)).unwrap();
        assert_eq!(from_text.len(), rust_frames.len());
        rkr_free_string(text);

        for handle in built {
            free_rkr_frame(handle);
        }
    }
}

unsafe fn c_build_same() -> Vec<*mut RKRConFrame> {
    let mut out = Vec::new();
    out.push(c_geometry());
    out.push(c_one());
    out.push(c_empty());
    out
}

unsafe fn c_geometry() -> *mut RKRConFrame {
    let cell = [10.5, 11.0, 12.25];
    let angles = [90.0, 90.0, 120.0];
    let builder = rkr_frame_new(
        cell.as_ptr(),
        angles.as_ptr(),
        c"geometry".as_ptr(),
        ptr::null(),
        ptr::null(),
        ptr::null(),
    );
    assert!(!builder.is_null());
    let units = units_json();
    assert_eq!(
        rkr_frame_builder_set_units(builder, units.as_ptr()),
        RKRStatus::RKR_STATUS_SUCCESS
    );
    let rows = [
        ("Cu", [0.0, -0.0, 1.0], [true, false, false], 10u64, 63.546, [-0.0, 0.1, -0.2], [0.0, -0.0, 1.5]),
        ("H", [1.25e-10, -1.0e20, 2.5], [false, true, false], 11, 1.008, [1.0e-20, 0.0, -0.0], [-2.0, 3.0, -4.0]),
        ("Cu", [-0.0, 2.5, -3.5], [true, true, true], 13, 63.546, [0.5, -0.5, 0.25], [f64::from_bits(1), 0.0, 1.0]),
        ("O", [f64::MAX, -f64::MAX, f64::MIN_POSITIVE], [false, false, true], 12, 15.999, [f64::MIN_POSITIVE, f64::MAX, -0.0], [1.0e-8, -1.0e8, 9.0]),
    ];
    for (symbol, xyz, fixed, id, mass, vel, force) in rows {
        let symbol = CString::new(symbol).unwrap();
        assert_eq!(
            rkr_frame_add_atom_full(
                builder,
                symbol.as_ptr(),
                xyz[0],
                xyz[1],
                xyz[2],
                fixed[0],
                fixed[1],
                fixed[2],
                id,
                mass,
                vel.as_ptr(),
                force.as_ptr(),
            ),
            RKRStatus::RKR_STATUS_SUCCESS
        );
    }
    let frame = rkr_frame_builder_build(builder);
    assert!(!frame.is_null(), "{}", last_message());
    frame
}

unsafe fn c_one() -> *mut RKRConFrame {
    let cell = [1.0, 2.0, 3.0];
    let angles = [90.0, 80.0, 70.0];
    let builder = rkr_frame_new(cell.as_ptr(), angles.as_ptr(), ptr::null(), ptr::null(), ptr::null(), ptr::null());
    assert!(!builder.is_null());
    assert_eq!(
        rkr_frame_add_atom_full(
            builder,
            c"He".as_ptr(),
            -0.0,
            f64::MIN_POSITIVE,
            -1.5e-7,
            false,
            false,
            true,
            7,
            4.0026,
            ptr::null(),
            ptr::null(),
        ),
        RKRStatus::RKR_STATUS_SUCCESS
    );
    let frame = rkr_frame_builder_build(builder);
    assert!(!frame.is_null());
    frame
}

unsafe fn c_empty() -> *mut RKRConFrame {
    let cell = [4.0, 5.0, 6.0];
    let angles = [90.0, 90.0, 90.0];
    let builder = rkr_frame_new(cell.as_ptr(), angles.as_ptr(), ptr::null(), ptr::null(), ptr::null(), ptr::null());
    assert!(!builder.is_null());
    let frame = rkr_frame_builder_build(builder);
    assert!(!frame.is_null());
    frame
}

#[test]
fn c_read_rejects_damage_and_null() {
    let frames = vec![rust_geometry(), rust_one()];
    let bytes = write_frames_to_vec(&frames).unwrap();
    let text = String::from_utf8(bytes.clone()).unwrap();
    let label = "Coordinates of Component 1\n";
    let cut = text.rfind(label).unwrap() + label.len();
    let directory = tempfile::tempdir().unwrap();
    let torn = directory.path().join("torn.con");
    std::fs::write(&torn, &text.as_bytes()[..cut]).unwrap();
    let name = CString::new(torn.to_str().unwrap()).unwrap();
    unsafe {
        let mut count = 7usize;
        let handles = rkr_read_all_frames(name.as_ptr(), &mut count);
        assert!(handles.is_null());
        assert_eq!(last_code(), RKRStatus::RKR_STATUS_PARSE_ERROR as i32);
        let message = last_message();
        assert!(message.contains("ended unexpectedly") || message.contains("Incomplete"), "{message}");

        let mut count = 7usize;
        assert!(rkr_read_all_frames(ptr::null(), &mut count).is_null());
        assert_eq!(last_code(), RKRStatus::RKR_STATUS_NULL_POINTER as i32);
        assert!(rkr_read_all_frames(name.as_ptr(), ptr::null_mut()).is_null());
        assert_eq!(last_code(), RKRStatus::RKR_STATUS_NULL_POINTER as i32);
        assert!(rkr_read_first_frame(ptr::null()).is_null());
        assert_eq!(last_code(), RKRStatus::RKR_STATUS_NULL_POINTER as i32);

        let mut out = ptr::null_mut();
        let mut len = 1usize;
        assert_eq!(
            rkr_write_frames_to_string(ptr::null(), 1, &mut out, &mut len),
            RKRStatus::RKR_STATUS_NULL_POINTER
        );
        assert_eq!(
            rkr_write_frames_to_string(ptr::null(), 0, ptr::null_mut(), &mut len),
            RKRStatus::RKR_STATUS_NULL_POINTER
        );

        free_rkr_frame(ptr::null_mut());
        free_c_frame(ptr::null_mut());
        free_rkr_frame_array(ptr::null_mut(), 0);
        free_rkr_frame_builder(ptr::null_mut());
        rkr_free_string(ptr::null_mut());
        rkr_free_position_block(ptr::null_mut());
        assert!(rkr_symbol_to_z(ptr::null()).eq(&0));
    }

    let zero = "\
zero count
{\"con_spec_version\":3,\"con_spec_minor\":1,\"units\":{\"length\":\"angstrom\",\"energy\":\"eV\",\"mass\":\"amu\",\"time\":\"fs\"}}
1.0 1.0 1.0
90.0 90.0 90.0
0 0
0 0 0
2
1 0
4.0 12.0
He
Coordinates of Component 1
0.0 0.0 0.0 0 1
";
    let zero_path = directory.path().join("zero.con");
    std::fs::write(&zero_path, zero).unwrap();
    let zero_name = CString::new(zero_path.to_str().unwrap()).unwrap();
    unsafe {
        let mut count = 3usize;
        assert!(rkr_read_all_frames(zero_name.as_ptr(), &mut count).is_null());
        assert_eq!(last_code(), RKRStatus::RKR_STATUS_PARSE_ERROR as i32);
        assert!(last_message().contains("count"), "{}", last_message());
    }

    let crlf: Vec<u8> = bytes.iter().flat_map(|byte| if *byte == b'\n' { vec![b'\r', b'\n'] } else { vec![*byte] }).collect();
    let mut bare = bytes.clone();
    bare.pop();
    for (label, body) in [("crlf.con", crlf), ("bare.con", bare)] {
        let path = directory.path().join(label);
        std::fs::write(&path, body).unwrap();
        let rust_frames = frames_from_bytes(&std::fs::read(&path).unwrap(), Some(4)).unwrap();
        let name = CString::new(path.to_str().unwrap()).unwrap();
        unsafe {
            let (handles, count) = read_c(&name, 4);
            assert_eq!(count, rust_frames.len());
            for index in 0..count {
                c_frame_matches_masses(*handles.add(index), &rust_frames[index]);
            }
            free_rkr_frame_array(handles, count);
        }
    }
}

#[test]
fn c_mass_mismatch_is_not_a_null_argument() {
    unsafe {
        let cell = [1.0, 1.0, 1.0];
        let angles = [90.0, 90.0, 90.0];
        let builder = rkr_frame_new(
            cell.as_ptr(),
            angles.as_ptr(),
            ptr::null(),
            ptr::null(),
            ptr::null(),
            ptr::null(),
        );
        assert!(!builder.is_null());
        assert_eq!(
            rkr_frame_add_atom_full(
                builder,
                c"Cu".as_ptr(),
                0.0,
                0.0,
                0.0,
                false,
                false,
                false,
                0,
                63.546,
                ptr::null(),
                ptr::null(),
            ),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_eq!(
            rkr_frame_add_atom_full(
                builder,
                c"Cu".as_ptr(),
                1.0,
                0.0,
                0.0,
                false,
                false,
                false,
                1,
                12.0,
                ptr::null(),
                ptr::null(),
            ),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        let frame = rkr_frame_builder_build(builder);
        assert!(frame.is_null());
        assert_ne!(last_code(), RKRStatus::RKR_STATUS_NULL_POINTER as i32);
        assert_eq!(last_code(), RKRStatus::RKR_STATUS_PARSE_ERROR as i32);
        assert!(
            last_message().contains("mass"),
            "{}",
            last_message()
        );
    }
}

#[test]
fn c_builder_null_symbol_is_an_error() {
    unsafe {
        let cell = [1.0, 1.0, 1.0];
        let angles = [90.0, 90.0, 90.0];
        let builder = rkr_frame_new(cell.as_ptr(), angles.as_ptr(), ptr::null(), ptr::null(), ptr::null(), ptr::null());
        assert!(!builder.is_null());
        let status = rkr_frame_add_atom_full(
            builder,
            ptr::null(),
            0.0,
            0.0,
            0.0,
            false,
            false,
            false,
            0,
            1.0,
            ptr::null(),
            ptr::null(),
        );
        assert_ne!(status, RKRStatus::RKR_STATUS_SUCCESS);
        assert!((status as i32) < 0);
        free_rkr_frame_builder(builder);
        assert!(rkr_frame_new(ptr::null(), angles.as_ptr(), ptr::null(), ptr::null(), ptr::null(), ptr::null()).is_null());
    }
}
