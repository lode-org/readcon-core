//! Byte and string readers the Python bindings call.
//!
//! `read_con_string` parses with `frames_from_bytes_phased` and, for a
//! UTF-8 failure, reports the located text error. `ConFrameIterator::from_bytes`
//! is the from-bytes iterator. A successful byte parse and a successful
//! string parse of the same text must carry the same coordinates.

#![no_main]

use libfuzzer_sys::fuzz_target;
use readcon_core::iterators::{
    ConFrameIterator, frames_from_bytes, frames_from_bytes_phased, frames_from_text,
};
use readcon_core::types::ConFrame;

fn coord_bits(frames: &[ConFrame]) -> Vec<u64> {
    let mut bits = Vec::new();
    for frame in frames {
        for atom in &frame.atom_data {
            bits.push(atom.x().to_bits());
            bits.push(atom.y().to_bits());
            bits.push(atom.z().to_bits());
        }
    }
    bits
}

fn same(left: &[ConFrame], right: &[ConFrame]) {
    assert_eq!(left.len(), right.len());
    assert_eq!(coord_bits(left), coord_bits(right));
    for (left, right) in left.iter().zip(right.iter()) {
        assert_eq!(left.atom_data.len(), right.atom_data.len());
        assert_eq!(left.header.natms_per_type, right.header.natms_per_type);
    }
}

fuzz_target!(|data: &[u8]| {
    if data.len() > 64 * 1024 {
        return;
    }
    let mut walked = 0usize;
    for item in ConFrameIterator::from_bytes(data) {
        if let Ok(frame) = item {
            std::hint::black_box(frame.atom_data.len());
        }
        walked += 1;
        if walked > 128 {
            break;
        }
    }

    let serial = frames_from_bytes(data, Some(1));
    let phased = frames_from_bytes_phased(data, Some(1));
    let parallel = frames_from_bytes(data, Some(4));
    let phased_parallel = frames_from_bytes_phased(data, Some(4));
    match (&serial, &phased, &parallel, &phased_parallel) {
        (Ok(serial), Ok(phased), Ok(parallel), Ok(phased_parallel)) => {
            same(serial, &phased.frames);
            same(serial, parallel);
            same(serial, &phased_parallel.frames);
        }
        (Err(_), Err(_), Err(_), Err(_)) => {}
        _ => panic!("byte readers disagree on success"),
    }

    let Ok(text) = std::str::from_utf8(data) else {
        return;
    };
    let from_string = frames_from_text(text, Some(1));
    let from_string_parallel = frames_from_text(text, Some(4));
    match (&serial, &from_string, &from_string_parallel) {
        (Ok(serial), Ok(from_string), Ok(parallel)) => {
            same(serial, from_string);
            same(serial, parallel);
        }
        (Err(_), Err(_), Err(_)) => {}
        _ => panic!("string readers disagree with the byte reader"),
    }
});
