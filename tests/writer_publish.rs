//! A writer that is killed mid-write must not replace the destination with
//! a partial file, and must not leave a `.readcon-write-*.tmp` name behind.

use readcon_core::iterators::frames_from_text;
use readcon_core::types::ConFrameBuilder;
use readcon_core::writer::{rewrite_frame_refs_to_path, write_frame_refs_to_path};
use std::path::Path;

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
fn a_killed_write_keeps_the_previous_file_or_a_complete_one() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("out.con");
    let old = b"previous-complete\n".to_vec();
    std::fs::write(&path, &old).unwrap();
    let path_buf = path.clone();
    let pid = unsafe { libc::fork() };
    assert!(pid >= 0, "fork");
    if pid == 0 {
        let frame = wide_frame(8_000);
        loop {
            let _ = write_frame_refs_to_path(&path_buf, &[&frame], 4, None, false, false);
        }
    }
    std::thread::sleep(std::time::Duration::from_millis(30));
    unsafe {
        libc::kill(pid, libc::SIGKILL);
        let mut status = 0;
        libc::waitpid(pid, &mut status, 0);
    }
    for _ in 0..20 {
        if scratch_names(dir.path()).is_empty() {
            break;
        }
        std::thread::sleep(std::time::Duration::from_millis(10));
    }
    let got = std::fs::read(&path).unwrap();
    if got != old {
        let text = String::from_utf8(got).expect("published text");
        let parsed = frames_from_text(&text, Some(1)).expect("complete frame");
        assert_eq!(parsed.len(), 1);
        assert_eq!(parsed[0].atom_data.len(), 8_000);
    }
    let left = scratch_names(dir.path());
    assert!(left.is_empty(), "scratch left behind: {left:?}");
}

#[test]
fn a_killed_rewrite_leaves_the_published_file_whole() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("out.con");
    let previous = wide_frame(64);
    write_frame_refs_to_path(&path, &[&previous], 1, None, false, false).unwrap();
    let previous_bytes = std::fs::read(&path).unwrap();
    let replacement = wide_frame(8_000);
    let complete = dir.path().join("complete.con");
    write_frame_refs_to_path(&complete, &[&replacement], 4, None, false, false).unwrap();
    let published = std::fs::read(&complete).unwrap();
    let path_buf = path.clone();
    let pid = unsafe { libc::fork() };
    assert!(pid >= 0, "fork");
    if pid == 0 {
        let frame = wide_frame(8_000);
        loop {
            let _ = rewrite_frame_refs_to_path(&path_buf, &[&frame], 4, None, false, false, false);
        }
    }
    std::thread::sleep(std::time::Duration::from_millis(30));
    unsafe {
        libc::kill(pid, libc::SIGKILL);
        let mut status = 0;
        libc::waitpid(pid, &mut status, 0);
    }
    let got = std::fs::read(&path).unwrap();
    assert!(
        got == previous_bytes || got == published,
        "published rewrite is neither complete file ({} bytes)",
        got.len()
    );
}
