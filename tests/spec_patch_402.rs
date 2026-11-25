//! Cell-geometry clauses added with specification 4.0.2.

use readcon_core::error::ParseError;
use readcon_core::iterators::{ConFrameIterator, read_coord_columns, read_positions_with_threads};
use readcon_core::types::{ConFrameBuilder, require_real_cell};
use std::fs;

fn class_of(text: &str) -> String {
    match ConFrameIterator::new(text).next() {
        Some(Err(err)) => err.class_name().to_string(),
        Some(Ok(_)) => "ok".into(),
        None => "empty".into(),
    }
}

fn periodic_frame(boxl: &str, angles: &str, pbc: &str) -> String {
    format!(
        "t\n{{\"con_spec_version\":4{pbc},\"units\":{{\"length\":\"angstrom\",\"energy\":\"eV\"}}}}\n\
         {boxl}\n{angles}\n\n\n1\n1\n1\nH\nCoordinates of Component 1\n0 0 0 0 0\n"
    )
}

/// CON-cell.7. Column and FFI readers reject impossible angles.
#[test]
fn con_cell_7_column_readers_reject_impossible_angles() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("impossible-angle.con");
    fs::write(&path, periodic_frame("10 10 10", "10 10 170", "")).unwrap();

    let positions = read_positions_with_threads(&path, None).unwrap_err();
    assert!(positions.to_string().contains("no real c vector"));
    let coords = match read_coord_columns(&path, None) {
        Ok(_) => panic!("coordinate columns accepted the frame"),
        Err(err) => err,
    };
    assert!(coords.to_string().contains("no real c vector"));

    #[cfg(feature = "capi")]
    {
        let c_path = std::ffi::CString::new(path.to_str().unwrap()).unwrap();
        let mut n_frames = 0usize;
        let mut n_atoms = 0usize;
        let block = unsafe {
            readcon_core::ffi::rkr_read_positions(c_path.as_ptr(), &mut n_frames, &mut n_atoms)
        };
        assert!(block.is_null());
        let message = unsafe {
            std::ffi::CStr::from_ptr(readcon_core::ffi::rkr_last_error_message()).to_string_lossy()
        };
        assert!(message.contains("ValidationError"), "{message}");
        let threaded = unsafe {
            readcon_core::ffi::rkr_read_positions_n_threads(
                c_path.as_ptr(),
                &mut n_frames,
                &mut n_atoms,
                2,
            )
        };
        assert!(threaded.is_null());
    }
}

/// CON-cell.7. Frame parsing and direct construction reject impossible angles.
#[test]
fn con_cell_7_impossible_angles_are_rejected() {
    let err = require_real_cell([10.0, 10.0, 170.0]);
    assert!(matches!(err, Err(ParseError::ValidationError(_))));
    assert_eq!(
        class_of(&periodic_frame("10 10 10", "10 10 170", "")),
        "ValidationError"
    );

    let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [10.0, 10.0, 170.0]);
    builder.prebox_header("title");
    builder.add_atom("H", 0.0, 0.0, 0.0, [false, false, false], 1, 1.0);
    assert!(builder.build().is_err());
}

/// CON-cell.3, CON-validate.1, CON-validate.4. A non-positive length or an
/// angle outside (0, 180) is a validate-mode check, periodic or not.
#[test]
fn degenerate_cells_are_validate_mode_checks() {
    for (boxl, angles) in [("0 0 0", "90 90 90"), ("10 10 10", "0 0 0")] {
        assert_eq!(class_of(&periodic_frame(boxl, angles, "")), "ok");
        assert_eq!(
            class_of(&periodic_frame(
                boxl,
                angles,
                ",\"validate\":true,\"sections\":[]"
            )),
            "ValidationError"
        );
    }
    assert_eq!(
        class_of(
            "t\nlegacy\n0 0 0\n90 90 90\n\n\n1\n1\n1\nH\nCoordinates of Component 1\n0 0 0 0 0\n"
        ),
        "ok"
    );

    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("zero-periodic.con");
    fs::write(&path, periodic_frame("0 0 0", "90 90 90", "")).unwrap();
    assert!(read_positions_with_threads(&path, None).is_ok());
    assert!(read_coord_columns(&path, None).is_ok());

    let mut builder = ConFrameBuilder::new([0.0, 0.0, 0.0], [90.0, 90.0, 90.0]);
    builder.prebox_header("molecule");
    builder.add_atom("H", 0.0, 0.0, 0.0, [false, false, false], 1, 1.0);
    assert!(builder.build().is_ok());
}
