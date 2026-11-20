//! A writer that is killed mid-write must not replace the destination with
//! a partial file, and must not leave a `.readcon-write-*.tmp` name behind.
#![cfg_attr(miri, ignore)]

use readcon_core::iterators::frames_from_text;
use readcon_core::types::ConFrameBuilder;
use readcon_core::writer::{publish_ranked_slices, write_frame_refs_to_path};
use std::path::Path;

// Writer integration tests touch the filesystem and spawn child processes.
// Run them under Miri with:
// MIRIFLAGS="-Zmiri-strict-provenance -Zmiri-disable-isolation" \
//   cargo +nightly miri test --test writer_publish -- --test-threads=1

fn wide_frame(n: usize) -> readcon_core::types::ConFrame {
    let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
    for i in 0..n {
        builder.add_atom(
            "Cu",
            i as f64 * 0.01,
            1.0,
            -1.0,
            [false, false, false],
            i as u64,
            63.546,
        );
    }
    builder.build().expect("frame")
}

fn scratch_names(dir: &Path) -> Vec<String> {
    let mut names = Vec::new();
    for entry in std::fs::read_dir(dir).expect("dir") {
        let name = entry.expect("entry").file_name();
        let name = name.to_string_lossy().into_owned();
        if name.starts_with(".readcon-write-") {
            names.push(name);
        }
    }
    names
}

#[test]
fn a_finished_write_replaces_the_destination_and_leaves_no_scratch() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("out.con");
    std::fs::write(&path, b"previous-complete\n").unwrap();
    let frame = wide_frame(32);
    write_frame_refs_to_path(&path, &[&frame], 4, None, false, false).unwrap();
    let text = std::fs::read_to_string(&path).unwrap();
    let parsed = frames_from_text(&text, Some(1)).unwrap();
    assert_eq!(parsed.len(), 1);
    assert_eq!(parsed[0].atom_data.len(), 32);
    assert!(scratch_names(dir.path()).is_empty());
}

#[test]
fn ranked_default_leaves_no_spare_and_opt_in_keeps_one() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("out.con");
    let frame = wide_frame(8);
    write_frame_refs_to_path(&path, &[&frame], 1, None, false, false).unwrap();
    let bytes = std::fs::read(&path).unwrap();
    let mid = bytes.len() / 2;
    let slices: [&[u8]; 2] = [&bytes[..mid], &bytes[mid..]];
    let spare = path.with_file_name(format!(
        "{}.rewrite",
        path.file_name().unwrap().to_string_lossy()
    ));
    publish_ranked_slices(&path, &slices, false, false).unwrap();
    assert_eq!(std::fs::read(&path).unwrap(), bytes);
    assert!(!spare.exists());
    publish_ranked_slices(&path, &slices, true, true).unwrap();
    assert_eq!(std::fs::read(&path).unwrap(), bytes);
    assert!(spare.exists());
    publish_ranked_slices(&path, &slices, true, false).unwrap();
    assert_eq!(std::fs::read(&path).unwrap(), bytes);
    assert!(!spare.exists());
}

#[test]
fn ranked_slices_round_trip_empty_and_one_byte_pieces() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("pieces.bin");
    let raw = b"abcdefghij".to_vec();
    let pieces: Vec<Vec<u8>> = raw.iter().copied().map(|byte| vec![byte]).collect();
    let mut slices = vec![Vec::new()];
    slices.extend(pieces);
    slices.push(Vec::new());
    let refs: Vec<&[u8]> = slices.iter().map(|slice| slice.as_slice()).collect();
    publish_ranked_slices(&path, &refs, false, false).unwrap();
    assert_eq!(std::fs::read(&path).unwrap(), raw);
    let other: [&[u8]; 3] = [&[], b"zz", &[]];
    publish_ranked_slices(&path, &other, true, false).unwrap();
    assert_eq!(std::fs::read(&path).unwrap(), b"zz");
}

#[test]
#[cfg_attr(miri, ignore)]
fn ranked_store_modes_round_trip_and_a_bad_override_keeps_the_file() {
    const MODE_ENV: &str = "READCON_TEST_RANKED_MODE";
    const PATH_ENV: &str = "READCON_TEST_RANKED_PATH";
    const EXPECT_ENV: &str = "READCON_TEST_RANKED_EXPECT";
    const INVALID_ENV: &str = "READCON_TEST_RANKED_INVALID";
    if let Ok(mode) = std::env::var(MODE_ENV) {
        let path = Path::new(&std::env::var(PATH_ENV).expect("child path")).to_path_buf();
        let expect = std::env::var(EXPECT_ENV).expect("child expected bytes");
        let slices: [&[u8]; 4] = [b"ab", &[], b"c", b"def"];
        unsafe { std::env::set_var("READCON_RANKED_WRITE", mode) };
        let wrote = publish_ranked_slices(&path, &slices, false, false);
        let got = std::fs::read(&path).unwrap_or_default();
        let spare = path.with_file_name(format!(
            "{}.rewrite",
            path.file_name().unwrap().to_string_lossy()
        ));
        let ok = wrote.is_ok() && got == expect.as_bytes() && !spare.exists();
        std::process::exit(if ok { 0 } else { 1 });
    }
    if std::env::var_os(INVALID_ENV).is_some() {
        let path = Path::new(&std::env::var(PATH_ENV).expect("child path")).to_path_buf();
        let slices: [&[u8]; 4] = [b"ab", &[], b"c", b"def"];
        unsafe { std::env::set_var("READCON_RANKED_WRITE", "ext4") };
        let rejected = publish_ranked_slices(&path, &slices, false, false);
        let kept = std::fs::read(&path).unwrap_or_default();
        let ok = rejected.is_err() && kept == b"abcdef";
        std::process::exit(if ok { 0 } else { 1 });
    }

    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("modes.bin");
    std::fs::write(&path, b"keep-me").unwrap();
    let exe = std::env::current_exe().expect("test binary");
    for mode in ["parallel", "sequential"] {
        let status = std::process::Command::new(&exe)
            .arg("ranked_store_modes_round_trip_and_a_bad_override_keeps_the_file")
            .arg("--exact")
            .env(MODE_ENV, mode)
            .env(PATH_ENV, path.as_os_str())
            .env(EXPECT_ENV, "abcdef")
            .status()
            .expect("spawn child");
        assert!(status.success(), "{mode} ranked store did not round-trip");
    }
    let status = std::process::Command::new(&exe)
        .arg("ranked_store_modes_round_trip_and_a_bad_override_keeps_the_file")
        .arg("--exact")
        .env(INVALID_ENV, "1")
        .env(PATH_ENV, path.as_os_str())
        .status()
        .expect("spawn child");
    assert!(
        status.success(),
        "a bad ranked-store override changed the file"
    );
}
