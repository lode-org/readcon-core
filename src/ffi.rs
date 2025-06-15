use crate::iterators::ConFrameIterator;
use std::ffi::{c_char, CStr, CString};
use std::ptr;

#[repr(C)]
pub struct CAtom {
    pub symbol: *const c_char,
    pub x: f64,
    pub y: f64,
    pub z: f64,
    pub is_fixed: bool,
    pub atom_id: u64,
    pub mass: f64,
}

#[repr(C)]
pub struct CFrame {
    pub atoms: *const CAtom,
    pub num_atoms: usize,
    pub cell: [f64; 3],
    pub angles: [f64; 3],
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
    let mut c_atoms: Vec<CAtom> = Vec::with_capacity(parsed_frame.atom_data.len());
    let mut atom_cursor = 0;
    // Iterate through each component type to get the correct mass
    for (component_index, num_atoms_in_component) in
        parsed_frame.header.natms_per_type.iter().enumerate()
    {
        // Get the mass for this specific component
        let component_mass = parsed_frame.header.masses_per_type[component_index];

        // Assign this mass to all atoms of this component
        for _ in 0..*num_atoms_in_component {
            let atom_datum = &parsed_frame.atom_data[atom_cursor];
            let symbol_cstr = CString::new(atom_datum.symbol.clone()).unwrap();

            c_atoms.push(CAtom {
                symbol: symbol_cstr.into_raw(),
                x: atom_datum.x,
                y: atom_datum.y,
                z: atom_datum.z,
                is_fixed: atom_datum.is_fixed,
                atom_id: atom_datum.atom_id,
                mass: component_mass,
            });
            atom_cursor += 1;
        }
    }

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
        let c_atoms_vec = Vec::from_raw_parts(
            frame_box.atoms as *mut CAtom,
            frame_box.num_atoms,
            frame_box.num_atoms,
        );

        // Third, iterate through the vec and retake ownership of each CString
        // so it can be properly dropped (deallocated).
        for atom in c_atoms_vec {
            let _ = CString::from_raw(atom.symbol as *mut c_char);
        }

        // The `frame_box` is dropped automatically at the end of this scope.
        // The `c_atoms_vec` is also dropped here. All memory is now freed.
    }
}
