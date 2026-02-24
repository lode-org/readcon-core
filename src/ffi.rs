use crate::helpers::symbol_to_atomic_number;
use crate::iterators::ConFrameIterator;
use crate::types::ConFrame;
use crate::writer::ConFrameWriter;
use std::ffi::{c_char, CStr, CString};
use std::fs::{self, File};
use std::ptr;

//=============================================================================
// C-Compatible Structs & Handles
//=============================================================================

/// An opaque handle to a full, lossless Rust `ConFrame` object.
/// The C/C++ side needs to treat this as a void pointer
#[repr(C)]
pub struct RKRConFrame {
    _private: [u8; 0],
}

/// An opaque handle to a Rust `ConFrameWriter` object.
/// The C/C++ side needs to treat this as a void pointer
#[repr(C)]
pub struct RKRConFrameWriter {
    _private: [u8; 0],
}

/// A transparent, "lossy" C-struct containing only the core atomic data.
/// This can be extracted from an `RKRConFrame` handle for direct data access.
/// The caller is responsible for freeing the `atoms` array using `free_c_frame`.
#[repr(C)]
pub struct CFrame {
    pub atoms: *mut CAtom,
    pub num_atoms: usize,
    pub cell: [f64; 3],
    pub angles: [f64; 3],
    pub has_velocities: bool,
}

#[repr(C)]
pub struct CAtom {
    pub atomic_number: u64,
    pub x: f64,
    pub y: f64,
    pub z: f64,
    pub atom_id: u64,
    pub mass: f64,
    pub is_fixed: bool,
    pub vx: f64,
    pub vy: f64,
    pub vz: f64,
    pub has_velocity: bool,
}

#[repr(C)]
pub struct CConFrameIterator {
    iterator: *mut ConFrameIterator<'static>,
    file_contents: *mut String,
}

//=============================================================================
// Iterator and Memory Management
//=============================================================================

/// Creates a new iterator for a .con file.
/// The caller OWNS the returned pointer and MUST call `free_con_frame_iterator`.
/// Returns NULL if there are no more frames or on error.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn read_con_file_iterator(
    filename_c: *const c_char,
) -> *mut CConFrameIterator {
    if filename_c.is_null() {
        return ptr::null_mut();
    }
    let filename = match unsafe { CStr::from_ptr(filename_c).to_str() } {
        Ok(s) => s,
        Err(_) => return ptr::null_mut(),
    };
    let file_contents_box = match fs::read_to_string(filename) {
        Ok(contents) => Box::new(contents),
        Err(_) => return ptr::null_mut(),
    };
    let file_contents_ptr = Box::into_raw(file_contents_box);
    let static_file_contents: &'static str = unsafe { &*file_contents_ptr };
    let iterator = Box::new(ConFrameIterator::new(static_file_contents));
    let c_iterator = Box::new(CConFrameIterator {
        iterator: Box::into_raw(iterator),
        file_contents: file_contents_ptr,
    });
    Box::into_raw(c_iterator)
}

/// Reads the next frame from the iterator, returning an opaque handle.
/// The caller OWNS the returned handle and must free it with `free_rkr_frame`.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn con_frame_iterator_next(
    iterator: *mut CConFrameIterator,
) -> *mut RKRConFrame {
    if iterator.is_null() {
        return ptr::null_mut();
    }
    let iter = unsafe { &mut *(*iterator).iterator };
    match iter.next() {
        Some(Ok(frame)) => Box::into_raw(Box::new(frame)) as *mut RKRConFrame,
        _ => ptr::null_mut(),
    }
}

/// Frees the memory for an opaque `RKRConFrame` handle.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn free_rkr_frame(frame_handle: *mut RKRConFrame) {
    if !frame_handle.is_null() {
        let _ = unsafe { Box::from_raw(frame_handle as *mut ConFrame) };
    }
}

/// Frees the memory for a `CConFrameIterator`.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn free_con_frame_iterator(iterator: *mut CConFrameIterator) {
    if iterator.is_null() {
        return;
    }
    unsafe {
        let c_iterator_box = Box::from_raw(iterator);
        let _ = Box::from_raw(c_iterator_box.iterator);
        let _ = Box::from_raw(c_iterator_box.file_contents);
    }
}

//=============================================================================
// Data Accessors (The "Getter" API)
//=============================================================================

/// Extracts the core atomic data into a transparent `CFrame` struct.
/// The caller OWNS the returned pointer and MUST call `free_c_frame` on it.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_to_c_frame(frame_handle: *const RKRConFrame) -> *mut CFrame {
    let frame = match unsafe { (frame_handle as *const ConFrame).as_ref() } {
        Some(f) => f,
        None => return ptr::null_mut(),
    };

    let masses_iter = frame
        .header
        .natms_per_type
        .iter()
        .zip(frame.header.masses_per_type.iter())
        .flat_map(|(num_atoms, mass)| std::iter::repeat_n(*mass, *num_atoms));

    let has_velocities = frame.has_velocities();

    let mut c_atoms: Vec<CAtom> = frame
        .atom_data
        .iter()
        .zip(masses_iter)
        .map(|(atom_datum, mass)| CAtom {
            atomic_number: symbol_to_atomic_number(&atom_datum.symbol),
            x: atom_datum.x,
            y: atom_datum.y,
            z: atom_datum.z,
            is_fixed: atom_datum.is_fixed,
            atom_id: atom_datum.atom_id,
            mass,
            vx: atom_datum.vx.unwrap_or(0.0),
            vy: atom_datum.vy.unwrap_or(0.0),
            vz: atom_datum.vz.unwrap_or(0.0),
            has_velocity: atom_datum.has_velocity(),
        })
        .collect();

    let atoms_ptr = c_atoms.as_mut_ptr();
    let num_atoms = c_atoms.len();
    std::mem::forget(c_atoms);

    let c_frame = Box::new(CFrame {
        atoms: atoms_ptr,
        num_atoms,
        cell: frame.header.boxl,
        angles: frame.header.angles,
        has_velocities,
    });

    Box::into_raw(c_frame)
}

