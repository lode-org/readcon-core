//! Append, flush, and in-memory serialization.
//!
//! These tests call the API that did not exist before this change:
//! `from_path_append`, a flush that leaves a parseable file, and
//! `write_frames_to_string`.

use readcon_core::ffi::{
    RKRConFrame, RKRStatus, create_writer_from_path_append_c, create_writer_from_path_c,
    free_rkr_writer, rkr_free_string, rkr_last_error_message, rkr_write_frames_to_string,
    rkr_writer_extend, rkr_writer_flush,
};
use readcon_core::iterators::ConFrameIterator;
use readcon_core::types::{ConFrame, ConFrameBuilder};
use readcon_core::writer::{ConFrameWriter, write_frames_to_string, write_frames_to_vec};
use std::ffi::{CStr, CString};
use std::fs;
use std::path::Path;
use std::process::Command;

fn frame(id: u64, x: f64) -> ConFrame {
    let mut builder = ConFrameBuilder::new([4.0, 4.0, 4.0], [90.0, 90.0, 90.0]);
    builder.add_atom("Cu", x, 0.1, 0.2, [false, false, false], id, 63.546);
    builder.build().unwrap()
}

fn frames() -> Vec<ConFrame> {
    vec![frame(0, 0.0), frame(1, 1.0), frame(2, 2.0)]
}

fn parse_count(path: &Path) -> usize {
    let text = fs::read_to_string(path).unwrap();
    ConFrameIterator::new(&text)
        .collect::<Result<Vec<_>, _>>()
        .unwrap()
        .len()
}

#[test]
fn append_matches_whole_file_write() {
    let dir = tempfile::tempdir().unwrap();
    let frames = frames();
    let whole = dir.path().join("whole.con");
    {
        let mut writer = ConFrameWriter::from_path(&whole).unwrap();
        writer.extend(frames.iter()).unwrap();
    }
    let whole_bytes = fs::read(&whole).unwrap();

    let part = dir.path().join("part.con");
    {
        let mut writer = ConFrameWriter::from_path(&part).unwrap();
        writer.write_frame(&frames[0]).unwrap();
    }
    {
        let mut writer = ConFrameWriter::from_path_append(&part).unwrap();
        writer.extend(frames[1..].iter()).unwrap();
    }
    assert_eq!(fs::read(&part).unwrap(), whole_bytes);

    let fresh = dir.path().join("fresh.con");
    {
        let mut writer = ConFrameWriter::from_path_append(&fresh).unwrap();
        writer.extend(frames.iter()).unwrap();
    }
    assert_eq!(fs::read(&fresh).unwrap(), whole_bytes);

    let mut bare = whole_bytes.clone();
    assert_eq!(bare.pop(), Some(b'\n'));
    let missing_nl = dir.path().join("missing-nl.con");
    fs::write(&missing_nl, &bare).unwrap();
    {
        let mut writer = ConFrameWriter::from_path_append(&missing_nl).unwrap();
        writer.write_frame(&frame(3, 3.0)).unwrap();
    }
    let mut expected = whole_bytes.clone();
    expected.extend(write_frames_to_vec(&[frame(3, 3.0)]).unwrap());
    assert_eq!(fs::read(&missing_nl).unwrap(), expected);

    let err = match ConFrameWriter::from_path_append(dir.path().join("x.con.gz")) {
        Ok(_) => panic!("gzip append was accepted"),
        Err(err) => err,
    };
    assert!(err.to_string().contains("uncompressed"), "{err}");

    let precise_a = dir.path().join("precise-a.con");
    let precise_b = dir.path().join("precise-b.con");
    {
        let mut writer = ConFrameWriter::from_path_with_precision(&precise_a, 6).unwrap();
        writer.write_frame(&frames[0]).unwrap();
    }
    {
        let mut writer = ConFrameWriter::from_path_append_with_precision(&precise_a, 6).unwrap();
        writer.extend(frames[1..].iter()).unwrap();
    }
    {
        let mut writer = ConFrameWriter::from_path_with_precision(&precise_b, 6).unwrap();
        writer.extend(frames.iter()).unwrap();
    }
    assert_eq!(fs::read(&precise_a).unwrap(), fs::read(&precise_b).unwrap());

    {
        let mut writer = ConFrameWriter::from_path(&part).unwrap();
        writer.write_frame(&frames[0]).unwrap();
    }
    assert_eq!(
        fs::read(&part).unwrap(),
        write_frames_to_vec(&frames[..1]).unwrap()
    );
}

