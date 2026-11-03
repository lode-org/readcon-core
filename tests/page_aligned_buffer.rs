//! The readers must leave a caller's buffer as they found it.
//!
//! `madvise(MADV_DONTNEED)` zeroes the heap pages it covers, and fails unless
//! its address starts a page. A release at page offsets from the start of a
//! borrowed buffer thus zeroes the buffer only when it starts on a page. A
//! heap buffer does so only by chance, so the test allocates one that does.
#![cfg(unix)]

mod common;

use readcon_core::iterators::{frames_from_bytes, frames_from_text};
use readcon_core::types::ConFrame;
use std::alloc::Layout;
use std::path::Path;
use std::ptr::NonNull;

// 64 frames in over a mebibyte: many pages, and 8 frames per worker of the
// largest pool below.
const COPIES: usize = 64;
// The serial parse and two pool sizes of the parallel one.
const THREADS: [usize; 3] = [1, 2, 8];

/// A copy of some bytes that starts on a page.
struct PageAligned {
    ptr: NonNull<u8>,
    layout: Layout,
}

impl PageAligned {
    fn copy_of(bytes: &[u8]) -> Self {
        // SAFETY: sysconf takes no pointers.
        let page = unsafe { libc::sysconf(libc::_SC_PAGESIZE) };
        let page = usize::try_from(page).expect("page size");
        let layout = Layout::from_size_align(bytes.len(), page).expect("layout");
        assert_ne!(layout.size(), 0);
        // SAFETY: the layout has a nonzero size.
        let ptr = NonNull::new(unsafe { std::alloc::alloc(layout) }).expect("allocation");
        // SAFETY: the new allocation holds `bytes.len()` bytes and overlaps
        // nothing.
        unsafe { std::ptr::copy_nonoverlapping(bytes.as_ptr(), ptr.as_ptr(), bytes.len()) };
        Self { ptr, layout }
    }

    fn bytes(&self) -> &[u8] {
        // SAFETY: `copy_of` initialised all `layout.size()` bytes.
        unsafe { std::slice::from_raw_parts(self.ptr.as_ptr(), self.layout.size()) }
    }
}

impl Drop for PageAligned {
    fn drop(&mut self) {
        // SAFETY: `copy_of` allocated `ptr` with `layout`.
        unsafe { std::alloc::dealloc(self.ptr.as_ptr(), self.layout) };
    }
}

fn check(what: &str, frames: Result<Vec<ConFrame>, impl std::fmt::Debug>, expected: &[ConFrame]) {
    let frames = frames.unwrap_or_else(|e| panic!("{what}: {e:?}"));
    assert_eq!(frames.len(), expected.len(), "{what}");
    for (i, (got, want)) in frames.iter().zip(expected).enumerate() {
        assert!(got == want, "{what}: frame {i} differs");
    }
}

fn changed_bytes(buffer: &[u8], original: &[u8]) -> usize {
    buffer.iter().zip(original).filter(|(a, b)| a != b).count()
}

#[test]
fn readers_leave_a_page_aligned_buffer_unchanged() {
    let text = std::fs::read_to_string(test_case!("cuh2.con"))
        .expect("fixture")
        .repeat(COPIES);
    let expected = frames_from_text(&text, Some(1)).expect("one-thread string read");
    assert_eq!(expected.len(), COPIES);

    let buffer = PageAligned::copy_of(text.as_bytes());
    assert_eq!(buffer.bytes().as_ptr() as usize % buffer.layout.align(), 0);
    for threads in THREADS {
        let what = format!("byte read, {threads} threads");
        let frames = frames_from_bytes(buffer.bytes(), Some(threads));
        assert_eq!(changed_bytes(buffer.bytes(), text.as_bytes()), 0, "{what}");
        check(&what, frames, &expected);

        let what = format!("string read, {threads} threads");
        let borrowed = std::str::from_utf8(buffer.bytes()).expect("utf8");
        let frames = frames_from_text(borrowed, Some(threads));
        assert_eq!(changed_bytes(buffer.bytes(), text.as_bytes()), 0, "{what}");
        check(&what, frames, &expected);
    }
}
