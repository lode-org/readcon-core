//! The chemfiles import the Python wheel calls: in-memory `read_chemfiles`
//! and the path helpers (`read_chemfiles`, first, nth, nsteps).

#![no_main]

use libfuzzer_sys::fuzz_target;
use readcon_core::chemfiles_import::{
    ChemfilesReadOpts, con_frame_from_trajectory_path, con_frame_from_trajectory_path_nth,
    con_frames_from_memory_with, con_frames_from_trajectory_path_with, nsteps_from_trajectory_path,
};
use readcon_core::types::ConFrame;

fn touch(frames: &[ConFrame]) {
    let mut sum = 0u64;
    for frame in frames {
        sum = sum.wrapping_add(frame.atom_data.len() as u64);
        sum = sum.wrapping_add(frame.header.boxl[0].to_bits());
    }
    std::hint::black_box(sum);
}

fn opts(data: &[u8]) -> ChemfilesReadOpts {
    let start = usize::from(data.first().copied().unwrap_or(0) % 4);
    let step = 1 + usize::from(data.get(1).copied().unwrap_or(0) % 3);
    let stop = if data.get(2).copied().unwrap_or(0) & 1 == 1 {
        Some(usize::from(data.get(2).copied().unwrap_or(0) % 8))
    } else {
        None
    };
    ChemfilesReadOpts {
        start,
        step,
        stop,
        format: Some("XYZ".into()),
        topology: None,
        topology_format: None,
        guess_bonds: data.get(3).copied().unwrap_or(0) & 1 == 1,
    }
}

fuzz_target!(|data: &[u8]| {
    if data.len() > 16 * 1024 {
        return;
    }
    let Ok(text) = std::str::from_utf8(data) else {
        return;
    };
    let read = opts(data);
    if let Ok(frames) = con_frames_from_memory_with(text, "XYZ", &read) {
        assert!(frames.len() <= text.len().saturating_add(1));
        touch(&frames);
    }

    let dir = match tempfile::tempdir() {
        Ok(dir) => dir,
        Err(_) => return,
    };
    let path = dir.path().join("in.xyz");
    if std::fs::write(&path, text.as_bytes()).is_err() {
        return;
    }
    if let Ok(frames) = con_frames_from_trajectory_path_with(&path, &read) {
        assert!(frames.len() <= text.len().saturating_add(1));
        touch(&frames);
    }
    if let Ok(count) = nsteps_from_trajectory_path(&path) {
        assert!(count <= text.len().saturating_add(1));
        if let Ok(frame) = con_frame_from_trajectory_path(&path) {
            touch(std::slice::from_ref(&frame));
        }
        if count > 0 {
            let index = usize::from(data.first().copied().unwrap_or(0)) % count;
            if let Ok(frame) = con_frame_from_trajectory_path_nth(&path, index) {
                touch(std::slice::from_ref(&frame));
            }
        }
    }
});
