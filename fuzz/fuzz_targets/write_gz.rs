//! `write_con` gzip: the streaming gzip writer and member gzip.

#![no_main]

use libfuzzer_sys::fuzz_target;
use readcon_core::compression::{read_file_bytes, write_gzip_members_limited};
use readcon_core::writer::{ConFrameWriter, write_frames_to_vec};

#[path = "write_bits.rs"]
mod write_bits;

fuzz_target!(|data: &[u8]| {
    if data.len() > 4096 {
        return;
    }
    let Some(frame) = write_bits::frame_from(data) else {
        return;
    };
    let Ok(dir) = tempfile::tempdir() else {
        return;
    };

    let path = dir.path().join("out.con.gz");
    if let Ok(mut writer) = ConFrameWriter::from_path_gzip(&path) {
        if writer.write_frame(&frame).is_ok() && writer.flush().is_ok() {
            drop(writer);
            if let Ok(bytes) = read_file_bytes(&path) {
                write_bits::read_back(&bytes, &frame);
            }
        }
    }

    if let Ok(plain) = write_frames_to_vec(std::slice::from_ref(&frame)) {
        let members = dir.path().join("members.con.gz");
        let count = 1 + usize::from(data.first().copied().unwrap_or(0) % 4);
        if write_gzip_members_limited(&members, &plain, count, 1).is_ok() {
            if let Ok(bytes) = read_file_bytes(&members) {
                write_bits::read_back(&bytes, &frame);
            }
        }
    }
});
