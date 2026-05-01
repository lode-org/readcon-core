use crate::helpers::symbol_to_atomic_number;
use crate::iterators::{self, ConFrameIterator};
use crate::types::{ConFrame, ConFrameBuilder};
use crate::writer::ConFrameWriter;
use std::ffi::{CStr, CString, c_char};
use std::fs::{self, File};
use std::path::Path;
use std::ptr;

//=============================================================================
// Version & Spec Constants (exported as #define by cbindgen)
//=============================================================================

/// CON/convel format spec version. Use `#if RKR_CON_SPEC_VERSION >= 2` in C/C++
/// to gate code that depends on atom_index semantics.
pub const RKR_CON_SPEC_VERSION: u32 = 2;

/// Returns the spec version at runtime (for dynamically linked consumers).
#[unsafe(no_mangle)]
pub extern "C" fn rkr_con_spec_version() -> u32 {
    crate::CON_SPEC_VERSION
}

/// Returns a pointer to a static, null-terminated library version string.
/// The returned pointer is valid for the lifetime of the process. Do NOT free it.
#[unsafe(no_mangle)]
pub extern "C" fn rkr_library_version() -> *const c_char {
    // concat! produces a &'static str with a trailing NUL byte
    const VERSION_NUL: &[u8] = concat!(env!("CARGO_PKG_VERSION"), "\0").as_bytes();
    VERSION_NUL.as_ptr() as *const c_char
}

/// Returns the spec version stored in a parsed frame's header.
/// Returns 0 on error (null handle).
#[unsafe(no_mangle)]
pub extern "C" fn rkr_frame_spec_version(frame_handle: *const RKRConFrame) -> u32 {
    match unsafe { (frame_handle as *const ConFrame).as_ref() } {
        Some(f) => f.header.spec_version,
        None => 0,
    }
}

/// Returns the JSON metadata line from a parsed frame as a heap-allocated
/// null-terminated C string. The caller MUST free with `rkr_free_string`.
/// Returns NULL on error.
///
/// # Safety
/// frame_handle must be valid. The caller takes ownership of the returned string.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_metadata_json(frame_handle: *const RKRConFrame) -> *mut c_char {
    let frame = match unsafe { (frame_handle as *const ConFrame).as_ref() } {
        Some(f) => f,
        None => return ptr::null_mut(),
    };
    let mut obj = serde_json::Map::new();
    obj.insert(
        "con_spec_version".to_string(),
        serde_json::Value::from(frame.header.spec_version),
    );
    for (k, v) in &frame.header.metadata {
        obj.insert(k.clone(), v.clone());
    }
    let json_str = serde_json::Value::Object(obj).to_string();
    match CString::new(json_str) {
        Ok(cs) => cs.into_raw(),
        Err(_) => ptr::null_mut(),
    }
}

/// Returns the per-frame energy from metadata, or NaN if absent.
#[unsafe(no_mangle)]
pub extern "C" fn rkr_frame_energy(frame_handle: *const RKRConFrame) -> f64 {
    match unsafe { (frame_handle as *const ConFrame).as_ref() } {
        Some(f) => f.header.energy().unwrap_or(f64::NAN),
        None => f64::NAN,
    }
}

/// Returns the potential type string from metadata as a heap-allocated
/// null-terminated C string. The caller MUST free with `rkr_free_string`.
/// Returns NULL if absent or on error.
///
/// # Safety
/// frame_handle must be valid. The caller takes ownership of the returned string.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_potential_type(frame_handle: *const RKRConFrame) -> *mut c_char {
    let frame = match unsafe { (frame_handle as *const ConFrame).as_ref() } {
        Some(f) => f,
        None => return ptr::null_mut(),
    };
    match frame.header.potential_type() {
        Some(pot_type) => match CString::new(pot_type) {
            Ok(cs) => cs.into_raw(),
            Err(_) => ptr::null_mut(),
        },
        None => ptr::null_mut(),
    }
}

/// Returns the zero-based frame index from metadata, or UINT64_MAX if absent.
#[unsafe(no_mangle)]
pub extern "C" fn rkr_frame_frame_index(frame_handle: *const RKRConFrame) -> u64 {
    match unsafe { (frame_handle as *const ConFrame).as_ref() } {
        Some(f) => f.header.frame_index().unwrap_or(u64::MAX),
        None => u64::MAX,
    }
}

/// Returns the simulation time from metadata, or NaN if absent.
#[unsafe(no_mangle)]
pub extern "C" fn rkr_frame_time(frame_handle: *const RKRConFrame) -> f64 {
    match unsafe { (frame_handle as *const ConFrame).as_ref() } {
        Some(f) => f.header.time().unwrap_or(f64::NAN),
        None => f64::NAN,
    }
}

/// Returns the integration timestep from metadata, or NaN if absent.
#[unsafe(no_mangle)]
pub extern "C" fn rkr_frame_timestep(frame_handle: *const RKRConFrame) -> f64 {
    match unsafe { (frame_handle as *const ConFrame).as_ref() } {
        Some(f) => f.header.timestep().unwrap_or(f64::NAN),
        None => f64::NAN,
    }
}

/// Returns the NEB bead index from metadata, or UINT64_MAX if absent.
#[unsafe(no_mangle)]
pub extern "C" fn rkr_frame_neb_bead(frame_handle: *const RKRConFrame) -> u64 {
    match unsafe { (frame_handle as *const ConFrame).as_ref() } {
        Some(f) => f.header.neb_bead().unwrap_or(u64::MAX),
        None => u64::MAX,
    }
}

