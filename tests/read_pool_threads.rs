//! A threaded read must not leave threads that outlive it unowned.
//!
//! A pool built for one call and dropped at return leaves its workers
//! detached. Each worker owns the handle std allocated for it, and the
//! call returns before the worker frees it. LeakSanitizer reported that
//! handle under the `ffi-entry` and `index-corrupt` fuzz targets. A
//! worker that has not started yet holds its handle only through memory
//! LeakSanitizer does not scan, so a read must also not return before
//! the workers it started are running.
//!
//! The library installs mimalloc as the process allocator, and std
//! allocates the thread handle with `System`, so a counting allocator in
//! this binary would not see it. The binary counts `pthread_create` and
//! the threads that began to run instead. New threads start after a
//! staggered delay, so a read that returns before its workers run is
//! caught without a sanitizer.
//!
//! ASan and TSan link their own `pthread_create` into the binary. ASan
//! aborts on a thread it did not record and TSan faults on one, so the
//! binary is empty under `asan_run` and `tsan_run`. LeakSanitizer checks
//! the same handles directly under ASan.

#![cfg(all(target_os = "linux", not(any(asan_run, tsan_run))))]

use readcon_core::ffi::{free_rkr_frame_array, rkr_read_all_frames_n_threads};
use readcon_core::iterators::read_all_frames_located;
use std::ffi::{CString, c_int, c_void};
use std::path::Path;
use std::sync::atomic::{AtomicUsize, Ordering};

static CREATED: AtomicUsize = AtomicUsize::new(0);
static RUNNING: AtomicUsize = AtomicUsize::new(0);
static SPAWNS: AtomicUsize = AtomicUsize::new(0);

type StartRoutine = extern "C" fn(*mut c_void) -> *mut c_void;
type PthreadCreate = unsafe extern "C" fn(
    *mut libc::pthread_t,
    *const libc::pthread_attr_t,
    StartRoutine,
    *mut c_void,
) -> c_int;

struct Start {
    routine: StartRoutine,
    arg: *mut c_void,
    delay_us: u32,
}

extern "C" fn counted_start(raw: *mut c_void) -> *mut c_void {
    let start = unsafe { Box::from_raw(raw.cast::<Start>()) };
    unsafe { libc::usleep(start.delay_us) };
    RUNNING.fetch_add(1, Ordering::SeqCst);
    (start.routine)(start.arg)
}

/// Counts the call and the thread's first instruction, and forwards to
/// the libc definition.
///
/// # Safety
///
/// Same contract as libc `pthread_create`.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn pthread_create(
    thread: *mut libc::pthread_t,
    attr: *const libc::pthread_attr_t,
    routine: StartRoutine,
    arg: *mut c_void,
) -> c_int {
    let next = unsafe { libc::dlsym(libc::RTLD_NEXT, c"pthread_create".as_ptr()) };
    assert!(!next.is_null(), "libc pthread_create not found");
    let next: PthreadCreate = unsafe { std::mem::transmute(next) };
    let delay_us = 2000 * (SPAWNS.fetch_add(1, Ordering::SeqCst) % 8) as u32;
    let start = Box::into_raw(Box::new(Start {
        routine,
        arg,
        delay_us,
    }))
    .cast::<c_void>();
    let rc = unsafe { next(thread, attr, counted_start, start) };
    if rc == 0 {
        CREATED.fetch_add(1, Ordering::SeqCst);
    } else {
        drop(unsafe { Box::from_raw(start.cast::<Start>()) });
    }
    rc
}

fn created() -> usize {
    CREATED.load(Ordering::SeqCst)
}

fn running() -> usize {
    RUNNING.load(Ordering::SeqCst)
}

/// One read at a worker count, returning the frame count.
type Read<'a> = Box<dyn Fn(usize) -> usize + 'a>;

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

    let reads: Vec<(&str, Read)> = vec![
        (
            "read_all_frames_located",
            Box::new(|n| {
                read_all_frames_located(&path, Some(n))
                    .expect("located")
                    .len()
            }),
        ),
        (
            "rkr_read_all_frames_n_threads",
            Box::new(|n| ffi_read(&path, n)),
        ),
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

    // One frame gives the workers no reason to start before the read
    // returns.
    let small = dir.path().join("one.con");
    std::fs::write(&small, one).expect("write one");

    let mut faults = Vec::new();
    for width in [2usize, 8] {
        assert_eq!(
            read_all_frames_located(&small, Some(width))
                .expect("one")
                .len(),
            1
        );
        let waiting = created().saturating_sub(running());
        if waiting != 0 {
            faults.push(format!(
                "first read at width {width}: returned with {waiting} threads not started"
            ));
        }
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
                faults.push(format!("{name} width {width}: started {threads} threads"));
            }
        }
    }
    assert!(faults.is_empty(), "{faults:#?}");
}
