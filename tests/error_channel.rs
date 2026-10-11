//! Thread-local C ABI error channel (D1, D4, D10).

use std::ffi::{CStr, CString};
use std::fs;
use std::path::PathBuf;

use readcon_core::ffi::{
    RKRStatus, free_rkr_frame, rkr_clear_error, rkr_last_error, rkr_read_first_frame,
};
use readcon_core::iterators::frames_from_text_located;
use readcon_core::units::{NATURAL_TIME_UNIT, velocity_file_time_unit, velocity_scale_to_natural};

fn path_for(name: &str) -> PathBuf {
    std::env::temp_dir().join(format!("readcon-{name}-{}", std::process::id()))
}

fn write(name: &str, text: &str) -> CString {
    let path = path_for(name);
    fs::write(&path, text).unwrap();
    CString::new(path.to_string_lossy().as_bytes()).unwrap()
}

fn one_atom(coord: &str) -> String {
    format!(
        "seed\n{{\"con_spec_version\":2}}\n10 10 10\n90 90 90\n0 0\n0 0 0\n1\n1\n1.0\nH\nCoordinates of Component 1\n{coord}\n"
    )
}

#[test]
fn last_error_names_the_class_and_the_line() {
    rkr_clear_error();
    let path = write("nan", &one_atom("nan 0 0 0 0"));
    let frame = unsafe { rkr_read_first_frame(path.as_ptr()) };
    assert!(frame.is_null());
    let err = rkr_last_error();
    assert!(!err.is_null());
    let err = unsafe { &*err };
    assert_eq!(err.code, RKRStatus::RKR_STATUS_PARSE_ERROR as i32);
    assert_eq!(err.line, 12);
    assert_eq!(err.frame_index, 0);
    let message = unsafe { CStr::from_ptr(err.message) }.to_string_lossy();
    assert!(message.contains("NonFiniteValue"), "{message}");
    let good = write("ok", &one_atom("0 0 0 0 0"));
    let frame = unsafe { rkr_read_first_frame(good.as_ptr()) };
    assert!(!frame.is_null());
    unsafe { free_rkr_frame(frame) };
    let still = rkr_last_error();
    assert!(!still.is_null());
    rkr_clear_error();
    assert!(rkr_last_error().is_null());
    let _ = fs::remove_file(path_for("nan"));
    let _ = fs::remove_file(path_for("ok"));
}

#[test]
fn a_signed_count_is_invalid_count() {
    rkr_clear_error();
    let text = "seed\n{\"con_spec_version\":2}\n10 10 10\n90 90 90\n0 0\n0 0 0\n1\n-1\n1.0\nH\nCoordinates of Component 1\n0 0 0 0 0\n";
    let path = write("neg", text);
    assert!(unsafe { rkr_read_first_frame(path.as_ptr()) }.is_null());
    let err = unsafe { &*rkr_last_error() };
    let message = unsafe { CStr::from_ptr(err.message) }.to_string_lossy();
    assert!(message.contains("InvalidCount"), "{message}");
    assert!(!message.contains("InvalidNumberFormat"), "{message}");
    assert_eq!(err.line, 8);
    let _ = fs::remove_file(path_for("neg"));
}

/// CON-error.4. The count token on line 8 wins at 1, 2, 3, and 8 threads.
#[test]
fn the_lowest_line_wins_at_every_thread_count() {
    let early = "seed\n{\"con_spec_version\":2}\n10 10 10\n90 90 90\n0 0\n0 0 0\n2\n1 0\n1.0 1.0\n";
    let text = format!("{early}{}", one_atom("nan 0 0 0 0"));
    for threads in [1usize, 2, 3, 8] {
        let err = frames_from_text_located(&text, Some(threads)).unwrap_err();
        assert_eq!(
            err.error.class_name(),
            "InvalidCount",
            "threads {threads}: {err}"
        );
        assert_eq!(err.line, 8, "threads {threads}");
        assert_eq!(err.frame_index, 0, "threads {threads}");
    }
}