/// Returns the NEB band index from metadata, or UINT64_MAX if absent.
#[unsafe(no_mangle)]
pub extern "C" fn rkr_frame_neb_band(frame_handle: *const RKRConFrame) -> u64 {
    match unsafe { (frame_handle as *const ConFrame).as_ref() } {
        Some(f) => f.header.neb_band().unwrap_or(u64::MAX),
        None => u64::MAX,
    }
}

//=============================================================================
// C-Compatible Structs & Handles
//=============================================================================

/// Error codes for RKR functions.
#[repr(C)]
#[allow(non_camel_case_types)]
#[derive(Debug, PartialEq, Eq)]
pub enum RKRStatus {
    /// Function completed successfully.
    RKR_STATUS_SUCCESS = 0,
    /// A null pointer was passed for a required argument.
    RKR_STATUS_NULL_POINTER = -1,
    /// An input string was not valid UTF-8.
    RKR_STATUS_INVALID_UTF8 = -2,
    /// JSON parsing or serialization failed.
    RKR_STATUS_INVALID_JSON = -3,
    /// File I/O error.
    RKR_STATUS_IO_ERROR = -4,
    /// Index out of bounds.
    RKR_STATUS_INDEX_OUT_OF_BOUNDS = -5,
    /// The destination buffer cannot hold a null-terminated string.
    RKR_STATUS_BUFFER_TOO_SMALL = -6,
    /// An internal logic error or unhandled state.
    RKR_STATUS_INTERNAL_ERROR = -7,
}

/// Returns a stable, static message for a status code.
/// The returned pointer is valid for the lifetime of the process. Do NOT free it.
#[unsafe(no_mangle)]
pub extern "C" fn rkr_status_message(status: RKRStatus) -> *const c_char {
    match status {
        RKRStatus::RKR_STATUS_SUCCESS => c"success".as_ptr(),
        RKRStatus::RKR_STATUS_NULL_POINTER => c"null pointer".as_ptr(),
        RKRStatus::RKR_STATUS_INVALID_UTF8 => c"invalid UTF-8".as_ptr(),
        RKRStatus::RKR_STATUS_INVALID_JSON => c"invalid JSON".as_ptr(),
        RKRStatus::RKR_STATUS_IO_ERROR => c"I/O error".as_ptr(),
        RKRStatus::RKR_STATUS_INDEX_OUT_OF_BOUNDS => c"index out of bounds".as_ptr(),
        RKRStatus::RKR_STATUS_BUFFER_TOO_SMALL => c"buffer too small".as_ptr(),
        RKRStatus::RKR_STATUS_INTERNAL_ERROR => c"internal error".as_ptr(),
    }
}

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
    pub has_forces: bool,
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
    pub fixed_x: bool,
    pub fixed_y: bool,
    pub fixed_z: bool,
    pub vx: f64,
    pub vy: f64,
    pub vz: f64,
    pub has_velocity: bool,
    pub fx: f64,
    pub fy: f64,
    pub fz: f64,
    pub has_forces: bool,
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
///
/// # Safety
/// filename_c must be valid. The caller takes ownership of the returned iterator.
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
///
/// # Safety
/// iterator must be valid. The caller takes ownership of the returned frame.
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
///
/// # Safety
/// frame_handle must be valid or null.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn free_rkr_frame(frame_handle: *mut RKRConFrame) {
    if !frame_handle.is_null() {
        let _ = unsafe { Box::from_raw(frame_handle as *mut ConFrame) };
    }
}

/// Frees the memory for a `CConFrameIterator`.
///
/// # Safety
/// iterator must be valid or null.
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
///
/// # Safety
/// frame_handle must be valid. The caller takes ownership of the returned CFrame.
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
            is_fixed: atom_datum.is_fixed(),
            fixed_x: atom_datum.fixed[0],
            fixed_y: atom_datum.fixed[1],
            fixed_z: atom_datum.fixed[2],
            atom_id: atom_datum.atom_id,
            mass,
            vx: atom_datum.vx.unwrap_or(0.0),
            vy: atom_datum.vy.unwrap_or(0.0),
            vz: atom_datum.vz.unwrap_or(0.0),
            has_velocity: atom_datum.has_velocity(),
            fx: atom_datum.fx.unwrap_or(0.0),
            fy: atom_datum.fy.unwrap_or(0.0),
            fz: atom_datum.fz.unwrap_or(0.0),
            has_forces: atom_datum.has_forces(),
        })
        .collect();

    let atoms_ptr = c_atoms.as_mut_ptr();
    let num_atoms = c_atoms.len();
    std::mem::forget(c_atoms);

    let has_forces = frame.has_forces();

    let c_frame = Box::new(CFrame {
        atoms: atoms_ptr,
        num_atoms,
        cell: frame.header.boxl,
        angles: frame.header.angles,
        has_velocities,
        has_forces,
    });

    Box::into_raw(c_frame)
}

/// Frees the memory of a `CFrame` struct, including its internal atoms array.
///
/// # Safety
/// frame must be valid or null.
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
/// Returns `RKR_STATUS_SUCCESS` on success, or an error code.
///
/// # Safety
/// frame_handle must be valid. buffer must be at least buffer_len bytes.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_get_header_line(
    frame_handle: *const RKRConFrame,
    is_prebox: bool,
    line_index: usize,
    buffer: *mut c_char,
    buffer_len: usize,
) -> RKRStatus {
    let frame = match unsafe { (frame_handle as *const ConFrame).as_ref() } {
        Some(f) => f,
        None => return RKRStatus::RKR_STATUS_NULL_POINTER,
    };
    if buffer.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    if buffer_len == 0 {
        return RKRStatus::RKR_STATUS_BUFFER_TOO_SMALL;
    }
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
        RKRStatus::RKR_STATUS_SUCCESS
    } else {
        RKRStatus::RKR_STATUS_INDEX_OUT_OF_BOUNDS
    }
}

