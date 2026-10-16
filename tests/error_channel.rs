//! Thread-local C ABI error channel (D1, D4, D10).

use std::ffi::{CStr, CString};
use std::fs;
use std::path::PathBuf;

use readcon_core::ffi::{
    RKRStatus, free_rkr_frame, rkr_clear_error, rkr_last_error, rkr_read_first_frame,
    rkr_read_nth_frame,
};
use readcon_core::iterators::{
    ConFrameIterator, LoadError, count_frames, frames_from_bytes, frames_from_text_located,
    read_all_frames_located, read_first_frame, read_first_frame_located, read_nth_frame,
    read_nth_frame_from_text, read_nth_frame_located,
};
use readcon_core::units::{
    NATURAL_TIME_UNIT, canonicalize_unit_expression, unit_conversion_factor,
    validate_unit_for_quantity, validate_v3_units_metadata, velocity_file_time_unit,
    velocity_scale_to_natural,
};

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

/// A skip that dies on an earlier frame must name that frame, not the index asked for.
#[test]
fn skip_failure_names_the_frame_that_failed() {
    let good = one_atom("0 0 0 0 0");
    let bad = "seed\n{\"con_spec_version\":2}\n10 10 10\n90 90 90\n0 0\n0 0 0\n1\n-1\n1.0\nH\nCoordinates of Component 1\n0 0 0 0 0\n";
    let text = format!("{good}{bad}{good}");
    let path = write("skip-idx", &text);
    let err = read_nth_frame_located(path_for("skip-idx").as_path(), 4).unwrap_err();
    match err {
        LoadError::Parse(located) => {
            assert_eq!(located.frame_index, 1, "{located}");
            assert_eq!(located.error.class_name(), "InvalidCount");
        }
        other => panic!("expected a parse error, got {other}"),
    }
    rkr_clear_error();
    assert!(unsafe { rkr_read_nth_frame(path.as_ptr(), 4) }.is_null());
    let stored = unsafe { &*rkr_last_error() };
    assert_eq!(stored.frame_index, 1);
    let message = unsafe { CStr::from_ptr(stored.message) }.to_string_lossy();
    assert!(message.contains("InvalidCount"), "{message}");
    let _ = fs::remove_file(path_for("skip-idx"));
}

fn expect_parse(err: LoadError) -> readcon_core::error::LocatedParseError {
    match err {
        LoadError::Parse(located) => located,
        other => panic!("expected a parse error, got {other}"),
    }
}

/// IO, UTF-8, empty files, and a failure on the frame that was asked for.
#[test]
fn located_readers_cover_every_load_error() {
    let missing = path_for("missing-load");
    let _ = fs::remove_file(&missing);
    let io_errs = [
        read_first_frame_located(&missing).unwrap_err(),
        read_all_frames_located(&missing, None).unwrap_err(),
        read_nth_frame_located(&missing, 0).unwrap_err(),
    ];
    for err in io_errs {
        match &err {
            LoadError::Io(io) => assert_eq!(io.kind(), std::io::ErrorKind::NotFound),
            other => panic!("expected io, got {other}"),
        }
        assert!(!err.to_string().is_empty(), "{err}");
    }

    let _ = write("empty-load", "");
    let empty = read_first_frame_located(path_for("empty-load").as_path()).unwrap_err();
    assert!(matches!(empty, LoadError::Empty), "{empty}");
    assert_eq!(empty.to_string(), "no frames found in file");
    let none = read_all_frames_located(path_for("empty-load").as_path(), Some(1)).unwrap();
    assert!(none.is_empty());

    // Files at or above 64 KiB are mapped. `as_str` is then the UTF-8 check.
    let mut bad = vec![b'\n'; 64 * 1024];
    bad[0] = 0xff;
    let bad_path = path_for("bad-utf8");
    fs::write(&bad_path, &bad).unwrap();
    let utf = read_first_frame_located(&bad_path).unwrap_err();
    assert!(matches!(utf, LoadError::Utf8(_)), "{utf}");
    assert!(utf.to_string().to_lowercase().contains("utf-8"), "{utf}");
    let _ = fs::remove_file(&bad_path);

    let nan = format!("{}{}", one_atom("0 0 0 0 0"), one_atom("nan 0 0 0 0"));
    let nan_path = write("nth-nan", &nan);
    let located =
        expect_parse(read_nth_frame_located(path_for("nth-nan").as_path(), 1).unwrap_err());
    assert_eq!(located.frame_index, 1);
    assert_eq!(located.line, 24, "{located}");
    assert_eq!(located.error.class_name(), "NonFiniteValue");
    let shown = LoadError::Parse(located).to_string();
    assert!(shown.contains("non-finite"), "{shown}");
    let _ = fs::remove_file(nan_path.to_string_lossy().to_string());

    let one = write("nth-past", &one_atom("0 0 0 0 0"));
    let past = expect_parse(read_nth_frame_located(path_for("nth-past").as_path(), 1).unwrap_err());
    assert_eq!(past.frame_index, 1, "{past}");
    assert_eq!(past.error.class_name(), "IncompleteFrame");
    assert!(past.line > 0, "{past}");
    let _ = fs::remove_file(one.to_string_lossy().to_string());
    let _ = fs::remove_file(path_for("empty-load"));
}

