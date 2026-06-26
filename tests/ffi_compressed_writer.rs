//! Round-trip coverage for the compressed-writer C ABI.
//!
//! These exercise the exact entry points the C++ `ConFrameWriter`
//! wrapper calls (`create_writer_gzip_c`, `create_writer_zstd_c`, and
//! their `_with_precision` variants), confirming that frames written
//! through the FFI land in a real gzip/zstd stream and parse back
//! identically through the transparent reader.

mod common;

use readcon_core::compression::read_file_contents;
use readcon_core::ffi::{
    create_writer_gzip_c, create_writer_gzip_with_precision_c, free_rkr_frame, free_rkr_writer,
    rkr_writer_extend, RKRConFrame, RKRStatus,
};
use readcon_core::iterators::ConFrameIterator;
use readcon_core::types::ConFrame;
use std::ffi::CString;
use std::fs;
use std::path::Path;

/// Parse the bundled multi-frame fixture into owned frames.
fn load_fixture_frames() -> Vec<ConFrame> {
    let data = fs::read_to_string(test_case!("tiny_multi_cuh2.con"))
        .expect("Can't find test fixture.");
    ConFrameIterator::new(&data)
        .map(|r| r.expect("fixture frame should parse"))
        .collect()
}

/// Box each frame and hand back raw `RKRConFrame` handles plus the
/// pointer array the FFI `extend` expects.
fn into_handles(frames: Vec<ConFrame>) -> Vec<*const RKRConFrame> {
    frames
        .into_iter()
        .map(|f| Box::into_raw(Box::new(f)) as *const RKRConFrame)
        .collect()
}

/// Free a slice of frame handles created by `into_handles`.
fn free_handles(handles: &[*const RKRConFrame]) {
    for &h in handles {
        unsafe { free_rkr_frame(h as *mut RKRConFrame) };
    }
}

/// Drive the writer FFI: create -> extend -> free, returning nothing
/// (panics on any failure so tests surface the real status).
fn write_through_ffi(handle: *mut readcon_core::ffi::RKRConFrameWriter, frames: &[*const RKRConFrame]) {
    assert!(!handle.is_null(), "writer handle should be non-null");
    let status = unsafe { rkr_writer_extend(handle, frames.as_ptr(), frames.len()) };
    assert_eq!(status, RKRStatus::RKR_STATUS_SUCCESS, "extend should succeed");
    // Dropping the writer flushes the BufWriter and finalizes the
    // compression stream.
    unsafe { free_rkr_writer(handle) };
}

/// Re-parse a (possibly compressed) file and assert the frame count.
fn assert_roundtrip(path: &Path, expected: &[ConFrame]) {
    let contents = read_file_contents(path).expect("should decompress + read");
    let text = contents.as_str().expect("valid UTF-8");
    let frames: Vec<ConFrame> = ConFrameIterator::new(text)
        .map(|r| r.expect("roundtrip frame should parse"))
        .collect();
    assert_eq!(
        frames.len(),
        expected.len(),
        "frame count must survive the compressed roundtrip"
    );
    assert_eq!(frames, *expected, "frame data must be identical after roundtrip");
}

#[test]
fn gzip_writer_ffi_roundtrip() {
    let frames = load_fixture_frames();
    assert!(!frames.is_empty());
    let expected = frames.clone();

    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("out.con.gz");
    let c_path = CString::new(path.to_str().unwrap()).unwrap();

    let handles = into_handles(frames);
    let writer = unsafe { create_writer_gzip_c(c_path.as_ptr()) };
    write_through_ffi(writer, &handles);
    free_handles(&handles);

    // gzip magic: 1f 8b
    let raw = fs::read(&path).unwrap();
    assert_eq!(&raw[..2], &[0x1f, 0x8b], "output must be a gzip stream");

    assert_roundtrip(&path, &expected);
}

#[test]
fn gzip_writer_with_precision_ffi_roundtrip() {
    let frames = load_fixture_frames();
    let expected = frames.clone();

    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("prec.con.gz");
    let c_path = CString::new(path.to_str().unwrap()).unwrap();

    let handles = into_handles(frames);
    let writer = unsafe { create_writer_gzip_with_precision_c(c_path.as_ptr(), 8) };
    write_through_ffi(writer, &handles);
    free_handles(&handles);

    let raw = fs::read(&path).unwrap();
    assert_eq!(&raw[..2], &[0x1f, 0x8b], "output must be a gzip stream");
    assert_roundtrip(&path, &expected);
}

#[cfg(feature = "zstd")]
#[test]
fn zstd_writer_ffi_roundtrip() {
    use readcon_core::ffi::{create_writer_zstd_c, create_writer_zstd_with_precision_c};

    let frames = load_fixture_frames();
    let expected = frames.clone();

    let dir = tempfile::tempdir().unwrap();

    // Default precision.
    {
        let path = dir.path().join("out.con.zst");
        let c_path = CString::new(path.to_str().unwrap()).unwrap();
        let handles = into_handles(frames.clone());
        let writer = unsafe { create_writer_zstd_c(c_path.as_ptr()) };
        write_through_ffi(writer, &handles);
        free_handles(&handles);

        // zstd magic: 28 b5 2f fd
        let raw = fs::read(&path).unwrap();
        assert_eq!(
            &raw[..4],
            &[0x28, 0xb5, 0x2f, 0xfd],
            "output must be a zstd stream"
        );
        assert_roundtrip(&path, &expected);
    }

    // Custom precision.
    {
        let path = dir.path().join("prec.con.zst");
        let c_path = CString::new(path.to_str().unwrap()).unwrap();
        let handles = into_handles(frames);
        let writer = unsafe { create_writer_zstd_with_precision_c(c_path.as_ptr(), 8) };
        write_through_ffi(writer, &handles);
        free_handles(&handles);

        let raw = fs::read(&path).unwrap();
        assert_eq!(
            &raw[..4],
            &[0x28, 0xb5, 0x2f, 0xfd],
            "output must be a zstd stream"
        );
        assert_roundtrip(&path, &expected);
    }
}