/// Gets a header string line as a newly allocated, null-terminated C string.
///
/// The caller OWNS the returned pointer and MUST call `rkr_free_string` on it
/// to prevent a memory leak. Returns NULL on error or if the index is invalid.
///
/// # Safety
/// frame_handle must be valid. The caller takes ownership of the returned string.
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
///
/// # Safety
/// s must be valid or null.
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
///
/// # Safety
/// filename_c must be valid. The caller takes ownership of the returned writer.
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
///
/// # Safety
/// writer_handle must be valid or null.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn free_rkr_writer(writer_handle: *mut RKRConFrameWriter) {
    if !writer_handle.is_null() {
        let _ = unsafe { Box::from_raw(writer_handle as *mut ConFrameWriter<File>) };
    }
}

/// Writes multiple frames from an array of handles to the file managed by the writer.
/// Returns `RKR_STATUS_SUCCESS` on success, or an error code.
///
/// # Safety
/// writer_handle and frame_handles must be valid.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_writer_extend(
    writer_handle: *mut RKRConFrameWriter,
    frame_handles: *const *const RKRConFrame,
    num_frames: usize,
) -> RKRStatus {
    let writer = match unsafe { (writer_handle as *mut ConFrameWriter<File>).as_mut() } {
        Some(w) => w,
        None => return RKRStatus::RKR_STATUS_NULL_POINTER,
    };
    if frame_handles.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }

    let handles_slice = unsafe { std::slice::from_raw_parts(frame_handles, num_frames) };
    let mut rust_frames: Vec<&ConFrame> = Vec::with_capacity(num_frames);
    if handles_slice.iter().any(|&handle| handle.is_null()) {
        // Fail fast if any handle is null, as this indicates a bug on the
        // caller's side.
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    for &handle in handles_slice.iter() {
        // Assume the handle is valid.
        match unsafe { (handle as *const ConFrame).as_ref() } {
            Some(frame) => rust_frames.push(frame),
            // This case should be unreachable if the handle is not null, but we handle it for safety.
            None => return RKRStatus::RKR_STATUS_NULL_POINTER,
        }
    }

    match writer.extend(rust_frames.into_iter()) {
        Ok(_) => RKRStatus::RKR_STATUS_SUCCESS,
        Err(_) => RKRStatus::RKR_STATUS_IO_ERROR,
    }
}

//=============================================================================
// Writer with Precision
//=============================================================================

/// Creates a new frame writer with custom floating-point precision.
/// The caller OWNS the returned pointer and MUST call `free_rkr_writer`.
///
/// # Safety
/// filename_c must be valid. The caller takes ownership of the returned writer.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn create_writer_from_path_with_precision_c(
    filename_c: *const c_char,
    precision: u8,
) -> *mut RKRConFrameWriter {
    if filename_c.is_null() {
        return ptr::null_mut();
    }
    let filename = match unsafe { CStr::from_ptr(filename_c).to_str() } {
        Ok(s) => s,
        Err(_) => return ptr::null_mut(),
    };
    match ConFrameWriter::from_path_with_precision(filename, precision as usize) {
        Ok(writer) => Box::into_raw(Box::new(writer)) as *mut RKRConFrameWriter,
        Err(_) => ptr::null_mut(),
    }
}

//=============================================================================
// Frame Builder FFI (construct ConFrame from C data)
//=============================================================================

/// An opaque handle to a Rust `ConFrameBuilder` object.
#[repr(C)]
pub struct RKRConFrameBuilder {
    _private: [u8; 0],
}

unsafe fn add_builder_atom(
    builder_handle: *mut RKRConFrameBuilder,
    symbol: *const c_char,
    x: f64,
    y: f64,
    z: f64,
    fixed: [bool; 3],
    atom_id: u64,
    mass: f64,
    velocity: Option<[f64; 3]>,
    forces: Option<[f64; 3]>,
) -> RKRStatus {
    if builder_handle.is_null() || symbol.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let builder = unsafe { &mut *(builder_handle as *mut ConFrameBuilder) };
    let sym = match unsafe { CStr::from_ptr(symbol).to_str() } {
        Ok(s) => s,
        Err(_) => return RKRStatus::RKR_STATUS_INVALID_UTF8,
    };

    match (velocity, forces) {
        (None, None) => builder.add_atom(sym, x, y, z, fixed, atom_id, mass),
        (Some([vx, vy, vz]), None) => {
            builder.add_atom_with_velocity(sym, x, y, z, fixed, atom_id, mass, vx, vy, vz);
        }
        (None, Some([fx, fy, fz])) => {
            builder.add_atom_with_forces(sym, x, y, z, fixed, atom_id, mass, fx, fy, fz);
        }
        (Some([vx, vy, vz]), Some([fx, fy, fz])) => builder.add_atom_with_velocity_and_forces(
            sym, x, y, z, fixed, atom_id, mass, vx, vy, vz, fx, fy, fz,
        ),
    }

    RKRStatus::RKR_STATUS_SUCCESS
}

