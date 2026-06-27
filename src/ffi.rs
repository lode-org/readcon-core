use crate::helpers::symbol_to_atomic_number;
use crate::iterators::{self, ConFrameIterator};
use crate::types::{ConFrame, ConFrameBuilder, meta};
use crate::writer::ConFrameWriter;
use std::ffi::{CStr, CString, c_char};
use std::fs::File;
use std::path::Path;
use std::ptr;
//=============================================================================
// Version & Spec Constants (exported as #define by cbindgen)
//=============================================================================
/// CON/convel format spec version. Use `#if RKR_CON_SPEC_VERSION >= 2` in C/C++
/// to gate code that depends on atom_index semantics.
///
/// Tracks `crate::CON_SPEC_VERSION` (which the Rust API exposes as
/// `CON_SPEC_VERSION`). Both macros are emitted into the C header for
/// the convenience of either naming convention; they always carry the
/// same value.
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
/// Returns the position of an atom inside the frame's `atom_data` array
/// matching the given `atom_id`. Returns `UINT64_MAX` if no atom with
/// that id exists or `frame_handle` is NULL.
///
/// O(N) per call. C/C++ consumers performing many lookups should cache
/// a `std::unordered_map<uint64_t, size_t>` from a single sweep over
/// the frame.
///
/// # Safety
///
/// `frame_handle` must point to a valid `RKRConFrame` allocation.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_atom_index_by_id(
    frame_handle: *const RKRConFrame,
    atom_id: u64,
) -> u64 {
    let frame = match unsafe { (frame_handle as *const ConFrame).as_ref() } {
        Some(f) => f,
        None => return u64::MAX,
    };
    match frame.atom_index_by_id(atom_id) {
        Some(idx) => idx as u64,
        None => u64::MAX,
    }
}
/// Returns the atomic number for a chemical symbol, or 0 if the symbol
/// is unknown or `symbol` is NULL. Lookup covers H..U (Z = 1..=92) and
/// is case-sensitive: "Fe" works, "fe" does not.
///
/// # Safety
///
/// `symbol` must be either NULL or a pointer to a NUL-terminated UTF-8
/// C string valid for reads up to the terminating NUL byte.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_symbol_to_z(symbol: *const c_char) -> u64 {
    if symbol.is_null() {
        return 0;
    }
    match unsafe { CStr::from_ptr(symbol) }.to_str() {
        Ok(s) => symbol_to_atomic_number(s),
        Err(_) => 0,
    }
}
/// Returns a pointer to a static, NUL-terminated chemical symbol for an
/// atomic number, or "X" for unknown values. Coverage is H..U
/// (Z = 1..=92). The returned pointer is valid for the lifetime of the
/// process; do NOT free it.
#[unsafe(no_mangle)]
pub extern "C" fn rkr_z_to_symbol(z: u64) -> *const c_char {
    // The static &str returned by helpers::atomic_number_to_symbol is
    // not NUL-terminated, so the FFI mirrors the table with literals
    // that have a trailing NUL. Index 0 holds "X" for unknown Z; indices
    // 1..=92 hold H..U in order.
    macro_rules! cstrs {
        ($($lit:literal),* $(,)?) => {
            [$(concat!($lit, "\0").as_bytes()),*]
        };
    }
    const TABLE: [&[u8]; 93] = cstrs![
        "X", "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne", "Na", "Mg", "Al", "Si", "P",
        "S", "Cl", "Ar", "K", "Ca", "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
        "Ga", "Ge", "As", "Se", "Br", "Kr", "Rb", "Sr", "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh",
        "Pd", "Ag", "Cd", "In", "Sn", "Sb", "Te", "I", "Xe", "Cs", "Ba", "La", "Ce", "Pr", "Nd",
        "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu", "Hf", "Ta", "W", "Re",
        "Os", "Ir", "Pt", "Au", "Hg", "Tl", "Pb", "Bi", "Po", "At", "Rn", "Fr", "Ra", "Ac", "Th",
        "Pa", "U",
    ];
    let idx = if (1..=92).contains(&z) { z as usize } else { 0 };
    TABLE[idx].as_ptr() as *const c_char
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
        meta::CON_SPEC_VERSION.into(),
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
    /// An optional section (velocities, forces, atom_energies) was
    /// requested but is not declared on the builder.
    RKR_STATUS_SECTION_ABSENT = -8,
    /// DLPack export or another validation step failed.
    RKR_STATUS_VALIDATION_ERROR = -9,
    /// Chemfiles selection parse/evaluate failed (requires chemfiles-enabled build).
    RKR_STATUS_SELECTION_ERROR = -10,
    /// Requested API is not in this build (Cargo feature off / symbols omitted).
    /// Never use `-7` for this — that is [`RKR_STATUS_INTERNAL_ERROR`].
    RKR_STATUS_FEATURE_DISABLED = -11,
}
/// Number of optional frame topology bonds (`metadata["bonds"]`), or 0 if absent.
///
/// # Safety
/// `frame_handle` must be a valid handle or NULL.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_bond_count(frame_handle: *const RKRConFrame) -> u64 {
    match unsafe { (frame_handle as *const ConFrame).as_ref() } {
        Some(f) => f.bonds().len() as u64,
        None => 0,
    }
}
/// Read one bond at `index` (0-based into the `bonds` metadata array).
///
/// Writes 0-based `atom_data` indices into `out_i` / `out_j`. When the bond
/// has an explicit order, sets `out_has_order` to 1 and `out_order` to that
/// integer; otherwise `out_has_order` is 0.
///
/// # Safety
/// `frame_handle` must be valid. Output pointers must be non-null.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_bond_at(
    frame_handle: *const RKRConFrame,
    index: u64,
    out_i: *mut u32,
    out_j: *mut u32,
    out_has_order: *mut u8,
    out_order: *mut i32,
) -> RKRStatus {
    if frame_handle.is_null()
        || out_i.is_null()
        || out_j.is_null()
        || out_has_order.is_null()
        || out_order.is_null()
    {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let Some(frame) = (unsafe { (frame_handle as *const ConFrame).as_ref() }) else {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    };
    let bonds = frame.bonds();
    let Some(bond) = bonds.get(index as usize) else {
        return RKRStatus::RKR_STATUS_INDEX_OUT_OF_BOUNDS;
    };
    unsafe {
        *out_i = bond.i;
        *out_j = bond.j;
        if let Some(order) = bond.order {
            *out_has_order = 1;
            *out_order = order;
        } else {
            *out_has_order = 0;
            *out_order = 0;
        }
    }
    RKRStatus::RKR_STATUS_SUCCESS
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
        RKRStatus::RKR_STATUS_SECTION_ABSENT => c"section absent".as_ptr(),
        RKRStatus::RKR_STATUS_VALIDATION_ERROR => c"validation error".as_ptr(),
        RKRStatus::RKR_STATUS_SELECTION_ERROR => c"selection error".as_ptr(),
        RKRStatus::RKR_STATUS_FEATURE_DISABLED => c"feature disabled in this build".as_ptr(),
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
    pub has_energies: bool,
}
/// Transparent atom record extracted via [`rkr_frame_to_c_frame`].
///
/// `is_fixed` is the OR of `fixed_x`, `fixed_y`, `fixed_z`; it is kept
/// for source compatibility with pre-spec-v2 callers that did not have
/// per-axis flags. New code should use the per-axis fields.
///
/// `vx`/`vy`/`vz`, `fx`/`fy`/`fz`, and `energy` carry meaningful values
/// only when `has_velocity`, `has_forces`, or `has_energy` is true
/// respectively; the values are zeroed otherwise.
#[repr(C)]
pub struct CAtom {
    pub atomic_number: u64,
    pub x: f64,
    pub y: f64,
    pub z: f64,
    pub atom_id: u64,
    pub mass: f64,
    /// True when any of `fixed_x`, `fixed_y`, `fixed_z` is true.
    /// Kept for source compatibility; prefer the per-axis fields.
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
    /// Per-atom energy contribution; meaningful only when
    /// `has_energy` is true. See [`crate::types::SECTION_ENERGIES`].
    pub energy: f64,
    pub has_energy: bool,
}
#[repr(C)]
pub struct CConFrameIterator {
    iterator: *mut ConFrameIterator<'static>,
    file_contents: *mut String,
}

/// Build a path/buffer-backed C iterator from an owned CON text buffer.
fn c_iterator_from_owned_string(contents: String) -> *mut CConFrameIterator {
    let file_contents_box = Box::new(contents);
    let file_contents_ptr = Box::into_raw(file_contents_box);
    let static_file_contents: &'static str = unsafe { &*file_contents_ptr };
    let iterator = Box::new(ConFrameIterator::new(static_file_contents));
    let c_iterator = Box::new(CConFrameIterator {
        iterator: Box::into_raw(iterator),
        file_contents: file_contents_ptr,
    });
    Box::into_raw(c_iterator)
}

//=============================================================================
// Iterator and Memory Management
//=============================================================================
/// Creates a new iterator for a .con / .convel path, including transparent
/// gzip (`.con.gz`) and zstd (`.con.zst`, requires `zstd` feature) inputs via
/// [`crate::compression::read_file_contents`].
///
/// Returns NULL if the file cannot be read, decompressed, or is not valid
/// UTF-8. A successfully-opened file with zero frames returns a non-NULL
/// iterator that yields NULL on the first call to [`con_frame_iterator_next`].
/// The caller OWNS the returned pointer and MUST call [`free_con_frame_iterator`].
///
/// # Safety
/// filename_c must be a valid null-terminated string. The caller takes
/// ownership of the returned iterator.
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
    let owned = match crate::compression::read_file_contents(Path::new(filename)) {
        Ok(fc) => match fc.as_str() {
            Ok(s) => s.to_owned(),
            Err(_) => return ptr::null_mut(),
        },
        Err(_) => return ptr::null_mut(),
    };
    c_iterator_from_owned_string(owned)
}

/// Iterate frames from an in-memory CON text buffer (null-terminated C string).
///
/// Use when the caller already decompressed (chemfiles, custom I/O) and wants
/// to avoid a temp file. Same ownership rules as [`read_con_file_iterator`].
///
/// # Safety
/// `contents_c` must be a valid null-terminated UTF-8 string, or NULL (returns NULL).
#[unsafe(no_mangle)]
pub unsafe extern "C" fn read_con_string_iterator(
    contents_c: *const c_char,
) -> *mut CConFrameIterator {
    if contents_c.is_null() {
        return ptr::null_mut();
    }
    let contents = match unsafe { CStr::from_ptr(contents_c).to_str() } {
        Ok(s) => s.to_owned(),
        Err(_) => return ptr::null_mut(),
    };
    c_iterator_from_owned_string(contents)
}

