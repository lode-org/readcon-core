//! A priced trajectory whose text changed through a public field.
//!
//! The file writer prices two or more frames by address and spells each
//! group into a slice of exactly that length. A store into `positions`, a
//! `set_f64_row` store, a replaced column, or a header edit does not retire
//! that price. The next write must still produce the serial bytes and must
//! not write past the slice.

use std::sync::Mutex;

#[cfg(feature = "zstd")]
use readcon_core::compression::write_fused_zstd_frame;
use readcon_core::compression::{read_file_bytes, write_fused_gzip_frame};
use readcon_core::iterators::frames_from_text;
use readcon_core::storage_dtype::FloatArray2;
use readcon_core::types::{ConFrame, ConFrameBuilder};
use readcon_core::writer::{
    ConFrameWriter, format_frame_refs_unstored, rewrite_frame_refs_to_path,
    write_frame_refs_to_path, write_frames_to_vec,
};

// The packed-length cache is process-global. Serialize cache-dependent tests
// so one test does not evict another's price before the mutated rewrite.
static CACHE_LOCK: Mutex<()> = Mutex::new(());

fn frames_with_copies(copies: usize) -> Vec<ConFrame> {
    let text = std::fs::read_to_string("resources/test/tiny_cuh2.con").unwrap();
    let mut combined = String::with_capacity(text.len() * copies);
    for _ in 0..copies {
        combined.push_str(&text);
    }
    frames_from_text(&combined, None).unwrap()
}

fn dense_uniform_frame(atoms: usize) -> ConFrame {
    let mut builder = ConFrameBuilder::new([20.0, 20.0, 20.0], [90.0, 90.0, 90.0]);
    for i in 0..atoms {
        builder.add_atom(
            "Cu",
            1.0 + (i as f64) * 0.001,
            2.0,
            3.0,
            [false; 3],
            i as u64,
            63.546,
        );
    }
    builder.build().unwrap()
}

fn binding_bytes(frames: &[ConFrame]) -> Vec<u8> {
    let mut buf = Vec::new();
    {
        let mut writer = ConFrameWriter::new(&mut buf);
        for frame in frames {
            writer.write_frame_bound(frame).unwrap();
        }
        writer.flush().unwrap();
    }
    buf
}

fn write_gz_and_assert_serial(path: &std::path::Path, frames: &[ConFrame], want: &[u8]) {
    let mut writer = ConFrameWriter::from_path_gzip(path).unwrap();
    for frame in frames {
        writer.write_frame(frame).unwrap();
    }
    writer.flush().unwrap();
    drop(writer);
    assert_eq!(read_file_bytes(path).unwrap(), want);
}

#[cfg(feature = "zstd")]
fn write_zst_and_assert_serial(path: &std::path::Path, frames: &[ConFrame], want: &[u8]) {
    let mut writer = ConFrameWriter::from_path_zstd(path).unwrap();
    for frame in frames {
        writer.write_frame(frame).unwrap();
    }
    writer.flush().unwrap();
    drop(writer);
    assert_eq!(read_file_bytes(path).unwrap(), want);
}

fn rewrite_matches_serial(copies: usize, edit: impl FnOnce(&mut Vec<ConFrame>)) {
    let _guard = CACHE_LOCK.lock().unwrap_or_else(|e| e.into_inner());
    let mut frames = frames_with_copies(copies);
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("traj.con");
    let rewrite_path = dir.path().join("traj_rewrite.con");
    let gz_path = dir.path().join("traj.con.gz");
    #[cfg(feature = "zstd")]
    let zst_path = dir.path().join("traj.con.zst");

    for workers in [1usize, 2, 8] {
        let refs: Vec<&ConFrame> = frames.iter().collect();
        write_frame_refs_to_path(&path, &refs, workers, None, false, false).unwrap();
        rewrite_frame_refs_to_path(&rewrite_path, &refs, workers, None, false, false, false)
            .unwrap();
    }
    edit(&mut frames);
    let want = write_frames_to_vec(&frames).unwrap();
    let want_bound = binding_bytes(&frames);
    for workers in [1usize, 2, 8] {
        let refs: Vec<&ConFrame> = frames.iter().collect();
        write_frame_refs_to_path(&path, &refs, workers, None, false, false).unwrap();
        assert_eq!(std::fs::read(&path).unwrap(), want, "workers {workers}");
        write_frame_refs_to_path(&path, &refs, workers, None, false, true).unwrap();
        assert_eq!(
            std::fs::read(&path).unwrap(),
            want_bound,
            "bind workers {workers}"
        );
        rewrite_frame_refs_to_path(&rewrite_path, &refs, workers, None, false, false, true)
            .unwrap();
        assert_eq!(
            std::fs::read(&rewrite_path).unwrap(),
            want,
            "rewrite workers {workers}"
        );
    }
    write_gz_and_assert_serial(&gz_path, &frames, &want);
    #[cfg(feature = "zstd")]
    write_zst_and_assert_serial(&zst_path, &frames, &want);
}