/// Creates a new frame builder with the given cell dimensions, angles, and header lines.
/// The caller OWNS the returned pointer and MUST call `free_rkr_frame_builder` or
/// `rkr_frame_builder_build`.
/// Returns NULL on error.
///
/// # Safety
/// cell and angles must point to 3 doubles. prebox0, prebox1, postbox0, postbox1 must be valid.
/// The caller takes ownership of the returned builder.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_new(
    cell: *const f64,
    angles: *const f64,
    prebox0: *const c_char,
    prebox1: *const c_char,
    postbox0: *const c_char,
    postbox1: *const c_char,
) -> *mut RKRConFrameBuilder {
    if cell.is_null() || angles.is_null() {
        return ptr::null_mut();
    }
    let cell_arr = unsafe { [*cell, *cell.add(1), *cell.add(2)] };
    let angles_arr = unsafe { [*angles, *angles.add(1), *angles.add(2)] };

    let get_str = |p: *const c_char| -> String {
        if p.is_null() {
            String::new()
        } else {
            unsafe { CStr::from_ptr(p) }
                .to_str()
                .unwrap_or("")
                .to_string()
        }
    };

    let builder = ConFrameBuilder::new(cell_arr, angles_arr)
        .prebox_header([get_str(prebox0), get_str(prebox1)])
        .postbox_header([get_str(postbox0), get_str(postbox1)]);

    Box::into_raw(Box::new(builder)) as *mut RKRConFrameBuilder
}

/// Parses and sets JSON metadata on an existing frame builder.
/// Returns `RKR_STATUS_SUCCESS` on success, or an error code.
///
/// # Safety
/// builder_handle and metadata_json must be valid.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_set_metadata_json(
    builder_handle: *mut RKRConFrameBuilder,
    metadata_json: *const c_char,
) -> RKRStatus {
    if builder_handle.is_null() || metadata_json.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let builder = unsafe { &mut *(builder_handle as *mut ConFrameBuilder) };
    let metadata_json = match unsafe { CStr::from_ptr(metadata_json).to_str() } {
        Ok(s) => s,
        Err(_) => return RKRStatus::RKR_STATUS_INVALID_UTF8,
    };
    match builder.set_metadata_json(metadata_json) {
        Ok(()) => RKRStatus::RKR_STATUS_SUCCESS,
        Err(_) => RKRStatus::RKR_STATUS_INVALID_JSON,
    }
}

/// Sets a numeric metadata key on an existing frame builder.
/// Returns `RKR_STATUS_SUCCESS` on success, or an error code.
///
/// # Safety
/// builder_handle and key must be valid.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_set_scalar_metadata(
    builder_handle: *mut RKRConFrameBuilder,
    key: *const c_char,
    value: f64,
) -> RKRStatus {
    if builder_handle.is_null() || key.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let builder = unsafe { &mut *(builder_handle as *mut ConFrameBuilder) };
    let key = match unsafe { CStr::from_ptr(key).to_str() } {
        Ok(s) => s,
        Err(_) => return RKRStatus::RKR_STATUS_INVALID_UTF8,
    };
    builder.set_scalar_metadata(key, value);
    RKRStatus::RKR_STATUS_SUCCESS
}

/// Sets a string metadata key on an existing frame builder.
/// Returns `RKR_STATUS_SUCCESS` on success, or an error code.
///
/// # Safety
/// builder_handle, key, and value must be valid.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_set_string_metadata(
    builder_handle: *mut RKRConFrameBuilder,
    key: *const c_char,
    value: *const c_char,
) -> RKRStatus {
    if builder_handle.is_null() || key.is_null() || value.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let builder = unsafe { &mut *(builder_handle as *mut ConFrameBuilder) };
    let key = match unsafe { CStr::from_ptr(key).to_str() } {
        Ok(s) => s,
        Err(_) => return RKRStatus::RKR_STATUS_INVALID_UTF8,
    };
    let value = match unsafe { CStr::from_ptr(value).to_str() } {
        Ok(s) => s,
        Err(_) => return RKRStatus::RKR_STATUS_INVALID_UTF8,
    };
    builder.set_string_metadata(key, value);
    RKRStatus::RKR_STATUS_SUCCESS
}

/// Sets the per-frame total energy metadata on an existing frame builder.
/// Returns `RKR_STATUS_SUCCESS` on success, or an error code.
///
/// # Safety
/// builder_handle must be valid.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_set_energy(
    builder_handle: *mut RKRConFrameBuilder,
    energy: f64,
) -> RKRStatus {
    if builder_handle.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let builder = unsafe { &mut *(builder_handle as *mut ConFrameBuilder) };
    builder.set_energy(energy);
    RKRStatus::RKR_STATUS_SUCCESS
}

/// Sets the zero-based frame index metadata on an existing frame builder.
/// Returns `RKR_STATUS_SUCCESS` on success, or an error code.
///
/// # Safety
/// builder_handle must be valid.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_set_frame_index(
    builder_handle: *mut RKRConFrameBuilder,
    idx: u64,
) -> RKRStatus {
    if builder_handle.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let builder = unsafe { &mut *(builder_handle as *mut ConFrameBuilder) };
    builder.set_frame_index(idx);
    RKRStatus::RKR_STATUS_SUCCESS
}

/// Sets the simulation time metadata on an existing frame builder.
/// Returns `RKR_STATUS_SUCCESS` on success, or an error code.
///
/// # Safety
/// builder_handle must be valid.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_set_time(
    builder_handle: *mut RKRConFrameBuilder,
    time: f64,
) -> RKRStatus {
    if builder_handle.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let builder = unsafe { &mut *(builder_handle as *mut ConFrameBuilder) };
    builder.set_time(time);
    RKRStatus::RKR_STATUS_SUCCESS
}

