//! CON-bin column reader.
//!
//! A file this crate wrote reads back bit-exactly. A header that lies about
//! the frame count, the atom count, the payload offset, or the element width,
//! a column shorter than that header, and a huge declared count must fail
//! before a column of that size is reserved.

#![no_main]

use libfuzzer_sys::fuzz_target;
use readcon_core::conbin::{map_file, read_owned_f64, write_from_con};
use readcon_core::iterators::frames_from_bytes;
use readcon_core::types::{ConFrame, ConFrameBuilder};
use readcon_core::units::NATURAL_TIME_UNIT;
use readcon_core::writer::write_frames_to_vec;

fn frame(atoms: usize, velocity: bool) -> ConFrame {
    let mut builder = ConFrameBuilder::new([8.0, 9.0, 10.0], [90.0, 90.0, 90.0]);
    builder
        .set_units(serde_json::json!({
            "length": "angstrom",
            "energy": "eV",
            "mass": "amu",
            "time": NATURAL_TIME_UNIT,
        }))
        .expect("units");
    for index in 0..atoms {
        builder.add_atom(
            "H",
            index as f64 * 0.25,
            -1.0,
            0.5,
            [index % 2 == 0, false, false],
            index as u64 + 1,
            1.008,
        );
        if velocity {
            builder.with_velocity([0.0, index as f64, -0.25]);
        }
    }
    builder.build().expect("frame")
}

fn patch_u64(bytes: &mut [u8], at: usize, value: u64) {
    if bytes.len() >= at + 8 {
        bytes[at..at + 8].copy_from_slice(&value.to_le_bytes());
    }
}

fn lie(bytes: &[u8], kind: u8, salt: u8) -> Vec<u8> {
    let mut out = bytes.to_vec();
    if out.len() < 40 {
        return out;
    }
    match kind % 8 {
        0 => {}
        1 => patch_u64(&mut out, 24, u64::from(salt).saturating_add(1) << 20),
        2 => patch_u64(&mut out, 16, u64::MAX / 4),
        3 => patch_u64(&mut out, 24, 1),
        4 => {
            let keep = 40 + usize::from(salt) % 24;
            out.truncate(keep.min(out.len()));
        }
        5 => patch_u64(&mut out, 32, u64::from(salt) % 32),
        6 => {
            let flags = u32::from_le_bytes(out[12..16].try_into().unwrap()) ^ 1;
            out[12..16].copy_from_slice(&flags.to_le_bytes());
        }
        _ => {
            if out.len() > 48 {
                out.pop();
            }
        }
    }
    out
}

fn column_fits(header_atoms_times_frames_xyz: usize, file_len: usize, offset: usize) -> bool {
    header_atoms_times_frames_xyz
        .checked_mul(8)
        .and_then(|one| one.checked_mul(2))
        .and_then(|both| offset.checked_add(both))
        .is_some_and(|end| end <= file_len)
}

fuzz_target!(|data: &[u8]| {
    if data.len() > 64 {
        return;
    }
    let atoms = 1 + usize::from(data.first().copied().unwrap_or(0) % 5);
    let frames_n = 1 + usize::from(data.get(1).copied().unwrap_or(0) % 3);
    let velocity = data.get(2).copied().unwrap_or(0) % 2 == 1;
    let frames: Vec<ConFrame> = (0..frames_n).map(|_| frame(atoms, velocity)).collect();
    let text = write_frames_to_vec(&frames).expect("text");
    let parsed = frames_from_bytes(&text, Some(1)).expect("parse");
    let Ok(dir) = tempfile::tempdir() else {
        return;
    };
    let con = dir.path().join("in.con");
    let bin = dir.path().join("in.conbin");
    if std::fs::write(&con, &text).is_err() {
        return;
    }
    let header = write_from_con(&con, &bin, false).expect("conbin");
    assert_eq!(header.n_frames, frames_n as u64);
    assert_eq!(header.n_atoms, atoms as u64);
    let owned = read_owned_f64(&bin, 2).expect("owned");
    let (got, positions, velocities) = owned;
    let n = (frames_n * atoms * 3) as usize;
    assert_eq!(positions.len(), n);
    assert_eq!(velocities.len(), n);
    assert_eq!(got.n_frames, frames_n as u64);
    let mut cursor = 0usize;
    for frame in &parsed {
        for atom in &frame.atom_data {
            assert_eq!(positions[cursor].to_bits(), atom.x().to_bits());
            assert_eq!(positions[cursor + 1].to_bits(), atom.y().to_bits());
            assert_eq!(positions[cursor + 2].to_bits(), atom.z().to_bits());
            let velocity = atom.velocity().unwrap_or([0.0, 0.0, 0.0]);
            assert_eq!(velocities[cursor].to_bits(), velocity[0].to_bits());
            assert_eq!(velocities[cursor + 1].to_bits(), velocity[1].to_bits());
            assert_eq!(velocities[cursor + 2].to_bits(), velocity[2].to_bits());
            cursor += 3;
        }
    }
    let mapped = map_file(&bin, 2).expect("map");
    let mapped_pos = mapped.positions_f64().expect("mapped positions");
    assert_eq!(
        mapped_pos.iter().map(|v| v.to_bits()).collect::<Vec<_>>(),
        positions.iter().map(|v| v.to_bits()).collect::<Vec<_>>()
    );

    let raw = std::fs::read(&bin).expect("bytes");
    let kind = data.get(3).copied().unwrap_or(1);
    if kind % 8 == 0 {
        return;
    }
    let lied = lie(&raw, kind, data.get(4).copied().unwrap_or(9));
    let path = dir.path().join("lied.conbin");
    if std::fs::write(&path, &lied).is_err() {
        return;
    }
    match read_owned_f64(&path, 2) {
        Ok((header, positions, velocities)) => {
            let count = header.position_len().expect("count fits");
            assert_eq!(positions.len(), count);
            assert_eq!(velocities.len(), count);
            let offset = usize::try_from(u64::from_le_bytes(
                lied.get(32..40)
                    .unwrap_or(&[0; 8])
                    .try_into()
                    .unwrap_or([0; 8]),
            ))
            .unwrap_or(usize::MAX);
            assert!(
                column_fits(count, lied.len(), offset),
                "reserved a column the file does not hold"
            );
        }
        Err(_) => {}
    }
    if let Ok(mapped) = map_file(&path, 1) {
        let _ = mapped.positions_f64();
        let _ = mapped.velocities_f64();
        let _ = mapped.positions_f32();
    }

    let huge = dir.path().join("huge.conbin");
    let mut header_only = raw[..40].to_vec();
    patch_u64(&mut header_only, 16, 1);
    patch_u64(&mut header_only, 24, 1 << 40);
    if std::fs::write(&huge, &header_only).is_ok() {
        assert!(
            read_owned_f64(&huge, 1).is_err(),
            "a huge declared atom count was reserved"
        );
    }
});