#[test]
fn parallel_workers_do_not_share_the_error_slot() {
    let a = one_atom("nan 0 0 0 0");
    let b = one_atom("inf 0 0 0 0");
    let pa = write("thr-a", &a);
    let pb = write("thr-b", &b);
    let (sa, sb) = std::thread::scope(|scope| {
        let left = scope.spawn(|| {
            assert!(unsafe { rkr_read_first_frame(pa.as_ptr()) }.is_null());
            unsafe { CStr::from_ptr((*rkr_last_error()).message) }
                .to_string_lossy()
                .into_owned()
        });
        let right = scope.spawn(|| {
            assert!(unsafe { rkr_read_first_frame(pb.as_ptr()) }.is_null());
            unsafe { CStr::from_ptr((*rkr_last_error()).message) }
                .to_string_lossy()
                .into_owned()
        });
        (left.join().unwrap(), right.join().unwrap())
    });
    assert!(sa.contains("nan"), "{sa}");
    assert!(sb.contains("inf"), "{sb}");
    assert_ne!(sa, sb);
    let _ = fs::remove_file(path_for("thr-a"));
    let _ = fs::remove_file(path_for("thr-b"));
}

#[test]
fn second_frame_keeps_its_index_and_file_line() {
    let text = format!("{}{}", one_atom("0 0 0 0 0"), one_atom("nan 0 0 0 0"));
    let err = frames_from_text_located(&text, Some(1)).unwrap_err();
    assert_eq!(err.frame_index, 1);
    assert_eq!(err.line, 24);
    assert_eq!(err.error.class_name(), "NonFiniteValue");
}

#[test]
fn v3_0_velocities_stay_in_the_natural_unit() {
    let mut meta = serde_json::Map::new();
    meta.insert(
        "units".into(),
        serde_json::json!({"length": "angstrom", "energy": "eV", "time": "fs"}),
    );
    let unit = velocity_file_time_unit(3, &meta, None).unwrap();
    assert_eq!(unit, NATURAL_TIME_UNIT);
    meta.insert("con_spec_minor".into(), serde_json::json!(1));
    let unit = velocity_file_time_unit(3, &meta, None).unwrap();
    assert_eq!(unit, "fs");
    let scale = velocity_scale_to_natural("fs").unwrap();
    assert!((scale - 10.180505710759414).abs() < 1e-9, "{scale}");
    assert!((velocity_scale_to_natural(NATURAL_TIME_UNIT).unwrap() - 1.0).abs() < 1e-12);
}

#[test]
fn class_names_and_write_errors_cover_every_variant() {
    use readcon_core::error::{LocatedParseError, ParseError};
    use readcon_core::writer::WriteError;
    use std::error::Error;
    use std::io;

    let cases = [
        (
            ParseError::IncompleteVelocitySection,
            "IncompleteVelocitySection",
        ),
        (ParseError::IncompleteForceSection, "IncompleteForceSection"),
        (
            ParseError::IncompleteEnergySection,
            "IncompleteEnergySection",
        ),
        (ParseError::UnsupportedVersion(0), "UnsupportedVersion"),
        (
            ParseError::IndexOutOfBounds { index: 3, len: 1 },
            "IndexOutOfBounds",
        ),
        (
            ParseError::MassMismatch {
                symbol: "H".into(),
                first_mass: 1.0,
                found_mass: 2.0,
                atom_index: 1,
            },
            "MassMismatch",
        ),
    ];
    for (err, name) in cases {
        assert_eq!(err.class_name(), name);
        let located = LocatedParseError::new(err.clone(), 0, 0);
        assert_eq!(located.line, err.line());
        assert!(!located.to_string().is_empty());
        assert!(Error::source(&located).is_some());
    }
    assert_eq!(ParseError::UnsupportedVersion(0).line(), 2);
    assert_eq!(ParseError::IncompleteVelocitySection.line(), 0);

    let write_io = WriteError::from(io::Error::new(io::ErrorKind::Other, "disk"));
    assert!(write_io.to_string().contains("disk"));
    assert!(std::error::Error::source(&write_io).is_some());
    let write_fmt = WriteError::Format(ParseError::InvalidCount("x".into()));
    assert!(write_fmt.to_string().contains("invalid count"));
    assert!(std::error::Error::source(&write_fmt).is_some());
    let back: io::Error = WriteError::Format(ParseError::InvalidUnits("t".into())).into();
    assert_eq!(back.kind(), io::ErrorKind::InvalidData);
    let back_io: io::Error =
        WriteError::from(io::Error::new(io::ErrorKind::NotFound, "gone")).into();
    assert_eq!(back_io.kind(), io::ErrorKind::NotFound);
}
