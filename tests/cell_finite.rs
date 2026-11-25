//! A cell with a NaN or an infinite component is refused at every entry
//! point that reads, builds, or writes one. The error is typed
//! (`ParseError::NonFiniteValue`) and names the field and, where the entry
//! point knows it, the frame.

use std::path::{Path, PathBuf};

use readcon_core::conbin;
use readcon_core::error::{ConvertError, ParseError};
use readcon_core::extxyz_scan::{
    ExtxyzSource, XyzColumn, extxyz_bytes, extxyz_bytes_with_threads, extxyz_path_with_threads,
    lattice_from_cell, scan_extxyz_bytes, tables_from_extxyz_bytes,
    tables_from_extxyz_bytes_with_threads, write_extxyz_path,
};
use readcon_core::iterators::{
    ConFrameIterator, LoadError, read_all_frames_located, read_coord_columns,
    read_first_frame_located, read_nth_frame_located, read_positions_with_threads,
};
use readcon_core::pdb_scan::{scan_pdb_path, tables_from_pdb_bytes, tables_from_pdb_path};
use readcon_core::types::{
    ConFrame, ConFrameBuilder, check_cell_finite, check_cell_rows, check_cell_rows_f32,
    check_cellpar_finite, check_lattice_finite,
};
use readcon_core::writer::{
    ConFrameWriter, WriteError, write_binding_columns, write_frame_refs_to_path,
    write_frame_refs_with_threads, write_frames_to_string, write_frames_to_vec,
    write_frames_to_vec_with_threads,
};

const BAD_TOKENS: [&str; 5] = ["NaN", "nan", "inf", "-inf", "Infinity"];

