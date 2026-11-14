#![no_main]

use libfuzzer_sys::fuzz_target;
use readcon_core::compression::{read_file_bytes, write_zstd_members_limited};
use readcon_core::writer::{ConFrameWriter, write_frames_to_vec};

#[path = "writer_gen.rs"]
mod writer_gen;

fuzz_target!(|data: &[u8]| {
    if data.len() > 4096 {
        return;
    }
    let Some(frames) = writer_gen::frames_from(data, false) else {
        return;
    };
    let plain = write_frames_to_vec(&frames).expect("plain");
    let Ok(dir) = tempfile::tempdir() else {
        return;
    };
    let path = dir.path().join("out.con.zst");
    {
        let mut writer = ConFrameWriter::from_path_zstd(&path).expect("zstd writer");
        for frame in &frames {
            writer.write_frame(frame).expect("zstd frame");
        }
        writer.flush().expect("zstd flush");
    }
    let inflated = read_file_bytes(&path).expect("inflate zstd");
    writer_gen::read_plain(&inflated, &frames);

    let members = 1 + usize::from(data.first().copied().unwrap_or(0) % 4);
    let member_path = dir.path().join("members.con.zst");
    write_zstd_members_limited(&member_path, &plain, members, 2).expect("zstd members");
    let inflated = read_file_bytes(&member_path).expect("inflate members");
    writer_gen::read_plain(&inflated, &frames);
});