/// Sets the timestep metadata on an existing frame builder.
/// Returns `RKR_STATUS_SUCCESS` on success, or an error code.
///
/// # Safety
/// builder_handle must be valid.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_set_timestep(
    builder_handle: *mut RKRConFrameBuilder,
    dt: f64,
) -> RKRStatus {
    if builder_handle.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let builder = unsafe { &mut *(builder_handle as *mut ConFrameBuilder) };
    builder.set_timestep(dt);
    RKRStatus::RKR_STATUS_SUCCESS
}

/// Sets the NEB bead index metadata on an existing frame builder.
/// Returns `RKR_STATUS_SUCCESS` on success, or an error code.
///
/// # Safety
/// builder_handle must be valid.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_set_neb_bead(
    builder_handle: *mut RKRConFrameBuilder,
    bead: u64,
) -> RKRStatus {
    if builder_handle.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let builder = unsafe { &mut *(builder_handle as *mut ConFrameBuilder) };
    builder.set_neb_bead(bead);
    RKRStatus::RKR_STATUS_SUCCESS
}

/// Sets the NEB band index metadata on an existing frame builder.
/// Returns `RKR_STATUS_SUCCESS` on success, or an error code.
///
/// # Safety
/// builder_handle must be valid.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_set_neb_band(
    builder_handle: *mut RKRConFrameBuilder,
    band: u64,
) -> RKRStatus {
    if builder_handle.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let builder = unsafe { &mut *(builder_handle as *mut ConFrameBuilder) };
    builder.set_neb_band(band);
    RKRStatus::RKR_STATUS_SUCCESS
}

/// Adds an atom (without velocity) to the frame builder.
/// Returns `RKR_STATUS_SUCCESS` on success, or an error code.
///
/// # Safety
/// builder_handle and symbol must be valid.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_add_atom(
    builder_handle: *mut RKRConFrameBuilder,
    symbol: *const c_char,
    x: f64,
    y: f64,
    z: f64,
    is_fixed: bool,
    atom_id: u64,
    mass: f64,
) -> RKRStatus {
    unsafe {
        add_builder_atom(
            builder_handle,
            symbol,
            x,
            y,
            z,
            [is_fixed; 3],
            atom_id,
            mass,
            None,
            None,
        )
    }
}

/// Adds an atom (without velocity) to the frame builder using per-axis fixed flags.
/// Returns `RKR_STATUS_SUCCESS` on success, or an error code.
///
/// # Safety
/// builder_handle and symbol must be valid.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_add_atom_with_fixed_mask(
    builder_handle: *mut RKRConFrameBuilder,
    symbol: *const c_char,
    x: f64,
    y: f64,
    z: f64,
    fixed_x: bool,
    fixed_y: bool,
    fixed_z: bool,
    atom_id: u64,
    mass: f64,
) -> RKRStatus {
    unsafe {
        add_builder_atom(
            builder_handle,
            symbol,
            x,
            y,
            z,
            [fixed_x, fixed_y, fixed_z],
            atom_id,
            mass,
            None,
            None,
        )
    }
}

/// Adds an atom with velocity data to the frame builder.
/// Returns `RKR_STATUS_SUCCESS` on success, or an error code.
///
/// # Safety
/// builder_handle and symbol must be valid.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_add_atom_with_velocity(
    builder_handle: *mut RKRConFrameBuilder,
    symbol: *const c_char,
    x: f64,
    y: f64,
    z: f64,
    is_fixed: bool,
    atom_id: u64,
    mass: f64,
    vx: f64,
    vy: f64,
    vz: f64,
) -> RKRStatus {
    unsafe {
        add_builder_atom(
            builder_handle,
            symbol,
            x,
            y,
            z,
            [is_fixed; 3],
            atom_id,
            mass,
            Some([vx, vy, vz]),
            None,
        )
    }
}

/// Adds an atom with velocity data to the frame builder using per-axis fixed flags.
/// Returns `RKR_STATUS_SUCCESS` on success, or an error code.
///
/// # Safety
/// builder_handle and symbol must be valid.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_add_atom_with_velocity_fixed_mask(
    builder_handle: *mut RKRConFrameBuilder,
    symbol: *const c_char,
    x: f64,
    y: f64,
    z: f64,
    fixed_x: bool,
    fixed_y: bool,
    fixed_z: bool,
    atom_id: u64,
    mass: f64,
    vx: f64,
    vy: f64,
    vz: f64,
) -> RKRStatus {
    unsafe {
        add_builder_atom(
            builder_handle,
            symbol,
            x,
            y,
            z,
            [fixed_x, fixed_y, fixed_z],
            atom_id,
            mass,
            Some([vx, vy, vz]),
            None,
        )
    }
}

/// Adds an atom with force data to the frame builder.
/// Returns `RKR_STATUS_SUCCESS` on success, or an error code.
///
/// # Safety
/// builder_handle and symbol must be valid.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_add_atom_with_forces(
    builder_handle: *mut RKRConFrameBuilder,
    symbol: *const c_char,
    x: f64,
    y: f64,
    z: f64,
    is_fixed: bool,
    atom_id: u64,
    mass: f64,
    fx: f64,
    fy: f64,
    fz: f64,
) -> RKRStatus {
    unsafe {
        add_builder_atom(
            builder_handle,
            symbol,
            x,
            y,
            z,
            [is_fixed; 3],
            atom_id,
            mass,
            None,
            Some([fx, fy, fz]),
        )
    }
}

