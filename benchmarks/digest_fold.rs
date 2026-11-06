//! Sequential touch digest over frame coordinate pointers.
//!
//! Symbols and cell lengths are shared by every frame in the repeated
//! fixture. Positions are per frame. The mix matches the library touch.

fn mix(hash: u64, value: u64) -> u64 {
    hash.wrapping_mul(0x9E3779B185EBCA87) ^ value
}

#[no_mangle]
pub extern "C" fn fold_shared_symbols(
    n_frames: u64,
    n_coords: u64,
    coord_ptrs: *const *const u8,
    n_atoms: u64,
    sym_lens: *const u64,
    sym_ptrs: *const *const u8,
    cell0: u64,
    cell1: u64,
    cell2: u64,
) -> u64 {
    let mut acc = 0u64;
    let frames = n_frames as usize;
    let coords_n = n_coords as usize;
    let atoms = n_atoms as usize;
    for index in 0..frames {
        let mut hash = index as u64;
        hash = mix(hash, cell0);
        hash = mix(hash, cell1);
        hash = mix(hash, cell2);
        for atom in 0..atoms {
            let len = unsafe { *sym_lens.add(atom) };
            let ptr = unsafe { *sym_ptrs.add(atom) };
            hash = mix(hash, len);
            for byte_i in 0..len as usize {
                let byte = unsafe { *ptr.add(byte_i) };
                hash = mix(hash, u64::from(byte));
            }
        }
        let base = unsafe { *coord_ptrs.add(index) };
        for coord_i in 0..coords_n {
            let bits = unsafe { *(base as *const u64).add(coord_i) };
            hash = mix(hash, bits);
        }
        acc ^= hash;
    }
    acc
}
