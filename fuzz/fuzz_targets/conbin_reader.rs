//! The CON-bin readers of `readcon_core::conbin` on a file built from the
//! input.
//!
//! The header fields occupy `HEADER_BYTES` of the input. The file is those
//! bytes, zeros out to `PAYLOAD_ALIGN`, and then the rest of the input,
//! which is where `write_from_con` puts the payload. When the mapped and
//! the copied reads both succeed, they must return the same bits. A
//! wrong-width accessor and a velocity accessor on a file with no velocity
//! run must return an error.
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
use readcon_core::conbin::{self, HEADER_BYTES, PAYLOAD_ALIGN};
use std::path::{Path, PathBuf};
use std::sync::OnceLock;

// One worker, and two, which split a run of two payload blocks or more.
const THREADS: [usize; 2] = [1, 2];

/// One file per process, so parallel jobs do not share it.
fn scratch_path() -> &'static Path {
    static PATH: OnceLock<PathBuf> = OnceLock::new();
    PATH.get_or_init(|| {
        std::env::temp_dir().join(format!("readcon-conbin-fuzz-{}.conbin", std::process::id()))
    })
}

fn file_bytes(data: &[u8]) -> Vec<u8> {
    if data.len() < HEADER_BYTES {
        return data.to_vec();
    }
    let (fields, payload) = data.split_at(HEADER_BYTES);
    let mut bytes = fields.to_vec();
    bytes.resize(PAYLOAD_ALIGN, 0);
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
            Some(*map.header()),
            header,
            "map_file and read_header disagree"
        );
        if map.header().binary32 {
            assert!(
                map.positions_f64().is_err(),
                "binary64 positions on a binary32 file"
            );
            assert!(
                map.velocities_f64().is_err(),
                "binary64 velocities on a binary32 file"
            );
        } else {
            assert!(
                map.positions_f32().is_err(),
                "binary32 positions on a binary64 file"
            );
            assert!(
                map.velocities_f32().is_err(),
                "binary32 velocities on a binary64 file"
            );
        }
        if !map.header().velocities {
            assert!(
                map.velocities_f64().is_err(),
                "velocities on a file with no velocity run"
            );
            assert!(
                map.velocities_f32().is_err(),
                "velocities on a file with no velocity run"
            );
        }
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
        if !header.velocities {
            assert!(
                copied.is_err(),
                "a velocity slice on a file with no velocity run"
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
        if !header.velocities {
            assert!(
                copied.is_err(),
                "a velocity slice on a file with no velocity run"
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
    let bytes = file_bytes(data);
    let path = scratch_path();
    if std::fs::write(path, &bytes).is_err() {
        return;
    }
    for threads in THREADS {
        check(path, bytes.len(), threads);
    }
    let _ = std::fs::remove_file(path);
});
