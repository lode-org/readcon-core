//! The CON-bin readers of `readcon_core::conbin` on one input.
//!
//! The input is written as the file. `read_owned_f64` must fail before it
//! reserves when the header names a column the file cannot hold. The same
//! bytes are also laid out as a header, zeros out to 4096, and the rest of
//! the input, which is where a page-sized header puts the payload.
//!
//! When a mapped read and a copied read both succeed, they return the same
//! bits. The copy rejects the other value width. A file with a velocity run
//! and no velocity slice is an error.
//!
//! libFuzzer saves every input that finds new coverage as a file in the
//! corpus directory it runs on, so run the target on a scratch copy:
//!
//! ```text
//! corpus=$(mktemp -d)
//! cp -a fuzz/corpus/conbin-reader/. "$corpus/"
//! cargo +nightly fuzz run conbin-reader "$corpus" -- -seed="$(cat fuzz/seed.txt)"
//! rm -rf "$corpus"
//! ```
#![no_main]

use libfuzzer_sys::fuzz_target;
use readcon_core::conbin::{self, read_header, read_owned_f64, sum_mapped};
use std::path::Path;

/// The six header fields. The library keeps this length private.
const HEADER_BYTES: usize = 40;
/// Padding after the fields so a payload can start on a 4 KiB boundary.
const PAYLOAD_PAD: usize = 4096;

// One worker, and two, which split a run of two payload blocks or more.
const THREADS: [usize; 2] = [1, 2];

fn file_bytes(data: &[u8]) -> Vec<u8> {
    if data.len() < HEADER_BYTES {
        return data.to_vec();
    }
    let (fields, payload) = data.split_at(HEADER_BYTES);
    let mut bytes = fields.to_vec();
    bytes.resize(PAYLOAD_PAD, 0);
    bytes.extend_from_slice(payload);
    bytes
}

fn same_bits_f64(a: &[f64], b: &[f64]) -> bool {
    a.len() == b.len() && a.iter().zip(b).all(|(x, y)| x.to_bits() == y.to_bits())
}

fn same_bits_f32(a: &[f32], b: &[f32]) -> bool {
    a.len() == b.len() && a.iter().zip(b).all(|(x, y)| x.to_bits() == y.to_bits())
}

fn check(path: &Path, file_len: usize, threads: usize) {
    let header = conbin::read_header(path).ok();
    let mapped = conbin::map_file(path, threads).ok();
    if let Some(map) = &mapped {
        assert_eq!(
            Some(map.header),
            header,
            "map_file and read_header disagree"
        );
        for run in [map.positions_f64(), map.velocities_f64()]
            .into_iter()
            .flatten()
        {
            std::hint::black_box(run.iter().fold(0u64, |acc, v| acc ^ v.to_bits()));
        }
        for run in [map.positions_f32(), map.velocities_f32()]
            .into_iter()
            .flatten()
        {
            std::hint::black_box(run.iter().fold(0u32, |acc, v| acc ^ v.to_bits()));
        }
    }
    let Some(header) = header else { return };
    let Ok(n) = header.position_len() else { return };
    // A copied run must fit in the file, which bounds each allocation.
    let fits = |width: usize| n.checked_mul(width).is_some_and(|bytes| bytes <= file_len);

    if fits(size_of::<f64>()) {
        let mut pos = vec![0.0f64; n];
        let mut vel = vec![0.0f64; n];
        let copied = conbin::read_into_threads(path, &mut pos, Some(&mut vel), threads);
        if header.binary32 {
            assert!(
                copied.is_err(),
                "a binary64 copy of a binary32 file succeeded"
            );
        }
        if copied.is_ok() && header.velocities {
            let no_slice = conbin::read_into_threads(path, &mut pos, None, threads);
            assert!(
                no_slice.is_err(),
                "a copy without a velocity slice succeeded"
            );
        }
        if let (Ok(_), Some(map)) = (&copied, &mapped) {
            if let Ok(run) = map.positions_f64() {
                assert!(
                    same_bits_f64(run, &pos),
                    "mapped and copied positions differ"
                );
            }
            if let (true, Ok(run)) = (header.velocities, map.velocities_f64()) {
                assert!(
                    same_bits_f64(run, &vel),
                    "mapped and copied velocities differ"
                );
            }
        }
    }

    if fits(size_of::<f32>()) {
        let mut pos = vec![0.0f32; n];
        let mut vel = vec![0.0f32; n];
        let copied = conbin::read_into_f32_threads(path, &mut pos, Some(&mut vel), threads);
        if !header.binary32 {
            assert!(
                copied.is_err(),
                "a binary32 copy of a binary64 file succeeded"
            );
        }
        if copied.is_ok() && header.velocities {
            let no_slice = conbin::read_into_f32_threads(path, &mut pos, None, threads);
            assert!(
                no_slice.is_err(),
                "a copy without a velocity slice succeeded"
            );
        }
        if let (Ok(_), Some(map)) = (&copied, &mapped) {
            if let Ok(run) = map.positions_f32() {
                assert!(
                    same_bits_f32(run, &pos),
                    "mapped and copied positions differ"
                );
            }
            if let (true, Ok(run)) = (header.velocities, map.velocities_f32()) {
                assert!(
                    same_bits_f32(run, &vel),
                    "mapped and copied velocities differ"
                );
            }
        }
    }
}

fuzz_target!(|data: &[u8]| {
    if data.len() > 64 * 1024 {
        return;
    }
    let Ok(dir) = tempfile::tempdir() else {
        return;
    };
    let raw = dir.path().join("raw.conbin");
    if std::fs::write(&raw, data).is_err() {
        return;
    }
    let _ = read_header(&raw);
    // The owned reader sizes its columns from the header. A count the
    // file cannot hold must fail before that reservation.
    let _ = read_owned_f64(&raw, 1);
    let _ = read_owned_f64(&raw, 2);
    for threads in THREADS {
        check(&raw, data.len(), threads);
    }
    let _ = sum_mapped(&raw, 1);
    let _ = sum_mapped(&raw, 2);

    if data.len() >= HEADER_BYTES {
        let built = file_bytes(data);
        let padded = dir.path().join("padded.conbin");
        if std::fs::write(&padded, &built).is_ok() {
            for threads in THREADS {
                check(&padded, built.len(), threads);
            }
        }
    }
});
