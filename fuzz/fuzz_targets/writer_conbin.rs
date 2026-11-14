#![no_main]

use libfuzzer_sys::fuzz_target;
use readcon_core::conbin::{read_owned_f64, write_from_con};
use readcon_core::writer::write_frames_to_vec;

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
    let Ok(dir) = tempfile::tempdir() else {
        return;
    };
    let con = dir.path().join("out.con");
    let bin = dir.path().join("out.conbin");
    std::fs::write(&con, &plain).expect("write con");
    write_from_con(&con, &bin, false).expect("conbin");
    let (_header, positions, velocities) = read_owned_f64(&bin, 1).expect("read conbin");
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
