//! A threaded read must not start threads that outlive it.
//!
//! A pool built for one call and dropped at return leaves its workers
//! detached. Each worker owns the handle std allocated for it, and the
//! call returns before the worker frees it. LeakSanitizer reported that
//! handle under the `ffi-entry` and `index-corrupt` fuzz targets.
//!
//! The library installs mimalloc as the process allocator, and std
//! allocates the thread handle with `System`, so a counting allocator in
//! this binary would not see it. The binary counts `pthread_create`
//! instead. After the first read at a width, a read at that width starts
//! no thread.

#![cfg(target_os = "linux")]

use readcon_core::ffi::{free_rkr_frame_array, rkr_read_all_frames_n_threads};
use readcon_core::iterators::read_all_frames_located;
use std::ffi::{CString, c_int, c_void};
use std::path::Path;
use std::sync::atomic::{AtomicUsize, Ordering};

static CREATED: AtomicUsize = AtomicUsize::new(0);

type StartRoutine = extern "C" fn(*mut c_void) -> *mut c_void;
type PthreadCreate = unsafe extern "C" fn(
    *mut libc::pthread_t,
    *const libc::pthread_attr_t,
    StartRoutine,
    *mut c_void,
) -> c_int;

/// Counts the call, then forwards to the libc definition.
///
/// # Safety
///
/// Same contract as libc `pthread_create`.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn pthread_create(
    thread: *mut libc::pthread_t,
    attr: *const libc::pthread_attr_t,
    start: StartRoutine,
    arg: *mut c_void,
) -> c_int {
    CREATED.fetch_add(1, Ordering::SeqCst);
    let next = unsafe { libc::dlsym(libc::RTLD_NEXT, c"pthread_create".as_ptr()) };
    assert!(!next.is_null(), "libc pthread_create not found");
    let next: PthreadCreate = unsafe { std::mem::transmute(next) };
    unsafe { next(thread, attr, start, arg) }
}

fn created() -> usize {
    CREATED.load(Ordering::SeqCst)
}

fn ffi_read(path: &Path, threads: usize) -> usize {
    let c_path = CString::new(path.to_str().expect("utf8 path")).expect("c path");
    let mut count = 0usize;
    let frames = unsafe { rkr_read_all_frames_n_threads(c_path.as_ptr(), &mut count, threads) };
    assert!(!frames.is_null(), "ffi read failed");
    unsafe { free_rkr_frame_array(frames, count) };
    count
}

#[test]
fn threaded_reads_reuse_their_workers() {
    let dir = tempfile::tempdir().expect("tempdir");
    let path = dir.path().join("traj.con");
    let one = include_str!("../resources/test/tiny_cuh2.con");
    std::fs::write(&path, one.repeat(32)).expect("write");
    let expect = read_all_frames_located(&path, None).expect("serial").len();
    assert!(expect > 8);

    let reads: Vec<(&str, Box<dyn Fn(usize) -> usize>)> = vec![
        (
            "read_all_frames_located",
            Box::new(|n| read_all_frames_located(&path, Some(n)).expect("located").len()),
        ),
        ("rkr_read_all_frames_n_threads", Box::new(|n| ffi_read(&path, n))),
        #[cfg(feature = "parallel")]
        (
            "read_all_frames_indexed",
            Box::new(|n| {
                readcon_core::iterators::read_all_frames_indexed(&path, Some(n))
                    .expect("indexed")
                    .len()
            }),
        ),
    ];

    let mut started = Vec::new();
    for width in [2usize, 8] {
        for (name, read) in &reads {
            assert_eq!(read(width), expect, "{name} width {width}");
        }
        for (name, read) in &reads {
            let before = created();
            for _ in 0..4 {
                assert_eq!(read(width), expect, "{name} width {width}");
            }
            let threads = created() - before;
            if threads != 0 {
                started.push(format!("{name} width {width}: {threads} threads"));
            }
        }
    }
    assert!(started.is_empty(), "reads started threads: {started:?}");
}
