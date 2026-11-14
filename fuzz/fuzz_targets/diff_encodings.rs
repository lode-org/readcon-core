//! One trajectory written as plain CON, gzip, zstd, and CON-bin.
//! The parsed coordinates must match across the four readers.

#![no_main]

use libfuzzer_sys::fuzz_target;
use readcon_core::compression::read_file_bytes;
use readcon_core::conbin::{read_owned_f64, write_from_con};
use readcon_core::iterators::frames_from_bytes;
use readcon_core::writer::{ConFrameWriter, write_frames_to_vec};

#[path = "writer_gen.rs"]
mod writer_gen;

fn bits(value: f64) -> u64 {
    value.to_bits()
}

fuzz_target!(|data: &[u8]| {
    if data.len() > 4096 {
        return;
    }
    let Some(frames) = writer_gen::frames_from(data, true) else {
        return;
    };
    let plain = write_frames_to_vec(&frames).expect("plain");
    let parsed = frames_from_bytes(&plain, Some(1)).expect("plain parse");
    writer_gen::assert_frames(&parsed, &frames);
    let parsed_parallel = frames_from_bytes(&plain, Some(4)).expect("parallel parse");
    writer_gen::assert_frames(&parsed_parallel, &frames);

    let Ok(dir) = tempfile::tempdir() else {
        return;
    };

    let gz_path = dir.path().join("out.con.gz");
    {
        let mut writer = ConFrameWriter::from_path_gzip(&gz_path).expect("gzip writer");
        for frame in &frames {
            writer.write_frame(frame).expect("gzip frame");
        }
        writer.flush().expect("gzip flush");
    }
    let inflated = read_file_bytes(&gz_path).expect("inflate gzip");
    writer_gen::read_plain(&inflated, &frames);

    let zst_path = dir.path().join("out.con.zst");
    {
        let mut writer = ConFrameWriter::from_path_zstd(&zst_path).expect("zstd writer");
        for frame in &frames {
            writer.write_frame(frame).expect("zstd frame");
        }
        writer.flush().expect("zstd flush");
    }
    let inflated = read_file_bytes(&zst_path).expect("inflate zstd");
    writer_gen::read_plain(&inflated, &frames);

    let con_path = dir.path().join("out.con");
    let bin_path = dir.path().join("out.conbin");
    std::fs::write(&con_path, &plain).expect("write con");
    write_from_con(&con_path, &bin_path, false).expect("conbin");
    let (_header, positions, velocities) = read_owned_f64(&bin_path, 1).expect("read conbin");
    let mut expect_pos = Vec::new();
    let mut expect_vel = Vec::new();
    for frame in &frames {
        for atom in &frame.atom_data {
            expect_pos.extend_from_slice(&[atom.x(), atom.y(), atom.z()]);
            expect_vel.extend_from_slice(&atom.velocity().unwrap_or([0.0; 3]));
        }
    }
    assert_eq!(positions.len(), expect_pos.len());
    assert_eq!(velocities.len(), expect_vel.len());
    for (got, expect) in positions.iter().zip(expect_pos.iter()) {
        assert_eq!(bits(*got), bits(*expect));
    }
    for (got, expect) in velocities.iter().zip(expect_vel.iter()) {
        assert_eq!(bits(*got), bits(*expect));
    }
});