/// Frees the memory of a `CFrame` struct, including its internal atoms array.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn free_c_frame(frame: *mut CFrame) {
    if frame.is_null() {
        return;
    }
    unsafe {
        let frame_box = Box::from_raw(frame);
        let _ = Vec::from_raw_parts(frame_box.atoms, frame_box.num_atoms, frame_box.num_atoms);
    }
}

/// Copies a header string line into a user-provided buffer.
/// This is a C style helper... where the user explicitly sets the buffer.
/// Returns the number of bytes written (excluding null terminator), or -1 on error.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_get_header_line(
    frame_handle: *const RKRConFrame,
    is_prebox: bool,
    line_index: usize,
    buffer: *mut c_char,
    buffer_len: usize,
) -> i32 {
    let frame = match unsafe { (frame_handle as *const ConFrame).as_ref() } {
        Some(f) => f,
        None => return -1,
    };
    let line_to_copy = if is_prebox {
        frame.header.prebox_header.get(line_index)
    } else {
        frame.header.postbox_header.get(line_index)
    };
    if let Some(line) = line_to_copy {
        let bytes = line.as_bytes();
        let len_to_copy = std::cmp::min(bytes.len(), buffer_len - 1);
        unsafe {
            ptr::copy_nonoverlapping(bytes.as_ptr(), buffer as *mut u8, len_to_copy);
            *buffer.add(len_to_copy) = 0;
        }
        len_to_copy as i32
    } else {
        -1
    }
}

/// Gets a header string line as a newly allocated, null-terminated C string.
///
/// The caller OWNS the returned pointer and MUST call `rkr_free_string` on it
/// to prevent a memory leak. Returns NULL on error or if the index is invalid.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_get_header_line_cpp(
    frame_handle: *const RKRConFrame,
    is_prebox: bool,
    line_index: usize,
) -> *mut c_char {
    let frame = match unsafe { (frame_handle as *const ConFrame).as_ref() } {
        Some(f) => f,
        None => return ptr::null_mut(),
    };

    let line_to_copy = if is_prebox {
        frame.header.prebox_header.get(line_index)
    } else {
        frame.header.postbox_header.get(line_index)
    };

    if let Some(line) = line_to_copy {
        // Convert the Rust string slice to a C-compatible, heap-allocated string.
        match CString::new(line.as_str()) {
            Ok(c_string) => c_string.into_raw(), // Give ownership to the C caller
            Err(_) => ptr::null_mut(),           // In case the string contains a null byte
        }
    } else {
        ptr::null_mut() // Index out of bounds
    }
}

/// Frees a C string that was allocated by Rust (e.g., from `rkr_frame_get_header_line`).
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_free_string(s: *mut c_char) {
    if !s.is_null() {
        // Retake ownership of the CString to deallocate it properly.
        let _ = unsafe { CString::from_raw(s) };
    }
}

//=============================================================================
// FFI Writer Functions (Writer Object Model)
//=============================================================================

/// Creates a new frame writer for the specified file.
/// The caller OWNS the returned pointer and MUST call `free_rkr_writer`.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn create_writer_from_path_c(
    filename_c: *const c_char,
) -> *mut RKRConFrameWriter {
    if filename_c.is_null() {
        return ptr::null_mut();
    }
    let filename = match unsafe { CStr::from_ptr(filename_c).to_str() } {
        Ok(s) => s,
        Err(_) => return ptr::null_mut(),
    };
    match crate::writer::ConFrameWriter::from_path(filename) {
        Ok(writer) => Box::into_raw(Box::new(writer)) as *mut RKRConFrameWriter,
        Err(_) => ptr::null_mut(),
    }
}

/// Frees the memory for an `RKRConFrameWriter`, closing the associated file.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn free_rkr_writer(writer_handle: *mut RKRConFrameWriter) {
    if !writer_handle.is_null() {
        let _ = unsafe { Box::from_raw(writer_handle as *mut ConFrameWriter<File>) };
    }
}

/// Writes multiple frames from an array of handles to the file managed by the writer.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_writer_extend(
    writer_handle: *mut RKRConFrameWriter,
    frame_handles: *const *const RKRConFrame,
    num_frames: usize,
) -> i32 {
    let writer = match unsafe { (writer_handle as *mut ConFrameWriter<File>).as_mut() } {
        Some(w) => w,
        None => return -1,
    };
    if frame_handles.is_null() {
        return -1;
    }

    let handles_slice = unsafe { std::slice::from_raw_parts(frame_handles, num_frames) };
    let mut rust_frames: Vec<&ConFrame> = Vec::with_capacity(num_frames);
    if handles_slice.iter().any(|&handle| handle.is_null()) {
        // Fail fast if any handle is null, as this indicates a bug on the
        // caller's side.
        return -1;
    }
    for &handle in handles_slice.iter() {
        // Assume the handle is valid.
        match unsafe { (handle as *const ConFrame).as_ref() } {
            Some(frame) => rust_frames.push(frame),
            // This case should be unreachable if the handle is not null, but we handle it for safety.
            None => return -1,
        }
    }

    match writer.extend(rust_frames.into_iter()) {
        Ok(_) => 0,
        Err(_) => -1,
    }
}
