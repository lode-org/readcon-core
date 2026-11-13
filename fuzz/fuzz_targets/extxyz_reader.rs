#![no_main]

use libfuzzer_sys::fuzz_target;
use readcon_core::compression::{
    Compression, detect_compression, read_file_bytes, write_gzip_members_limited,
    write_zstd_members_limited,
};
use readcon_core::extxyz_scan::tables_from_extxyz_bytes_with_threads;

fn accept(bytes: &[u8], threads: usize) {
    if bytes.len() > 2 * 1024 * 1024 {
        return;
    }
    if let Ok(tables) = tables_from_extxyz_bytes_with_threads(bytes, threads) {
        let atoms = tables.n_frames.saturating_mul(tables.n_atoms);
        assert_eq!(tables.positions.len(), atoms.saturating_mul(3));
        assert_eq!(tables.masses.len(), atoms);
    }
}

/// `read_extxyz` inflates a gzip or zstd file, then scans the plain text.
fn read_compressed(data: &[u8]) {
    if !matches!(
        detect_compression(data),
        Compression::Gzip | Compression::Zstd
    ) {
        return;
    }
    let Ok(dir) = tempfile::tempdir() else {
        return;
    };
    let path = dir.path().join("fuzz.extxyz.gz");
    if std::fs::write(&path, data).is_err() {
        return;
    }
    let Ok(plain) = read_file_bytes(&path) else {
        return;
    };
    for threads in [1usize, 8] {
        accept(&plain, threads);
    }
}

/// `write_extxyz` member-compresses the formatted bytes for `.gz` and `.zst`.
fn write_compressed(data: &[u8]) {
    if data.len() > 4096 {
        return;
    }
    let Ok(dir) = tempfile::tempdir() else {
        return;
    };
    let members = readcon_core::compression::compression_workers(data.len()).max(2);
    for threads in [1usize, 8] {
        let gz = dir.path().join(format!("out-{threads}.extxyz.gz"));
        if write_gzip_members_limited(&gz, data, members, threads).is_ok()
            && let Ok(plain) = read_file_bytes(&gz)
        {
            accept(&plain, threads);
        }
        let zst = dir.path().join(format!("out-{threads}.extxyz.zst"));
        if write_zstd_members_limited(&zst, data, members, threads).is_ok()
            && let Ok(plain) = read_file_bytes(&zst)
        {
            accept(&plain, threads);
        }
    }
}

fuzz_target!(|data: &[u8]| {
    if data.len() > 128 * 1024 {
        return;
    }
    for threads in [1usize, 8] {
        accept(data, threads);
    }
    read_compressed(data);
    write_compressed(data);
});