/// Adds an atom with force data to the frame builder using per-axis fixed flags.
/// Returns `RKR_STATUS_SUCCESS` on success, or an error code.
///
/// # Safety
/// builder_handle and symbol must be valid.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_add_atom_with_forces_fixed_mask(
    builder_handle: *mut RKRConFrameBuilder,
    symbol: *const c_char,
    x: f64,
    y: f64,
    z: f64,
    fixed_x: bool,
    fixed_y: bool,
    fixed_z: bool,
    atom_id: u64,
    mass: f64,
    fx: f64,
    fy: f64,
    fz: f64,
) -> RKRStatus {
    unsafe {
        add_builder_atom(
            builder_handle,
            symbol,
            x,
            y,
            z,
            [fixed_x, fixed_y, fixed_z],
            atom_id,
            mass,
            None,
            Some([fx, fy, fz]),
        )
    }
}

/// Adds an atom with velocity and force data to the frame builder.
/// Returns `RKR_STATUS_SUCCESS` on success, or an error code.
///
/// # Safety
/// builder_handle and symbol must be valid.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_add_atom_with_velocity_and_forces(
    builder_handle: *mut RKRConFrameBuilder,
    symbol: *const c_char,
    x: f64,
    y: f64,
    z: f64,
    is_fixed: bool,
    atom_id: u64,
    mass: f64,
    vx: f64,
    vy: f64,
    vz: f64,
    fx: f64,
    fy: f64,
    fz: f64,
) -> RKRStatus {
    unsafe {
        add_builder_atom(
            builder_handle,
            symbol,
            x,
            y,
            z,
            [is_fixed; 3],
            atom_id,
            mass,
            Some([vx, vy, vz]),
            Some([fx, fy, fz]),
        )
    }
}

/// Adds an atom with velocity and force data using per-axis fixed flags.
/// Returns `RKR_STATUS_SUCCESS` on success, or an error code.
///
/// # Safety
/// builder_handle and symbol must be valid.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_add_atom_with_velocity_and_forces_fixed_mask(
    builder_handle: *mut RKRConFrameBuilder,
    symbol: *const c_char,
    x: f64,
    y: f64,
    z: f64,
    fixed_x: bool,
    fixed_y: bool,
    fixed_z: bool,
    atom_id: u64,
    mass: f64,
    vx: f64,
    vy: f64,
    vz: f64,
    fx: f64,
    fy: f64,
    fz: f64,
) -> RKRStatus {
    unsafe {
        add_builder_atom(
            builder_handle,
            symbol,
            x,
            y,
            z,
            [fixed_x, fixed_y, fixed_z],
            atom_id,
            mass,
            Some([vx, vy, vz]),
            Some([fx, fy, fz]),
        )
    }
}

/// Consumes the builder and returns a finalized RKRConFrame handle.
/// The builder handle is invalidated after this call.
/// The caller OWNS the returned frame and MUST call `free_rkr_frame`.
/// Returns NULL on error.
///
/// # Safety
/// builder_handle must be valid. The caller takes ownership of the returned frame.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_build(
    builder_handle: *mut RKRConFrameBuilder,
) -> *mut RKRConFrame {
    if builder_handle.is_null() {
        return ptr::null_mut();
    }
    let builder = unsafe { *Box::from_raw(builder_handle as *mut ConFrameBuilder) };
    let frame = builder.build();
    Box::into_raw(Box::new(frame)) as *mut RKRConFrame
}

/// Frees a frame builder without building.
///
/// # Safety
/// builder_handle must be valid or null.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn free_rkr_frame_builder(builder_handle: *mut RKRConFrameBuilder) {
    if !builder_handle.is_null() {
        let _ = unsafe { Box::from_raw(builder_handle as *mut ConFrameBuilder) };
    }
}

/// Creates a new gzip-compressed frame writer for the specified file.
/// The caller OWNS the returned pointer and MUST call `free_rkr_writer`.
///
/// # Safety
/// filename_c must be valid. The caller takes ownership of the returned writer.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn create_writer_gzip_c(filename_c: *const c_char) -> *mut RKRConFrameWriter {
    if filename_c.is_null() {
        return ptr::null_mut();
    }
    let filename = match unsafe { CStr::from_ptr(filename_c).to_str() } {
        Ok(s) => s,
        Err(_) => return ptr::null_mut(),
    };
    match ConFrameWriter::from_path_gzip(filename) {
        Ok(writer) => Box::into_raw(Box::new(writer)) as *mut RKRConFrameWriter,
        Err(_) => ptr::null_mut(),
    }
}

//=============================================================================
// Direct mmap-based Reader FFI
//=============================================================================

/// Reads the first frame from a .con file.
/// Uses `read_to_string` for small files (< 64 KiB) and mmap for larger ones.
/// Stops after the first frame rather than parsing the entire file.
/// The caller OWNS the returned handle and MUST call `free_rkr_frame`.
/// Returns NULL on error.
///
/// # Safety
/// filename_c must be valid. The caller takes ownership of the returned frame.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_read_first_frame(filename_c: *const c_char) -> *mut RKRConFrame {
    if filename_c.is_null() {
        return ptr::null_mut();
    }
    let filename = match unsafe { CStr::from_ptr(filename_c).to_str() } {
        Ok(s) => s,
        Err(_) => return ptr::null_mut(),
    };
    match iterators::read_first_frame(Path::new(filename)) {
        Ok(frame) => Box::into_raw(Box::new(frame)) as *mut RKRConFrame,
        Err(_) => ptr::null_mut(),
    }
}