#[test]
fn flush_leaves_a_parseable_file() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("flush.con");
    let frames = frames();
    let mut writer = ConFrameWriter::from_path(&path).unwrap();
    writer.write_frame(&frames[0]).unwrap();
    assert_eq!(
        fs::metadata(&path).unwrap().len(),
        0,
        "a small frame stays buffered until flush"
    );
    writer.flush().unwrap();
    assert_eq!(parse_count(&path), 1);
    writer.write_frame(&frames[1]).unwrap();
    writer.flush().unwrap();
    assert_eq!(parse_count(&path), 2);
}

#[test]
fn string_matches_file_bytes() {
    let dir = tempfile::tempdir().unwrap();
    let frames = frames();
    let path = dir.path().join("file.con");
    {
        let mut writer = ConFrameWriter::from_path(&path).unwrap();
        writer.extend(frames.iter()).unwrap();
    }
    let file = fs::read(&path).unwrap();
    let bytes = write_frames_to_vec(&frames).unwrap();
    let text = write_frames_to_string(&frames).unwrap();
    assert_eq!(bytes, file);
    assert_eq!(text.as_bytes(), file);
    assert!(ConFrameIterator::new(&text).all(|frame| frame.is_ok()));
}

#[test]
fn c_append_flush_and_string_match_the_file() {
    let dir = tempfile::tempdir().unwrap();
    let frames = frames();
    let path = dir.path().join("c.con");
    let name = CString::new(path.to_str().unwrap()).unwrap();
    let handles: Vec<*const RKRConFrame> = frames
        .iter()
        .map(|frame| frame as *const ConFrame as *const RKRConFrame)
        .collect();
    unsafe {
        let writer = create_writer_from_path_c(name.as_ptr());
        assert!(!writer.is_null());
        assert_eq!(
            rkr_writer_extend(writer, handles.as_ptr(), 1),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_eq!(fs::metadata(&path).unwrap().len(), 0);
        assert_eq!(rkr_writer_flush(writer), RKRStatus::RKR_STATUS_SUCCESS);
        assert_eq!(parse_count(&path), 1);
        free_rkr_writer(writer);

        let writer = create_writer_from_path_append_c(name.as_ptr());
        assert!(!writer.is_null());
        assert_eq!(
            rkr_writer_extend(writer, handles.as_ptr().add(1), handles.len() - 1),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_eq!(rkr_writer_flush(writer), RKRStatus::RKR_STATUS_SUCCESS);
        free_rkr_writer(writer);

        let mut text = std::ptr::null_mut();
        let mut len = 0usize;
        assert_eq!(
            rkr_write_frames_to_string(handles.as_ptr(), handles.len(), &mut text, &mut len),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        let serialized = std::slice::from_raw_parts(text as *const u8, len);
        assert_eq!(serialized, fs::read(&path).unwrap().as_slice());
        rkr_free_string(text);

        let gzip = CString::new(dir.path().join("x.con.gz").to_str().unwrap()).unwrap();
        assert!(create_writer_from_path_append_c(gzip.as_ptr()).is_null());
        let message = CStr::from_ptr(rkr_last_error_message());
        assert!(message.to_string_lossy().contains("uncompressed"));
    }
}

#[test]
fn cpp_append_flush_and_string_match_the_file() {
    let dir = tempfile::tempdir().unwrap();
    let mut lib_dir = std::env::current_exe().unwrap();
    lib_dir.pop();
    let source = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/c/test_writer_append.cpp");
    let binary = dir.path().join("test_writer_append");
    let status = Command::new("g++")
        .args(["-std=c++17", "-Wall", "-Wextra", "-Werror", "-I", "include"])
        .arg(&source)
        .arg(format!("-L{}", lib_dir.display()))
        .arg("-lreadcon_core")
        .arg(format!("-Wl,-rpath,{}", lib_dir.display()))
        .arg("-o")
        .arg(&binary)
        .status()
        .expect("g++");
    assert!(
        status.success(),
        "g++ failed to compile the C++ writer test"
    );
    let run = Command::new(&binary)
        .arg(dir.path())
        .status()
        .expect("run cpp writer test");
    assert!(run.success(), "C++ append, flush, or string check failed");
}