/// The pre-located helpers stay reachable after the C ABI moved to located reads.
#[test]
fn legacy_readers_report_range_and_parse_failures() {
    let _ = write("legacy-empty", "");
    let empty = path_for("legacy-empty");
    let err = read_first_frame(&empty).unwrap_err();
    assert!(err.to_string().contains("No frames"), "{err}");
    let err = read_nth_frame(&empty, 0).unwrap_err();
    assert!(err.to_string().contains("out of range"), "{err}");

    let text = one_atom("0 0 0 0 0");
    let _ = write("legacy-one", &text);
    let frame = read_nth_frame(path_for("legacy-one").as_path(), 0).unwrap();
    assert_eq!(frame.atom_data.len(), 1);
    let err = read_nth_frame_from_text(&text, 3).unwrap_err();
    assert!(err.to_string().contains("only 1"), "{err}");
    let bad = format!("{text}{}", one_atom("nan 0 0 0 0"));
    let err = read_nth_frame_from_text(&bad, 1).unwrap_err();
    assert!(err.to_string().contains("non-finite"), "{err}");
    assert_eq!(count_frames(path_for("legacy-one").as_path()).unwrap(), 1);

    let broken = "seed\n{\"con_spec_version\":2}\n10 10 10\n90 90 90\n0 0\n0 0 0\n1\n-1\n";
    let _ = write("legacy-bad", broken);
    let err = count_frames(path_for("legacy-bad").as_path()).unwrap_err();
    assert!(err.to_string().contains("invalid count"), "{err}");
    let err = read_first_frame(path_for("legacy-bad").as_path()).unwrap_err();
    assert!(err.to_string().contains("invalid count"), "{err}");

    let mut bytes = text.into_bytes();
    let at = bytes.windows(11).position(|w| w == b"Coordinates").unwrap();
    bytes[at] = 0xff;
    let err = ConFrameIterator::from_bytes(&bytes)
        .next()
        .unwrap()
        .unwrap_err();
    assert_eq!(err.class_name(), "ValidationError");
    assert!(err.to_string().contains("UTF-8"), "{err}");

    let nan = one_atom("nan 0 0 0 0");
    let mut iter = ConFrameIterator::new(&nan);
    let err = iter.next_with_raw_span(&nan).unwrap().unwrap_err();
    assert_eq!(err.class_name(), "NonFiniteValue");

    let _ = fs::remove_file(path_for("legacy-empty"));
    let _ = fs::remove_file(path_for("legacy-one"));
    let _ = fs::remove_file(path_for("legacy-bad"));
}

#[test]
fn located_parallel_policy_reads_an_empty_buffer_and_a_long_file() {
    assert!(frames_from_text_located("", Some(2)).unwrap().is_empty());
    let one = one_atom("0 0 0 0 0");
    let copies = (48 * 1024) / one.len() + 2;
    let big = one.repeat(copies);
    assert!(big.len() >= 48 * 1024);
    assert_eq!(frames_from_text_located(&big, None).unwrap().len(), copies);
    assert_eq!(
        frames_from_bytes(big.as_bytes(), None).unwrap().len(),
        copies
    );

    let later = format!("{one}{}", one_atom("nan 0 0 0 0"));
    let err = frames_from_text_located(&later, Some(2)).unwrap_err();
    assert_eq!(err.frame_index, 1);
    assert_eq!(err.line, 24, "{err}");
    assert_eq!(err.error.class_name(), "NonFiniteValue");
}

