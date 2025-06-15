use crate::helpers::symbol_to_atomic_number;
use crate::iterators::ConFrameIterator;
use std::ffi::{c_char, CStr};
use std::ptr;

#[repr(C)]
pub struct CAtom {
    pub atomic_number: u64,
    pub x: f64,
    pub y: f64,
    pub z: f64,
    pub atom_id: u64,
    pub mass: f64,
    pub is_fixed: bool, // must be here for padding issues
}

#[repr(C)]
pub struct CFrame {
    pub atoms: *const CAtom,
    pub num_atoms: usize,
    pub cell: [f64; 3],
    pub angles: [f64; 3],
}

/// Takes a C-style string symbol and returns the corresponding atomic number.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rust_symbol_to_atomic_number(symbol_c: *const c_char) -> u64 {
    if symbol_c.is_null() {
        return 0;
    }
    let symbol_str = match unsafe { CStr::from_ptr(symbol_c).to_str() } {
        Ok(s) => s,
        Err(_) => return 0,
    };
    symbol_to_atomic_number(symbol_str)
}

/// Parses a .con file and returns a pointer to a CFrame struct.
///
/// The caller OWNS the returned pointer and MUST call free_con_frame()
/// on it to prevent a memory leak.
/// Returns a null pointer on error.
/// This function is `unsafe` because it dereferences a raw C pointer.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn read_con_file(filename_c: *const c_char) -> *mut CFrame {
    // Safely convert the C string to a Rust string inside an unsafe block
    let filename = unsafe {
        if filename_c.is_null() {
            return ptr::null_mut();
        }
        match CStr::from_ptr(filename_c).to_str() {
            Ok(s) => s,
            Err(_) => return ptr::null_mut(),
        }
    };

    let file_contents = match std::fs::read_to_string(filename) {
        Ok(contents) => contents,
        Err(_) => return ptr::null_mut(),
    };

    let mut iterator = ConFrameIterator::new(&file_contents);
    let parsed_frame = match iterator.next() {
        Some(Ok(frame)) => frame,
        _ => return ptr::null_mut(), // Return null on parse error or if empty
    };

    // --- Convert the Rust data into C-compatible data ---
    // Iterate through each component type to get the correct mass
    // Create a flat iterator that yields the correct mass for each atom in order.
    let masses_iter = parsed_frame
        .header
        .natms_per_type
        .iter()
        .zip(parsed_frame.header.masses_per_type.iter())
        .flat_map(|(num_atoms, mass)| std::iter::repeat_n(*mass, *num_atoms));

    // Zip the atom data with its corresponding mass, then map to the C-struct.
    let mut c_atoms: Vec<CAtom> = parsed_frame
        .atom_data
        .into_iter()
        .zip(masses_iter)
        .map(|(atom_datum, mass)| CAtom {
            atomic_number: symbol_to_atomic_number(&atom_datum.symbol),
            x: atom_datum.x,
            y: atom_datum.y,
            z: atom_datum.z,
            is_fixed: atom_datum.is_fixed,
            atom_id: atom_datum.atom_id,
            mass,
        })
        .collect();

    // Turn the Vec<CAtom> into a raw pointer for C.
    // Leaks memory here, giving ownership to the caller.
    let atoms_ptr = c_atoms.as_mut_ptr();
    let num_atoms = c_atoms.len();
    std::mem::forget(c_atoms);

    // Create the final CFrame struct on the heap
    let c_frame = Box::new(CFrame {
        atoms: atoms_ptr,
        num_atoms,
        cell: parsed_frame.header.boxl,
        angles: parsed_frame.header.angles,
    });

    // Give ownership of the CFrame to the C++ caller
    Box::into_raw(c_frame)
}

/// Frees the memory allocated by read_con_file.
///
/// Must be called on any non-null pointer returned by read_con_file.
/// This function is `unsafe` because it deals with raw pointers and memory deallocation.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn free_con_frame(frame: *mut CFrame) {
    if frame.is_null() {
        return;
    }

    unsafe {
        // Retake ownership of the main CFrame struct from the raw pointer.
        let frame_box = Box::from_raw(frame);

        // Retake ownership of the slice of CAtoms.
        let _ = Vec::from_raw_parts(
            frame_box.atoms as *mut CAtom,
            frame_box.num_atoms,
            frame_box.num_atoms,
        );
        // The `frame_box` is dropped automatically at the end of this scope.
        // The `c_atoms_vec` is also dropped here. All memory is now freed.
    }
}
