//! C entry points with the inputs a caller can pass without the harness
//! reading off the end of its own buffer: null, a short prefix, a large
//! owned buffer, and element names that are not UTF-8.
//!
//! `free_*` and `rkr_trajectory_free` treat NULL as a no-op. A second free
//! of the same non-null handle is undefined, so this target frees each
//! live handle once and then frees NULL again. After a live free, accessors
//! are called on NULL, which is the defined empty handle.

#![no_main]

use libfuzzer_sys::fuzz_target;
use readcon_core::ffi::{
    con_frame_iterator_forward, con_frame_iterator_next, free_con_frame_iterator, free_rkr_frame,
    free_rkr_frame_array, free_rkr_frame_builder, read_con_buffer_iterator,
    read_con_string_iterator, rkr_frame_add_atom, rkr_frame_atom_count, rkr_frame_builder_build,
    rkr_frame_builder_set_metadata_json, rkr_frame_builder_set_string_metadata, rkr_frame_new,
    rkr_read_all_frames, rkr_read_all_frames_n_threads, rkr_read_chemfiles_memory,
    rkr_read_first_frame, rkr_symbol_to_z, rkr_trajectory_free, rkr_trajectory_open,
};
use std::ffi::CString;
use std::ptr;

fn drain_iterator(iter: *mut readcon_core::ffi::CConFrameIterator) {
    if iter.is_null() {
        return;
    }
    unsafe {
        let mut seen = 0usize;
        while seen < 64 {
            let frame = con_frame_iterator_next(iter);
            if frame.is_null() {
                break;
            }
            let _ = rkr_frame_atom_count(frame);
            free_rkr_frame(frame);
            seen += 1;
        }
        free_con_frame_iterator(iter);
    }
}

fuzz_target!(|data: &[u8]| {
    if data.len() > 8 * 1024 {
        return;
    }
    unsafe {
        let _ = read_con_buffer_iterator(ptr::null(), 1);
        let empty = read_con_buffer_iterator(ptr::null(), 0);
        drain_iterator(empty);
        let _ = read_con_string_iterator(ptr::null());
        let _ = rkr_symbol_to_z(ptr::null());
        let _ = rkr_trajectory_open(ptr::null(), 0);
        let _ = rkr_read_first_frame(ptr::null());
        let mut num = 0usize;
        let _ = rkr_read_all_frames(ptr::null(), &mut num);
        let _ = rkr_read_all_frames(ptr::null(), ptr::null_mut());
        let _ = rkr_read_all_frames_n_threads(ptr::null(), &mut num, 2);
        let _ = rkr_read_all_frames_n_threads(ptr::null(), ptr::null_mut(), 0);
        let _ = rkr_read_chemfiles_memory(ptr::null(), ptr::null(), &mut num);
        free_rkr_frame(ptr::null_mut());
        free_rkr_frame(ptr::null_mut());
        free_con_frame_iterator(ptr::null_mut());
        free_con_frame_iterator(ptr::null_mut());
        free_rkr_frame_builder(ptr::null_mut());
        free_rkr_frame_builder(ptr::null_mut());
        rkr_trajectory_free(ptr::null_mut());
        rkr_trajectory_free(ptr::null_mut());
        free_rkr_frame_array(ptr::null_mut(), 0);
        free_rkr_frame_array(ptr::null_mut(), 0);
        let _ = rkr_frame_atom_count(ptr::null());
        let _ = con_frame_iterator_next(ptr::null_mut());
        let _ = con_frame_iterator_forward(ptr::null_mut());
        let _ = rkr_frame_builder_build(ptr::null_mut());
        let _ = rkr_frame_add_atom(ptr::null_mut(), ptr::null(), 0.0, 0.0, 0.0, false, 0, 1.0);

        let bad = CString::new(vec![0xffu8, 0x80, 0xfe]).unwrap();
        let bad_ptr = bad.as_ptr();
        let _ = rkr_symbol_to_z(bad_ptr);
        let _ = read_con_string_iterator(bad_ptr);
        if !data.is_empty() {
            drain_iterator(read_con_buffer_iterator(data.as_ptr(), 1));
            drain_iterator(read_con_buffer_iterator(data.as_ptr(), data.len()));
        }

        let huge_len = (8 * 1024) + (usize::from(data.first().copied().unwrap_or(0)) * 64);
        let mut huge = vec![b'\n'; huge_len.min(32 * 1024)];
        if !data.is_empty() {
            for (index, byte) in huge.iter_mut().enumerate() {
                let source = data[index % data.len()];
                if source != 0 {
                    *byte = source;
                }
            }
        }
        drain_iterator(read_con_buffer_iterator(huge.as_ptr(), huge.len()));

        let cell = [1.0f64, 1.0, 1.0];
        let angles = [90.0f64, 90.0, 90.0];
        let builder = rkr_frame_new(
            cell.as_ptr(),
            angles.as_ptr(),
            bad_ptr,
            ptr::null(),
            ptr::null(),
            bad_ptr,
        );
        if !builder.is_null() {
            let symbol = CString::new("H").unwrap();
            let _ = rkr_frame_add_atom(
                builder,
                bad_ptr,
                f64::NAN,
                f64::INFINITY,
                f64::NEG_INFINITY,
                false,
                1,
                f64::NAN,
            );
            let _ = rkr_frame_add_atom(
                builder,
                symbol.as_ptr(),
                f64::NAN,
                f64::INFINITY,
                0.0,
                false,
                2,
                1.0,
            );
            let _ = rkr_frame_builder_set_string_metadata(builder, bad_ptr, bad_ptr);
            let _ = rkr_frame_builder_set_string_metadata(builder, ptr::null(), ptr::null());
            let _ = rkr_frame_builder_set_metadata_json(builder, bad_ptr);
            let _ = rkr_frame_builder_set_metadata_json(builder, ptr::null());
            let frame = rkr_frame_builder_build(builder);
            if !frame.is_null() {
                std::hint::black_box(rkr_frame_atom_count(frame));
                free_rkr_frame(frame);
                std::hint::black_box(rkr_frame_atom_count(ptr::null()));
            }
            free_rkr_frame_builder(ptr::null_mut());
        }
        let _ = rkr_frame_new(
            ptr::null(),
            angles.as_ptr(),
            ptr::null(),
            ptr::null(),
            ptr::null(),
            ptr::null(),
        );

        let xyz = CString::new("0\n\n").unwrap();
        let format = CString::new("XYZ").unwrap();
        let frames = rkr_read_chemfiles_memory(xyz.as_ptr(), format.as_ptr(), &mut num);
        if !frames.is_null() {
            free_rkr_frame_array(frames, num);
        }
        free_rkr_frame_array(ptr::null_mut(), num);
        let _ = rkr_read_chemfiles_memory(bad_ptr, format.as_ptr(), &mut num);
        let _ = rkr_read_chemfiles_memory(xyz.as_ptr(), bad_ptr, &mut num);

        let missing = CString::new("no-such-readcon-fuzz.con").unwrap();
        let opened = rkr_trajectory_open(missing.as_ptr(), 0);
        if !opened.is_null() {
            rkr_trajectory_free(opened);
        }
        rkr_trajectory_free(ptr::null_mut());
        let _ = rkr_trajectory_open(bad_ptr, 1);
        let _ = rkr_read_first_frame(bad_ptr);
        let _ = rkr_read_all_frames_n_threads(bad_ptr, &mut num, usize::MAX);
    }
});
