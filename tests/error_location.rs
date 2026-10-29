//! Opt-in error locations: `ConFrameIterator::next_located` and
//! `locate_first_error` (CON-error.2, CON-error.4).

use readcon_core::error::{ErrorLocation, LocatedParseError};
use readcon_core::iterators::{ConFrameIterator, locate_first_error, locate_first_error_in_file};
use readcon_core::writer::ConFrameWriter;
use std::io::Write;
use std::path::{Path, PathBuf};

mod common;

fn two_frames() -> String {
    std::fs::read_to_string(test_case!("tiny_multi_cuh2.con")).expect("fixture")
}

/// Replace 1-based line `n` of `text`.
fn with_line(text: &str, n: usize, line: &str) -> String {
    let mut lines: Vec<&str> = text.lines().collect();
    lines[n - 1] = line;
    lines.join("\n") + "\n"
}

fn located(text: &str) -> LocatedParseError {
    locate_first_error(text.as_bytes()).expect("an error")
}

fn at(err: &LocatedParseError) -> (usize, u64, Option<u64>) {
    let ErrorLocation {
        frame,
        line,
        column,
        ..
    } = err.location;
    (frame, line, column)
}

#[test]
fn bad_float_in_second_frame() {
    let text = with_line(&two_frames(), 29, "   0.63x4    0.9045    6.9752 7    0");
    let err = located(&text);
    assert_eq!(err.error.class_name(), "InvalidNumberFormat");
    assert_eq!(at(&err), (1, 29, Some(4)));
    let line_start = text.lines().take(28).map(|l| l.len() + 1).sum::<usize>();
    assert_eq!(err.location.byte_offset, line_start);
    assert_eq!(
        err.to_string(),
        "line 29, column 4 (frame 1): invalid number format: invalid float: 0.63x4"
    );
}

#[test]
fn truncated_last_frame_points_past_the_end() {
    let full = two_frames();
    let text: String = full.lines().take(33).map(|l| format!("{l}\n")).collect();
    let err = located(&text);
    assert_eq!(err.error.class_name(), "IncompleteFrame");
    assert_eq!(at(&err), (1, 34, None));
    assert_eq!(err.location.byte_offset, text.len());
    // Same answer when the final newline is also gone.
    let err = located(text.trim_end_matches('\n'));
    assert_eq!(at(&err), (1, 34, None));
}

#[test]
fn metadata_line_of_a_later_frame() {
    let text = with_line(&two_frames(), 19, "{\"con_spec_version\":2,}");
    let err = located(&text);
    assert_eq!(err.error.class_name(), "InvalidMetadataJson");
    // `ParseError::line` keeps its frame-relative answer.
    assert_eq!(err.error.line(), 2);
    assert_eq!(at(&err), (1, 19, None));
}

#[test]
fn extra_field_and_non_finite_columns() {
    let text = with_line(&two_frames(), 13, "   0.6394    0.9045    6.9753 7    0 9");
    let err = located(&text);
    assert_eq!(err.error.class_name(), "InvalidVectorLength");
    assert_eq!(at(&err), (0, 13, Some(38)));

    let text = with_line(&two_frames(), 20, "15.3456\tnan\t100.0");
    let err = located(&text);
    assert_eq!(err.error.class_name(), "NonFiniteValue");
    assert_eq!(at(&err), (1, 20, Some(9)));
}

#[test]
fn repeated_token_has_no_column() {
    // The flag and the id are both `9`, so the column is not reported.
    let text = with_line(&two_frames(), 13, "   0.6394    0.9045    6.9753 9    9");
    let err = located(&text);
    assert_eq!(err.error.class_name(), "InvalidFixedFlag");
    assert_eq!(at(&err), (0, 13, None));
}