/// Iterate frames from a byte buffer (not necessarily null-terminated).
///
/// `len` is the number of bytes at `data`. Bytes must be valid UTF-8 CON text.
///
/// # Safety
/// `data` must be valid for `len` bytes if non-null and `len > 0`.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn read_con_buffer_iterator(
    data: *const u8,
    len: usize,
) -> *mut CConFrameIterator {
    if data.is_null() && len > 0 {
        return ptr::null_mut();
    }
    if len == 0 {
        return c_iterator_from_owned_string(String::new());
    }
    let slice = unsafe { std::slice::from_raw_parts(data, len) };
    let contents = match std::str::from_utf8(slice) {
        Ok(s) => s.to_owned(),
        Err(_) => return ptr::null_mut(),
    };
    c_iterator_from_owned_string(contents)
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
        .map(|(atom_datum, mass)| {
            let [vx, vy, vz] = atom_datum.velocity.unwrap_or([0.0; 3]);
            let [fx, fy, fz] = atom_datum.force.unwrap_or([0.0; 3]);
            CAtom {
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
                vx,
                vy,
                vz,
                has_velocity: atom_datum.has_velocity(),
                fx,
                fy,
                fz,
                has_forces: atom_datum.has_forces(),
                energy: atom_datum.energy.unwrap_or(0.0),
                has_energy: atom_datum.has_energy(),
            }
        })
        .collect();
    let atoms_ptr = c_atoms.as_mut_ptr();
    let num_atoms = c_atoms.len();
    std::mem::forget(c_atoms);
    let has_forces = frame.has_forces();
    let has_energies = frame.has_energies();
    let c_frame = Box::new(CFrame {
        atoms: atoms_ptr,
        num_atoms,
        cell: frame.header.boxl,
        angles: frame.header.angles,
        has_velocities,
        has_forces,
        has_energies,
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
/// Copies a header string line into a caller-provided buffer.
///
/// `is_prebox=true` selects from the two prebox lines (line 0 = user
/// text, line 1 = JSON metadata); `false` selects from the two postbox
/// lines. Strings longer than `buffer_len - 1` bytes are truncated; the
/// final byte is always set to NUL.
///
/// Returns `RKR_STATUS_SUCCESS` on success,
/// `RKR_STATUS_INDEX_OUT_OF_BOUNDS` if `line_index >= 2`,
/// `RKR_STATUS_NULL_POINTER` if `frame_handle` or `buffer` is NULL,
/// `RKR_STATUS_BUFFER_TOO_SMALL` if `buffer_len == 0`.
///
/// Pair with [`rkr_frame_get_header_line_cpp`] when the caller prefers
/// an allocated string with no fixed length cap; that variant returns
/// NULL for the same out-of-bounds condition.
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
    let line_to_copy: Option<&str> = if is_prebox {
        match line_index {
            0 => Some(frame.header.prebox_header.user.as_str()),
            1 => Some(frame.header.prebox_header.metadata_line()),
            _ => None,
        }
    } else {
        frame.header.postbox_header.get(line_index).map(String::as_str)
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
/// The caller OWNS the returned pointer and MUST call `rkr_free_string`
/// on it to prevent a memory leak. Returns NULL on error or if the
/// index is invalid (use [`rkr_frame_get_header_line`] when a status
/// code is preferred to NULL-vs-success disambiguation).
///
/// The `_cpp` suffix is historical; the function is callable from both
/// C and C++.
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
    let line_to_copy: Option<&str> = if is_prebox {
        match line_index {
            0 => Some(frame.header.prebox_header.user.as_str()),
            1 => Some(frame.header.prebox_header.metadata_line()),
            _ => None,
        }
    } else {
        frame.header.postbox_header.get(line_index).map(String::as_str)
    };
    if let Some(line) = line_to_copy {
        // Convert the Rust string slice to a C-compatible, heap-allocated string.
        match CString::new(line) {
            Ok(c_string) => c_string.into_raw(), // Give ownership to the C caller
            Err(_) => ptr::null_mut(),           // In case the string contains a null byte
        }
    } else {
        ptr::null_mut() // Index out of bounds
    }
}
/// Frees a C string that was allocated by Rust (e.g., from
/// `rkr_frame_metadata_json`, `rkr_frame_potential_type`, or
/// `rkr_frame_get_header_line_cpp`). Safe to call with NULL (no-op).
///
/// # Safety
/// s must be either NULL or a pointer previously returned by an
/// allocating Rust FFI function in this crate.
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
/// Type-erased writer that backs every `RKRConFrameWriter` handle.
///
/// `ConFrameWriter<W>` is generic over its sink, so a plain `File`, a
/// gzip `GzEncoder<File>`, and a zstd encoder all monomorphise to
/// distinct, layout-incompatible types. Boxing the sink as
/// `Box<dyn Write>` collapses them to a single concrete handle type, so
/// `free_rkr_writer` and `rkr_writer_extend` can cast the opaque pointer
/// to exactly one type regardless of the compression chosen at
/// construction. Dropping the box flushes the `BufWriter` and then runs
/// the sink's own `Drop` (gzip/zstd finalize their streams there).
type RkrWriter = ConFrameWriter<Box<dyn std::io::Write>>;
/// Boxes a sink into an `RKRConFrameWriter` handle at the requested
/// precision. `precision == None` selects the writer's built-in default.
#[inline]
fn into_rkr_writer(
    sink: Box<dyn std::io::Write>,
    precision: Option<u8>,
) -> *mut RKRConFrameWriter {
    let writer: RkrWriter = match precision {
        Some(p) => ConFrameWriter::with_precision(sink, p as usize),
        None => ConFrameWriter::new(sink),
    };
    Box::into_raw(Box::new(writer)) as *mut RKRConFrameWriter
}
/// Parses a borrowed C string, returning `None` for null or non-UTF-8.
#[inline]
unsafe fn cstr_path<'a>(filename_c: *const c_char) -> Option<&'a str> {
    if filename_c.is_null() {
        return None;
    }
    unsafe { CStr::from_ptr(filename_c).to_str().ok() }
}
/// Creates a new frame writer for the specified file.
/// The caller OWNS the returned pointer and MUST call `free_rkr_writer`.
///
/// # Safety
/// filename_c must be valid. The caller takes ownership of the returned writer.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn create_writer_from_path_c(
    filename_c: *const c_char,
) -> *mut RKRConFrameWriter {
    let filename = match unsafe { cstr_path(filename_c) } {
        Some(s) => s,
        None => return ptr::null_mut(),
    };
    match File::create(filename) {
        Ok(file) => into_rkr_writer(Box::new(file), None),
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
        let _ = unsafe { Box::from_raw(writer_handle as *mut RkrWriter) };
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
    let writer = match unsafe { (writer_handle as *mut RkrWriter).as_mut() } {
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
    let filename = match unsafe { cstr_path(filename_c) } {
        Some(s) => s,
        None => return ptr::null_mut(),
    };
    match File::create(filename) {
        Ok(file) => into_rkr_writer(Box::new(file), Some(precision)),
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
#[allow(clippy::too_many_arguments)]
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
    builder.add_atom(sym, x, y, z, fixed, atom_id, mass);
    if let Some(v) = velocity {
        builder.with_velocity(v);
    }
    if let Some(f) = forces {
        builder.with_force(f);
    }
    RKRStatus::RKR_STATUS_SUCCESS
}
/// Attaches a velocity vector to the most recently added atom on a builder.
/// No-op if no atom has been added yet.
///
/// # Safety
/// builder_handle must be valid. velocity must point to 3 contiguous f64 values.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_set_last_velocity(
    builder_handle: *mut RKRConFrameBuilder,
    velocity: *const f64,
) -> RKRStatus {
    if builder_handle.is_null() || velocity.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let builder = unsafe { &mut *(builder_handle as *mut ConFrameBuilder) };
    let v = unsafe { [*velocity, *velocity.add(1), *velocity.add(2)] };
    builder.with_velocity(v);
    RKRStatus::RKR_STATUS_SUCCESS
}
/// Attaches a force vector to the most recently added atom on a builder.
/// No-op if no atom has been added yet.
///
/// # Safety
/// builder_handle must be valid. force must point to 3 contiguous f64 values.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_set_last_force(
    builder_handle: *mut RKRConFrameBuilder,
    force: *const f64,
) -> RKRStatus {
    if builder_handle.is_null() || force.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let builder = unsafe { &mut *(builder_handle as *mut ConFrameBuilder) };
    let f = unsafe { [*force, *force.add(1), *force.add(2)] };
    builder.with_force(f);
    RKRStatus::RKR_STATUS_SUCCESS
}
/// Attaches a per-atom energy to the most recently added atom on a
/// builder. No-op if no atom has been added yet.
///
/// Use this together with the per-frame `energy` metadata key when a
/// caller wants to round-trip an "Energies of Component" decomposition
/// alongside the total.
///
/// # Safety
/// builder_handle must be valid.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_set_last_energy(
    builder_handle: *mut RKRConFrameBuilder,
    energy: f64,
) -> RKRStatus {
    if builder_handle.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let builder = unsafe { &mut *(builder_handle as *mut ConFrameBuilder) };
    builder.with_energy(energy);
    RKRStatus::RKR_STATUS_SUCCESS
}
// ----- v0.11.0 in-place mutation FFI ---------------------------------------
//
// Mirrors `ConFrameBuilder::set_atom_* / clear_atom_* / *_from_flat /
// get_atom_* / atom_count` for C / C++ / Python / Julia consumers. All
// mutators return RKRStatus; getters return raw values via out-parameters
// (so a caller can distinguish "atom has no force" from "successful read of
// f={0,0,0}" via the `has_*` boolean out-parameter).
//
// IndexOutOfBounds errors from the Rust side surface as
// RKR_STATUS_INDEX_OUT_OF_BOUNDS; all NULL-handle / NULL-out-pointer paths
// return RKR_STATUS_NULL_POINTER. Bulk setters with the wrong length return
// RKR_STATUS_INDEX_OUT_OF_BOUNDS as well (the caller sized the buffer
// wrong).
fn map_builder_err(e: crate::error::ParseError) -> RKRStatus {
    use crate::error::ParseError;
    match e {
        ParseError::IndexOutOfBounds { .. } | ParseError::InvalidVectorLength { .. } => {
            RKRStatus::RKR_STATUS_INDEX_OUT_OF_BOUNDS
        }
        _ => RKRStatus::RKR_STATUS_INTERNAL_ERROR,
    }
}
/// Returns the number of atoms currently held in the builder.
///
/// # Safety
/// builder_handle must be a valid pointer returned by rkr_frame_new and
/// not yet consumed by rkr_frame_builder_build / freed.
/// Returns 0 on NULL handle.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_atom_count(
    builder_handle: *const RKRConFrameBuilder,
) -> usize {
    if builder_handle.is_null() {
        return 0;
    }
    let builder = unsafe { &*(builder_handle as *const ConFrameBuilder) };
    builder.atom_count()
}
/// Updates the Cartesian position of an existing atom.
/// # Safety
/// builder_handle must be valid.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_set_atom_position(
    builder_handle: *mut RKRConFrameBuilder,
    index: usize,
    x: f64,
    y: f64,
    z: f64,
) -> RKRStatus {
    if builder_handle.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let builder = unsafe { &mut *(builder_handle as *mut ConFrameBuilder) };
    match builder.set_atom_position(index, x, y, z) {
        Ok(_) => RKRStatus::RKR_STATUS_SUCCESS,
        Err(e) => map_builder_err(e),
    }
}
/// Sets the velocity vector of an existing atom from 3 contiguous f64 values.
/// # Safety
/// builder_handle must be valid; velocity must point to 3 contiguous f64.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_set_atom_velocity(
    builder_handle: *mut RKRConFrameBuilder,
    index: usize,
    velocity: *const f64,
) -> RKRStatus {
    if builder_handle.is_null() || velocity.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let builder = unsafe { &mut *(builder_handle as *mut ConFrameBuilder) };
    let v = unsafe { [*velocity, *velocity.add(1), *velocity.add(2)] };
    match builder.set_atom_velocity(index, v) {
        Ok(_) => RKRStatus::RKR_STATUS_SUCCESS,
        Err(e) => map_builder_err(e),
    }
}
/// Sets the force vector of an existing atom from 3 contiguous f64 values.
/// # Safety
/// builder_handle must be valid; force must point to 3 contiguous f64.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_set_atom_force(
    builder_handle: *mut RKRConFrameBuilder,
    index: usize,
    force: *const f64,
) -> RKRStatus {
    if builder_handle.is_null() || force.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let builder = unsafe { &mut *(builder_handle as *mut ConFrameBuilder) };
    let f = unsafe { [*force, *force.add(1), *force.add(2)] };
    match builder.set_atom_force(index, f) {
        Ok(_) => RKRStatus::RKR_STATUS_SUCCESS,
        Err(e) => map_builder_err(e),
    }
}
/// Sets the per-atom energy contribution of an existing atom.
/// # Safety
/// builder_handle must be valid.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_set_atom_energy(
    builder_handle: *mut RKRConFrameBuilder,
    index: usize,
    energy: f64,
) -> RKRStatus {
    if builder_handle.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let builder = unsafe { &mut *(builder_handle as *mut ConFrameBuilder) };
    match builder.set_atom_energy(index, energy) {
        Ok(_) => RKRStatus::RKR_STATUS_SUCCESS,
        Err(e) => map_builder_err(e),
    }
}
/// Updates per-direction fixed flags `[fixed_x, fixed_y, fixed_z]`.
/// # Safety
/// builder_handle must be valid.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_set_atom_fixed(
    builder_handle: *mut RKRConFrameBuilder,
    index: usize,
    fixed_x: bool,
    fixed_y: bool,
    fixed_z: bool,
) -> RKRStatus {
    if builder_handle.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let builder = unsafe { &mut *(builder_handle as *mut ConFrameBuilder) };
    match builder.set_atom_fixed(index, [fixed_x, fixed_y, fixed_z]) {
        Ok(_) => RKRStatus::RKR_STATUS_SUCCESS,
        Err(e) => map_builder_err(e),
    }
}
/// Updates the mass of an existing atom.
/// # Safety
/// builder_handle must be valid.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_set_atom_mass(
    builder_handle: *mut RKRConFrameBuilder,
    index: usize,
    mass: f64,
) -> RKRStatus {
    if builder_handle.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let builder = unsafe { &mut *(builder_handle as *mut ConFrameBuilder) };
    match builder.set_atom_mass(index, mass) {
        Ok(_) => RKRStatus::RKR_STATUS_SUCCESS,
        Err(e) => map_builder_err(e),
    }
}
/// Updates the atom_id (pre-grouping index from .con column 5) of an
/// existing atom. The underlying `Array1<u64>` buffer pointer stays
/// stable; callers that hold a raw `*const u64` via
/// `rkr_frame_builder_atom_ids_data` do not need to refresh after this.
/// # Safety
/// builder_handle must be valid.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_set_atom_id(
    builder_handle: *mut RKRConFrameBuilder,
    index: usize,
    atom_id: u64,
) -> RKRStatus {
    if builder_handle.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let builder = unsafe { &mut *(builder_handle as *mut ConFrameBuilder) };
    match builder.set_atom_id(index, atom_id) {
        Ok(_) => RKRStatus::RKR_STATUS_SUCCESS,
        Err(e) => map_builder_err(e),
    }
}
/// Removes velocity / force / energy data from an existing atom.
/// # Safety
/// builder_handle must be valid.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_clear_atom_velocity(
    builder_handle: *mut RKRConFrameBuilder,
    index: usize,
) -> RKRStatus {
    if builder_handle.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let builder = unsafe { &mut *(builder_handle as *mut ConFrameBuilder) };
    match builder.clear_atom_velocity(index) {
        Ok(_) => RKRStatus::RKR_STATUS_SUCCESS,
        Err(e) => map_builder_err(e),
    }
}
/// # Safety
/// builder_handle must be valid.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_clear_atom_force(
    builder_handle: *mut RKRConFrameBuilder,
    index: usize,
) -> RKRStatus {
    if builder_handle.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let builder = unsafe { &mut *(builder_handle as *mut ConFrameBuilder) };
    match builder.clear_atom_force(index) {
        Ok(_) => RKRStatus::RKR_STATUS_SUCCESS,
        Err(e) => map_builder_err(e),
    }
}
/// # Safety
/// builder_handle must be valid.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_clear_atom_energy(
    builder_handle: *mut RKRConFrameBuilder,
    index: usize,
) -> RKRStatus {
    if builder_handle.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let builder = unsafe { &mut *(builder_handle as *mut ConFrameBuilder) };
    match builder.clear_atom_energy(index) {
        Ok(_) => RKRStatus::RKR_STATUS_SUCCESS,
        Err(e) => map_builder_err(e),
    }
}
/// Bulk-update positions for every atom from a flat row-major
/// `[x0,y0,z0,x1,y1,z1,...]` buffer of length `3 * atom_count()`.
/// # Safety
/// builder_handle must be valid; positions must point to `3 * len` f64.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_set_positions_from_flat(
    builder_handle: *mut RKRConFrameBuilder,
    positions: *const f64,
    len: usize,
) -> RKRStatus {
    if builder_handle.is_null() || positions.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let builder = unsafe { &mut *(builder_handle as *mut ConFrameBuilder) };
    let slice = unsafe { std::slice::from_raw_parts(positions, len) };
    match builder.set_positions_from_flat(slice) {
        Ok(_) => RKRStatus::RKR_STATUS_SUCCESS,
        Err(e) => map_builder_err(e),
    }
}
/// Bulk-update forces for every atom.
/// # Safety
/// builder_handle must be valid; forces must point to `3 * len` f64.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_set_forces_from_flat(
    builder_handle: *mut RKRConFrameBuilder,
    forces: *const f64,
    len: usize,
) -> RKRStatus {
    if builder_handle.is_null() || forces.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let builder = unsafe { &mut *(builder_handle as *mut ConFrameBuilder) };
    let slice = unsafe { std::slice::from_raw_parts(forces, len) };
    match builder.set_forces_from_flat(slice) {
        Ok(_) => RKRStatus::RKR_STATUS_SUCCESS,
        Err(e) => map_builder_err(e),
    }
}
/// Bulk-update per-atom energies (one f64 per atom).
/// # Safety
/// builder_handle must be valid; energies must point to `len` f64.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_set_atom_energies_from_flat(
    builder_handle: *mut RKRConFrameBuilder,
    energies: *const f64,
    len: usize,
) -> RKRStatus {
    if builder_handle.is_null() || energies.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let builder = unsafe { &mut *(builder_handle as *mut ConFrameBuilder) };
    let slice = unsafe { std::slice::from_raw_parts(energies, len) };
    match builder.set_atom_energies_from_flat(slice) {
        Ok(_) => RKRStatus::RKR_STATUS_SUCCESS,
        Err(e) => map_builder_err(e),
    }
}
/// Reads the position of an existing atom into 3 contiguous f64 out values.
/// # Safety
/// builder_handle must be valid; out_xyz must point to 3 writable f64.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_get_atom_position(
    builder_handle: *const RKRConFrameBuilder,
    index: usize,
    out_xyz: *mut f64,
) -> RKRStatus {
    if builder_handle.is_null() || out_xyz.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let builder = unsafe { &*(builder_handle as *const ConFrameBuilder) };
    match builder.get_atom_position(index) {
        Ok((x, y, z)) => unsafe {
            *out_xyz = x;
            *out_xyz.add(1) = y;
            *out_xyz.add(2) = z;
            RKRStatus::RKR_STATUS_SUCCESS
        },
        Err(e) => map_builder_err(e),
    }
}
/// Reads the velocity / force vector of an atom (if any) into 3 contiguous
/// f64. `*has_value` is set to `true` if the atom carries that vector,
/// `false` if it does not (in which case `out_xyz` is left untouched).
///
/// # Safety
/// builder_handle, out_xyz, has_value must all be valid pointers.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_get_atom_velocity(
    builder_handle: *const RKRConFrameBuilder,
    index: usize,
    out_xyz: *mut f64,
    has_value: *mut bool,
) -> RKRStatus {
    if builder_handle.is_null() || out_xyz.is_null() || has_value.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let builder = unsafe { &*(builder_handle as *const ConFrameBuilder) };
    match builder.get_atom_velocity(index) {
        Ok(Some(v)) => unsafe {
            *out_xyz = v[0];
            *out_xyz.add(1) = v[1];
            *out_xyz.add(2) = v[2];
            *has_value = true;
            RKRStatus::RKR_STATUS_SUCCESS
        },
        Ok(None) => unsafe {
            *has_value = false;
            RKRStatus::RKR_STATUS_SUCCESS
        },
        Err(e) => map_builder_err(e),
    }
}
/// # Safety
/// builder_handle, out_xyz, has_value must all be valid pointers.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_get_atom_force(
    builder_handle: *const RKRConFrameBuilder,
    index: usize,
    out_xyz: *mut f64,
    has_value: *mut bool,
) -> RKRStatus {
    if builder_handle.is_null() || out_xyz.is_null() || has_value.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let builder = unsafe { &*(builder_handle as *const ConFrameBuilder) };
    match builder.get_atom_force(index) {
        Ok(Some(f)) => unsafe {
            *out_xyz = f[0];
            *out_xyz.add(1) = f[1];
            *out_xyz.add(2) = f[2];
            *has_value = true;
            RKRStatus::RKR_STATUS_SUCCESS
        },
        Ok(None) => unsafe {
            *has_value = false;
            RKRStatus::RKR_STATUS_SUCCESS
        },
        Err(e) => map_builder_err(e),
    }
}
/// Reads the per-atom energy of an atom (if any). `*has_value` is set to
/// `true` if the atom carries an energy contribution, else `false` and
/// `*out_value` is left untouched.
/// # Safety
/// builder_handle, out_value, has_value must all be valid pointers.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_get_atom_energy(
    builder_handle: *const RKRConFrameBuilder,
    index: usize,
    out_value: *mut f64,
    has_value: *mut bool,
) -> RKRStatus {
    if builder_handle.is_null() || out_value.is_null() || has_value.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let builder = unsafe { &*(builder_handle as *const ConFrameBuilder) };
    match builder.get_atom_energy(index) {
        Ok(Some(e)) => unsafe {
            *out_value = e;
            *has_value = true;
            RKRStatus::RKR_STATUS_SUCCESS
        },
        Ok(None) => unsafe {
            *has_value = false;
            RKRStatus::RKR_STATUS_SUCCESS
        },
        Err(e) => map_builder_err(e),
    }
}
/// Reads the mass of an existing atom.
/// # Safety
/// builder_handle and out_mass must be valid pointers.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_get_atom_mass(
    builder_handle: *const RKRConFrameBuilder,
    index: usize,
    out_mass: *mut f64,
) -> RKRStatus {
    if builder_handle.is_null() || out_mass.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let builder = unsafe { &*(builder_handle as *const ConFrameBuilder) };
    match builder.get_atom_mass(index) {
        Ok(m) => unsafe {
            *out_mass = m;
            RKRStatus::RKR_STATUS_SUCCESS
        },
        Err(e) => map_builder_err(e),
    }
}
// ----- v0.11.0 DLPack tier-3 export FFI -------------------------------------
//
// Cross-language zero-copy via the DLPack 1.0 ABI. Each per-atom field of
// the builder is exported as an owning `DLManagedTensorVersioned*`. The
// caller is responsible for invoking the tensor's deleter callback to
// release the backing storage when finished. v0.11 ships the OWNING /
// CLONED variant: the tensor carries its own copy of the field data so it
// remains valid past the builder's lifetime. This is the conservative
// choice for cross-process / language-runtime consumers (Python GC,
// Julia GC, ...) where the consumer may outlive the Rust-side
// that hands out a non-owning view backed by `Arc<ndarray::Array<...>>`
// storage (matches metatensor v2's `Arc<RwLock<ArrayD<T>>>` pattern) for
// in-process zero-copy.
//
// Optional sections (velocities, forces, atom_energies) return
// RKR_STATUS_SECTION_ABSENT when the section is not declared on the
// builder; the out parameter is left untouched. Always-present fields
// (positions, masses, atom_ids) always return a tensor on success.
/// Re-export of dlpk's `DLManagedTensorVersioned` for the C ABI surface.
/// Defined here so cbindgen emits a forward declaration without pulling
/// in the full dlpk header; consumers include `<dlpack/dlpack.h>` (or
/// equivalent) and cast through the standard DLPack ABI.
pub use dlpk::sys::DLManagedTensorVersioned as RKRDLManagedTensorVersioned;
fn map_dlpack_err(e: crate::error::ParseError) -> RKRStatus {
    use crate::error::ParseError;
    match e {
        ParseError::ValidationError(_) => RKRStatus::RKR_STATUS_VALIDATION_ERROR,
        _ => RKRStatus::RKR_STATUS_INTERNAL_ERROR,
    }
}
/// Options for DLPack export precision and placement.
///
/// Pass to `*_dlpack_ex` entry points. NULL options on those APIs (or the
/// legacy non-`_ex` functions) mean **float64 on CPU** (`float_bits=64`,
/// `device_type=1` kDLCPU, `device_id=0`).
///
/// - `float_bits`: `32` or `64` for float sections (positions, velocities,
///   forces, energies, masses). Atom-id exports ignore this and stay u64.
/// - `device_type` / `device_id`: DLPack device tags. Only **CPU** (`1`) is
///   supported today; other values return `RKR_STATUS_VALIDATION_ERROR`.
///   Reserved so GPU/device-resident exports can land without another ABI break.
#[repr(C)]
#[derive(Clone, Copy, Debug)]
pub struct RKRDlpackExportOptions {
    pub float_bits: u8,
    pub device_type: i32,
    pub device_id: i32,
}

