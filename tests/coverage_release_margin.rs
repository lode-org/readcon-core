//! Behaviour that the line-coverage gate was missing on v0.23.2.

use readcon_core::conbin::{QueueLimits, sum_mapped, sum_split_streams, write_from_con};
use readcon_core::distrib::{block_owner, block_range, rkr_block_range};
use readcon_core::iterators::{ConFrameIterator, release_parsed_frames};

#[test]
fn page_default_is_one_request_of_one_page() {
    let limits = QueueLimits::page_default(4096);
    assert_eq!(limits.page, 4096);
    assert_eq!(limits.logical_block, 4096);
    assert_eq!(limits.max_request, 4096);
    assert_eq!(limits.nr_requests, 1);
    assert_eq!(limits.read_ahead, 4096);
    assert_eq!(limits.nr_hw_queues, 1);
    assert!(!limits.rotational);
}

#[test]
fn block_owner_is_none_outside_the_partition() {
    assert_eq!(block_owner(10, 0, 0), None);
    assert_eq!(block_owner(10, 2, 10), None);
    assert_eq!(block_owner(10, 3, 0), Some(0));
}

#[test]
fn block_range_c_abi_matches_the_rust_partition() {
    let mut start = 9u64;
    let mut end = 9u64;
    let rc = unsafe { rkr_block_range(10, 3, 1, &mut start, &mut end) };
    assert_eq!(rc, 0);
    let expect = block_range(10, 3, 1);
    assert_eq!(start as usize, expect.start);
    assert_eq!(end as usize, expect.end);
    assert_eq!(
        unsafe { rkr_block_range(10, 3, 1, std::ptr::null_mut(), &mut end) },
        -1
    );
    assert_eq!(
        unsafe { rkr_block_range(10, 3, 1, &mut start, std::ptr::null_mut()) },
        -1
    );
}

#[test]
fn release_parsed_frames_uses_the_worker_pool() {
    let text = include_str!("../resources/test/tiny_multi_cuh2.con");
    let frames: Vec<_> = ConFrameIterator::new(text)
        .map(|frame| frame.expect("parse"))
        .collect();
    assert!(frames.len() >= 2);
    release_parsed_frames(frames, 2);
}

#[cfg(target_os = "linux")]
#[test]
fn split_streams_match_one_stream_on_a_cold_file() {
    let dir = tempfile::tempdir().unwrap();
    let con = dir.path().join("many.con");
    std::fs::write(
        &con,
        include_str!("../resources/test/tiny_cuh2.con").repeat(80),
    )
    .unwrap();
    let bin = dir.path().join("many.conbin");
    write_from_con(&con, &bin, false).unwrap();
    use std::os::fd::AsRawFd;
    let file = std::fs::File::open(&bin).unwrap();
    file.sync_all().unwrap();
    let _ = unsafe { libc::posix_fadvise(file.as_raw_fd(), 0, 0, libc::POSIX_FADV_DONTNEED) };
    let one = sum_mapped(&bin, 2).unwrap();
    let _ = unsafe { libc::posix_fadvise(file.as_raw_fd(), 0, 0, libc::POSIX_FADV_DONTNEED) };
    let split = sum_split_streams(&bin, 2).unwrap();
    assert_eq!(one, split);
}