#[test]
fn conformance_invalid_fixtures() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("resources/conformance/invalid");
    let cases: [(&str, &str, u64, Option<u64>); 4] = [
        ("column4_out_of_range.con", "InvalidFixedFlag", 12, Some(28)),
        ("per_type_zero.con", "InvalidCount", 8, None),
        ("missing_spec_version.con", "MissingSpecVersion", 2, None),
        ("v3_missing_units.con", "InvalidUnits", 2, None),
    ];
    for (name, class, line, column) in cases {
        let err = locate_first_error_in_file(&root.join(name))
            .expect("read")
            .expect("an error");
        assert_eq!(err.error.class_name(), class, "{name}");
        assert_eq!(at(&err), (0, line, column), "{name}");
    }
}

#[test]
fn missing_declared_section_points_at_the_next_line() {
    let frame = "PRE\n{\"con_spec_version\":2,\"sections\":[\"forces\"]}\n10 10 10\n90 90 90\n\n\n1\n1\n1.0\nH\nCoordinates of Component 1\n0 0 0 0 0\n";
    let text = format!("{frame}{frame}");
    let err = located(&text);
    assert_eq!(err.error.class_name(), "IncompleteSection");
    assert_eq!(at(&err), (0, 13, None));
}

#[test]
fn section_arity_column_is_the_value() {
    let spaced =
        r#"{"con_spec_version": 2, "section_arity": {"forces": 5}, "sections": ["forces"]}"#;
    let err = located(&with_line(&two_frames(), 2, spaced));
    assert_eq!(err.error.class_name(), "InvalidVectorLength");
    assert_eq!(at(&err), (0, 2, Some(53)));

    let compact = r#"{"con_spec_version":2,"section_arity":{"forces":5},"sections":["forces"]}"#;
    let err = located(&with_line(&two_frames(), 19, compact));
    assert_eq!(err.error.class_name(), "InvalidVectorLength");
    assert_eq!(at(&err), (1, 19, Some(49)));

    // Two entries fit the error, so neither is named.
    let twice = r#"{"con_spec_version":2,"section_arity":{"forces":5,"velocities":5},"sections":["forces"]}"#;
    let err = located(&with_line(&two_frames(), 2, twice));
    assert_eq!(err.error.class_name(), "InvalidVectorLength");
    assert_eq!(at(&err), (0, 2, None));
}

#[test]
fn unknown_section_is_on_the_metadata_line() {
    let meta = r#"{"con_spec_version":2, "sections": ["bogus"]}"#;
    let err = located(&with_line(&two_frames(), 19, meta));
    assert_eq!(err.error.class_name(), "UnknownSection");
    assert_eq!(at(&err), (1, 19, Some(37)));
}

#[test]
fn missing_time_unit_is_on_the_metadata_line() {
    let text = std::fs::read_to_string(test_case!("tiny_multi_cuh2.convel")).expect("fixture");
    let meta = r#"{"con_spec_version":3,"con_spec_minor":1,"units":{"length":"angstrom","energy":"eV"},"sections":["velocities"]}"#;
    let err = located(&with_line(&text, 28, meta));
    assert_eq!(err.error.class_name(), "InvalidUnits");
    assert_eq!(at(&err), (1, 28, None));
}

#[test]
fn unknown_symbol_is_on_the_symbol_line() {
    let text = with_line(
        &two_frames(),
        19,
        r#"{"con_spec_version":2,"validate":true,"sections":[]}"#,
    );
    let err = located(&with_line(&text, 27, "  Zz"));
    assert_eq!(err.error.class_name(), "ValidationError");
    assert_eq!(
        err.error.to_string(),
        "CON validation failed: unknown component symbol Zz"
    );
    assert_eq!(at(&err), (1, 27, Some(3)));

    let text = std::fs::read_to_string(test_case!("tiny_multi_cuh2.convel")).expect("fixture");
    let meta = r#"{"con_spec_version":2,"validate":true,"sections":["velocities"]}"#;
    let text = with_line(&with_line(&text, 2, meta), 19, " H");
    let err = located(&text);
    assert_eq!(
        err.error.to_string(),
        "CON validation failed: Velocities component 1 symbol mismatch: expected Cu, found H"
    );
    assert_eq!(at(&err), (0, 19, Some(2)));
}