impl Default for RKRDlpackExportOptions {
    fn default() -> Self {
        Self {
            float_bits: 64,
            device_type: 1, // kDLCPU
            device_id: 0,
        }
    }
}

/// Resolve options pointer; NULL → defaults. Rejects unsupported device/bits.
fn resolve_dlpack_opts(opts: *const RKRDlpackExportOptions) -> Result<RKRDlpackExportOptions, RKRStatus> {
    let o = if opts.is_null() {
        RKRDlpackExportOptions::default()
    } else {
        unsafe { *opts }
    };
    // Only CPU for now (kDLCPU == 1 in dlpack.h).
    if o.device_type != 1 {
        return Err(RKRStatus::RKR_STATUS_VALIDATION_ERROR);
    }
    if o.float_bits != 32 && o.float_bits != 64 {
        return Err(RKRStatus::RKR_STATUS_VALIDATION_ERROR);
    }
    Ok(o)
}

fn export_owned_array2_dlpack(
    arr: &ndarray::ArcArray2<f64>,
    out_tensor: *mut *mut RKRDLManagedTensorVersioned,
) -> RKRStatus {
    export_owned_array2_dlpack_opts(arr, &RKRDlpackExportOptions::default(), out_tensor)
}

fn export_owned_array2_dlpack_opts(
    arr: &ndarray::ArcArray2<f64>,
    opts: &RKRDlpackExportOptions,
    out_tensor: *mut *mut RKRDLManagedTensorVersioned,
) -> RKRStatus {
    let result = match opts.float_bits {
        64 => {
            let shared = arr.clone();
            dlpk::DLPackTensor::try_from(shared)
        }
        32 => {
            let f32_arr: ndarray::ArcArray2<f32> = arr.mapv(|x| x as f32);
            dlpk::DLPackTensor::try_from(f32_arr)
        }
        _ => {
            return RKRStatus::RKR_STATUS_VALIDATION_ERROR;
        }
    };
    match result {
        Ok(tensor) => {
            let raw = tensor.into_raw();
            unsafe {
                *out_tensor = raw.as_ptr();
            }
            RKRStatus::RKR_STATUS_SUCCESS
        }
        Err(e) => map_dlpack_err(crate::error::ParseError::ValidationError(format!(
            "DLPack export failed: {e}"
        ))),
    }
}

fn export_owned_array1_f64_dlpack(
    arr: &ndarray::ArcArray1<f64>,
    out_tensor: *mut *mut RKRDLManagedTensorVersioned,
) -> RKRStatus {
    export_owned_array1_f64_dlpack_opts(arr, &RKRDlpackExportOptions::default(), out_tensor)
}

fn export_owned_array1_f64_dlpack_opts(
    arr: &ndarray::ArcArray1<f64>,
    opts: &RKRDlpackExportOptions,
    out_tensor: *mut *mut RKRDLManagedTensorVersioned,
) -> RKRStatus {
    let result = match opts.float_bits {
        64 => dlpk::DLPackTensor::try_from(arr.clone()),
        32 => {
            let f32_arr: ndarray::ArcArray1<f32> = arr.mapv(|x| x as f32);
            dlpk::DLPackTensor::try_from(f32_arr)
        }
        _ => return RKRStatus::RKR_STATUS_VALIDATION_ERROR,
    };
    match result {
        Ok(tensor) => {
            let raw = tensor.into_raw();
            unsafe {
                *out_tensor = raw.as_ptr();
            }
            RKRStatus::RKR_STATUS_SUCCESS
        }
        Err(e) => map_dlpack_err(crate::error::ParseError::ValidationError(format!(
            "DLPack export failed: {e}"
        ))),
    }
}
fn export_owned_array1_u64_dlpack(
    arr: &ndarray::ArcArray1<u64>,
    out_tensor: *mut *mut RKRDLManagedTensorVersioned,
) -> RKRStatus {
    let shared = arr.clone();
    match dlpk::DLPackTensor::try_from(shared) {
        Ok(tensor) => {
            let raw = tensor.into_raw();
            unsafe {
                *out_tensor = raw.as_ptr();
            }
            RKRStatus::RKR_STATUS_SUCCESS
        }
        Err(e) => map_dlpack_err(crate::error::ParseError::ValidationError(format!(
            "DLPack export failed: {e}"
        ))),
    }
}
/// Export builder positions as a DLPack-managed tensor.
///
/// On success the caller-supplied `*out_tensor` is set to a newly-
/// allocated `DLManagedTensorVersioned*` that owns a clone of the
/// builder's `(N, 3) f64` row-major positions buffer. The caller MUST
/// invoke `(*out_tensor)->deleter(*out_tensor)` to release it.
///
/// # Safety
/// `builder_handle` must be a valid builder handle; `out_tensor` must
/// be a valid pointer to a writable `*mut DLManagedTensorVersioned`.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_positions_dlpack(
    builder_handle: *const RKRConFrameBuilder,
    out_tensor: *mut *mut RKRDLManagedTensorVersioned,
) -> RKRStatus {
    unsafe { rkr_frame_builder_positions_dlpack_ex(builder_handle, std::ptr::null(), out_tensor) }
}

/// Like [`rkr_frame_builder_positions_dlpack`] with explicit precision/device.
///
/// `opts` may be NULL (float64 / CPU). See [`RKRDlpackExportOptions`].
///
/// # Safety
/// Same as the non-`_ex` entry; `opts` must be null or point at a valid struct.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_positions_dlpack_ex(
    builder_handle: *const RKRConFrameBuilder,
    opts: *const RKRDlpackExportOptions,
    out_tensor: *mut *mut RKRDLManagedTensorVersioned,
) -> RKRStatus {
    if builder_handle.is_null() || out_tensor.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let o = match resolve_dlpack_opts(opts) {
        Ok(o) => o,
        Err(st) => return st,
    };
    let builder = unsafe { &*(builder_handle as *const ConFrameBuilder) };
    export_owned_array2_dlpack_opts(builder.positions_2d_ref(), &o, out_tensor)
}

