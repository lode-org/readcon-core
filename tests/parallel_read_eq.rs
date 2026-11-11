//! Parallel reads match [`readcon_core::iterators::read_all_frames`].
//!
//! The same assertions run with and without the `parallel` feature. Without
//! it, a worker count still parses on the calling thread.

use readcon_core::error::ParseError;
use readcon_core::iterators::{read_all_frames, read_all_frames_with_threads};
use readcon_core::types::ConFrame;
use std::error::Error;
use std::fs;
use std::path::{Path, PathBuf};

fn fixture(name: &str) -> String {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("resources/test")
        .join(name);
    fs::read_to_string(path).unwrap_or_else(|err| panic!("{name}: {err}"))
}

fn error_key(err: Box<dyn Error>) -> String {
    match err.downcast::<ParseError>() {
        Ok(parse) => format!("{parse:?}"),
        Err(other) => other.to_string(),
    }
}

fn assert_frames(label: &str, path: &Path) {
    let serial = read_all_frames(path).unwrap_or_else(|err| panic!("{label} serial: {err}"));
    for threads in [1usize, 2, 4, 8] {
        let parallel = read_all_frames_with_threads(path, Some(threads))
            .unwrap_or_else(|err| panic!("{label} threads {threads}: {err}"));
        assert_eq!(parallel, serial, "{label} threads {threads}");
    }
}

fn assert_error(label: &str, path: &Path) {
    let serial = error_key(
        read_all_frames(path).expect_err(&format!("{label} serial parsed a truncated file")),
    );
    for threads in [1usize, 2, 4, 8] {
        let parallel = error_key(
            read_all_frames_with_threads(path, Some(threads)).expect_err(&format!(
                "{label} threads {threads} parsed a truncated file"
            )),
        );
        assert_eq!(parallel, serial, "{label} threads {threads}");
    }
}

fn write_frames(dir: &Path, name: &str, text: &str) -> PathBuf {
    let path = dir.join(name);
    fs::write(&path, text).unwrap();
    path
}

#[test]
fn parallel_reads_match_serial_frames() {
    let dir = tempfile::tempdir().unwrap();
    let cases = [
        ("con", "tiny_multi_cuh2.con"),
        ("con-wide", "cuh2.con"),
        ("convel", "tiny_multi_cuh2.convel"),
        ("convel-one", "tiny_cuh2.convel"),
        ("vel-force", "tiny_cuh2_vel_forces.con"),
    ];
    for (label, name) in cases {
        let text = fixture(name);
        let repeated = text.repeat(4);
        let path = write_frames(dir.path(), name, &repeated);
        assert_frames(&format!("{label} x4"), &path);
    }

    let one = fixture("cuh2.con");
    let single = write_frames(dir.path(), "single.con", &one);
    let serial: Vec<ConFrame> = read_all_frames(&single).unwrap();
    assert_eq!(serial.len(), 1);
    assert_frames("single", &single);

    let empty = write_frames(dir.path(), "empty.con", "");
    let serial_empty = read_all_frames(&empty).unwrap();
    assert!(serial_empty.is_empty());
    assert_frames("empty", &empty);

    let truncated = write_frames(
        dir.path(),
        "truncated.con",
        &format!("{one}{}", &one[..one.len() / 2]),
    );
    assert_error("truncated con", &truncated);

    let convel = fixture("tiny_cuh2.convel");
    let truncated_convel = write_frames(
        dir.path(),
        "truncated.convel",
        &format!("{convel}{}", &convel[..convel.len() / 2]),
    );
    assert_error("truncated convel", &truncated_convel);

    let vel = fixture("tiny_cuh2_vel_forces.con");
    let truncated_vel = write_frames(
        dir.path(),
        "truncated-vel.con",
        &format!("{vel}{}", &vel[..vel.len() / 2]),
    );
    assert_error("truncated vel+force", &truncated_vel);
}