#[test]
fn velocity_row() {
    let text = std::fs::read_to_string(test_case!("tiny_multi_cuh2.convel")).expect("fixture");
    let text = with_line(&text, 21, "   0.001234    0.00z345   -0.003456 7    0");
    let err = located(&text);
    assert_eq!(err.error.class_name(), "InvalidNumberFormat");
    assert_eq!(at(&err), (0, 21, Some(16)));
}

#[test]
fn invalid_utf8_line() {
    let mut bytes = two_frames().into_bytes();
    let line_18 = two_frames()
        .lines()
        .take(17)
        .map(|l| l.len() + 1)
        .sum::<usize>();
    bytes[line_18] = 0xff;
    let err = locate_first_error(&bytes).expect("an error");
    assert_eq!(err.error.class_name(), "ValidationError");
    assert_eq!(at(&err), (1, 18, None));
}

#[test]
fn crlf_lines_count_the_same() {
    let text =
        with_line(&two_frames(), 29, "   0.63x4    0.9045    6.9752 7    0").replace('\n', "\r\n");
    assert_eq!(at(&located(&text)), (1, 29, Some(4)));
}

#[test]
fn lowest_line_wins_and_valid_input_has_none() {
    assert!(locate_first_error(two_frames().as_bytes()).is_none());
    let text = with_line(&two_frames(), 30, "   3.1969    0.9045    6.9752 x    1");
    let text = with_line(&text, 13, "   3.1969    0.9045    6.9753 7    y");
    assert_eq!(at(&located(&text)), (0, 13, Some(36)));
}

#[test]
fn gzip_input_is_located_in_its_text() {
    let text = with_line(&two_frames(), 29, "   0.63x4    0.9045    6.9752 7    0");
    let dir = tempfile::tempdir().expect("tempdir");
    let path = dir.path().join("bad.con.gz");
    let mut gz = flate2::write::GzEncoder::new(
        std::fs::File::create(&path).expect("create"),
        flate2::Compression::default(),
    );
    gz.write_all(text.as_bytes()).expect("write");
    gz.finish().expect("finish");
    let err = locate_first_error_in_file(&path)
        .expect("read")
        .expect("an error");
    assert_eq!(at(&err), (1, 29, Some(4)));
}

fn written(frames: &[readcon_core::types::ConFrame]) -> Vec<u8> {
    let mut buf = Vec::new();
    ConFrameWriter::new(&mut buf)
        .extend(frames.iter())
        .expect("write");
    buf
}

/// The opt-in path parses the same frames and reports the same errors, so
/// default writer output does not move.
#[test]
fn next_located_matches_next() {
    let dir = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("resources/test");
    let mut checked = 0;
    for entry in std::fs::read_dir(&dir).expect("fixtures") {
        let path = entry.expect("entry").path();
        let Some(ext) = path.extension().and_then(|e| e.to_str()) else {
            continue;
        };
        if ext != "con" && ext != "convel" {
            continue;
        }
        let text = std::fs::read_to_string(&path).expect("read");
        let plain: Vec<_> = ConFrameIterator::new(&text).collect();
        let mut iter = ConFrameIterator::new(&text);
        let mut opt_in = Vec::new();
        while let Some(r) = iter.next_located() {
            opt_in.push(r);
        }
        assert_eq!(plain.len(), opt_in.len(), "{path:?}");
        let mut ok_plain = Vec::new();
        let mut ok_opt_in = Vec::new();
        for (a, b) in plain.into_iter().zip(opt_in) {
            match (a, b) {
                (Ok(a), Ok(b)) => {
                    ok_plain.push(a);
                    ok_opt_in.push(b);
                }
                (Err(a), Err(b)) => {
                    assert_eq!(a.class_name(), b.error.class_name(), "{path:?}");
                    assert_eq!(a.to_string(), b.error.to_string(), "{path:?}");
                }
                _ => panic!("next and next_located disagree on {path:?}"),
            }
        }
        assert_eq!(written(&ok_plain), written(&ok_opt_in), "{path:?}");
        checked += 1;
    }
    assert!(checked >= 10, "only {checked} fixtures");
}