/// Export builder velocities as a DLPack-managed tensor.
///
/// Returns `RKR_STATUS_SECTION_ABSENT` if the velocities section is not
/// declared; otherwise `(N, 3) f64`. See positions_dlpack for ownership
/// semantics.
///
/// # Safety
/// `builder_handle` must be a valid builder handle; `out_tensor` must
/// be a valid pointer to a writable `*mut DLManagedTensorVersioned`.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_velocities_dlpack(
    builder_handle: *const RKRConFrameBuilder,
    out_tensor: *mut *mut RKRDLManagedTensorVersioned,
) -> RKRStatus {
    unsafe { rkr_frame_builder_velocities_dlpack_ex(builder_handle, std::ptr::null(), out_tensor) }
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_velocities_dlpack_ex(
    builder_handle: *const RKRConFrameBuilder,
    opts: *const RKRDlpackExportOptions,
    out_tensor: *mut *mut RKRDLManagedTensorVersioned,
) -> RKRStatus {
    if builder_handle.is_null() || out_tensor.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let o = match resolve_dlpack_opts(opts) {
        Ok(o) => o,
        Err(st) => return st,
    };
    let builder = unsafe { &*(builder_handle as *const ConFrameBuilder) };
    if !builder.has_velocities_section() {
        return RKRStatus::RKR_STATUS_SECTION_ABSENT;
    }
    export_owned_array2_dlpack_opts(builder.velocities_2d_ref(), &o, out_tensor)
}

/// Export builder forces as a DLPack-managed tensor.
///
/// Returns `RKR_STATUS_SECTION_ABSENT` if the forces section is not
/// declared.
///
/// # Safety
/// `builder_handle` must be a valid builder handle; `out_tensor` must
/// be a valid pointer to a writable `*mut DLManagedTensorVersioned`.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_forces_dlpack(
    builder_handle: *const RKRConFrameBuilder,
    out_tensor: *mut *mut RKRDLManagedTensorVersioned,
) -> RKRStatus {
    unsafe { rkr_frame_builder_forces_dlpack_ex(builder_handle, std::ptr::null(), out_tensor) }
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_forces_dlpack_ex(
    builder_handle: *const RKRConFrameBuilder,
    opts: *const RKRDlpackExportOptions,
    out_tensor: *mut *mut RKRDLManagedTensorVersioned,
) -> RKRStatus {
    if builder_handle.is_null() || out_tensor.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let o = match resolve_dlpack_opts(opts) {
        Ok(o) => o,
        Err(st) => return st,
    };
    let builder = unsafe { &*(builder_handle as *const ConFrameBuilder) };
    if !builder.has_forces_section() {
        return RKRStatus::RKR_STATUS_SECTION_ABSENT;
    }
    export_owned_array2_dlpack_opts(builder.forces_2d_ref(), &o, out_tensor)
}

/// Export builder per-atom energies as a DLPack-managed tensor.
///
/// Returns `RKR_STATUS_SECTION_ABSENT` if the energies section is not
/// declared; otherwise `(N,) f64`.
///
/// # Safety
/// `builder_handle` must be a valid builder handle; `out_tensor` must
/// be a valid pointer to a writable `*mut DLManagedTensorVersioned`.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_atom_energies_dlpack(
    builder_handle: *const RKRConFrameBuilder,
    out_tensor: *mut *mut RKRDLManagedTensorVersioned,
) -> RKRStatus {
    unsafe {
        rkr_frame_builder_atom_energies_dlpack_ex(builder_handle, std::ptr::null(), out_tensor)
    }
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_atom_energies_dlpack_ex(
    builder_handle: *const RKRConFrameBuilder,
    opts: *const RKRDlpackExportOptions,
    out_tensor: *mut *mut RKRDLManagedTensorVersioned,
) -> RKRStatus {
    if builder_handle.is_null() || out_tensor.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let o = match resolve_dlpack_opts(opts) {
        Ok(o) => o,
        Err(st) => return st,
    };
    let builder = unsafe { &*(builder_handle as *const ConFrameBuilder) };
    if !builder.has_energies_section() {
        return RKRStatus::RKR_STATUS_SECTION_ABSENT;
    }
    export_owned_array1_f64_dlpack_opts(builder.atom_energies_1d_ref(), &o, out_tensor)
}

/// Export builder per-atom masses as a DLPack-managed tensor `(N,) f64`.
///
/// # Safety
/// `builder_handle` must be a valid builder handle; `out_tensor` must
/// be a valid pointer to a writable `*mut DLManagedTensorVersioned`.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_masses_dlpack(
    builder_handle: *const RKRConFrameBuilder,
    out_tensor: *mut *mut RKRDLManagedTensorVersioned,
) -> RKRStatus {
    unsafe { rkr_frame_builder_masses_dlpack_ex(builder_handle, std::ptr::null(), out_tensor) }
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_masses_dlpack_ex(
    builder_handle: *const RKRConFrameBuilder,
    opts: *const RKRDlpackExportOptions,
    out_tensor: *mut *mut RKRDLManagedTensorVersioned,
) -> RKRStatus {
    if builder_handle.is_null() || out_tensor.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let o = match resolve_dlpack_opts(opts) {
        Ok(o) => o,
        Err(st) => return st,
    };
    let builder = unsafe { &*(builder_handle as *const ConFrameBuilder) };
    export_owned_array1_f64_dlpack_opts(builder.masses_1d_ref(), &o, out_tensor)
}
/// Export builder per-atom ids as a DLPack-managed tensor `(N,) u64`.
///
/// # Safety
/// `builder_handle` must be a valid builder handle; `out_tensor` must
/// be a valid pointer to a writable `*mut DLManagedTensorVersioned`.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_atom_ids_dlpack(
    builder_handle: *const RKRConFrameBuilder,
    out_tensor: *mut *mut RKRDLManagedTensorVersioned,
) -> RKRStatus {
    if builder_handle.is_null() || out_tensor.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let builder = unsafe { &*(builder_handle as *const ConFrameBuilder) };
    export_owned_array1_u64_dlpack(builder.atom_ids_1d_ref(), out_tensor)
}
// ----- v0.11.1 in-process zero-copy raw-pointer FFI -------------------------
//
// The DLPack tier-3 export above clones field data into an owning tensor so
// the consumer can outlive the builder; this is the right contract for
// language-runtime / cross-process consumers (Python GC, Julia GC,
// inter-process exchange). For *in-process* zero-copy on the hot path
// (LAMMPS-style `lmp->atom->x` direct pointer access used by integrators,
// dynamics drivers, eOn's Matter Eigen::Map<RowMajor> views), we expose
// raw pointers into the builder's storage. The lifetime contract is
// purely caller-managed: the pointer is valid while the builder is alive
// and no add_atom call has grown the underlying ndarray. This mirrors
// the LAMMPS / OpenMM / GROMACS C-side hot path and is what makes a
// thin Matter wrapper over ConFrameBuilder fast.
//
// Cross-language ML consumers should use the DLPack tier above; raw
// pointer access is for in-process hot paths only.
/// Borrow the positions buffer as a raw `(N, 3) f64` row-major pointer.
/// Returns NULL on invalid handle. Pointer is valid until the builder
/// is dropped or `add_atom` reallocates.
///
/// # Safety
/// builder_handle must be valid; the returned pointer must not be
/// dereferenced after a call to add_atom on the same builder.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_positions_data(
    builder_handle: *mut RKRConFrameBuilder,
) -> *mut f64 {
    if builder_handle.is_null() {
        return std::ptr::null_mut();
    }
    let builder = unsafe { &mut *(builder_handle as *mut ConFrameBuilder) };
    builder
        .positions_view_mut()
        .as_slice_memory_order_mut()
        .map(|s| s.as_mut_ptr())
        .unwrap_or(std::ptr::null_mut())
}
/// Borrow the velocities buffer as a raw `(N, 3) f64` row-major pointer.
/// Returns NULL if the velocities section is absent or the handle is
/// invalid.
///
/// # Safety
/// Same contract as rkr_frame_builder_positions_data.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_velocities_data(
    builder_handle: *mut RKRConFrameBuilder,
) -> *mut f64 {
    if builder_handle.is_null() {
        return std::ptr::null_mut();
    }
    let builder = unsafe { &mut *(builder_handle as *mut ConFrameBuilder) };
    if !builder.has_velocities_section() {
        return std::ptr::null_mut();
    }
    let slice = builder.velocities_mut();
    if slice.is_empty() {
        std::ptr::null_mut()
    } else {
        slice.as_mut_ptr()
    }
}
/// Borrow the forces buffer as a raw `(N, 3) f64` row-major pointer.
/// Returns NULL if the forces section is absent.
///
/// # Safety
/// Same contract as rkr_frame_builder_positions_data.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_forces_data(
    builder_handle: *mut RKRConFrameBuilder,
) -> *mut f64 {
    if builder_handle.is_null() {
        return std::ptr::null_mut();
    }
    let builder = unsafe { &mut *(builder_handle as *mut ConFrameBuilder) };
    if !builder.has_forces_section() {
        return std::ptr::null_mut();
    }
    let slice = builder.forces_mut();
    if slice.is_empty() {
        std::ptr::null_mut()
    } else {
        slice.as_mut_ptr()
    }
}
/// Borrow the per-atom energies buffer as a raw `(N,) f64` pointer.
/// Returns NULL if the energies section is absent.
///
/// # Safety
/// Same contract as rkr_frame_builder_positions_data.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_atom_energies_data(
    builder_handle: *mut RKRConFrameBuilder,
) -> *mut f64 {
    if builder_handle.is_null() {
        return std::ptr::null_mut();
    }
    let builder = unsafe { &mut *(builder_handle as *mut ConFrameBuilder) };
    if !builder.has_energies_section() {
        return std::ptr::null_mut();
    }
    let slice = builder.atom_energies_mut();
    if slice.is_empty() {
        std::ptr::null_mut()
    } else {
        slice.as_mut_ptr()
    }
}
/// Borrow the per-atom masses buffer as a raw `(N,) f64` pointer.
///
/// # Safety
/// Same contract as rkr_frame_builder_positions_data.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_masses_data(
    builder_handle: *mut RKRConFrameBuilder,
) -> *mut f64 {
    if builder_handle.is_null() {
        return std::ptr::null_mut();
    }
    let builder = unsafe { &mut *(builder_handle as *mut ConFrameBuilder) };
    let slice = builder.masses_mut();
    if slice.is_empty() {
        std::ptr::null_mut()
    } else {
        slice.as_mut_ptr()
    }
}
/// Borrow the per-atom atom_ids buffer as a raw `(N,) u64` pointer.
///
/// # Safety
/// Same contract as rkr_frame_builder_positions_data.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_atom_ids_data(
    builder_handle: *const RKRConFrameBuilder,
) -> *const u64 {
    if builder_handle.is_null() {
        return std::ptr::null();
    }
    let builder = unsafe { &*(builder_handle as *const ConFrameBuilder) };
    let slice = builder.atom_ids();
    if slice.is_empty() {
        std::ptr::null()
    } else {
        slice.as_ptr()
    }
}
// ----- end v0.11.0 in-place mutation FFI ------------------------------------
/// Adds an atom with optional per-axis fixed mask, velocity, and force vectors.
///
/// `velocity` and `force` are pointers to 3 contiguous f64 values, or NULL if
/// absent. This is the unified entry point that replaces the eight
/// `rkr_frame_add_atom_*` convenience functions; callers may continue using
/// those for source compatibility.
///
/// # Safety
/// builder_handle and symbol must be valid. velocity (if non-null) must point
/// to 3 contiguous f64 values, and force (if non-null) likewise.
#[unsafe(no_mangle)]
#[allow(clippy::too_many_arguments)]
pub unsafe extern "C" fn rkr_frame_add_atom_full(
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
    velocity: *const f64,
    force: *const f64,
) -> RKRStatus {
    let velocity = if velocity.is_null() {
        None
    } else {
        Some(unsafe { [*velocity, *velocity.add(1), *velocity.add(2)] })
    };
    let force = if force.is_null() {
        None
    } else {
        Some(unsafe { [*force, *force.add(1), *force.add(2)] })
    };
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
            velocity,
            force,
        )
    }
}
/// Creates a new frame builder with the given cell dimensions, angles,
/// and header lines.
///
/// `prebox1` is accepted for source compatibility but ignored: the
/// JSON metadata line is regenerated by the writer from the builder's
/// `spec_version`, `metadata`, and `sections`. Pass NULL or any string.
/// The caller OWNS the returned pointer and MUST call
/// `free_rkr_frame_builder` or consume it via `rkr_frame_builder_build`.
/// Returns NULL on error.
///
/// # Safety
/// cell and angles must point to 3 doubles. prebox0, postbox0, and
/// postbox1 must be NULL or valid null-terminated strings; prebox1 is
/// not dereferenced. The caller takes ownership of the returned
/// builder.
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
    // prebox1 is the JSON metadata slot, regenerated on write from
    // metadata + sections; it is accepted for ABI continuity but ignored.
    let _ = get_str(prebox1);
    let mut builder = ConFrameBuilder::new(cell_arr, angles_arr);
    builder
        .prebox_header(get_str(prebox0))
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
// -----------------------------------------------------------------------------
// Legacy add_atom variants (kept for source compatibility)
//
// The unified entry point is `rkr_frame_add_atom_full`, which accepts
// optional velocity and force pointers. The eight functions below
// pre-date the unified call and remain in the API for code that was
// written against earlier 0.x releases. New callers should prefer
// `rkr_frame_add_atom_full`.
// -----------------------------------------------------------------------------
/// **Deprecated**: prefer `rkr_frame_add_atom_full` with NULL velocity
/// and force pointers. Adds an atom (no velocity, no forces) to the
/// builder using a single uniform fixed flag.
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
/// **Deprecated**: prefer `rkr_frame_add_atom_full`. Adds an atom (no
/// velocity, no forces) using per-axis fixed flags.
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
/// **Deprecated**: prefer `rkr_frame_add_atom_full`. Adds an atom with
/// a velocity vector and a single uniform fixed flag.
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
/// **Deprecated**: prefer `rkr_frame_add_atom_full`. Adds an atom with
/// a velocity vector and per-axis fixed flags.
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
/// **Deprecated**: prefer `rkr_frame_add_atom_full`. Adds an atom with
/// a force vector and a single uniform fixed flag.
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
/// **Deprecated**: prefer `rkr_frame_add_atom_full`. Adds an atom with
/// a force vector and per-axis fixed flags.
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
/// **Deprecated**: prefer `rkr_frame_add_atom_full`. Adds an atom with
/// both velocity and force vectors and a single uniform fixed flag.
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
/// **Deprecated**: prefer `rkr_frame_add_atom_full`. Adds an atom with
/// both velocity and force vectors and per-axis fixed flags.
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
/// Cheap, copy-on-write clone of a frame builder. Returned handle owns
/// a new `ConFrameBuilder` whose per-atom buffers share storage with
/// the source via ArcArray; any subsequent mutation triggers a
/// per-buffer copy-on-write so writes do not leak across clones.
///
/// Intended for downstream consumers (NEB image bulk allocation,
/// trajectory snapshots) that need many builders carrying the same
/// per-atom data without paying N copies up-front. Returns NULL on
/// NULL input.
///
/// The caller OWNS the returned handle and MUST call
/// `free_rkr_frame_builder` (or consume via `rkr_frame_builder_build`).
///
/// # Safety
/// `builder_handle` must be a valid pointer returned by `rkr_frame_new`
/// (or by an earlier `rkr_frame_builder_clone`) and not yet freed.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_builder_clone(
    builder_handle: *const RKRConFrameBuilder,
) -> *mut RKRConFrameBuilder {
    if builder_handle.is_null() {
        return std::ptr::null_mut();
    }
    let builder = unsafe { &*(builder_handle as *const ConFrameBuilder) };
    let cloned = builder.clone();
    Box::into_raw(Box::new(cloned)) as *mut RKRConFrameBuilder
}
/// Creates a new gzip-compressed frame writer for the specified file.
/// The caller OWNS the returned pointer and MUST call `free_rkr_writer`.
///
/// # Safety
/// filename_c must be valid. The caller takes ownership of the returned writer.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn create_writer_gzip_c(filename_c: *const c_char) -> *mut RKRConFrameWriter {
    let filename = match unsafe { cstr_path(filename_c) } {
        Some(s) => s,
        None => return ptr::null_mut(),
    };
    match crate::compression::gzip_writer(Path::new(filename)) {
        Ok(encoder) => into_rkr_writer(Box::new(encoder), None),
        Err(_) => ptr::null_mut(),
    }
}
/// Creates a gzip-compressed frame writer with a custom floating-point
/// precision. The caller OWNS the returned pointer and MUST call
/// `free_rkr_writer`.
///
/// # Safety
/// filename_c must be valid. The caller takes ownership of the returned writer.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn create_writer_gzip_with_precision_c(
    filename_c: *const c_char,
    precision: u8,
) -> *mut RKRConFrameWriter {
    let filename = match unsafe { cstr_path(filename_c) } {
        Some(s) => s,
        None => return ptr::null_mut(),
    };
    match crate::compression::gzip_writer(Path::new(filename)) {
        Ok(encoder) => into_rkr_writer(Box::new(encoder), Some(precision)),
        Err(_) => ptr::null_mut(),
    }
}
/// Creates a new zstd-compressed frame writer for the specified file.
/// The caller OWNS the returned pointer and MUST call `free_rkr_writer`.
///
/// Only present when readcon-core is built with the `zstd` Cargo
/// feature; the C header guards the declaration with
/// `READCON_CORE_HAS_ZSTD`.
///
/// # Safety
/// filename_c must be valid. The caller takes ownership of the returned writer.
#[cfg(feature = "zstd")]
#[unsafe(no_mangle)]
pub unsafe extern "C" fn create_writer_zstd_c(filename_c: *const c_char) -> *mut RKRConFrameWriter {
    let filename = match unsafe { cstr_path(filename_c) } {
        Some(s) => s,
        None => return ptr::null_mut(),
    };
    match crate::compression::zstd_writer(Path::new(filename)) {
        Ok(encoder) => into_rkr_writer(Box::new(encoder), None),
        Err(_) => ptr::null_mut(),
    }
}
/// Creates a zstd-compressed frame writer with a custom floating-point
/// precision. The caller OWNS the returned pointer and MUST call
/// `free_rkr_writer`.
///
/// Only present when readcon-core is built with the `zstd` Cargo
/// feature; the C header guards the declaration with
/// `READCON_CORE_HAS_ZSTD`.
///
/// # Safety
/// filename_c must be valid. The caller takes ownership of the returned writer.
#[cfg(feature = "zstd")]
#[unsafe(no_mangle)]
pub unsafe extern "C" fn create_writer_zstd_with_precision_c(
    filename_c: *const c_char,
    precision: u8,
) -> *mut RKRConFrameWriter {
    let filename = match unsafe { cstr_path(filename_c) } {
        Some(s) => s,
        None => return ptr::null_mut(),
    };
    match crate::compression::zstd_writer(Path::new(filename)) {
        Ok(encoder) => into_rkr_writer(Box::new(encoder), Some(precision)),
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
            // shrink_to_fit ensures len == capacity so the matching
            // free_rkr_frame_array can soundly call Vec::from_raw_parts
            // with len == cap.
            let mut handles: Vec<*mut RKRConFrame> = frames
                .into_iter()
                .map(|f| Box::into_raw(Box::new(f)) as *mut RKRConFrame)
                .collect();
            handles.shrink_to_fit();
            debug_assert_eq!(handles.len(), handles.capacity());
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
/// Free only the outer pointer array from `rkr_read_all_frames` (not the frames).
///
/// # Safety
/// `frames` null or from `rkr_read_all_frames` with length `num_frames`. Frame
/// pointers must be owned elsewhere (e.g. language wrappers).
#[unsafe(no_mangle)]
pub unsafe extern "C" fn free_rkr_frame_ptr_array(frames: *mut *mut RKRConFrame, num_frames: usize) {
    if frames.is_null() {
        return;
    }
    unsafe {
        let _ptrs = Vec::from_raw_parts(frames, num_frames, num_frames);
    }
}

//=============================================================================
// ---------------------------------------------------------------------------
// Metatensor TensorBlock exports (`metatensor` Cargo feature)
//
// Boundary types are metatensor-sys only (`metatensor::c_api::mts_block_t`).
// Construction: `metatensor_export` (high-level). Transfer/free: single helpers
// in that module (`tensor_block_into_raw_mts` / `mts_block_free_sys`).
// Lean builds omit these symbols (`READCON_CORE_HAS_METATENSOR` in the header).
// ---------------------------------------------------------------------------
/// Free an owned block from `rkr_frame_metatensor_*_block`.
/// Prefer this or `mts_block_free` (metatensor.h) — not both on the same pointer.
///
/// # Safety
/// `block` is NULL or an owning `mts_block_t*` from this library's transfer helper.
#[cfg(feature = "metatensor")]
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_mts_block_free(block: *mut metatensor::c_api::mts_block_t) {
    unsafe { crate::metatensor_export::mts_block_free_sys(block) };
}
/// Positions `[N,3]` TensorBlock. Caller frees with `rkr_mts_block_free` / `mts_block_free`.
#[cfg(feature = "metatensor")]
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_metatensor_positions_block(
    frame_handle: *const RKRConFrame,
    out_block: *mut *mut metatensor::c_api::mts_block_t,
) -> RKRStatus {
    if frame_handle.is_null() || out_block.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    unsafe { *out_block = std::ptr::null_mut() };
    let Some(frame) = (unsafe { (frame_handle as *const ConFrame).as_ref() }) else {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    };
    match std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        crate::metatensor_export::frame_positions_block(frame)
    })) {
        Ok(Ok(b)) => {
            unsafe { *out_block = crate::metatensor_export::tensor_block_into_raw_mts(b) };
            RKRStatus::RKR_STATUS_SUCCESS
        }
        Ok(Err(_)) | Err(_) => RKRStatus::RKR_STATUS_INTERNAL_ERROR,
    }
}
#[cfg(feature = "metatensor")]
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_metatensor_velocities_block(
    frame_handle: *const RKRConFrame,
    out_block: *mut *mut metatensor::c_api::mts_block_t,
) -> RKRStatus {
    if frame_handle.is_null() || out_block.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    unsafe { *out_block = std::ptr::null_mut() };
    let Some(frame) = (unsafe { (frame_handle as *const ConFrame).as_ref() }) else {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    };
    match std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        crate::metatensor_export::frame_velocities_block(frame)
    })) {
        Ok(Ok(Some(b))) => {
            unsafe { *out_block = crate::metatensor_export::tensor_block_into_raw_mts(b) };
            RKRStatus::RKR_STATUS_SUCCESS
        }
        Ok(Ok(None)) => RKRStatus::RKR_STATUS_SECTION_ABSENT,
        Ok(Err(_)) | Err(_) => RKRStatus::RKR_STATUS_INTERNAL_ERROR,
    }
}
#[cfg(feature = "metatensor")]
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_metatensor_forces_block(
    frame_handle: *const RKRConFrame,
    out_block: *mut *mut metatensor::c_api::mts_block_t,
) -> RKRStatus {
    if frame_handle.is_null() || out_block.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    unsafe { *out_block = std::ptr::null_mut() };
    let Some(frame) = (unsafe { (frame_handle as *const ConFrame).as_ref() }) else {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    };
    match std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        crate::metatensor_export::frame_forces_block(frame)
    })) {
        Ok(Ok(Some(b))) => {
            unsafe { *out_block = crate::metatensor_export::tensor_block_into_raw_mts(b) };
            RKRStatus::RKR_STATUS_SUCCESS
        }
        Ok(Ok(None)) => RKRStatus::RKR_STATUS_SECTION_ABSENT,
        Ok(Err(_)) | Err(_) => RKRStatus::RKR_STATUS_INTERNAL_ERROR,
    }
}
#[cfg(feature = "metatensor")]
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_metatensor_atom_energies_block(
    frame_handle: *const RKRConFrame,
    out_block: *mut *mut metatensor::c_api::mts_block_t,
) -> RKRStatus {
    if frame_handle.is_null() || out_block.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    unsafe { *out_block = std::ptr::null_mut() };
    let Some(frame) = (unsafe { (frame_handle as *const ConFrame).as_ref() }) else {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    };
    match std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        crate::metatensor_export::frame_energies_block(frame)
    })) {
        Ok(Ok(Some(b))) => {
            unsafe { *out_block = crate::metatensor_export::tensor_block_into_raw_mts(b) };
            RKRStatus::RKR_STATUS_SUCCESS
        }
        Ok(Ok(None)) => RKRStatus::RKR_STATUS_SECTION_ABSENT,
        Ok(Err(_)) | Err(_) => RKRStatus::RKR_STATUS_INTERNAL_ERROR,
    }
}
#[cfg(not(feature = "zstd"))]
#[unsafe(no_mangle)]
pub unsafe extern "C" fn create_writer_zstd_c(_filename_c: *const c_char) -> *mut RKRConFrameWriter {
    ptr::null_mut()
}
#[cfg(not(feature = "zstd"))]
#[unsafe(no_mangle)]
pub unsafe extern "C" fn create_writer_zstd_with_precision_c(
    _filename_c: *const c_char,
    _precision: u8,
) -> *mut RKRConFrameWriter {
    ptr::null_mut()
}
//=============================================================================
/// Lean-build stubs: always export metatensor C symbols so Fortran/C can link without `#ifdef`.
/// Real implementations live under `feature = "metatensor"`.
#[cfg(not(feature = "metatensor"))]
#[repr(C)]
pub struct mts_block_t {
    _private: [u8; 0],
}
#[cfg(not(feature = "metatensor"))]
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_mts_block_free(_block: *mut mts_block_t) {}
#[cfg(not(feature = "metatensor"))]
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_metatensor_positions_block(
    _frame_handle: *const RKRConFrame,
    out_block: *mut *mut mts_block_t,
) -> RKRStatus {
    if !out_block.is_null() {
        unsafe { *out_block = std::ptr::null_mut() };
    }
    RKRStatus::RKR_STATUS_FEATURE_DISABLED
}
#[cfg(not(feature = "metatensor"))]
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_metatensor_velocities_block(
    _frame_handle: *const RKRConFrame,
    out_block: *mut *mut mts_block_t,
) -> RKRStatus {
    if !out_block.is_null() {
        unsafe { *out_block = std::ptr::null_mut() };
    }
    RKRStatus::RKR_STATUS_FEATURE_DISABLED
}
#[cfg(not(feature = "metatensor"))]
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_metatensor_forces_block(
    _frame_handle: *const RKRConFrame,
    out_block: *mut *mut mts_block_t,
) -> RKRStatus {
    if !out_block.is_null() {
        unsafe { *out_block = std::ptr::null_mut() };
    }
    RKRStatus::RKR_STATUS_FEATURE_DISABLED
}
#[cfg(not(feature = "metatensor"))]
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_metatensor_atom_energies_block(
    _frame_handle: *const RKRConFrame,
    out_block: *mut *mut mts_block_t,
) -> RKRStatus {
    if !out_block.is_null() {
        unsafe { *out_block = std::ptr::null_mut() };
    }
    RKRStatus::RKR_STATUS_FEATURE_DISABLED
}
// ----- Frame section buffers (no CFrame AoS required) -------------------------
/// Number of atoms on the frame (atom_data order).
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_atom_count(frame_handle: *const RKRConFrame) -> usize {
    let Some(frame) = (unsafe { (frame_handle as *const ConFrame).as_ref() }) else {
        return 0;
    };
    frame.atom_data.len()
}
/// Copy positions as row-major `[x0,y0,z0,...]` into `out` (length >= 3*N).
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_copy_positions(
    frame_handle: *const RKRConFrame,
    out: *mut f64,
    out_len: usize,
) -> RKRStatus {
    if frame_handle.is_null() || out.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let Some(frame) = (unsafe { (frame_handle as *const ConFrame).as_ref() }) else {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    };
    let n = frame.atom_data.len();
    let need = n.saturating_mul(3);
    if out_len < need {
        return RKRStatus::RKR_STATUS_BUFFER_TOO_SMALL;
    }
    let slice = unsafe { std::slice::from_raw_parts_mut(out, need) };
    for (i, a) in frame.atom_data.iter().enumerate() {
        slice[i * 3] = a.x;
        slice[i * 3 + 1] = a.y;
        slice[i * 3 + 2] = a.z;
    }
    RKRStatus::RKR_STATUS_SUCCESS
}
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_copy_velocities(
    frame_handle: *const RKRConFrame,
    out: *mut f64,
    out_len: usize,
) -> RKRStatus {
    if frame_handle.is_null() || out.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let Some(frame) = (unsafe { (frame_handle as *const ConFrame).as_ref() }) else {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    };
    if !frame.has_velocities() {
        return RKRStatus::RKR_STATUS_SECTION_ABSENT;
    }
    let n = frame.atom_data.len();
    let need = n.saturating_mul(3);
    if out_len < need {
        return RKRStatus::RKR_STATUS_BUFFER_TOO_SMALL;
    }
    let slice = unsafe { std::slice::from_raw_parts_mut(out, need) };
    for (i, a) in frame.atom_data.iter().enumerate() {
        let [vx, vy, vz] = a.velocity.unwrap_or([0.0; 3]);
        slice[i * 3] = vx;
        slice[i * 3 + 1] = vy;
        slice[i * 3 + 2] = vz;
    }
    RKRStatus::RKR_STATUS_SUCCESS
}
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_copy_forces(
    frame_handle: *const RKRConFrame,
    out: *mut f64,
    out_len: usize,
) -> RKRStatus {
    if frame_handle.is_null() || out.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let Some(frame) = (unsafe { (frame_handle as *const ConFrame).as_ref() }) else {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    };
    if !frame.has_forces() {
        return RKRStatus::RKR_STATUS_SECTION_ABSENT;
    }
    let n = frame.atom_data.len();
    let need = n.saturating_mul(3);
    if out_len < need {
        return RKRStatus::RKR_STATUS_BUFFER_TOO_SMALL;
    }
    let slice = unsafe { std::slice::from_raw_parts_mut(out, need) };
    for (i, a) in frame.atom_data.iter().enumerate() {
        let [fx, fy, fz] = a.force.unwrap_or([0.0; 3]);
        slice[i * 3] = fx;
        slice[i * 3 + 1] = fy;
        slice[i * 3 + 2] = fz;
    }
    RKRStatus::RKR_STATUS_SUCCESS
}
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_copy_atom_energies(
    frame_handle: *const RKRConFrame,
    out: *mut f64,
    out_len: usize,
) -> RKRStatus {
    if frame_handle.is_null() || out.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let Some(frame) = (unsafe { (frame_handle as *const ConFrame).as_ref() }) else {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    };
    if !frame.has_energies() {
        return RKRStatus::RKR_STATUS_SECTION_ABSENT;
    }
    let n = frame.atom_data.len();
    if out_len < n {
        return RKRStatus::RKR_STATUS_BUFFER_TOO_SMALL;
    }
    let slice = unsafe { std::slice::from_raw_parts_mut(out, n) };
    for (i, a) in frame.atom_data.iter().enumerate() {
        slice[i] = a.energy.unwrap_or(0.0);
    }
    RKRStatus::RKR_STATUS_SUCCESS
}
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_copy_masses(
    frame_handle: *const RKRConFrame,
    out: *mut f64,
    out_len: usize,
) -> RKRStatus {
    if frame_handle.is_null() || out.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let Some(frame) = (unsafe { (frame_handle as *const ConFrame).as_ref() }) else {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    };
    let n = frame.atom_data.len();
    if out_len < n {
        return RKRStatus::RKR_STATUS_BUFFER_TOO_SMALL;
    }
    let slice = unsafe { std::slice::from_raw_parts_mut(out, n) };
    let mut expanded: Vec<f64> = Vec::with_capacity(n);
    for (ti, &count) in frame.header.natms_per_type.iter().enumerate() {
        let m = frame.header.masses_per_type.get(ti).copied().unwrap_or(0.0);
        expanded.extend(std::iter::repeat_n(m, count));
    }
    if expanded.len() != n {
        expanded.resize(n, 0.0);
    }
    slice.copy_from_slice(&expanded[..n]);
    RKRStatus::RKR_STATUS_SUCCESS
}
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_copy_atom_ids(
    frame_handle: *const RKRConFrame,
    out: *mut u64,
    out_len: usize,
) -> RKRStatus {
    if frame_handle.is_null() || out.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let Some(frame) = (unsafe { (frame_handle as *const ConFrame).as_ref() }) else {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    };
    let n = frame.atom_data.len();
    if out_len < n {
        return RKRStatus::RKR_STATUS_BUFFER_TOO_SMALL;
    }
    let slice = unsafe { std::slice::from_raw_parts_mut(out, n) };
    for (i, a) in frame.atom_data.iter().enumerate() {
        slice[i] = a.atom_id;
    }
    RKRStatus::RKR_STATUS_SUCCESS
}
fn frame_positions_arc(frame: &ConFrame) -> ndarray::ArcArray2<f64> {
    let n = frame.atom_data.len();
    let mut data = Vec::with_capacity(n * 3);
    for a in &frame.atom_data {
        data.extend_from_slice(&[a.x, a.y, a.z]);
    }
    ndarray::ArcArray2::from_shape_vec((n, 3), data)
        .unwrap_or_else(|_| ndarray::ArcArray2::zeros((0, 3)))
}