fn frame_text(box_line: &str, angle_line: &str, atoms: usize) -> String {
    frame_text_with_meta(r#"{"con_spec_version":2}"#, box_line, angle_line, atoms)
}

fn frame_text_with_meta(metadata: &str, box_line: &str, angle_line: &str, atoms: usize) -> String {
    let mut text = format!("seed\n{metadata}\n");
    text.push_str(box_line);
    text.push('\n');
    text.push_str(angle_line);
    text.push_str("\n0 0\n0 0 0\n1\n");
    text.push_str(&format!("{atoms}\n1.0\nH\nCoordinates of Component 1\n"));
    for atom in 0..atoms {
        text.push_str(&format!("{}.5 1.25 2.0 0 {atom}\n", atom % 7));
    }
    text
}

fn good_frame_text(atoms: usize) -> String {
    frame_text("10 11 12", "90 91 92", atoms)
}

/// Three frames; the middle one has `token` in one cell line.
fn trajectory_with(in_box_line: bool, index: usize, token: &str, atoms: usize) -> String {
    let mut lengths = ["10", "11", "12"];
    let mut angles = ["90", "91", "92"];
    if in_box_line {
        lengths[index] = token;
    } else {
        angles[index] = token;
    }
    let bad = frame_text(&lengths.join(" "), &angles.join(" "), atoms);
    let good = good_frame_text(atoms);
    format!("{good}{bad}{good}")
}

/// A typed cell error that names `field`, `token`, and `frame` when given.
fn assert_cell_error(error: &ParseError, field: &str, frame: Option<u64>, token: &str) {
    assert!(
        matches!(error, ParseError::NonFiniteValue(_)),
        "not typed: {error:?}"
    );
    assert_eq!(error.class_name(), "NonFiniteValue");
    assert!(error.is_non_finite_cell(), "{error}");
    assert_eq!(error.named_frame(), frame, "{error}");
    let text = match frame {
        Some(frame) => format!("cell field {field} of frame {frame} is {token}"),
        None => format!("cell field {field} is {token}"),
    };
    assert!(error.to_string().contains(&text), "{error}");
}

/// The typed cell error a converter returned. A message fails the test.
fn typed_cell(error: &ConvertError) -> &ParseError {
    assert!(
        error.is_non_finite_cell(),
        "not a typed cell error: {error:?}"
    );
    error.parse_error().unwrap()
}

/// NaN, +Inf, and -Inf, with the spelling a cell error gives each.
const NON_FINITE: [(f64, &str); 3] = [
    (f64::NAN, "NaN"),
    (f64::INFINITY, "inf"),
    (f64::NEG_INFINITY, "-inf"),
];

fn write_text(dir: &tempfile::TempDir, name: &str, text: &str) -> PathBuf {
    let path = dir.path().join(name);
    std::fs::write(&path, text).unwrap();
    path
}

fn untyped(error: Box<dyn std::error::Error>) -> (ParseError, u64) {
    match error.downcast::<readcon_core::error::LocatedParseError>() {
        Ok(located) => (located.error, located.frame_index),
        Err(other) => match other.downcast::<LoadError>() {
            Ok(load) => match *load {
                LoadError::Parse(located) => (located.error, located.frame_index),
                other => panic!("not a parse error: {other}"),
            },
            Err(other) => panic!("untyped error: {other}"),
        },
    }
}

#[test]
fn the_text_iterator_names_the_cell_field() {
    for token in BAD_TOKENS {
        for index in 0..3 {
            for in_box_line in [true, false] {
                let text = trajectory_with(in_box_line, index, token, 2);
                let mut frames = ConFrameIterator::new(&text);
                assert!(frames.next().unwrap().is_ok());
                let error = frames.next().unwrap().unwrap_err();
                let field = if in_box_line { "boxl" } else { "angles" };
                assert_cell_error(&error, &format!("{field}[{index}]"), None, token);
            }
        }
    }
}

#[test]
fn every_located_reader_names_the_frame_on_one_and_many_workers() {
    let dir = tempfile::tempdir().unwrap();
    for token in BAD_TOKENS {
        for (in_box_line, index, field) in [(true, 1, "boxl[1]"), (false, 2, "angles[2]")] {
            let text = trajectory_with(in_box_line, index, token, 2);
            let path = write_text(&dir, "bad.con", &text);
            for workers in [None, Some(1), Some(2), Some(4)] {
                match read_all_frames_located(&path, workers).unwrap_err() {
                    LoadError::Parse(located) => {
                        assert_eq!(located.frame_index, 1, "workers {workers:?}");
                        assert_cell_error(&located.error, field, Some(1), token);
                    }
                    other => panic!("workers {workers:?}: {other}"),
                }
            }
            match read_nth_frame_located(&path, 1).unwrap_err() {
                LoadError::Parse(located) => {
                    assert_cell_error(&located.error, field, Some(1), token);
                }
                other => panic!("{other}"),
            }
            let (error, frame) = untyped(read_coord_columns(&path, None).err().unwrap());
            assert_cell_error(&error, field, Some(1), token);
            assert_eq!(frame, 1);
            let (error, frame) =
                untyped(read_positions_with_threads(&path, Some(2)).err().unwrap());
            assert_cell_error(&error, field, Some(1), token);
            assert_eq!(frame, 1);
        }
    }
}

#[test]
fn the_first_frame_reader_names_frame_zero() {
    let dir = tempfile::tempdir().unwrap();
    let path = write_text(&dir, "first.con", &frame_text("NaN 11 12", "90 91 92", 2));
    match read_first_frame_located(&path).unwrap_err() {
        LoadError::Parse(located) => {
            assert_cell_error(&located.error, "boxl[0]", Some(0), "NaN");
        }
        other => panic!("{other}"),
    }
}

#[test]
fn a_wide_frame_names_its_cell_field_on_many_workers() {
    let dir = tempfile::tempdir().unwrap();
    let path = write_text(&dir, "wide.con", &frame_text("10 inf 12", "90 91 92", 5000));
    for workers in [None, Some(2), Some(4)] {
        match read_all_frames_located(&path, workers).unwrap_err() {
            LoadError::Parse(located) => {
                assert_eq!(located.frame_index, 0);
                assert_cell_error(&located.error, "boxl[1]", Some(0), "inf");
            }
            other => panic!("{other}"),
        }
    }
}

#[cfg(feature = "parallel")]
#[test]
fn the_parallel_frame_parse_reports_the_bad_frame() {
    let text = trajectory_with(true, 0, "NaN", 3);
    for workers in [None, Some(2), Some(4)] {
        let results = readcon_core::iterators::parse_frames_parallel_with_threads(&text, workers);
        assert_eq!(results.len(), 3);
        assert!(results[0].is_ok());
        let error = results[1].as_ref().unwrap_err();
        assert_cell_error(error, "boxl[0]", None, "NaN");
        assert!(results[2].is_ok());
    }
}

#[test]
fn a_cell_number_too_large_for_binary64_is_refused_as_non_finite() {
    let text = frame_text("10 1e999 12", "90 91 92", 2);
    let error = ConFrameIterator::new(&text).next().unwrap().unwrap_err();
    assert_cell_error(&error, "boxl[1]", None, "1e999");
}

fn assert_all_read_modes_reject(text: &str) {
    let error = ConFrameIterator::new(text).next().unwrap().unwrap_err();
    assert!(matches!(error, ParseError::ValidationError(_)), "{error}");

    let dir = tempfile::tempdir().unwrap();
    let path = write_text(&dir, "bad-cell.con", text);
    for workers in [None, Some(1), Some(2)] {
        assert!(
            read_all_frames_located(&path, workers).is_err(),
            "read_all_frames_located accepted workers={workers:?}"
        );
        assert!(
            read_coord_columns(&path, workers).is_err(),
            "read_coord_columns accepted workers={workers:?}"
        );
        assert!(
            read_positions_with_threads(&path, workers).is_err(),
            "read_positions_with_threads accepted workers={workers:?}"
        );
    }
    assert!(read_first_frame_located(&path).is_err());
    assert!(read_nth_frame_located(&path, 0).is_err());
}

#[test]
fn all_read_modes_reject_negative_lengths() {
    assert_all_read_modes_reject(&frame_text("-1 10 10", "90 90 90", 1));
}

fn assert_all_read_modes_accept(text: &str) {
    let frame = ConFrameIterator::new(text).next().unwrap().unwrap();
    let dir = tempfile::tempdir().unwrap();
    let path = write_text(&dir, "unset-cell.con", text);
    for workers in [None, Some(1), Some(2)] {
        assert_eq!(read_all_frames_located(&path, workers).unwrap().len(), 1);
        let mut cells = frame.header.boxl.to_vec();
        cells.extend_from_slice(&frame.header.angles);
        assert_eq!(read_coord_columns(&path, workers).unwrap().cells, cells);
        assert_eq!(
            read_positions_with_threads(&path, workers)
                .unwrap()
                .n_frames,
            1
        );
    }
    assert!(read_first_frame_located(&path).is_ok());
    assert!(read_nth_frame_located(&path, 0).is_ok());
}

#[test]
fn all_read_modes_refuse_zero_lengths_only_on_marked_periodic_axes() {
    assert_all_read_modes_reject(&frame_text_with_meta(
        r#"{"con_spec_version":2,"pbc":[true,true,true]}"#,
        "0 0 0",
        "90 90 90",
        1,
    ));
    assert_all_read_modes_reject(&frame_text_with_meta(
        r#"{"con_spec_version":2,"pbc":[false,false,true]}"#,
        "10 10 0",
        "90 90 90",
        1,
    ));
    // CON 1 and 2 writers, ASE, and earlier readcon write zero lengths for
    // a frame without a cell, with no pbc key.
    assert_all_read_modes_accept(&frame_text("0 0 0", "90 90 90", 1));
    assert_all_read_modes_accept(&frame_text("10 10 0", "90 90 60", 1));
    assert_all_read_modes_accept(&frame_text_with_meta(
        r#"{"con_spec_version":2,"pbc":[false,false,false]}"#,
        "-0 0 -0",
        "90 90 90",
        1,
    ));
    assert_all_read_modes_accept(&frame_text_with_meta(
        r#"{"con_spec_version":2,"pbc":[true,true,false]}"#,
        "10 10 0",
        "90 90 90",
        1,
    ));
}

/// With `lattice_vectors` present, lines 3-4 do not decide the cell, so an
/// impossible or negative line is read, not refused.
#[test]
fn all_read_modes_leave_lines_3_4_alone_when_lattice_vectors_decide() {
    let lattice = r#""lattice_vectors":[[10,0,0],[0,10,0],[0,0,10]]"#;
    let meta = format!(r#"{{"con_spec_version":2,{lattice}}}"#);
    assert_all_read_modes_accept(&frame_text_with_meta(&meta, "10 10 10", "10 10 170", 1));
    assert_all_read_modes_accept(&frame_text_with_meta(&meta, "-1 10 10", "90 90 90", 1));
    let periodic = format!(r#"{{"con_spec_version":2,"pbc":[true,true,true],{lattice}}}"#);
    assert_all_read_modes_accept(&frame_text_with_meta(&periodic, "0 0 0", "90 90 90", 1));
}

#[test]
fn all_read_modes_accept_a_flat_cell_on_the_triangle_boundary() {
    assert_all_read_modes_accept(&frame_text("10 10 10", "60 60 120", 1));
}

#[test]
fn all_read_modes_reject_impossible_angles() {
    assert_all_read_modes_reject(&frame_text("10 10 10", "10 10 170", 1));
}

#[test]
fn finite_cells_read_the_same_on_every_worker_count() {
    let dir = tempfile::tempdir().unwrap();
    let text = format!("{}{}", good_frame_text(3), good_frame_text(3));
    let path = write_text(&dir, "good.con", &text);
    for workers in [None, Some(1), Some(2), Some(4)] {
        let frames = read_all_frames_located(&path, workers).unwrap();
        assert_eq!(frames.len(), 2);
        for frame in &frames {
            assert_eq!(frame.header.boxl, [10.0, 11.0, 12.0]);
            assert_eq!(frame.header.angles, [90.0, 91.0, 92.0]);
        }
    }
}

fn built_frame() -> ConFrame {
    let mut builder = ConFrameBuilder::new([10.0, 11.0, 12.0], [90.0, 91.0, 92.0]);
    builder.add_atom("H", 0.0, 0.0, 0.0, [false; 3], 0, 1.0);
    builder.build().unwrap()
}

fn with_cell(mut frame: ConFrame, boxl: [f64; 3], angles: [f64; 3]) -> ConFrame {
    frame.header.boxl = boxl;
    frame.header.angles = angles;
    frame
}

#[test]
fn the_builder_refuses_a_non_finite_cell() {
    for bad in [f64::NAN, f64::INFINITY, f64::NEG_INFINITY] {
        let token = bad.to_string();
        for index in 0..3 {
            let mut lengths = [10.0; 3];
            lengths[index] = bad;
            let error = ConFrameBuilder::try_new(lengths, [90.0; 3]).err().unwrap();
            assert_cell_error(&error, &format!("cell[{index}]"), None, &token);
            let error = ConFrame::try_builder(lengths, [90.0; 3]).err().unwrap();
            assert_cell_error(&error, &format!("cell[{index}]"), None, &token);

            let mut angles = [90.0; 3];
            angles[index] = bad;
            let error = ConFrameBuilder::try_new([10.0; 3], angles).err().unwrap();
            assert_cell_error(&error, &format!("angles[{index}]"), None, &token);

            let mut builder = ConFrameBuilder::new(lengths, [90.0; 3]);
            builder.add_atom("H", 0.0, 0.0, 0.0, [false; 3], 0, 1.0);
            let error = builder.build().unwrap_err();
            assert_cell_error(&error, &format!("cell[{index}]"), None, &token);
        }
    }
    assert!(ConFrameBuilder::try_new([10.0; 3], [90.0; 3]).is_ok());
}

#[test]
fn a_builder_with_a_frame_index_names_the_frame() {
    let mut builder = ConFrameBuilder::new([f64::NAN, 10.0, 10.0], [90.0; 3]);
    builder.metadata(std::collections::BTreeMap::from([(
        "frame_index".to_string(),
        serde_json::json!(7),
    )]));
    let error = builder.build().unwrap_err();
    assert_cell_error(&error, "cell[0]", Some(7), "NaN");
}

#[test]
fn set_lattice_vectors_refuses_a_non_finite_matrix_and_keeps_the_header() {
    let mut frame = built_frame();
    let before = frame.header.clone();
    for bad in [f64::NAN, f64::INFINITY, f64::NEG_INFINITY] {
        for (row, column) in [(0, 0), (1, 2), (2, 1)] {
            let mut vectors = [[10.0, 0.0, 0.0], [0.0, 11.0, 0.0], [0.0, 0.0, 12.0]];
            vectors[row][column] = bad;
            let error = frame.header.set_lattice_vectors(vectors).unwrap_err();
            assert_cell_error(
                &error,
                &format!("lattice_vectors[{row}][{column}]"),
                None,
                &bad.to_string(),
            );
            assert_eq!(frame.header.boxl, before.boxl);
            assert_eq!(frame.header.angles, before.angles);
            assert!(frame.header.lattice_vectors().is_none());
        }
    }
    let good = [[10.0, 0.0, 0.0], [0.0, 11.0, 0.0], [0.0, 0.0, 12.0]];
    frame.header.set_lattice_vectors(good).unwrap();
    assert_eq!(frame.header.lattice_vectors(), Some(good));
}

#[test]
fn the_check_helpers_name_their_fields() {
    let error = check_cell_finite(&[1.0, f64::NAN, 3.0], "boxl", &[90.0; 3], "angles").unwrap_err();
    assert_cell_error(&error, "boxl[1]", None, "NaN");
    let error =
        check_cell_finite(&[1.0; 3], "boxl", &[90.0, 90.0, f64::INFINITY], "angles").unwrap_err();
    assert_cell_error(&error, "angles[2]", None, "inf");
    let error = check_cellpar_finite(&[1.0, 1.0, 1.0, 90.0, f64::NEG_INFINITY, 90.0]).unwrap_err();
    assert_cell_error(&error, "cell[4]", None, "-inf");
    let error =
        check_lattice_finite(&[[1.0, 0.0, 0.0], [0.0, 1.0, f64::NAN], [0.0; 3]]).unwrap_err();
    assert_cell_error(&error, "lattice_vectors[1][2]", None, "NaN");
    let rows = [
        10.0,
        10.0,
        10.0,
        90.0,
        90.0,
        90.0,
        1.0,
        f64::NAN,
        1.0,
        90.0,
        90.0,
        90.0,
    ];
    let error = check_cell_rows(&rows).unwrap_err();
    assert_cell_error(&error, "cell[1]", Some(1), "NaN");
    assert!(check_cell_rows(&rows[..6]).is_ok());
    let rows32 = [
        10.0f32,
        10.0,
        10.0,
        90.0,
        90.0,
        90.0,
        1.0,
        1.0,
        f32::INFINITY,
        90.0,
        90.0,
        90.0,
    ];
    let error = check_cell_rows_f32(&rows32).unwrap_err();
    assert_cell_error(&error, "cell[2]", Some(1), "inf");
}

#[test]
fn the_stream_writer_refuses_a_non_finite_cell_and_writes_nothing_of_it() {
    for bad in [f64::NAN, f64::INFINITY, f64::NEG_INFINITY] {
        let good = built_frame();
        let mut one_frame = Vec::new();
        ConFrameWriter::new(&mut one_frame)
            .write_frame(&good)
            .unwrap();

        for broken in [
            with_cell(built_frame(), [10.0, bad, 12.0], [90.0; 3]),
            with_cell(built_frame(), [10.0; 3], [90.0, 90.0, bad]),
        ] {
            let mut out = Vec::new();
            {
                let mut writer = ConFrameWriter::new(&mut out);
                writer.write_frame(&good).unwrap();
                match writer.write_frame(&broken).unwrap_err() {
                    WriteError::Format(error) => {
                        assert!(error.is_non_finite_cell(), "{error}");
                        assert_eq!(error.named_frame(), Some(1), "{error}");
                    }
                    other => panic!("not a format error: {other}"),
                }
            }
            assert_eq!(out, one_frame, "bytes of the bad frame leaked");

            let mut out = Vec::new();
            let mut writer = ConFrameWriter::new(&mut out);
            let frames = [&good, &broken];
            let error = writer.extend(frames.into_iter()).unwrap_err();
            assert!(matches!(&error, WriteError::Format(e) if e.is_non_finite_cell()));
        }
    }
}

#[test]
fn the_batch_writers_name_the_frame_by_its_place_in_the_batch() {
    let broken = with_cell(built_frame(), [f64::NAN, 11.0, 12.0], [90.0; 3]);
    let frames = vec![built_frame(), broken, built_frame()];
    let check = |error: WriteError| match error {
        WriteError::Format(error) => assert_cell_error(&error, "boxl[0]", Some(1), "NaN"),
        other => panic!("not a format error: {other}"),
    };
    check(write_frames_to_vec(&frames).unwrap_err());
    check(write_frames_to_string(&frames).unwrap_err());
    let dir = tempfile::tempdir().unwrap();
    let refs: Vec<&ConFrame> = frames.iter().collect();
    for workers in [0, 1, 2, 4] {
        check(write_frames_to_vec_with_threads(&frames, workers, None, false).unwrap_err());
        check(write_frame_refs_with_threads(&refs, workers, None, false).unwrap_err());
        for canonical in [false, true] {
            let path = dir.path().join(format!("out-{workers}-{canonical}.con"));
            check(
                write_frame_refs_to_path(&path, &refs, workers, None, canonical, false)
                    .unwrap_err(),
            );
            assert!(!path.exists(), "a refused write created {path:?}");
        }
        let bound = dir.path().join(format!("bound-{workers}.con"));
        check(write_frame_refs_to_path(&bound, &refs, workers, None, false, true).unwrap_err());
        assert!(!bound.exists());
    }
}

#[test]
fn the_column_writer_names_the_frame_and_the_field_and_creates_no_file() {
    let dir = tempfile::tempdir().unwrap();
    let positions = [0.0; 6];
    let masses = [1.0; 2];
    let mut cell = vec![
        10.0, 10.0, 10.0, 90.0, 90.0, 90.0, 10.0, 10.0, 10.0, 90.0, 90.0, 90.0,
    ];
    cell[7] = f64::NAN;
    for workers in [1, 2] {
        let path = dir.path().join(format!("columns-{workers}.con"));
        let error = write_binding_columns(
            &path, 2, 1, &positions, &masses, &cell, None, None, None, "H", workers,
        )
        .unwrap_err();
        match error {
            WriteError::Format(error) => assert_cell_error(&error, "cell[1]", Some(1), "NaN"),
            other => panic!("{other}"),
        }
        assert!(!path.exists());
    }
}

#[test]
fn a_finite_cell_is_written_and_read_back_bit_for_bit() {
    let lengths = [10.123456789012345, 1.0 / 3.0, 7.5e-3];
    let angles = [89.99999999999999, 120.00000000000001, 60.5];
    let frame = with_cell(built_frame(), lengths, angles);
    let text = write_frames_to_string(std::slice::from_ref(&frame)).unwrap();
    let back = ConFrameIterator::new(&text).next().unwrap().unwrap();
    for (left, right) in lengths.iter().zip(back.header.boxl.iter()) {
        assert_eq!(left.to_bits(), right.to_bits());
    }
    for (left, right) in angles.iter().zip(back.header.angles.iter()) {
        assert_eq!(left.to_bits(), right.to_bits());
    }
    let again = write_frames_to_string(std::slice::from_ref(&back)).unwrap();
    assert_eq!(again, text);
}

fn bin_columns(path: &Path, cell: &[f64]) -> Result<conbin::ConBinHeader, ParseError> {
    let frames = (cell.len() / 6) as u64;
    let positions = vec![0.5; frames as usize * 3];
    conbin::write_f64_columns(
        path,
        frames,
        1,
        &positions,
        None,
        None,
        Some(cell),
        None,
        None,
    )
}

#[test]
fn the_conbin_writer_refuses_a_non_finite_cell_and_publishes_nothing() {
    let dir = tempfile::tempdir().unwrap();
    for bad in [f64::NAN, f64::INFINITY, f64::NEG_INFINITY] {
        for slot in [0, 3, 5] {
            let mut cell = [10.0, 11.0, 12.0, 90.0, 91.0, 92.0].repeat(3);
            cell[6 + slot] = bad;
            let path = dir.path().join("bad.conbin");
            let error = bin_columns(&path, &cell).unwrap_err();
            assert_cell_error(&error, &format!("cell[{slot}]"), Some(1), &bad.to_string());
            assert!(!path.exists());
        }
    }
}

#[test]
fn the_conbin_reader_refuses_a_stored_non_finite_cell() {
    let dir = tempfile::tempdir().unwrap();
    let sentinel = 12.345678901234567_f64;
    let mut cell = [10.0, 11.0, 12.0, 90.0, 91.0, 92.0].repeat(3);
    cell[6 + 2] = sentinel;
    let path = dir.path().join("stored.conbin");
    bin_columns(&path, &cell).unwrap();
    let mapped = conbin::map_file(&path, 1).unwrap();
    let read = mapped.cell_f64().unwrap().unwrap();
    assert_eq!(read.len(), cell.len());
    for (left, right) in read.iter().zip(cell.iter()) {
        assert_eq!(left.to_bits(), right.to_bits());
    }
    drop(mapped);

    for bad in [f64::NAN, f64::INFINITY, f64::NEG_INFINITY] {
        let mut bytes = std::fs::read(&path).unwrap();
        let needle = sentinel.to_le_bytes();
        let at = bytes
            .windows(8)
            .position(|window| window == needle)
            .expect("sentinel is stored");
        bytes[at..at + 8].copy_from_slice(&bad.to_le_bytes());
        let patched = dir.path().join("patched.conbin");
        std::fs::write(&patched, &bytes).unwrap();
        let mapped = conbin::map_file(&patched, 1).unwrap();
        let error = mapped.cell_f64().unwrap_err();
        assert_cell_error(&error, "cell[2]", Some(1), &bad.to_string());
    }
}

#[test]
fn text_to_conbin_names_the_frame_and_the_binary32_overflow() {
    let dir = tempfile::tempdir().unwrap();
    let out = dir.path().join("out.conbin");

    let bad = write_text(
        &dir,
        "bad.con",
        &format!(
            "{}{}",
            good_frame_text(2),
            frame_text("10 NaN 12", "90 91 92", 2)
        ),
    );
    for threads in [1, 2, 4] {
        let error = conbin::write_from_con_with_threads(&bad, &out, false, threads).unwrap_err();
        assert_cell_error(&error, "boxl[1]", Some(1), "NaN");
        assert!(!out.exists());
    }

    let big = write_text(
        &dir,
        "big.con",
        &format!(
            "{}{}",
            good_frame_text(2),
            frame_text("10 1e300 12", "90 91 92", 2)
        ),
    );
    assert!(conbin::write_from_con(&big, &out, false).is_ok());
    std::fs::remove_file(&out).unwrap();
    for threads in [1, 2] {
        let error = conbin::write_from_con_with_threads(&big, &out, true, threads).unwrap_err();
        assert_cell_error(
            &error,
            "cell[1]",
            Some(1),
            &format!("{} (infinite in binary32)", 1e300_f64),
        );
        assert!(!out.exists());
    }

    let good = write_text(
        &dir,
        "good.con",
        &format!("{}{}", good_frame_text(2), good_frame_text(2)),
    );
    for binary32 in [false, true] {
        for threads in [1, 2] {
            conbin::write_from_con_with_threads(&good, &out, binary32, threads).unwrap();
            std::fs::remove_file(&out).unwrap();
        }
    }
}

fn extxyz_frame(lattice: &str, atoms: usize) -> String {
    let mut text =
        format!("{atoms}\nLattice=\"{lattice}\" Properties=species:S:1:pos:R:3 pbc=\"T T T\"\n");
    for atom in 0..atoms {
        text.push_str(&format!("Cu {}.25 0.5 1.0\n", atom % 9));
    }
    text
}

fn extxyz_trajectory(bad_lattice: &str, atoms: usize) -> String {
    let good = extxyz_frame("4 0 0 0 5 0 0 0 6", atoms);
    let bad = extxyz_frame(bad_lattice, atoms);
    format!("{good}{bad}{good}")
}

#[test]
fn the_extxyz_scan_names_the_lattice_field_and_the_frame() {
    let finite = ["4", "0", "0", "0", "5", "0", "0", "0", "6"];
    for slot in 0..9 {
        for (spelling, shown) in [
            ("nan", "NaN"),
            ("inf", "inf"),
            ("-inf", "-inf"),
            ("6e999", "inf"),
        ] {
            let mut lattice = finite;
            lattice[slot] = spelling;
            let text = extxyz_trajectory(&lattice.join(" "), 3);
            let field = format!("Lattice[{slot}]");
            for workers in [1, 2, 4] {
                let error = scan_extxyz_bytes(text.as_bytes(), workers).unwrap_err();
                assert_cell_error(typed_cell(&error), &field, Some(1), shown);
            }
            let error = tables_from_extxyz_bytes(text.as_bytes()).unwrap_err();
            assert_cell_error(typed_cell(&error), &field, Some(1), shown);
        }
    }
}

#[test]
fn the_text_form_of_the_extxyz_and_pdb_scans_still_recovers_the_cell_error() {
    let text = extxyz_trajectory("4 0 0 0 inf 0 0 0 6", 3);
    for workers in [1, 2] {
        let message = tables_from_extxyz_bytes_with_threads(text.as_bytes(), workers).unwrap_err();
        let error = ParseError::from_cell_text(&message)
            .unwrap_or_else(|| panic!("not a cell error: {message}"));
        assert_cell_error(&error, "Lattice[4]", Some(1), "inf");
    }
    let dir = tempfile::tempdir().unwrap();
    let path = write_text(
        &dir,
        "bad.pdb",
        &format!("CRYST1   10.000   12.000   -inf  90.00  90.00  90.00 P 1\n{PDB_ATOM}END\n"),
    );
    let typed = scan_pdb_path(&path).unwrap_err();
    assert_cell_error(typed_cell(&typed), "cell[2]", Some(0), "-inf");
    let message = tables_from_pdb_path(&path).unwrap_err();
    assert_eq!(message, typed.to_string());
    let error = ParseError::from_cell_text(&message).unwrap();
    assert_cell_error(&error, "cell[2]", Some(0), "-inf");
    assert!(tables_from_pdb_path(&dir.path().join("missing.pdb")).unwrap_err() == "read");
}

#[test]
fn the_extxyz_scan_refuses_a_lattice_that_has_no_angle() {
    let text = extxyz_trajectory("0 0 0 0 5 0 0 0 6", 3);
    let error = tables_from_extxyz_bytes(text.as_bytes()).unwrap_err();
    assert_cell_error(typed_cell(&error), "cell[4]", Some(1), "NaN");
}

#[test]
fn a_wide_extxyz_frame_names_its_lattice_field_on_many_workers() {
    for (spelling, shown) in [("nan", "NaN"), ("inf", "inf"), ("-inf", "-inf")] {
        let text = extxyz_frame(&format!("4 0 0 0 {spelling} 0 0 0 6"), 5000);
        for workers in [1, 2, 4] {
            let error = scan_extxyz_bytes(text.as_bytes(), workers).unwrap_err();
            assert_cell_error(typed_cell(&error), "Lattice[4]", Some(0), shown);
        }
    }
}

#[test]
fn a_malformed_extxyz_file_is_still_a_message() {
    let error = tables_from_extxyz_bytes(b"1\nnote\nH 0 0 0\n").unwrap_err();
    assert!(error.parse_error().is_none(), "{error:?}");
    assert_eq!(error, "lattice");
}

#[test]
fn finite_extxyz_cells_read_the_same_on_every_worker_count() {
    let text = extxyz_trajectory("4 0 0 0 5.5 0 0 0 6.25", 3);
    let serial = tables_from_extxyz_bytes(text.as_bytes()).unwrap();
    for workers in [2, 4] {
        let split = tables_from_extxyz_bytes_with_threads(text.as_bytes(), workers).unwrap();
        assert_eq!(split.cell.len(), serial.cell.len());
        for (left, right) in split.cell.iter().zip(serial.cell.iter()) {
            assert_eq!(left.to_bits(), right.to_bits());
        }
    }
    assert_eq!(&serial.cell[6..9], &[4.0, 5.5, 6.25]);
}

fn extxyz_columns(n_frames: usize, n_atoms: usize) -> (XyzColumn, XyzColumn) {
    let species = XyzColumn {
        name: "species".to_string(),
        kind: b'S',
        width: 1,
        text: vec!["Cu".to_string(); n_frames * n_atoms],
        real: Vec::new(),
    };
    let positions = XyzColumn {
        name: "pos".to_string(),
        kind: b'R',
        width: 3,
        text: Vec::new(),
        real: (0..n_frames * n_atoms * 3)
            .map(|i| i as f64 * 0.25)
            .collect(),
    };
    (species, positions)
}

#[test]
fn the_extxyz_writers_refuse_a_non_finite_cell_and_create_no_file() {
    let dir = tempfile::tempdir().unwrap();
    for (n_frames, n_atoms) in [(3usize, 2usize), (1, 5000)] {
        let (species, positions) = extxyz_columns(n_frames, n_atoms);
        let columns: [&(dyn ExtxyzSource + Sync); 2] = [&species, &positions];
        for slot in 0..6 {
            for (bad, token) in NON_FINITE {
                let mut cell = [4.0, 5.0, 6.0, 90.0, 90.0, 90.0].repeat(n_frames);
                let row = n_frames - 1;
                cell[row * 6 + slot] = bad;
                let frame = Some(row as u64);
                let field = format!("cell[{slot}]");
                let check = |error: ConvertError| {
                    assert_cell_error(typed_cell(&error), &field, frame, token);
                };
                check(extxyz_bytes(n_frames, n_atoms, &cell, &columns).unwrap_err());
                for workers in [0, 1, 2, 4] {
                    check(
                        extxyz_bytes_with_threads(n_frames, n_atoms, &cell, &columns, workers)
                            .unwrap_err(),
                    );
                    let path = dir.path().join(format!("out-{n_frames}-{workers}.xyz"));
                    check(
                        extxyz_path_with_threads(
                            &path, n_frames, n_atoms, &cell, &columns, workers,
                        )
                        .unwrap_err(),
                    );
                    assert!(!path.exists(), "a refused write created {path:?}");
                }
            }
        }
    }
}

#[test]
fn the_extxyz_table_writer_refuses_a_non_finite_cell() {
    let dir = tempfile::tempdir().unwrap();
    let text = extxyz_trajectory("4 0 0 0 5 0 0 0 6", 2);
    let finite = tables_from_extxyz_bytes(text.as_bytes()).unwrap();
    for slot in 0..6 {
        for (bad, token) in NON_FINITE {
            let mut tables = finite.clone();
            tables.cell[6 + slot] = bad;
            let path = dir.path().join("tables.xyz");
            let error = write_extxyz_path(&path, &tables).unwrap_err();
            assert_cell_error(typed_cell(&error), &format!("cell[{slot}]"), Some(1), token);
            assert!(!path.exists());
        }
    }
}

#[test]
fn a_finite_orthorhombic_extxyz_cell_round_trips_bit_for_bit() {
    let text = extxyz_trajectory("4.25 0 0 0 5.5 0 0 0 6.125", 2);
    let tables = tables_from_extxyz_bytes(text.as_bytes()).unwrap();
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("round.xyz");
    write_extxyz_path(&path, &tables).unwrap();
    let back = tables_from_extxyz_bytes(&std::fs::read(&path).unwrap()).unwrap();
    assert_eq!(back.cell.len(), tables.cell.len());
    for (left, right) in back.cell.iter().zip(tables.cell.iter()) {
        assert_eq!(left.to_bits(), right.to_bits());
    }
}

const PDB_ATOM: &str =
    "ATOM      1   Cu MOL     1       0.000   1.000   2.000  1.00  0.00          CU\n";

#[test]
fn the_pdb_scan_names_the_cryst_field_and_the_frame() {
    let finite = ["10.000", "12.000", "14.000", "90.00", "90.00", "90.00"];
    for slot in 0..6 {
        for token in BAD_TOKENS {
            let mut cryst = finite;
            cryst[slot] = token;
            let text = format!("CRYST1 {} P 1\n{PDB_ATOM}END\n", cryst.join(" "));
            let error = tables_from_pdb_bytes(text.as_bytes()).unwrap_err();
            let shown = match token {
                "NaN" | "nan" => "NaN",
                "inf" | "Infinity" => "inf",
                _ => "-inf",
            };
            assert_cell_error(typed_cell(&error), &format!("cell[{slot}]"), Some(0), shown);
        }
    }
    let later = format!(
        "CRYST1   10.000   12.000   14.000  90.00  90.00  90.00 P 1\n{PDB_ATOM}ENDMDL\nCRYST1   10.000   12.000   14.000  90.00  nan  90.00 P 1\n{PDB_ATOM}ENDMDL\n"
    );
    let error = tables_from_pdb_bytes(later.as_bytes()).unwrap_err();
    assert_cell_error(typed_cell(&error), "cell[4]", Some(1), "NaN");

    let good =
        format!("CRYST1   10.000   12.000   14.000  90.00  91.50  90.00 P 1\n{PDB_ATOM}END\n");
    let tables = tables_from_pdb_bytes(good.as_bytes()).unwrap();
    assert_eq!(tables.cell, vec![10.0, 12.0, 14.0, 90.0, 91.5, 90.0]);
}

#[test]
fn from_cell_text_only_recovers_cell_errors() {
    assert!(ParseError::from_cell_text("read").is_none());
    assert!(ParseError::from_cell_text("non-finite value: NaN").is_none());
    assert!(ParseError::from_cell_text("lattice").is_none());
    let error = ParseError::non_finite_cell("cell[0]", f64::NAN).in_frame(3);
    let again = ParseError::from_cell_text(&error.to_string()).unwrap();
    assert_eq!(again.to_string(), error.to_string());
    assert_eq!(again.named_frame(), Some(3));
    let named_twice = again.in_frame(9);
    assert_eq!(named_twice.named_frame(), Some(3));
}

#[test]
fn lattice_from_cell_refuses_a_non_finite_cell_parameter_and_an_overflowing_lattice() {
    for slot in 0..6 {
        for (value, token) in NON_FINITE {
            let mut cell = [10.0, 11.0, 12.0, 90.0, 91.0, 92.0];
            cell[slot] = value;
            let error = lattice_from_cell(&cell).expect_err("non-finite cell parameter");
            assert_cell_error(typed_cell(&error), &format!("cell[{slot}]"), None, token);
        }
    }
    let error =
        lattice_from_cell(&[1.0, 1.0, 1e200, 90.0, 90.0, 90.0]).expect_err("c * c overflows");
    assert_cell_error(typed_cell(&error), "Lattice[8]", None, "inf");
    let lattice = lattice_from_cell(&[10.0, 11.0, 12.0, 90.0, 90.0, 90.0]).unwrap();
    assert_eq!(lattice, [10.0, 0.0, 0.0, 0.0, 11.0, 0.0, 0.0, 0.0, 12.0]);
}
