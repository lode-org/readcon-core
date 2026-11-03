#![no_main]

use libfuzzer_sys::fuzz_target;
use readcon_core::compression::MMAP_THRESHOLD;
use readcon_core::frame_index::frame_start_offsets_checked;
use readcon_core::iterators::{read_all_frames_indexed, read_all_frames_with_threads};

fuzz_target!(|data: &[u8]| {
    let text = String::from_utf8_lossy(data);
    let _ = frame_start_offsets_checked(&text);

    // Blank lines pad the file to the size from which it is mapped.
    let mmap_len = MMAP_THRESHOLD as usize;
    let mut bytes = data.to_vec();
    if bytes.len() < mmap_len {
        bytes.resize(mmap_len, b'\n');
    }

    let Ok(dir) = tempfile::tempdir() else {
        return;
    };
    let path = dir.path().join("fuzz-mmap.con");
    if std::fs::write(&path, &bytes).is_err() {
        return;
    }
    let _ = read_all_frames_with_threads(&path, Some(1));
    let _ = read_all_frames_with_threads(&path, Some(2));
    let _ = read_all_frames_indexed(&path, Some(1));
    let _ = read_all_frames_indexed(&path, Some(2));
});