/// DLPack positions from a frame (default float64 / CPU).
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_positions_dlpack(
    frame_handle: *const RKRConFrame,
    out_tensor: *mut *mut RKRDLManagedTensorVersioned,
) -> RKRStatus {
    unsafe { rkr_frame_positions_dlpack_ex(frame_handle, std::ptr::null(), out_tensor) }
}

/// Frame positions with [`RKRDlpackExportOptions`] (`opts` NULL → f64/CPU).
///
/// # Safety
/// `frame_handle` / `out_tensor` valid; `opts` null or valid.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_positions_dlpack_ex(
    frame_handle: *const RKRConFrame,
    opts: *const RKRDlpackExportOptions,
    out_tensor: *mut *mut RKRDLManagedTensorVersioned,
) -> RKRStatus {
    if frame_handle.is_null() || out_tensor.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    unsafe { *out_tensor = std::ptr::null_mut() };
    let o = match resolve_dlpack_opts(opts) {
        Ok(o) => o,
        Err(st) => return st,
    };
    let Some(frame) = (unsafe { (frame_handle as *const ConFrame).as_ref() }) else {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    };
    let arr = frame_positions_arc(frame);
    export_owned_array2_dlpack_opts(&arr, &o, out_tensor)
}

/// DLPack velocities from a frame, or `SECTION_ABSENT` if missing (f64/CPU).
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_velocities_dlpack(
    frame_handle: *const RKRConFrame,
    out_tensor: *mut *mut RKRDLManagedTensorVersioned,
) -> RKRStatus {
    unsafe { rkr_frame_velocities_dlpack_ex(frame_handle, std::ptr::null(), out_tensor) }
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_velocities_dlpack_ex(
    frame_handle: *const RKRConFrame,
    opts: *const RKRDlpackExportOptions,
    out_tensor: *mut *mut RKRDLManagedTensorVersioned,
) -> RKRStatus {
    if frame_handle.is_null() || out_tensor.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    unsafe { *out_tensor = std::ptr::null_mut() };
    let o = match resolve_dlpack_opts(opts) {
        Ok(o) => o,
        Err(st) => return st,
    };
    let Some(frame) = (unsafe { (frame_handle as *const ConFrame).as_ref() }) else {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    };
    if !frame.has_velocities() {
        return RKRStatus::RKR_STATUS_SECTION_ABSENT;
    }
    let n = frame.atom_data.len();
    let mut data = Vec::with_capacity(n * 3);
    for a in &frame.atom_data {
        let v = a.velocity.unwrap_or([0.0; 3]);
        data.extend_from_slice(&v);
    }
    let arr = ndarray::ArcArray2::from_shape_vec((n, 3), data)
        .unwrap_or_else(|_| ndarray::ArcArray2::zeros((0, 3)));
    export_owned_array2_dlpack_opts(&arr, &o, out_tensor)
}

/// DLPack forces from a frame, or `SECTION_ABSENT` if missing (f64/CPU default).
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_forces_dlpack(
    frame_handle: *const RKRConFrame,
    out_tensor: *mut *mut RKRDLManagedTensorVersioned,
) -> RKRStatus {
    unsafe { rkr_frame_forces_dlpack_ex(frame_handle, std::ptr::null(), out_tensor) }
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_forces_dlpack_ex(
    frame_handle: *const RKRConFrame,
    opts: *const RKRDlpackExportOptions,
    out_tensor: *mut *mut RKRDLManagedTensorVersioned,
) -> RKRStatus {
    if frame_handle.is_null() || out_tensor.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    unsafe { *out_tensor = std::ptr::null_mut() };
    let o = match resolve_dlpack_opts(opts) {
        Ok(o) => o,
        Err(st) => return st,
    };
    let Some(frame) = (unsafe { (frame_handle as *const ConFrame).as_ref() }) else {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    };
    if !frame.has_forces() {
        return RKRStatus::RKR_STATUS_SECTION_ABSENT;
    }
    let n = frame.atom_data.len();
    let mut data = Vec::with_capacity(n * 3);
    for a in &frame.atom_data {
        let f = a.force.unwrap_or([0.0; 3]);
        data.extend_from_slice(&f);
    }
    let arr = ndarray::ArcArray2::from_shape_vec((n, 3), data)
        .unwrap_or_else(|_| ndarray::ArcArray2::zeros((0, 3)));
    export_owned_array2_dlpack_opts(&arr, &o, out_tensor)
}

/// DLPack per-atom energies, or `SECTION_ABSENT` if missing (f64/CPU default).
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_atom_energies_dlpack(
    frame_handle: *const RKRConFrame,
    out_tensor: *mut *mut RKRDLManagedTensorVersioned,
) -> RKRStatus {
    unsafe { rkr_frame_atom_energies_dlpack_ex(frame_handle, std::ptr::null(), out_tensor) }
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_atom_energies_dlpack_ex(
    frame_handle: *const RKRConFrame,
    opts: *const RKRDlpackExportOptions,
    out_tensor: *mut *mut RKRDLManagedTensorVersioned,
) -> RKRStatus {
    if frame_handle.is_null() || out_tensor.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    unsafe { *out_tensor = std::ptr::null_mut() };
    let o = match resolve_dlpack_opts(opts) {
        Ok(o) => o,
        Err(st) => return st,
    };
    let Some(frame) = (unsafe { (frame_handle as *const ConFrame).as_ref() }) else {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    };
    if !frame.has_energies() {
        return RKRStatus::RKR_STATUS_SECTION_ABSENT;
    }
    let data: Vec<f64> = frame
        .atom_data
        .iter()
        .map(|a| a.energy.unwrap_or(0.0))
        .collect();
    let arr = ndarray::ArcArray1::from_vec(data);
    export_owned_array1_f64_dlpack_opts(&arr, &o, out_tensor)
}

// Chemfiles selection (always linked; real impl needs --features chemfiles)
//=============================================================================
/// Opaque handle for a cached selection evaluation result.
pub struct RKRSelectionResult;
/// Evaluate a chemfiles selection-language string on an `RKRConFrame`.
///
/// On success writes a heap-allocated result handle to `*out_result` (caller
/// frees with [`rkr_selection_result_free`]). Returns
/// `RKR_STATUS_SELECTION_ERROR` for invalid grammar, evaluation failure, or
/// when this build was compiled without the `chemfiles` feature.
///
/// # Safety
/// `frame_handle`, `selection`, and `out_result` must be non-null; `selection`
/// must point to a valid UTF-8 C string.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_frame_select(
    frame_handle: *const RKRConFrame,
    selection: *const c_char,
    out_result: *mut *mut RKRSelectionResult,
) -> RKRStatus {
    if frame_handle.is_null() || selection.is_null() || out_result.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let frame = unsafe { &*(frame_handle as *const ConFrame) };
    let sel_str = match unsafe { CStr::from_ptr(selection) }.to_str() {
        Ok(s) => s,
        Err(_) => return RKRStatus::RKR_STATUS_INVALID_UTF8,
    };
    match crate::chemfiles_selection::evaluate_selection_on_con_frame(sel_str, frame) {
        Ok(result) => {
            let boxed = Box::new(result);
            unsafe {
                *out_result = Box::into_raw(boxed) as *mut RKRSelectionResult;
            }
            RKRStatus::RKR_STATUS_SUCCESS
        }
        Err(_) => RKRStatus::RKR_STATUS_SELECTION_ERROR,
    }
}
/// Number of matches in a selection result.
///
/// # Safety
/// `result_handle` must be a valid handle from [`rkr_frame_select`] or NULL.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_selection_result_match_count(
    result_handle: *const RKRSelectionResult,
) -> u64 {
    if result_handle.is_null() {
        return 0;
    }
    let result =
        unsafe { &*(result_handle as *const crate::chemfiles_selection::SelectionResult) };
    result.matches.len() as u64
}
/// Selection context size (1=atom, 2=pair, 3=angle, 4=dihedral).
///
/// # Safety
/// `result_handle` must be valid or NULL (returns 0).
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_selection_result_context_size(
    result_handle: *const RKRSelectionResult,
) -> u32 {
    if result_handle.is_null() {
        return 0;
    }
    let result =
        unsafe { &*(result_handle as *const crate::chemfiles_selection::SelectionResult) };
    result.context_size as u32
}
/// Copy match `match_index` atom indices into `out_atoms` (up to 4 slots).
/// Writes actual arity to `*out_size` when non-null.
///
/// # Safety
/// Handles and `out_atoms` must be valid; `out_atoms` needs space for 4 `uint64_t`.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_selection_result_match_at(
    result_handle: *const RKRSelectionResult,
    match_index: u64,
    out_atoms: *mut u64,
    out_size: *mut u32,
) -> RKRStatus {
    if result_handle.is_null() || out_atoms.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let result =
        unsafe { &*(result_handle as *const crate::chemfiles_selection::SelectionResult) };
    let idx = match_index as usize;
    if idx >= result.matches.len() {
        return RKRStatus::RKR_STATUS_INDEX_OUT_OF_BOUNDS;
    }
    let m = &result.matches[idx];
    unsafe {
        for i in 0..4 {
            *out_atoms.add(i) = if i < m.size {
                m.atoms[i] as u64
            } else {
                u64::MAX
            };
        }
        if !out_size.is_null() {
            *out_size = m.size as u32;
        }
    }
    RKRStatus::RKR_STATUS_SUCCESS
}
/// Fill `out_indices` with primary atom indices for each match (length =
/// match count). Returns `RKR_STATUS_BUFFER_TOO_SMALL` if `capacity` is too small.
///
/// # Safety
/// `result_handle` and `out_indices` must be valid when capacity > 0.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_selection_result_primary_indices(
    result_handle: *const RKRSelectionResult,
    out_indices: *mut u64,
    capacity: u64,
    out_written: *mut u64,
) -> RKRStatus {
    if result_handle.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    let result =
        unsafe { &*(result_handle as *const crate::chemfiles_selection::SelectionResult) };
    let n = result.matches.len() as u64;
    if !out_written.is_null() {
        unsafe {
            *out_written = n;
        }
    }
    if n == 0 {
        return RKRStatus::RKR_STATUS_SUCCESS;
    }
    if out_indices.is_null() {
        return RKRStatus::RKR_STATUS_NULL_POINTER;
    }
    if capacity < n {
        return RKRStatus::RKR_STATUS_BUFFER_TOO_SMALL;
    }
    unsafe {
        for (i, m) in result.matches.iter().enumerate() {
            *out_indices.add(i) = m.atoms[0] as u64;
        }
    }
    RKRStatus::RKR_STATUS_SUCCESS
}
/// Free a selection result from [`rkr_frame_select`]. Safe with NULL.
///
/// # Safety
/// `result_handle` must be from `rkr_frame_select` or NULL.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_selection_result_free(result_handle: *mut RKRSelectionResult) {
    if result_handle.is_null() {
        return;
    }
    unsafe {
        drop(Box::from_raw(
            result_handle as *mut crate::chemfiles_selection::SelectionResult,
        ));
    }
}
/// Returns 1 when this library build includes chemfiles selection support.
#[unsafe(no_mangle)]
pub extern "C" fn rkr_has_chemfiles_support() -> u8 {
    #[cfg(feature = "chemfiles")]
    {
        1
    }
    #[cfg(not(feature = "chemfiles"))]
    {
        0
    }
}
/// Read the first frame from a chemfiles-supported path (XYZ, PDB, GRO, …).
/// Returns NULL on error or without the `chemfiles` feature. Caller: `free_rkr_frame`.
///
/// # Safety
/// `path_c` must be a valid NUL-terminated UTF-8 path.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_read_chemfiles_first(path_c: *const c_char) -> *mut RKRConFrame {
    if path_c.is_null() {
        return std::ptr::null_mut();
    }
    let Ok(path_str) = unsafe { CStr::from_ptr(path_c) }.to_str() else {
        return std::ptr::null_mut();
    };
    match crate::chemfiles_import::con_frame_from_trajectory_path(path_str) {
        Ok(frame) => Box::into_raw(Box::new(frame)) as *mut RKRConFrame,
        Err(_) => std::ptr::null_mut(),
    }
}
/// Read all frames from memory with chemfiles `format` (e.g. `"XYZ"`).
/// Sets `*num_frames`. Free frames with `free_rkr_frame` and the array with
/// `free_rkr_frame_array`. NULL on error / without chemfiles.
///
/// # Safety
/// `data_c`, `format_c` valid UTF-8 C strings; `num_frames` non-null.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_read_chemfiles_memory(
    data_c: *const c_char,
    format_c: *const c_char,
    num_frames: *mut usize,
) -> *mut *mut RKRConFrame {
    if data_c.is_null() || format_c.is_null() || num_frames.is_null() {
        return std::ptr::null_mut();
    }
    let Ok(data) = unsafe { CStr::from_ptr(data_c) }.to_str() else {
        return std::ptr::null_mut();
    };
    let Ok(format) = unsafe { CStr::from_ptr(format_c) }.to_str() else {
        return std::ptr::null_mut();
    };
    match crate::chemfiles_import::con_frames_from_memory(data, format) {
        Ok(frames) => {
            let n = frames.len();
            unsafe { *num_frames = n };
            let mut ptrs: Vec<*mut RKRConFrame> = frames
                .into_iter()
                .map(|f| Box::into_raw(Box::new(f)) as *mut RKRConFrame)
                .collect();
            let p = ptrs.as_mut_ptr();
            std::mem::forget(ptrs);
            p
        }
        Err(_) => std::ptr::null_mut(),
    }
}
/// Free a DLPack tensor from `rkr_frame_builder_*_dlpack` (calls deleter). Safe with NULL.
///
/// # Safety
/// `tensor` must be NULL or a pointer from a dlpack export of this library.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_dlpack_delete(tensor: *mut RKRDLManagedTensorVersioned) {
    if tensor.is_null() {
        return;
    }
    unsafe {
        let t = &mut *tensor;
        if let Some(del) = t.deleter {
            del(tensor);
        }
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    use std::ffi::{CStr, CString};
    #[test]
    fn frame_copy_positions_without_cframe() {
        let handle = test_frame_handle();
        let n = unsafe { rkr_frame_atom_count(handle) };
        assert_eq!(n, 1);
        let mut buf = vec![0.0f64; n * 3];
        assert_eq!(
            unsafe { rkr_frame_copy_positions(handle, buf.as_mut_ptr(), buf.len()) },
            RKRStatus::RKR_STATUS_SUCCESS
        );
        let mut tensor: *mut RKRDLManagedTensorVersioned = std::ptr::null_mut();
        assert_eq!(
            unsafe { rkr_frame_positions_dlpack(handle, &mut tensor) },
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert!(!tensor.is_null());
        unsafe { rkr_dlpack_delete(tensor) };
        assert_eq!(
            unsafe { rkr_frame_copy_velocities(handle, buf.as_mut_ptr(), buf.len()) },
            RKRStatus::RKR_STATUS_SECTION_ABSENT
        );
        unsafe { free_rkr_frame(handle) };
    }
    #[test]
    fn read_all_frames_c_abi_tiny() {
        let path = std::ffi::CString::new("resources/test/tiny_cuh2.con").unwrap();
        let mut n: usize = 0;
        let arr = unsafe { rkr_read_all_frames(path.as_ptr(), &mut n) };
        assert!(!arr.is_null() && n >= 1);
        let first = unsafe { *arr };
        let nat = unsafe { rkr_frame_atom_count(first) };
        let mut buf = vec![0.0f64; nat * 3];
        assert_eq!(
            unsafe { rkr_frame_copy_positions(first, buf.as_mut_ptr(), buf.len()) },
            RKRStatus::RKR_STATUS_SUCCESS
        );
        unsafe { free_rkr_frame_array(arr, n) };
    }

    #[test]
    fn free_rkr_frame_ptr_array_keeps_frames() {
        let path = std::ffi::CString::new("resources/test/tiny_cuh2.con").unwrap();
        let mut n: usize = 0;
        let arr = unsafe { rkr_read_all_frames(path.as_ptr(), &mut n) };
        assert!(!arr.is_null() && n >= 1);
        let first = unsafe { *arr };
        // free only outer array; first frame remains owned
        let rest: Vec<*mut RKRConFrame> = (1..n).map(|i| unsafe { *arr.add(i) }).collect();
        unsafe { free_rkr_frame_ptr_array(arr, n) };
        assert!(unsafe { rkr_frame_atom_count(first) } >= 1);
        unsafe { free_rkr_frame(first) };
        for h in rest {
            if !h.is_null() {
                unsafe { free_rkr_frame(h) };
            }
        }
    }
    fn test_frame_handle() -> *mut RKRConFrame {
        let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
        builder
            .prebox_header("Generated by test")
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
            (RKRStatus::RKR_STATUS_SECTION_ABSENT, "section absent"),
            (RKRStatus::RKR_STATUS_VALIDATION_ERROR, "validation error"),
            (RKRStatus::RKR_STATUS_SELECTION_ERROR, "selection error"),
            (
                RKRStatus::RKR_STATUS_FEATURE_DISABLED,
                "feature disabled in this build",
            ),
        ];
        for (status, expected) in cases {
            let message = unsafe { CStr::from_ptr(rkr_status_message(status)) };
            assert_eq!(message.to_str().unwrap(), expected);
        }
    }
    // ----- DLPack FFI smoke tests ----------------------------------------------
    /// Assert DLPack tensor layout without assuming the host language uses f64
    /// buffers — consumers must read `dtype` / `ndim` / `shape` from the tensor.
    unsafe fn assert_dlpack_cpu_float(
        t: *mut RKRDLManagedTensorVersioned,
        expect_ndim: i32,
        expect_shape: &[i64],
        expect_bits: u8,
    ) {
        assert!(!t.is_null());
        let dl = unsafe { &(*t).dl_tensor };
        assert_eq!(dl.ndim, expect_ndim);
        let shape = unsafe { std::slice::from_raw_parts(dl.shape, expect_ndim as usize) };
        assert_eq!(shape, expect_shape);
        assert_eq!(dl.dtype.code, dlpk::sys::DLDataTypeCode::kDLFloat);
        assert_eq!(dl.dtype.bits, expect_bits);
        assert_eq!(dl.dtype.lanes, 1);
        assert_eq!(dl.device, dlpk::sys::DLDevice::cpu());
        assert!(!dl.data.is_null());
    }

    #[test]
    fn frame_optional_section_dlpack_present_and_absent() {
        // Absent on coordinate-only frame
        let handle = test_frame_handle();
        let mut t: *mut RKRDLManagedTensorVersioned = std::ptr::null_mut();
        assert_eq!(
            unsafe { rkr_frame_velocities_dlpack(handle, &mut t) },
            RKRStatus::RKR_STATUS_SECTION_ABSENT
        );
        assert!(t.is_null());
        assert_eq!(
            unsafe { rkr_frame_forces_dlpack(handle, &mut t) },
            RKRStatus::RKR_STATUS_SECTION_ABSENT
        );
        assert_eq!(
            unsafe { rkr_frame_atom_energies_dlpack(handle, &mut t) },
            RKRStatus::RKR_STATUS_SECTION_ABSENT
        );
        unsafe { free_rkr_frame(handle) };

        // Present on .convel fixture — (N, 3) float, N from atom_count
        let path = CString::new("resources/test/tiny_cuh2.convel").unwrap();
        let fr = unsafe { rkr_read_first_frame(path.as_ptr()) };
        assert!(!fr.is_null());
        let n = unsafe { rkr_frame_atom_count(fr) } as i64;
        assert!(n > 0);
        let mut vel: *mut RKRDLManagedTensorVersioned = std::ptr::null_mut();
        let st = unsafe { rkr_frame_velocities_dlpack(fr, &mut vel) };
        assert_eq!(st, RKRStatus::RKR_STATUS_SUCCESS);
        unsafe {
            assert_dlpack_cpu_float(vel, 2, &[n, 3], 64);
            rkr_dlpack_delete(vel);
            free_rkr_frame(fr);
        }

        // Forces (N,3) + energies (N,) via builder → frame
        let cell = [10.0f64; 3];
        let ang = [90.0f64; 3];
        let b = unsafe {
            rkr_frame_new(
                cell.as_ptr(),
                ang.as_ptr(),
                std::ptr::null(),
                std::ptr::null(),
                std::ptr::null(),
                std::ptr::null(),
            )
        };
        assert!(!b.is_null());
        let sym = CString::new("H").unwrap();
        unsafe {
            rkr_frame_add_atom_with_velocity_and_forces_fixed_mask(
                b,
                sym.as_ptr(),
                0.0,
                0.0,
                0.0,
                false,
                false,
                false,
                0,
                1.0,
                0.1,
                0.0,
                0.0,
                0.0,
                0.0,
                -1.0,
            );
            rkr_frame_builder_set_last_energy(b, -0.5);
        }
        let built = unsafe { rkr_frame_builder_build(b) };
        assert!(!built.is_null());
        let n_built = unsafe { rkr_frame_atom_count(built) } as i64;
        let mut frc: *mut RKRDLManagedTensorVersioned = std::ptr::null_mut();
        let mut eng: *mut RKRDLManagedTensorVersioned = std::ptr::null_mut();
        assert_eq!(
            unsafe { rkr_frame_forces_dlpack(built, &mut frc) },
            RKRStatus::RKR_STATUS_SUCCESS
        );
        unsafe { assert_dlpack_cpu_float(frc, 2, &[n_built, 3], 64) };
        assert_eq!(
            unsafe { rkr_frame_atom_energies_dlpack(built, &mut eng) },
            RKRStatus::RKR_STATUS_SUCCESS
        );
        unsafe { assert_dlpack_cpu_float(eng, 1, &[n_built], 64) };
        // Explicit f32 export via options (caller-chosen precision)
        let opts32 = RKRDlpackExportOptions {
            float_bits: 32,
            device_type: 1,
            device_id: 0,
        };
        let mut pos32: *mut RKRDLManagedTensorVersioned = std::ptr::null_mut();
        assert_eq!(
            unsafe { rkr_frame_positions_dlpack_ex(built, &opts32, &mut pos32) },
            RKRStatus::RKR_STATUS_SUCCESS
        );
        unsafe {
            assert_dlpack_cpu_float(pos32, 2, &[n_built, 3], 32);
            rkr_dlpack_delete(pos32);
        }
        // Reject unsupported device / bits
        let bad_dev = RKRDlpackExportOptions {
            float_bits: 64,
            device_type: 2,
            device_id: 0,
        };
        let mut junk: *mut RKRDLManagedTensorVersioned = std::ptr::null_mut();
        assert_eq!(
            unsafe { rkr_frame_positions_dlpack_ex(built, &bad_dev, &mut junk) },
            RKRStatus::RKR_STATUS_VALIDATION_ERROR
        );
        let bad_bits = RKRDlpackExportOptions {
            float_bits: 16,
            device_type: 1,
            device_id: 0,
        };
        assert_eq!(
            unsafe { rkr_frame_positions_dlpack_ex(built, &bad_bits, &mut junk) },
            RKRStatus::RKR_STATUS_VALIDATION_ERROR
        );
        unsafe {
            rkr_dlpack_delete(frc);
            rkr_dlpack_delete(eng);
            free_rkr_frame(built);
        }
    }

    #[test]
    fn ffi_positions_dlpack_round_trip() {
        let handle = test_builder_handle();
        let sym = c_string("Cu");
        unsafe {
            rkr_frame_add_atom_full(
                handle,
                sym.as_ptr(),
                1.0,
                2.0,
                3.0,
                false,
                false,
                false,
                7,
                63.5,
                ptr::null(),
                ptr::null(),
            )
        };
        let mut t: *mut RKRDLManagedTensorVersioned = ptr::null_mut();
        let status = unsafe { rkr_frame_builder_positions_dlpack(handle, &mut t) };
        assert_eq!(status, RKRStatus::RKR_STATUS_SUCCESS);
        assert!(!t.is_null());
        // Inspect the DLPack tensor: shape (1, 3), dtype kDLFloat / 64, CPU.
        let dl = unsafe { &(*t).dl_tensor };
        assert_eq!(dl.ndim, 2);
        let shape = unsafe { std::slice::from_raw_parts(dl.shape, 2) };
        assert_eq!(shape, &[1, 3]);
        assert_eq!(dl.dtype.code, dlpk::sys::DLDataTypeCode::kDLFloat);
        assert_eq!(dl.dtype.bits, 64);
        assert_eq!(dl.dtype.lanes, 1);
        assert_eq!(dl.device, dlpk::sys::DLDevice::cpu());
        let data = unsafe { std::slice::from_raw_parts(dl.data as *const f64, 3) };
        assert_eq!(data, &[1.0, 2.0, 3.0]);
        // Invoke the deleter the same way a C consumer would.
        let deleter = unsafe { (*t).deleter };
        if let Some(del) = deleter {
            unsafe { del(t) };
        }
        unsafe { free_rkr_frame_builder(handle) };
    }
    #[test]
    fn ffi_velocities_dlpack_section_absent() {
        let handle = test_builder_handle();
        let sym = c_string("Cu");
        unsafe {
            rkr_frame_add_atom_full(
                handle,
                sym.as_ptr(),
                0.0,
                0.0,
                0.0,
                false,
                false,
                false,
                0,
                63.5,
                ptr::null(),
                ptr::null(),
            )
        };
        let mut t: *mut RKRDLManagedTensorVersioned = ptr::null_mut();
        let status = unsafe { rkr_frame_builder_velocities_dlpack(handle, &mut t) };
        assert_eq!(status, RKRStatus::RKR_STATUS_SECTION_ABSENT);
        assert!(t.is_null());
        unsafe { free_rkr_frame_builder(handle) };
    }
    #[test]
    fn ffi_dlpack_null_handle_rejects() {
        let mut t: *mut RKRDLManagedTensorVersioned = ptr::null_mut();
        let status = unsafe { rkr_frame_builder_positions_dlpack(ptr::null(), &mut t) };
        assert_eq!(status, RKRStatus::RKR_STATUS_NULL_POINTER);
        assert!(t.is_null());
    }
    #[cfg(feature = "chemfiles")]
    #[test]
    fn rkr_frame_select_finds_oxygen() {
        use crate::types::ConFrameBuilder;
        let mut b = ConFrameBuilder::new([10.0; 3], [90.0; 3]);
        b.add_atom("O", 0.0, 0.0, 0.0, [false; 3], 0, 16.0);
        b.add_atom("H", 1.0, 0.0, 0.0, [false; 3], 1, 1.0);
        let frame = b.build();
        let frame_ptr = Box::into_raw(Box::new(frame)) as *mut RKRConFrame;
        let sel = CString::new("name O").unwrap();
        let mut out: *mut RKRSelectionResult = ptr::null_mut();
        let st = unsafe { rkr_frame_select(frame_ptr, sel.as_ptr(), &mut out) };
        assert_eq!(st, RKRStatus::RKR_STATUS_SUCCESS);
        assert!(!out.is_null());
        let n = unsafe { rkr_selection_result_match_count(out) };
        assert_eq!(n, 1);
        let mut atoms = [u64::MAX; 4];
        let mut size = 0u32;
        let st2 = unsafe { rkr_selection_result_match_at(out, 0, atoms.as_mut_ptr(), &mut size) };
        assert_eq!(st2, RKRStatus::RKR_STATUS_SUCCESS);
        assert_eq!(size, 1);
        assert_eq!(atoms[0], 0);
        unsafe {
            rkr_selection_result_free(out);
            free_rkr_frame(frame_ptr);
        }
    }
        /// C surface: chemfiles selection.cpp chain topology via `rkr_frame_select`.
    #[cfg(feature = "chemfiles")]
    #[test]
    fn rkr_frame_select_cpp_topology_bonds_angles_dihedrals() {
        use crate::types::{Bond, ConFrameBuilder};
        // H-O-O-H chain (chemfiles testing_frame topology), bonds in atom_data order.
        let mut b = ConFrameBuilder::new([10.0; 3], [90.0; 3]);
        b.add_atom("H", 0.0, 1.0, 2.0, [false; 3], 0, 1.0);
        b.add_atom("O", 1.0, 2.0, 3.0, [false; 3], 1, 16.0);
        b.add_atom("O", 2.0, 3.0, 4.0, [false; 3], 2, 16.0);
        b.add_atom("H", 3.0, 4.0, 5.0, [false; 3], 3, 1.0);
        let mut frame = b.build();
        let id_to = |id: u64| {
            frame
                .atom_data
                .iter()
                .position(|a| a.atom_id == id)
                .unwrap() as u32
        };
        frame.header.set_bonds(&[
            Bond::new(id_to(0), id_to(1)),
            Bond::new(id_to(1), id_to(2)),
            Bond::new(id_to(2), id_to(3)),
        ]);
        let frame_ptr = Box::into_raw(Box::new(frame)) as *mut RKRConFrame;
        let run = |sel: &str| -> (u64, u32) {
            let csel = CString::new(sel).unwrap();
            let mut out: *mut RKRSelectionResult = ptr::null_mut();
            let st = unsafe { rkr_frame_select(frame_ptr, csel.as_ptr(), &mut out) };
            assert_eq!(st, RKRStatus::RKR_STATUS_SUCCESS, "select failed: {sel}");
            let n = unsafe { rkr_selection_result_match_count(out) };
            let ctx = unsafe { rkr_selection_result_context_size(out) };
            unsafe { rkr_selection_result_free(out) };
            (n, ctx)
        };
        assert_eq!(run("bonds: all"), (3, 2));
        assert_eq!(run("angles: all"), (2, 3));
        assert_eq!(run("dihedrals: all"), (1, 4));
        assert_eq!(run("bonds: name(#1) O and type(#2) H").0, 2);
        assert_eq!(
            run("two: type(#1) H and name(#2) O and is_bonded(#1, #2)").0,
            run("bonds: type(#1) H and name(#2) O").0
        );
        unsafe { free_rkr_frame(frame_ptr) };
    }
    #[cfg(feature = "metatensor")]
    fn assert_mts_block_shape(block: *mut metatensor::c_api::mts_block_t, n: usize, props: usize) {
        assert!(!block.is_null());
        let mut array = unsafe { std::mem::zeroed::<metatensor::c_api::mts_array_t>() };
        let status = unsafe { metatensor::c_api::mts_block_data(block, &mut array) };
        assert_eq!(status, metatensor::c_api::MTS_SUCCESS);
        let shape_fn = array.shape.expect("mts_array_t.shape from metatensor C API");
        let mut shape_ptr: *const usize = std::ptr::null();
        let mut shape_count: usize = 0;
        let st_shape = unsafe { shape_fn(array.ptr, &mut shape_ptr, &mut shape_count) };
        assert_eq!(st_shape, metatensor::c_api::MTS_SUCCESS);
        assert_eq!(shape_count, 2);
        let shape = unsafe { std::slice::from_raw_parts(shape_ptr, shape_count) };
        assert_eq!(shape[0], n);
        assert_eq!(shape[1], props);
        let samples = unsafe { metatensor::c_api::mts_block_labels(block, 0) };
        let prop_lab = unsafe { metatensor::c_api::mts_block_labels(block, 1) };
        assert!(!samples.is_null() && !prop_lab.is_null());
    }
    #[cfg(feature = "metatensor")]
    #[test]
    fn metatensor_positions_via_c_abi() {
        let handle = test_frame_handle();
        let mut out: *mut metatensor::c_api::mts_block_t = std::ptr::null_mut();
        let st = unsafe { rkr_frame_metatensor_positions_block(handle, &mut out) };
        assert_eq!(st, RKRStatus::RKR_STATUS_SUCCESS);
        assert_mts_block_shape(out, 1, 3);
        unsafe { rkr_mts_block_free(out) };
        for (name, export) in [
            (
                "velocities",
                rkr_frame_metatensor_velocities_block
                    as unsafe extern "C" fn(
                        *const RKRConFrame,
                        *mut *mut metatensor::c_api::mts_block_t,
                    ) -> RKRStatus,
            ),
            (
                "forces",
                rkr_frame_metatensor_forces_block
                    as unsafe extern "C" fn(
                        *const RKRConFrame,
                        *mut *mut metatensor::c_api::mts_block_t,
                    ) -> RKRStatus,
            ),
            (
                "atom_energies",
                rkr_frame_metatensor_atom_energies_block
                    as unsafe extern "C" fn(
                        *const RKRConFrame,
                        *mut *mut metatensor::c_api::mts_block_t,
                    ) -> RKRStatus,
            ),
        ] {
            let mut o: *mut metatensor::c_api::mts_block_t = std::ptr::null_mut();
            let st_abs = unsafe { export(handle, &mut o) };
            assert_eq!(
                st_abs,
                RKRStatus::RKR_STATUS_SECTION_ABSENT,
                "{name} must be SECTION_ABSENT on minimal test frame"
            );
            assert!(o.is_null());
        }
        unsafe { free_rkr_frame(handle) };
    }

    #[cfg(feature = "metatensor")]
    #[test]
    fn metatensor_optional_sections_via_c_abi() {
        // Frame with velocities, forces, and per-atom energies — all four block exports
        let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
        builder.add_atom("H", 0.0, 0.0, 0.0, [false; 3], 1, 1.0);
        builder.add_atom("O", 1.0, 0.0, 0.0, [false; 3], 2, 16.0);
        builder.set_atom_velocity(0, [0.1, 0.2, 0.3]).unwrap();
        builder.set_atom_velocity(1, [0.0, 0.1, 0.0]).unwrap();
        builder.set_atom_force(0, [1.0, 0.0, 0.0]).unwrap();
        builder.set_atom_force(1, [0.0, 1.0, 0.0]).unwrap();
        builder.set_atom_energy(0, -0.5).unwrap();
        builder.set_atom_energy(1, -1.0).unwrap();
        let frame = builder.build();
        let handle = Box::into_raw(Box::new(frame)) as *mut RKRConFrame;
        let mut pos: *mut metatensor::c_api::mts_block_t = std::ptr::null_mut();
        assert_eq!(
            unsafe { rkr_frame_metatensor_positions_block(handle, &mut pos) },
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_mts_block_shape(pos, 2, 3);
        unsafe { rkr_mts_block_free(pos) };
        let mut vel: *mut metatensor::c_api::mts_block_t = std::ptr::null_mut();
        assert_eq!(
            unsafe { rkr_frame_metatensor_velocities_block(handle, &mut vel) },
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_mts_block_shape(vel, 2, 3);
        unsafe { rkr_mts_block_free(vel) };
        let mut frc: *mut metatensor::c_api::mts_block_t = std::ptr::null_mut();
        assert_eq!(
            unsafe { rkr_frame_metatensor_forces_block(handle, &mut frc) },
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_mts_block_shape(frc, 2, 3);
        unsafe { rkr_mts_block_free(frc) };
        let mut eng: *mut metatensor::c_api::mts_block_t = std::ptr::null_mut();
        assert_eq!(
            unsafe { rkr_frame_metatensor_atom_energies_block(handle, &mut eng) },
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_mts_block_shape(eng, 2, 1);
        unsafe { rkr_mts_block_free(eng) };
        unsafe { free_rkr_frame(handle) };
    }

    #[test]
    fn string_iterator_yields_frames_from_buffer() {
        let text = std::fs::read_to_string("resources/test/tiny_cuh2.con")
            .expect("fixture tiny_cuh2.con");
        let c_text = CString::new(text.as_str()).unwrap();
        let it = unsafe { read_con_string_iterator(c_text.as_ptr()) };
        assert!(!it.is_null());
        let mut n = 0usize;
        loop {
            let fr = unsafe { con_frame_iterator_next(it) };
            if fr.is_null() {
                break;
            }
            n += 1;
            unsafe { free_rkr_frame(fr) };
        }
        unsafe { free_con_frame_iterator(it) };
        assert!(n >= 1, "string iterator should yield >=1 frame");

        let bytes = text.as_bytes();
        let it2 = unsafe { read_con_buffer_iterator(bytes.as_ptr(), bytes.len()) };
        assert!(!it2.is_null());
        let fr2 = unsafe { con_frame_iterator_next(it2) };
        assert!(!fr2.is_null());
        unsafe {
            free_rkr_frame(fr2);
            free_con_frame_iterator(it2);
        }
    }

    #[test]
    fn file_iterator_reads_gzip_when_present() {
        use flate2::write::GzEncoder;
        use flate2::Compression;
        use std::io::Write;
        let plain = std::fs::read("resources/test/tiny_cuh2.con").expect("fixture");
        let dir = tempfile::tempdir().expect("tempdir");
        let gz_path = dir.path().join("tiny_cuh2.con.gz");
        {
            let f = std::fs::File::create(&gz_path).unwrap();
            let mut enc = GzEncoder::new(f, Compression::default());
            enc.write_all(&plain).unwrap();
            enc.finish().unwrap();
        }
        let c_path = CString::new(gz_path.to_str().unwrap()).unwrap();
        let it = unsafe { read_con_file_iterator(c_path.as_ptr()) };
        assert!(
            !it.is_null(),
            "path iterator must decompress .con.gz transparently"
        );
        let fr = unsafe { con_frame_iterator_next(it) };
        assert!(!fr.is_null());
        let n = unsafe { rkr_frame_atom_count(fr) };
        assert!(n > 0);
        unsafe {
            free_rkr_frame(fr);
            free_con_frame_iterator(it);
        }
    }
}
