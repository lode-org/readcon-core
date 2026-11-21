//! A priced trajectory whose text changed through a public field.
//!
//! The file writer prices two or more frames by address and spells each
//! group into a slice of exactly that length. A store into `positions`, a
//! replaced column, or a header edit does not retire that price. The next
//! write must still produce the serial bytes and must not write past the
//! slice.

use readcon_core::iterators::frames_from_text;
use readcon_core::storage_dtype::FloatArray2;
use readcon_core::types::ConFrame;
use readcon_core::writer::{write_frame_refs_to_path, write_frames_to_vec};

fn frames() -> Vec<ConFrame> {
    let text = std::fs::read_to_string("resources/test/tiny_cuh2.con").unwrap();
    let mut both = text.clone();
    both.push_str(&text);
    frames_from_text(&both, None).unwrap()
}

fn rewrite_matches_serial(edit: impl FnOnce(&mut Vec<ConFrame>)) {
    let mut frames = frames();
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("two.con");
    for workers in [1usize, 2, 8] {
        let refs: Vec<&ConFrame> = frames.iter().collect();
        write_frame_refs_to_path(&path, &refs, workers, None, false, false).unwrap();
    }
    edit(&mut frames);
    let want = write_frames_to_vec(&frames).unwrap();
    for workers in [1usize, 2, 8] {
        let refs: Vec<&ConFrame> = frames.iter().collect();
        write_frame_refs_to_path(&path, &refs, workers, None, false, false).unwrap();
        assert_eq!(std::fs::read(&path).unwrap(), want, "workers {workers}");
    }
}

#[test]
fn a_store_into_positions_after_a_write_is_written() {
    rewrite_matches_serial(|frames| {
        for v in frames[0].positions.f64_mut_slice().unwrap() {
            *v = 1.234_567_890_123_456_7e22;
        }
    });
}

#[test]
fn a_shorter_positions_store_after_a_write_is_written() {
    rewrite_matches_serial(|frames| {
        for v in frames[0].positions.f64_mut_slice().unwrap() {
            *v = 1.0;
        }
    });
}

#[test]
fn a_replaced_positions_column_after_a_write_is_written() {
    rewrite_matches_serial(|frames| {
        let n = frames[0].atom_data.len();
        frames[0].positions =
            FloatArray2::from_f64_row_major(n, 3, vec![-9.876_543_210_987_654e-17; n * 3]);
    });
}

#[test]
fn a_header_edit_after_a_write_is_written() {
    rewrite_matches_serial(|frames| {
        frames[1]
            .header
            .prebox_header
            .user
            .push_str(" with a much longer first header line");
    });
}