fn heavy_mutations_match_serial(edit: impl Fn(&mut Vec<ConFrame>)) {
    let _guard = CACHE_LOCK.lock().unwrap_or_else(|e| e.into_inner());
    // 1000 frames * 3000 atoms crosses direct_slice_write's 3_000_000 threshold
    // so workers=8 enters place_packed and format_packed_buffers.
    let mut frames = vec![dense_uniform_frame(3000); 1000];
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("heavy.con");

    {
        let refs: Vec<&ConFrame> = frames.iter().collect();
        let initial = format_frame_refs_unstored(&refs, 8, None, false, false).unwrap();
        assert_eq!(initial.len(), 8);
    }

    edit(&mut frames);
    let want = write_frames_to_vec(&frames).unwrap();

    // First mutated call hits the stale cache inside format_frame_refs_unstored.
    let refs: Vec<&ConFrame> = frames.iter().collect();
    let parts = format_frame_refs_unstored(&refs, 8, None, false, false).unwrap();
    let unstored: Vec<u8> = parts.into_iter().flatten().collect();
    assert_eq!(unstored, want);

    // Re-price and mutate again to exercise place_packed at workers=8.
    let mut frames = vec![dense_uniform_frame(3000); 1000];
    {
        let refs: Vec<&ConFrame> = frames.iter().collect();
        write_frame_refs_to_path(&path, &refs, 8, None, false, false).unwrap();
    }
    edit(&mut frames);
    let want = write_frames_to_vec(&frames).unwrap();
    for workers in [1usize, 2, 8] {
        let refs: Vec<&ConFrame> = frames.iter().collect();
        write_frame_refs_to_path(&path, &refs, workers, None, false, false).unwrap();
        assert_eq!(
            std::fs::read(&path).unwrap(),
            want,
            "heavy workers {workers}"
        );
    }
}

#[test]
fn a_store_into_positions_after_a_write_is_written() {
    rewrite_matches_serial(2, |frames| {
        for v in frames[0].positions.f64_mut_slice().unwrap() {
            *v = 1.234_567_890_123_456_7e22;
        }
    });
}

#[test]
fn a_shorter_positions_store_after_a_write_is_written() {
    rewrite_matches_serial(2, |frames| {
        for v in frames[0].positions.f64_mut_slice().unwrap() {
            *v = 1.0;
        }
    });
}

#[test]
fn a_set_f64_row_store_after_a_write_is_written() {
    rewrite_matches_serial(12, |frames| {
        let n = frames[0].atom_data.len();
        for i in 0..n {
            frames[0]
                .positions
                .set_f64_row(i, [1.234_567_890_123_456_7e22, -2.5e-18, 9.876_543_21e14]);
            frames[9].positions.set_f64_row(i, [1.0, 2.0, 3.0]);
        }
    });
}

#[test]
fn a_replaced_positions_column_after_a_write_is_written() {
    rewrite_matches_serial(12, |frames| {
        let n = frames[0].atom_data.len();
        frames[0].positions =
            FloatArray2::from_f64_row_major(n, 3, vec![-9.876_543_210_987_654e-17; n * 3]);
    });
}

#[test]
fn a_header_edit_after_a_write_is_written() {
    rewrite_matches_serial(12, |frames| {
        frames[1]
            .header
            .prebox_header
            .user
            .push_str(" with a much longer first header line");
    });
}

#[test]
fn heavy_unstored_and_packed_paths_recover_after_mutations() {
    heavy_mutations_match_serial(|frames| {
        for v in frames[0].positions.f64_mut_slice().unwrap() {
            *v = 1.234_567_890_123_456_7e22;
        }
    });
    heavy_mutations_match_serial(|frames| {
        frames[0].positions.set_f64_row(
            0,
            [-9.876_543_210_987_654e-17, 1.0, 1.234_567_890_123_456_7e22],
        );
        let n = frames[1].atom_data.len();
        frames[1].positions = FloatArray2::from_f64_row_major(n, 3, vec![1.0; n * 3]);
        frames[999]
            .header
            .prebox_header
            .user
            .push_str(" with a longer header");
    });
}

#[test]
fn fused_compressed_frame_mutations_match_serial() {
    let dir = tempfile::tempdir().unwrap();
    let mut frame = dense_uniform_frame(128);
    for (idx, edit) in [
        Box::new(|f: &mut ConFrame| {
            for v in f.positions.f64_mut_slice().unwrap() {
                *v = 1.234_567_890_123_456_7e22;
            }
        }) as Box<dyn FnOnce(&mut ConFrame)>,
        Box::new(|f: &mut ConFrame| {
            f.positions
                .set_f64_row(0, [-9.876_543_210_987_654e-17, 2.0, 3.0]);
        }),
        Box::new(|f: &mut ConFrame| {
            let n = f.atom_data.len();
            f.positions = FloatArray2::from_f64_row_major(n, 3, vec![1.0; n * 3]);
        }),
        Box::new(|f: &mut ConFrame| {
            f.header
                .prebox_header
                .user
                .push_str(" fused compressed header edit");
        }),
    ]
    .into_iter()
    .enumerate()
    {
        edit(&mut frame);
        let want = write_frames_to_vec(std::slice::from_ref(&frame)).unwrap();
        for threads in [1usize, 2, 8] {
            let gz_path = dir.path().join(format!("fused-{idx}-{threads}.con.gz"));
            write_fused_gzip_frame(&gz_path, &frame, threads.max(2), threads).unwrap();
            assert_eq!(
                read_file_bytes(&gz_path).unwrap(),
                want,
                "fused gz step {idx} threads {threads}"
            );
            #[cfg(feature = "zstd")]
            {
                let zst_path = dir.path().join(format!("fused-{idx}-{threads}.con.zst"));
                write_fused_zstd_frame(&zst_path, &frame, threads.max(2), threads).unwrap();
                assert_eq!(
                    read_file_bytes(&zst_path).unwrap(),
                    want,
                    "fused zst step {idx} threads {threads}"
                );
            }
        }
    }
}
