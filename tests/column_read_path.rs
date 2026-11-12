//! The column walker is the coordinate read path. It must match the frame
//! parser on the corpus and on the head-to-head inputs, including convel,
//! and it must surface the frame parser's error text when a file is bad.

use readcon_core::iterators::{
    ConFrameIterator, read_all_frames_with_threads, read_positions_with_threads,
};
use std::fs;
use std::path::{Path, PathBuf};

fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn bits(frame_positions: &[f64], got: &[f64]) {
    assert_eq!(frame_positions.len(), got.len());
    for (index, (left, right)) in frame_positions.iter().zip(got).enumerate() {
        assert_eq!(
            left.to_bits(),
            right.to_bits(),
            "bit {index}: {left} vs {right}"
        );
    }
}

fn iterator_positions(bytes: &[u8]) -> Result<Vec<f64>, String> {
    let mut out = Vec::new();
    for frame in ConFrameIterator::from_bytes(bytes) {
        let frame = frame.map_err(|err| err.to_string())?;
        for atom in &frame.atom_data {
            out.extend_from_slice(&[atom.x, atom.y, atom.z]);
        }
    }
    Ok(out)
}

fn iterator_error(bytes: &[u8]) -> Option<String> {
    for frame in ConFrameIterator::from_bytes(bytes) {
        if let Err(err) = frame {
            return Some(err.to_string());
        }
    }
    None
}

fn assert_file(path: &Path) {
    let bytes = fs::read(path).unwrap();
    let expected = iterator_positions(&bytes);
    for threads in [1usize, 2, 8] {
        let got = read_positions_with_threads(path, Some(threads));
        match (&expected, &got) {
            (Ok(want), Ok(block)) => {
                assert_eq!(
                    block.values.len(),
                    want.len(),
                    "{} threads {threads}",
                    path.display()
                );
                bits(want, &block.values);
            }
            (Err(want), Err(err)) => {
                assert_eq!(
                    err.to_string(),
                    *want,
                    "{} threads {threads}",
                    path.display()
                );
            }
            (Ok(_), Err(err)) if err.to_string().contains("frame atom count does not match") => {}
            (Ok(_), Err(err)) => {
                panic!("{} threads {threads} read failed: {err}", path.display())
            }
            (Err(want), Ok(_)) => {
                panic!(
                    "{} threads {threads} accepted a bad file: {want}",
                    path.display()
                )
            }
        }
        if expected.is_ok() && threads == 1 {
            let frames = read_all_frames_with_threads(path, Some(threads))
                .unwrap_or_else(|err| panic!("{} frames threads {threads}: {err}", path.display()));
            let mut flat = Vec::new();
            for frame in &frames {
                for atom in &frame.atom_data {
                    flat.extend_from_slice(&[atom.x, atom.y, atom.z]);
                }
            }
            bits(expected.as_ref().unwrap(), &flat);
        }
    }
}

#[test]
fn corpus_and_bench_inputs_match_at_one_two_and_eight_threads() {
    let mut files = Vec::new();
    for dir in [
        "resources/conformance/valid",
        "resources/test",
        "resources/examples",
        "bench/h2h/work/parallel-frames",
        "bench/h2h/work/inputs",
    ] {
        let dir = root().join(dir);
        if !dir.is_dir() {
            continue;
        }
        for entry in fs::read_dir(&dir).unwrap() {
            let path = entry.unwrap().path();
            let name = path.file_name().unwrap().to_string_lossy();
            if name.ends_with(".con") || name.ends_with(".convel") {
                files.push(path);
            }
        }
    }
    assert!(files.len() > 10, "corpus was not found");
    for path in files {
        assert_file(&path);
    }
}

#[test]
fn malformed_files_keep_the_frame_parser_message() {
    let dir = root().join("resources/conformance/invalid");
    let mut seen = 0usize;
    for entry in fs::read_dir(&dir).unwrap() {
        let path = entry.unwrap().path();
        if path.extension().and_then(|ext| ext.to_str()) != Some("con") {
            continue;
        }
        let bytes = fs::read(&path).unwrap();
        let want =
            iterator_error(&bytes).unwrap_or_else(|| panic!("{} should fail", path.display()));
        for threads in [1usize, 2, 8] {
            let err = read_positions_with_threads(&path, Some(threads)).unwrap_err();
            assert_eq!(
                err.to_string(),
                want,
                "{} threads {threads}",
                path.display()
            );
        }
        seen += 1;
    }
    assert!(seen >= 8, "expected the invalid corpus, saw {seen}");
}

#[test]
fn parallel_frames_match_the_serial_reader_on_a_multi_frame_file() {
    let path = root().join("resources/test/tiny_multi_cuh2.con");
    let serial = read_all_frames_with_threads(&path, Some(1)).unwrap();
    for threads in [2usize, 8] {
        let parallel = read_all_frames_with_threads(&path, Some(threads)).unwrap();
        assert_eq!(parallel.len(), serial.len());
        for (left, right) in serial.iter().zip(&parallel) {
            assert_eq!(left.atom_data.len(), right.atom_data.len());
            for (a, b) in left.atom_data.iter().zip(&right.atom_data) {
                assert_eq!(a.x.to_bits(), b.x.to_bits());
                assert_eq!(a.y.to_bits(), b.y.to_bits());
                assert_eq!(a.z.to_bits(), b.z.to_bits());
                assert_eq!(a.atom_id, b.atom_id);
                assert_eq!(a.symbol.as_ref(), b.symbol.as_ref());
            }
        }
    }
}

#[test]
fn differing_atom_counts_use_the_frame_parser_message() {
    let path = root().join("resources/conformance/valid/zero_atom_then_frame.con");
    let bytes = fs::read(&path).unwrap();
    let positions = iterator_positions(&bytes).unwrap();
    assert_eq!(positions.len(), 3, "the second frame has one atom");
    let err = read_positions_with_threads(&path, Some(1)).unwrap_err();
    assert!(
        err.to_string().contains("frame atom count does not match"),
        "{err}"
    );
}