#[cfg(feature = "parallel")]
#[test]
fn parallel_blank_chunk_is_an_incomplete_frame() {
    let err = frames_from_text_located(" \n", Some(2)).unwrap_err();
    assert_eq!(err.error.class_name(), "IncompleteFrame");
    assert_eq!(err.frame_index, 0);
    assert_eq!(err.line, 1, "{err}");

    let parts = readcon_core::iterators::parse_frames_parallel(" \n");
    assert_eq!(parts.len(), 1);
    assert!(matches!(
        &parts[0],
        Err(err) if err.class_name() == "IncompleteFrame"
    ));

    // A truncated header stops the byte scanner on the error. A non-breaking
    // space is not ASCII whitespace, so it is still a chunk, and the parser
    // then reports that the chunk holds no frame.
    let err = frames_from_bytes(b"seed\n", Some(2)).unwrap_err();
    assert_eq!(err.class_name(), "IncompleteHeader");
    let blank = "\u{00A0}\n";
    let err = frames_from_bytes(blank.as_bytes(), Some(2)).unwrap_err();
    assert_eq!(err.class_name(), "IncompleteFrame");
}

#[cfg(feature = "parallel")]
#[test]
fn indexed_read_covers_owned_and_mapped_files() {
    let one = one_atom("0 0 0 0 0");
    let small = path_for("idx-small");
    fs::write(&small, &one).unwrap();
    let frames = readcon_core::iterators::read_all_frames_indexed(&small, Some(1)).unwrap();
    assert_eq!(frames.len(), 1);
    let again = readcon_core::iterators::read_all_frames_indexed(&small, None).unwrap();
    assert_eq!(again.len(), 1);

    let copies = (64 * 1024) / one.len() + 2;
    let big = one.repeat(copies);
    let mapped = path_for("idx-mapped");
    fs::write(&mapped, &big).unwrap();
    assert!(mapped.metadata().unwrap().len() >= 64 * 1024);
    let first = read_first_frame_located(&mapped).unwrap();
    assert_eq!(first.atom_data.len(), 1);
    let frames = readcon_core::iterators::read_all_frames_indexed(&mapped, Some(2)).unwrap();
    assert_eq!(frames.len(), copies);

    for path in [small, mapped] {
        let _ = fs::remove_file(readcon_core::frame_index::sidecar_path(&path));
        let _ = fs::remove_file(path);
    }
}

#[test]
fn unit_edges_cover_override_time_and_rejected_spellings() {
    let mut meta = serde_json::Map::new();
    meta.insert("con_spec_minor".into(), serde_json::json!(1));
    assert_eq!(velocity_file_time_unit(3, &meta, Some("ps")).unwrap(), "ps");
    let missing = velocity_file_time_unit(3, &meta, None).unwrap_err();
    assert_eq!(missing.class_name(), "InvalidUnits");
    assert!(missing.to_string().contains("units.time"));

    validate_unit_for_quantity("velocity", "angstrom/fs").unwrap();
    validate_unit_for_quantity("force", "eV/angstrom").unwrap();
    let unknown = validate_unit_for_quantity("spell", "fs").unwrap_err();
    assert!(
        unknown.to_string().contains("unknown quantity"),
        "{unknown}"
    );

    assert!(validate_v3_units_metadata(&serde_json::json!({"length": 1, "energy": "eV"})).is_err());
    assert!(
        validate_v3_units_metadata(&serde_json::json!({"length": " ", "energy": "eV"})).is_err()
    );
    assert!(
        validate_v3_units_metadata(&serde_json::json!({
            "length": "angstrom",
            "energy": "eV",
            "time": 3
        }))
        .is_err()
    );

    let factor = unit_conversion_factor("(angstrom)", "angstrom").unwrap();
    assert!((factor - 1.0).abs() < 1e-12, "{factor}");
    let inv = unit_conversion_factor("m^-2", "m^-2").unwrap();
    assert!((inv - 1.0).abs() < 1e-12, "{inv}");
    assert!(
        unit_conversion_factor("m^", "m")
            .unwrap_err()
            .to_string()
            .contains("exponent")
    );
    assert!(
        unit_conversion_factor("(m", "m")
            .unwrap_err()
            .to_string()
            .contains("unbalanced")
    );
    assert!(unit_conversion_factor("@", "m").is_err());

    assert_eq!(canonicalize_unit_expression("kg").unwrap(), "kg");
    assert_eq!(canonicalize_unit_expression("mol").unwrap(), "mol");
    assert_eq!(canonicalize_unit_expression("e").unwrap(), "e");
    assert!(canonicalize_unit_expression("").is_err());
    assert!(canonicalize_unit_expression("   ").is_err());
}
