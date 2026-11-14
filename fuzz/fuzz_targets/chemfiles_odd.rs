//! Chemfiles to CON conversion of odd frames: no atoms, non-finite
//! coordinates, and a species or atom count the body does not contain.

#![no_main]

use libfuzzer_sys::fuzz_target;
use readcon_core::chemfiles_import::{
    ChemfilesReadOpts, con_frame_from_trajectory_path, con_frames_from_memory,
    con_frames_from_memory_with, con_frames_from_trajectory_path_with,
};
use readcon_core::types::ConFrame;

fn touch(frames: &[ConFrame]) {
    let mut sum = 0u64;
    for frame in frames {
        sum = sum.wrapping_add(frame.atom_data.len() as u64);
        sum = sum.wrapping_add(frame.header.natm_types as u64);
        for atom in &frame.atom_data {
            sum = sum.wrapping_add(atom.x().to_bits());
        }
    }
    std::hint::black_box(sum);
}

fn accept_memory(data: &str, format: &str, guess_bonds: bool) {
    match con_frames_from_memory(data, format) {
        Ok(frames) => touch(&frames),
        Err(_) => {}
    }
    let opts = ChemfilesReadOpts {
        start: 0,
        step: 1,
        stop: None,
        format: Some(format.to_string()),
        topology: None,
        topology_format: None,
        guess_bonds,
    };
    if let Ok(frames) = con_frames_from_memory_with(data, format, &opts) {
        touch(&frames);
    }
}

fn accept_path(data: &str, format: &str, guess_bonds: bool) {
    let Ok(dir) = tempfile::tempdir() else {
        return;
    };
    let path = dir
        .path()
        .join(format!("odd.{}", format.to_ascii_lowercase()));
    if std::fs::write(&path, data).is_err() {
        return;
    }
    if let Ok(frame) = con_frame_from_trajectory_path(&path) {
        touch(std::slice::from_ref(&frame));
    }
    let opts = ChemfilesReadOpts {
        start: 0,
        step: 1,
        stop: None,
        format: Some(format.to_string()),
        topology: None,
        topology_format: None,
        guess_bonds,
    };
    if let Ok(frames) = con_frames_from_trajectory_path_with(&path, &opts) {
        touch(&frames);
    }
}

fn accept(data: &str, format: &str, guess_bonds: bool) {
    accept_memory(data, format, guess_bonds);
    accept_path(data, format, guess_bonds);
}

fuzz_target!(|data: &[u8]| {
    if data.len() > 4 * 1024 {
        return;
    }
    let guess = data.first().copied().unwrap_or(0) & 1 == 1;
    accept("0\n\n", "XYZ", guess);
    accept(
        "2\nnon-finite\nH nan nan nan\nH inf -inf nan\n",
        "XYZ",
        guess,
    );
    let species = 50_000_000u64 + u64::from(data.get(1).copied().unwrap_or(0)) * 1_000_000;
    let huge = format!("{species}\nhuge species count\nH 0 0 0\n");
    accept(&huge, "XYZ", false);
    let many_names = format!(
        "3\nmany names\nH 0 0 0\nHe 1 0 0\nLi 0 1 0\n\
         0\nempty species\n\
         1\nstill non-finite\nXx nan inf -inf\n"
    );
    accept(&many_names, "XYZ", guess);

    if data.is_empty() {
        return;
    }
    let text = String::from_utf8_lossy(data);
    let count = 1 + usize::from(data[0] % 4);
    let mut body = format!("{count}\nfuzz\n");
    for index in 0..count {
        let byte = data.get(index + 1).copied().unwrap_or(b'H');
        let symbol = if byte.is_ascii_alphabetic() {
            (byte as char).to_string()
        } else {
            "X".to_string()
        };
        body.push_str(&symbol);
        body.push_str(" 0 0 0\n");
    }
    accept(&body, "XYZ", guess);
    accept(&text, "XYZ", false);
    accept(&text, "CON", false);
});
