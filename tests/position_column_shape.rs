//! A positions column that is not one `(x, y, z)` row per atom.
//!
//! The writer reads every atom's coordinates from that column. An empty
//! column on a frame with atoms, or one with other than three columns, is
//! a `ValidationError` and not an index panic. A Fortran-ordered `(n, 3)`
//! column writes the same text as the row-major one.

use ndarray::ShapeBuilder;
use readcon_core::error::ParseError;
use readcon_core::iterators::ConFrameIterator;
use readcon_core::storage_dtype::FloatArray2;
use readcon_core::types::ConFrame;
use readcon_core::writer::{ConFrameWriter, WriteError, write_frames_to_vec_with_threads};

fn frame() -> ConFrame {
    let text = std::fs::read_to_string("resources/test/tiny_cuh2_vel_forces.con").unwrap();
    ConFrameIterator::new(&text).next().unwrap().unwrap()
}

fn write(frame: &ConFrame) -> Result<Vec<u8>, WriteError> {
    let mut out = Vec::new();
    ConFrameWriter::new(&mut out).write_frame(frame)?;
    Ok(out)
}

fn validation_error(result: Result<Vec<u8>, WriteError>) -> String {
    match result {
        Err(WriteError::Format(ParseError::ValidationError(message))) => message,
        Err(other) => panic!("expected ValidationError, got {other}"),
        Ok(_) => panic!("wrote a frame whose positions column has no row per atom"),
    }
}

#[test]
fn an_empty_positions_column_with_atoms_is_a_validation_error() {
    let mut frame = frame();
    frame.positions = FloatArray2::zeros_f64(0, 3);
    let message = validation_error(write(&frame));
    assert!(message.contains("(0, 3)"), "{message}");
}

#[test]
fn a_one_column_positions_block_is_a_validation_error() {
    let mut frame = frame();
    frame.positions = FloatArray2::from_f64_row_major(4, 1, vec![1.0, 2.0, 3.0, 4.0]);
    let message = validation_error(write(&frame));
    assert!(message.contains("(4, 1)"), "{message}");
}

#[test]
fn the_threaded_writer_reports_the_same_error() {
    let mut frame = frame();
    frame.positions = FloatArray2::zeros_f64(0, 3);
    let frames = vec![frame.clone(), frame];
    match write_frames_to_vec_with_threads(&frames, 2, None, false) {
        Err(WriteError::Format(ParseError::ValidationError(_))) => {}
        other => panic!("expected ValidationError, got {:?}", other.map(|b| b.len())),
    }
}

#[test]
fn a_fortran_ordered_positions_column_writes_the_row_major_text() {
    let frame = frame();
    let expected = write(&frame).unwrap();
    let n = frame.atom_data.len();
    let mut column_major = Vec::with_capacity(n * 3);
    for axis in 0..3 {
        column_major.extend((0..n).map(|i| frame.xyz_at(i)[axis]));
    }
    let fortran = ndarray::Array2::from_shape_vec((n, 3).f(), column_major).unwrap();
    let mut reordered = frame.clone();
    reordered.positions = FloatArray2::F64(fortran.into_shared());
    for i in 0..n {
        assert_eq!(reordered.xyz_at(i), frame.xyz_at(i));
    }
    assert_eq!(write(&reordered).unwrap(), expected);
}

#[test]
fn set_f64_row_on_a_fortran_ordered_positions_column_moves_only_that_row() {
    let frame = frame();
    let n = frame.atom_data.len();
    let mut column_major = Vec::with_capacity(n * 3);
    for axis in 0..3 {
        column_major.extend((0..n).map(|i| frame.xyz_at(i)[axis]));
    }
    let fortran = ndarray::Array2::from_shape_vec((n, 3).f(), column_major).unwrap();
    let mut moved = frame.clone();
    moved.positions = FloatArray2::F64(fortran.into_shared());
    moved.positions.set_f64_row(1, [9.0, 8.0, 7.0]);
    assert_eq!(moved.xyz_at(1), [9.0, 8.0, 7.0]);
    for i in (0..n).filter(|&i| i != 1) {
        assert_eq!(moved.xyz_at(i), frame.xyz_at(i));
    }
}
