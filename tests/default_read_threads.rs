//! Default reads stay on the calling thread.
//!
//! A worker pool starts only when the caller asks for two or more threads.

use readcon_core::iterators::{read_all_frames, read_all_frames_with_threads};
use std::path::Path;

fn thread_count() -> usize {
    let text = std::fs::read_to_string("/proc/self/status").unwrap();
    for line in text.lines() {
        if let Some(rest) = line.strip_prefix("Threads:") {
            return rest.split_whitespace().next().unwrap().parse().unwrap();
        }
    }
    panic!("thread count missing");
}

fn wide_file(dir: &Path) -> std::path::PathBuf {
    let path = dir.join("wide.con");
    let one = include_str!("../resources/test/tiny_cuh2.con");
    std::fs::write(&path, one.repeat(200)).unwrap();
    assert!(
        path.metadata().unwrap().len() > 64 * 1024,
        "fixture must be wide enough to exercise the old pool gate"
    );
    path
}

#[test]
fn default_read_starts_no_worker_threads_unless_two_or_more_are_requested() {
    let dir = tempfile::tempdir().unwrap();
    let path = wide_file(dir.path());
    let before = thread_count();
    let frames = read_all_frames(&path).unwrap();
    assert_eq!(
        thread_count(),
        before,
        "default read started worker threads"
    );
    assert!(frames.len() > 1);
    assert_eq!(frames[0].atom_data.len(), 4);

    let widened = read_all_frames_with_threads(&path, Some(2)).unwrap();
    assert_eq!(widened.len(), frames.len());
    assert!(
        thread_count() > before,
        "asking for two threads did not start workers"
    );
}
