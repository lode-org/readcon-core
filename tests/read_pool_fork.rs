//! A threaded read in a forked child must not wait on the parent's pool.
//!
//! The child of `fork` keeps the parent's memory but only the thread
//! that called `fork`. A child that reused a pool the parent had already
//! built queued its job for workers it does not have and never returned.
//! The reads below use the pools behind `shared_pool`, and the threaded
//! write uses the one behind `on_pool`.

#![cfg(all(unix, feature = "parallel"))]

use readcon_core::ffi::{free_rkr_frame_array, rkr_read_all_frames_n_threads};
use readcon_core::iterators::{
    read_all_frames_indexed, read_all_frames_located, read_all_frames_phased,
};
use readcon_core::writer::write_frames_to_vec_with_threads;
use std::ffi::CString;
use std::path::Path;
use std::time::{Duration, Instant};

fn ffi_read(path: &Path, threads: usize) -> usize {
    let c_path = CString::new(path.to_str().expect("utf8 path")).expect("c path");
    let mut count = 0usize;
    let frames = unsafe { rkr_read_all_frames_n_threads(c_path.as_ptr(), &mut count, threads) };
    assert!(!frames.is_null(), "ffi read failed");
    unsafe { free_rkr_frame_array(frames, count) };
    count
}

/// Frame counts of the threaded reads, then the length of a threaded write.
fn threaded_calls(path: &Path, threads: usize) -> [usize; 5] {
    let frames = read_all_frames_located(path, Some(threads)).expect("located");
    [
        frames.len(),
        ffi_read(path, threads),
        read_all_frames_indexed(path, Some(threads))
            .expect("indexed")
            .len(),
        read_all_frames_phased(path, Some(threads))
            .expect("phased")
            .frames
            .len(),
        write_frames_to_vec_with_threads(&frames, threads, None, false)
            .expect("write")
            .len(),
    ]
}

#[test]
fn a_forked_child_reads_with_threads() {
    let dir = tempfile::tempdir().expect("tempdir");
    let path = dir.path().join("traj.con");
    let one = include_str!("../resources/test/tiny_cuh2.con");
    std::fs::write(&path, one.repeat(32)).expect("write");
    let serial = read_all_frames_located(&path, None).expect("serial");
    let n = serial.len();
    assert!(n > 8);
    let written = write_frames_to_vec_with_threads(&serial, 1, None, false)
        .expect("serial write")
        .len();
    let expect = [n, n, n, n, written];
    assert_eq!(threaded_calls(&path, 2), expect);

    let pid = unsafe { libc::fork() };
    assert!(pid >= 0, "fork failed");
    if pid == 0 {
        // Width 2 is the pool the parent built. Width 3 is new to both.
        let ok = std::panic::catch_unwind(|| {
            threaded_calls(&path, 2) == expect && threaded_calls(&path, 3) == expect
        });
        unsafe { libc::_exit(if matches!(ok, Ok(true)) { 0 } else { 1 }) };
    }

    let deadline = Instant::now() + Duration::from_secs(60);
    let mut status = 0;
    loop {
        let done = unsafe { libc::waitpid(pid, &mut status, libc::WNOHANG) };
        assert!(done >= 0, "waitpid failed");
        if done == pid {
            break;
        }
        if Instant::now() > deadline {
            unsafe {
                libc::kill(pid, libc::SIGKILL);
                libc::waitpid(pid, &mut status, 0);
            }
            panic!("the forked child did not finish its threaded reads in 60 s");
        }
        std::thread::sleep(Duration::from_millis(20));
    }
    assert!(
        libc::WIFEXITED(status) && libc::WEXITSTATUS(status) == 0,
        "the forked child failed its reads, status {status:#x}"
    );
    assert_eq!(threaded_calls(&path, 2), expect);
}
