#![no_main]

use libfuzzer_sys::fuzz_target;
use readcon_core::compression::{
    codec_deflate, codec_inflate, read_file_text, Compression,
};
use readcon_core::extxyz_scan::tables_from_extxyz_bytes_with_threads;
use readcon_core::iterators::frames_from_bytes;

fn touch_con(bytes: &[u8], threads: usize) {
    let Ok(frames) = frames_from_bytes(bytes, Some(threads)) else {
        return;
    };
    for frame in &frames {
        let _ = frame.header.lattice_vectors();
        let _ = frame.header.metadata.get("lattice_vectors");
    }
}

fn deflate_round_trip(data: &[u8], threads: usize) {
    if data.len() > 4096 {
        return;
    }
    let Ok(encoded) = codec_deflate(data, 4, threads, false) else {
        return;
    };
    if let Ok(back) = codec_inflate(&encoded, threads) {
        assert_eq!(back, data);
    }
}

fn text_of_compressed(data: &[u8]) {
    if !matches!(
        readcon_core::compression::detect_compression(data),
        Compression::Zstd
    ) {
        return;
    }
    let Ok(dir) = tempfile::tempdir() else {
        return;
    };
    let path = dir.path().join("fuzz.con.zst");
    if std::fs::write(&path, data).is_err() {
        return;
    }
    let _ = read_file_text(&path);
}

fn accept_extxyz(bytes: &[u8], threads: usize) {
    if let Ok(tables) = tables_from_extxyz_bytes_with_threads(bytes, threads) {
        let atoms = tables.n_frames.saturating_mul(tables.n_atoms);
        assert_eq!(tables.positions.len(), atoms.saturating_mul(3));
        assert_eq!(tables.masses.len(), atoms);
    }
}

fuzz_target!(|data: &[u8]| {
    if data.len() > 128 * 1024 {
        return;
    }
    for threads in [1usize, 8] {
        let Ok(plain) = codec_inflate(data, threads) else {
            continue;
        };
        if plain.len() > 2 * 1024 * 1024 {
            continue;
        }
        touch_con(&plain, threads);
        // read_extxyz scans the inflated bytes, not a CON frame.
        accept_extxyz(&plain, threads);
        deflate_round_trip(data, threads);
    }
    text_of_compressed(data);
});
