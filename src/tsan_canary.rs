//! A data race built only into the ThreadSanitizer stress extension.
//!
//! The stress process has to show that this extension's instrumentation
//! calls a live runtime before it trusts a clean run. Two threads call
//! [`rkr_tsan_canary_race`] with no synchronization. The race is the point.

use std::cell::UnsafeCell;
use std::sync::atomic::{AtomicUsize, Ordering};

struct Shared(UnsafeCell<u64>);

// SAFETY: both threads write this cell on purpose. The data race is the
// signal the stress script requires from ThreadSanitizer.
unsafe impl Sync for Shared {}

static WORD: Shared = Shared(UnsafeCell::new(0));
static ARRIVED: AtomicUsize = AtomicUsize::new(0);

/// Unsynchronized read and write of [`WORD`]. A runtime that is watching
/// this object reports a data race in this function.
#[unsafe(no_mangle)]
#[inline(never)]
pub extern "C" fn rkr_tsan_canary_race() {
    unsafe {
        let cell = WORD.0.get();
        let value = std::ptr::read(cell);
        std::ptr::write(cell, value.wrapping_add(1));
    }
}

/// Start two threads and wait until both have called the canary.
#[unsafe(no_mangle)]
pub extern "C" fn rkr_tsan_canary_launch() {
    let mut threads = Vec::new();
    for _ in 0..2 {
        threads.push(std::thread::spawn(|| {
            ARRIVED.fetch_add(1, Ordering::Release);
            while ARRIVED.load(Ordering::Acquire) < 2 {
                std::thread::yield_now();
            }
            rkr_tsan_canary_race();
        }));
    }
    for thread in threads {
        let _ = thread.join();
    }
}
