//! The column walker is the coordinate read path. It must match the frame
//! parser on the corpus and on the head-to-head inputs, including convel,
//! and it must surface the frame parser's error text when a file is bad.

use readcon_core::ffi::{
    rkr_free_position_block, rkr_last_error_message, rkr_position_block_values,
    rkr_read_all_frames, rkr_read_positions_n_threads,
};
use readcon_core::iterators::{
    ConFrameIterator, read_all_frames_with_threads, read_coord_columns, read_positions_with_threads,
};
use readcon_core::types::ConFrameBuilder;
use readcon_core::writer::ConFrameWriter;
use std::ffi::{CStr, CString};
use std::fs;
use std::path::{Path, PathBuf};

fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn c_string(path: &Path) -> CString {
    CString::new(path.to_str().expect("utf-8 path")).unwrap()
}

fn c_error() -> String {
    unsafe {
        let msg = rkr_last_error_message();
        if msg.is_null() {
            return String::new();
        }
        CStr::from_ptr(msg).to_string_lossy().into_owned()
    }
}

fn c_frame_error(path: &Path) -> Option<String> {
    let name = c_string(path);
    let mut n_frames = 0usize;
    unsafe {
        let frames = rkr_read_all_frames(name.as_ptr(), &mut n_frames);
        if frames.is_null() {
            return Some(c_error());
        }
        readcon_core::ffi::free_rkr_frame_array(frames, n_frames);
    }
    None
}

fn c_positions(path: &Path, threads: usize) -> Result<Vec<f64>, String> {
    let name = c_string(path);
    let mut n_frames = 0usize;
    let mut n_atoms = 0usize;
    unsafe {
        let block =
            rkr_read_positions_n_threads(name.as_ptr(), &mut n_frames, &mut n_atoms, threads);
        if block.is_null() {
            return Err(c_error());
        }
        let ptr = rkr_position_block_values(block);
        let len = n_frames * n_atoms * 3;
        let values = if ptr.is_null() || len == 0 {
            Vec::new()
        } else {
            std::slice::from_raw_parts(ptr, len).to_vec()
        };
        rkr_free_position_block(block);
        Ok(values)
    }
}

fn assert_c(path: &Path, threads: usize, rust_values: &[f64]) {
    let got = c_positions(path, threads)
        .unwrap_or_else(|err| panic!("{} C threads {threads}: {err}", path.display()));
    bits(rust_values, &got);
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
                assert_c(path, threads, want);
            }
            (Err(want), Err(err)) => {
                assert_eq!(
                    err.to_string(),
                    *want,
                    "{} threads {threads}",
                    path.display()
                );
                let c_err = c_positions(path, threads).expect_err("C accepted a bad file");
                if let Some(frame_err) = c_frame_error(path) {
                    assert_eq!(c_err, frame_err, "{} threads {threads}", path.display());
                }
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
        if let Ok(want) = expected.as_ref()
            && threads == 1
        {
            let frames = read_all_frames_with_threads(path, Some(threads))
                .unwrap_or_else(|err| panic!("{} frames threads {threads}: {err}", path.display()));
            let mut flat = Vec::new();
            for frame in &frames {
                for atom in &frame.atom_data {
                    flat.extend_from_slice(&[atom.x, atom.y, atom.z]);
                }
            }
            bits(want, &flat);
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
            let c_err = c_positions(&path, threads).expect_err("C accepted a bad file");
            let frame_err = c_frame_error(&path).expect("frame reader accepted a bad file");
            assert_eq!(c_err, frame_err, "{} threads {threads}", path.display());
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
    let c_err = c_positions(&path, 1).expect_err("C accepted differing counts");
    assert!(c_err.contains("frame atom count does not match"), "{c_err}");
}

#[test]
fn a_custom_header_fills_columns_from_the_frames() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("custom.con");
    let mut first = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
    let mut meta = std::collections::BTreeMap::new();
    meta.insert(
        "generator".to_string(),
        serde_json::Value::String("column-test".to_string()),
    );
    first.metadata(meta);
    first.add_atom("Cu", 0.0, 0.0, 0.0, [true, false, false], 1, 63.546);
    first.add_atom("H", 1.0, 0.0, 0.0, [false, false, false], 2, 1.008);
    let mut second = ConFrameBuilder::new([11.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
    second.add_atom("O", 0.2, 0.0, 0.0, [false, false, true], 4, 16.0);
    second.add_atom("H", 1.2, 0.0, 0.0, [false, false, false], 3, 1.008);
    let frames = [first.build().unwrap(), second.build().unwrap()];
    {
        let mut writer = ConFrameWriter::from_path(&path).unwrap();
        writer.extend(frames.iter()).unwrap();
    }
    let columns = read_coord_columns(&path, Some(2)).unwrap();
    assert_eq!(columns.block.n_frames, 2);
    assert_eq!(columns.block.n_atoms, 2);
    assert_eq!(columns.block.values.len(), 12);
    assert!(columns.partial_fixed);
    assert_eq!(columns.species.len(), 2);
    assert_eq!(columns.atom_ids, vec![1, 2, 4, 3]);
    assert!((columns.cells[0] - 10.0).abs() < 1e-12);
    assert!((columns.masses[0] - 63.546).abs() < 1e-9);
}

#[test]
fn an_empty_file_has_no_coordinate_columns() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("empty.con");
    fs::write(&path, b" \n\t\n").unwrap();
    let columns = read_coord_columns(&path, None).unwrap();
    assert_eq!(columns.block.n_frames, 0);
    assert!(columns.block.values.is_empty());
    assert!(columns.species.is_empty());
}