/// Reads all frames from a .con file using mmap.
/// Returns an array of frame handles and sets `num_frames` to the count.
/// The caller OWNS both the array and each frame handle.
/// Free frames with `free_rkr_frame` and the array with `free_rkr_frame_array`.
/// Returns NULL on error.
///
/// # Safety
/// filename_c and num_frames must be valid. The caller takes ownership of the returned handles and array.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_read_all_frames(
    filename_c: *const c_char,
    num_frames: *mut usize,
) -> *mut *mut RKRConFrame {
    if filename_c.is_null() || num_frames.is_null() {
        return ptr::null_mut();
    }
    let filename = match unsafe { CStr::from_ptr(filename_c).to_str() } {
        Ok(s) => s,
        Err(_) => return ptr::null_mut(),
    };
    match iterators::read_all_frames(Path::new(filename)) {
        Ok(frames) => {
            let count = frames.len();
            let mut handles: Vec<*mut RKRConFrame> = frames
                .into_iter()
                .map(|f| Box::into_raw(Box::new(f)) as *mut RKRConFrame)
                .collect();
            let ptr = handles.as_mut_ptr();
            std::mem::forget(handles);
            unsafe { *num_frames = count };
            ptr
        }
        Err(_) => ptr::null_mut(),
    }
}

/// Frees an array of frame handles returned by `rkr_read_all_frames`.
/// Each frame is freed individually, then the array itself.
///
/// # Safety
/// frames must be valid or null.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn free_rkr_frame_array(frames: *mut *mut RKRConFrame, num_frames: usize) {
    if frames.is_null() {
        return;
    }
    unsafe {
        let handles = Vec::from_raw_parts(frames, num_frames, num_frames);
        for handle in handles {
            if !handle.is_null() {
                let _ = Box::from_raw(handle as *mut ConFrame);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::ffi::{CStr, CString};

    fn test_frame_handle() -> *mut RKRConFrame {
        let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0])
            .prebox_header(["Generated by test".to_string(), "Metadata".to_string()])
            .postbox_header(["0 0".to_string(), "0 0 0".to_string()]);
        builder.add_atom("Cu", 0.0, 0.0, 0.0, [false, false, false], 0, 63.546);
        Box::into_raw(Box::new(builder.build())) as *mut RKRConFrame
    }

    #[test]
    fn header_line_rejects_null_buffer() {
        let frame = test_frame_handle();
        let status = unsafe { rkr_frame_get_header_line(frame, true, 0, std::ptr::null_mut(), 16) };
        unsafe { free_rkr_frame(frame) };

        assert_eq!(status, RKRStatus::RKR_STATUS_NULL_POINTER);
    }

    #[test]
    fn header_line_rejects_empty_buffer() {
        let frame = test_frame_handle();
        let mut buffer = [0 as c_char; 1];
        let status = unsafe { rkr_frame_get_header_line(frame, true, 0, buffer.as_mut_ptr(), 0) };
        unsafe { free_rkr_frame(frame) };

        assert_eq!(status, RKRStatus::RKR_STATUS_BUFFER_TOO_SMALL);
    }

    #[test]
    fn header_line_truncates_and_terminates_buffer() {
        let frame = test_frame_handle();
        let mut buffer = [0 as c_char; 10];
        let status =
            unsafe { rkr_frame_get_header_line(frame, true, 0, buffer.as_mut_ptr(), buffer.len()) };
        unsafe { free_rkr_frame(frame) };

        assert_eq!(status, RKRStatus::RKR_STATUS_SUCCESS);
        let copied = unsafe { CStr::from_ptr(buffer.as_ptr()) };
        assert_eq!(copied.to_str().unwrap(), "Generated");
    }

    fn test_builder_handle() -> *mut RKRConFrameBuilder {
        let cell = [10.0, 11.0, 12.0];
        let angles = [90.0, 91.0, 92.0];
        unsafe {
            rkr_frame_new(
                cell.as_ptr(),
                angles.as_ptr(),
                ptr::null(),
                ptr::null(),
                ptr::null(),
                ptr::null(),
            )
        }
    }

    fn c_string(s: &str) -> CString {
        CString::new(s).unwrap()
    }

    unsafe fn assert_single_atom(
        frame: *mut RKRConFrame,
        fixed: [bool; 3],
        velocity: Option<[f64; 3]>,
        forces: Option<[f64; 3]>,
    ) {
        let c_frame = unsafe { rkr_frame_to_c_frame(frame) };
        assert!(!c_frame.is_null());
        let c_frame_ref = unsafe { &*c_frame };
        assert_eq!(c_frame_ref.num_atoms, 1);
        assert_eq!(c_frame_ref.has_velocities, velocity.is_some());
        assert_eq!(c_frame_ref.has_forces, forces.is_some());

        let atom = unsafe { &*c_frame_ref.atoms };
        assert_eq!(atom.fixed_x, fixed[0]);
        assert_eq!(atom.fixed_y, fixed[1]);
        assert_eq!(atom.fixed_z, fixed[2]);
        assert_eq!(atom.is_fixed, fixed.iter().any(|&value| value));
        assert_eq!(atom.has_velocity, velocity.is_some());
        assert_eq!(atom.has_forces, forces.is_some());
        if let Some([vx, vy, vz]) = velocity {
            assert_eq!([atom.vx, atom.vy, atom.vz], [vx, vy, vz]);
        }
        if let Some([fx, fy, fz]) = forces {
            assert_eq!([atom.fx, atom.fy, atom.fz], [fx, fy, fz]);
        }

        unsafe { free_c_frame(c_frame) };
        unsafe { free_rkr_frame(frame) };
    }

    #[test]
    fn builder_preserves_fixed_mask_for_atom_without_velocity_or_forces() {
        let builder = test_builder_handle();
        let symbol = c_string("Cu");

        let status = unsafe {
            rkr_frame_add_atom_with_fixed_mask(
                builder,
                symbol.as_ptr(),
                1.0,
                2.0,
                3.0,
                true,
                false,
                true,
                7,
                63.546,
            )
        };
        assert_eq!(status, RKRStatus::RKR_STATUS_SUCCESS);

        let frame = unsafe { rkr_frame_builder_build(builder) };
        unsafe { assert_single_atom(frame, [true, false, true], None, None) };
    }

    #[test]
    fn builder_preserves_fixed_mask_for_atom_with_velocity() {
        let builder = test_builder_handle();
        let symbol = c_string("H");

        let status = unsafe {
            rkr_frame_add_atom_with_velocity_fixed_mask(
                builder,
                symbol.as_ptr(),
                1.0,
                2.0,
                3.0,
                false,
                true,
                false,
                9,
                1.008,
                0.1,
                0.2,
                0.3,
            )
        };
        assert_eq!(status, RKRStatus::RKR_STATUS_SUCCESS);

        let frame = unsafe { rkr_frame_builder_build(builder) };
        unsafe { assert_single_atom(frame, [false, true, false], Some([0.1, 0.2, 0.3]), None) };
    }

    #[test]
    fn builder_preserves_fixed_mask_for_atom_with_forces() {
        let builder = test_builder_handle();
        let symbol = c_string("O");

        let status = unsafe {
            rkr_frame_add_atom_with_forces_fixed_mask(
                builder,
                symbol.as_ptr(),
                1.0,
                2.0,
                3.0,
                true,
                true,
                false,
                11,
                15.999,
                -0.1,
                -0.2,
                -0.3,
            )
        };
        assert_eq!(status, RKRStatus::RKR_STATUS_SUCCESS);

        let frame = unsafe { rkr_frame_builder_build(builder) };
        unsafe { assert_single_atom(frame, [true, true, false], None, Some([-0.1, -0.2, -0.3])) };
    }

    #[test]
    fn builder_preserves_fixed_mask_for_atom_with_velocity_and_forces() {
        let builder = test_builder_handle();
        let symbol = c_string("N");

        let status = unsafe {
            rkr_frame_add_atom_with_velocity_and_forces_fixed_mask(
                builder,
                symbol.as_ptr(),
                1.0,
                2.0,
                3.0,
                false,
                true,
                true,
                13,
                14.007,
                0.4,
                0.5,
                0.6,
                -0.4,
                -0.5,
                -0.6,
            )
        };
        assert_eq!(status, RKRStatus::RKR_STATUS_SUCCESS);

        let frame = unsafe { rkr_frame_builder_build(builder) };
        unsafe {
            assert_single_atom(
                frame,
                [false, true, true],
                Some([0.4, 0.5, 0.6]),
                Some([-0.4, -0.5, -0.6]),
            )
        };
    }

    #[test]
    fn builder_bool_fixed_functions_set_all_axes_together() {
        let builder = test_builder_handle();
        let cu = c_string("Cu");
        let h = c_string("H");

        let atom_status =
            unsafe { rkr_frame_add_atom(builder, cu.as_ptr(), 1.0, 2.0, 3.0, true, 1, 63.546) };
        assert_eq!(atom_status, RKRStatus::RKR_STATUS_SUCCESS);

        let velocity_status = unsafe {
            rkr_frame_add_atom_with_velocity(
                builder,
                h.as_ptr(),
                4.0,
                5.0,
                6.0,
                false,
                2,
                1.008,
                0.7,
                0.8,
                0.9,
            )
        };
        assert_eq!(velocity_status, RKRStatus::RKR_STATUS_SUCCESS);

        let frame = unsafe { rkr_frame_builder_build(builder) };
        let c_frame = unsafe { rkr_frame_to_c_frame(frame) };
        assert!(!c_frame.is_null());
        let c_frame_ref = unsafe { &*c_frame };
        assert_eq!(c_frame_ref.num_atoms, 2);

        let atoms = unsafe { std::slice::from_raw_parts(c_frame_ref.atoms, c_frame_ref.num_atoms) };
        assert_eq!(
            [atoms[0].fixed_x, atoms[0].fixed_y, atoms[0].fixed_z],
            [true, true, true]
        );
        assert_eq!(
            [atoms[1].fixed_x, atoms[1].fixed_y, atoms[1].fixed_z],
            [false, false, false]
        );

        unsafe { free_c_frame(c_frame) };
        unsafe { free_rkr_frame(frame) };
    }

    #[test]
    fn status_message_returns_static_strings_for_all_status_values() {
        let cases = [
            (RKRStatus::RKR_STATUS_SUCCESS, "success"),
            (RKRStatus::RKR_STATUS_NULL_POINTER, "null pointer"),
            (RKRStatus::RKR_STATUS_INVALID_UTF8, "invalid UTF-8"),
            (RKRStatus::RKR_STATUS_INVALID_JSON, "invalid JSON"),
            (RKRStatus::RKR_STATUS_IO_ERROR, "I/O error"),
            (
                RKRStatus::RKR_STATUS_INDEX_OUT_OF_BOUNDS,
                "index out of bounds",
            ),
            (RKRStatus::RKR_STATUS_BUFFER_TOO_SMALL, "buffer too small"),
            (RKRStatus::RKR_STATUS_INTERNAL_ERROR, "internal error"),
        ];

        for (status, expected) in cases {
            let message = unsafe { CStr::from_ptr(rkr_status_message(status)) };
            assert_eq!(message.to_str().unwrap(), expected);
        }
    }
}
