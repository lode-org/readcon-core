#![no_main]

use libfuzzer_sys::fuzz_target;
use readcon_core::ffi::{
    con_frame_iterator_next, free_con_frame_iterator, free_rkr_frame, free_rkr_frame_array,
    read_con_buffer_iterator, rkr_read_all_frames_n_threads, rkr_read_chemfiles_memory,
};
use std::ffi::CString;

fuzz_target!(|data: &[u8]| {
    if data.len() > 64 * 1024 {
        return;
    }
    unsafe {
        let iter = read_con_buffer_iterator(data.as_ptr(), data.len());
        if !iter.is_null() {
            let mut seen = 0usize;
            loop {
                let frame = con_frame_iterator_next(iter);
                if frame.is_null() || seen > data.len() {
                    if !frame.is_null() {
                        free_rkr_frame(frame);
                    }
                    break;
                }
                free_rkr_frame(frame);
                seen += 1;
            }
            free_con_frame_iterator(iter);
        }
    }
    let Ok(dir) = tempfile::tempdir() else {
        return;
    };
    let path = dir.path().join("fuzz.con");
    if std::fs::write(&path, data).is_err() {
        return;
    }
    let Ok(c_path) = CString::new(path.to_string_lossy().as_bytes()) else {
        return;
    };
    for threads in [1usize, 8] {
        let mut count = 0usize;
        let frames = unsafe { rkr_read_all_frames_n_threads(c_path.as_ptr(), &mut count, threads) };
        if !frames.is_null() {
            unsafe { free_rkr_frame_array(frames, count) };
        }
    }
    // Same chemfiles memory entry the C API uses. Interior NULs cannot be
    // a C string, so the prefix before the first NUL is the buffer.
    let end = data
        .iter()
        .position(|byte| *byte == 0)
        .unwrap_or(data.len());
    let slice = &data[..end.min(16 * 1024)];
    if let Ok(c_data) = CString::new(slice) {
        let format = CString::new("XYZ").expect("format");
        let mut count = 0usize;
        let frames =
            unsafe { rkr_read_chemfiles_memory(c_data.as_ptr(), format.as_ptr(), &mut count) };
        if !frames.is_null() {
            unsafe { free_rkr_frame_array(frames, count) };
        }
    }
});
