//! `write_con` with no compression: `ConFrameWriter::from_path`.

#![no_main]

use libfuzzer_sys::fuzz_target;
use readcon_core::writer::ConFrameWriter;

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
    let path = dir.path().join("out.con");
    let Ok(mut writer) = ConFrameWriter::from_path(&path) else {
        return;
    };
    if writer.write_frame(&frame).is_err() {
        return;
    }
    if writer.flush().is_err() {
        return;
    }
    drop(writer);
    let Ok(bytes) = std::fs::read(&path) else {
        return;
    };
    write_bits::read_back(&bytes, &frame);
});
