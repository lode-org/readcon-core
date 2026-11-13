//! Multi-frame CON trajectory read with frame seeking.
//!
//! `read_nth_frame_from_text` skips frames, `parse_frame_at` uses the span
//! table, and both must match a full `frames_from_bytes` parse.

#![no_main]

use libfuzzer_sys::fuzz_target;
use readcon_core::index_proj::parse_frame_at;
use readcon_core::iterators::{frame_start_offsets, frames_from_bytes, read_nth_frame_from_text};
use readcon_core::types::ConFrame;

fn same_bits(left: f64, right: f64) -> bool {
    left.to_bits() == right.to_bits()
}

fn assert_frame(got: &ConFrame, expect: &ConFrame) {
    assert_eq!(got.atom_data.len(), expect.atom_data.len());
    for (got_atom, expect_atom) in got.atom_data.iter().zip(expect.atom_data.iter()) {
        assert_eq!(got_atom.symbol.as_ref(), expect_atom.symbol.as_ref());
        assert!(same_bits(got_atom.x(), expect_atom.x()));
        assert!(same_bits(got_atom.y(), expect_atom.y()));
        assert!(same_bits(got_atom.z(), expect_atom.z()));
        assert_eq!(got_atom.fixed(), expect_atom.fixed());
        match (got_atom.velocity(), expect_atom.velocity()) {
            (Some(got_v), Some(expect_v)) => {
                assert!(same_bits(got_v[0], expect_v[0]));
                assert!(same_bits(got_v[1], expect_v[1]));
                assert!(same_bits(got_v[2], expect_v[2]));
            }
            (None, None) => {}
            (got_v, expect_v) => panic!("velocity {got_v:?} vs {expect_v:?}"),
        }
    }
    assert_eq!(got.masses.len(), expect.masses.len());
    for index in 0..got.masses.len() {
        assert!(same_bits(
            got.masses.get_f64(index),
            expect.masses.get_f64(index)
        ));
    }
    for index in 0..3 {
        assert!(same_bits(got.header.boxl[index], expect.header.boxl[index]));
        assert!(same_bits(
            got.header.angles[index],
            expect.header.angles[index]
        ));
    }
}

fuzz_target!(|data: &[u8]| {
    if data.len() > 16 * 1024 {
        return;
    }
    let Ok(text) = std::str::from_utf8(data) else {
        return;
    };
    let offsets = frame_start_offsets(text);
    assert!(offsets.len() <= text.len().saturating_add(1));
    let full = frames_from_bytes(data, Some(1));
    let n = match &full {
        Ok(frames) => frames.len(),
        Err(_) => offsets.len(),
    };
    let index = if n == 0 {
        usize::from(data.first().copied().unwrap_or(0))
    } else {
        usize::from(data.first().copied().unwrap_or(0)) % n
    };
    let nth = read_nth_frame_from_text(text, index);
    let spanned = parse_frame_at(text, index);
    if let Ok(frames) = &full {
        if index < frames.len() {
            let expect = &frames[index];
            assert_frame(&nth.expect("seek"), expect);
            assert_frame(&spanned.expect("span"), expect);
        } else {
            assert!(nth.is_err());
            assert!(spanned.is_err());
        }
        assert_eq!(offsets.len(), frames.len());
    }
    if data.len() <= 1024 && data.first().copied().unwrap_or(0) % 16 == 0 {
        let Ok(dir) = tempfile::tempdir() else {
            return;
        };
        let path = dir.path().join("traj.con");
        if std::fs::write(&path, data).is_ok() {
            let _ = readcon_core::iterators::read_nth_frame(&path, index);
        }
    }
});
