//! Gzip and zstd CON / convel readers.
//!
//! A valid member, including two concatenated members, must inflate to the
//! bytes that were compressed and parse back to the same bits. A truncated
//! stream, a bad CRC, a mismatched gzip ISIZE, or an index that lies about
//! the plain length must not panic. A successful inflate is never larger
//! than the plaintext that was compressed.

#![no_main]

use libfuzzer_sys::fuzz_target;
use readcon_core::compression::{
    codec_deflate, codec_inflate, default_deflate_threads, with_serial_decode,
    write_gzip_members_limited,
};
use readcon_core::iterators::{frames_from_bytes, read_all_frames};
use readcon_core::types::{ConFrame, ConFrameBuilder};
use readcon_core::units::NATURAL_TIME_UNIT;

fn finite(byte: u8) -> f64 {
    match byte % 5 {
        0 => 0.0,
        1 => -0.0,
        2 => 0.5,
        3 => 1.25,
        _ => -2.5,
    }
}

fn frame(atoms: usize, velocity: bool, scale: f64) -> ConFrame {
    let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
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
            "Cu",
            scale + index as f64,
            finite(index as u8),
            1.0,
            [false, false, false],
            index as u64,
            63.546,
        );
        if velocity {
            builder.with_velocity([0.1, -0.2, index as f64 * 0.01]);
        }
    }
    builder.build().expect("frame")
}

fn bits(frames: &[ConFrame]) -> Vec<u64> {
    let mut out = Vec::new();
    for frame in frames {
        for value in frame.header.boxl.iter().chain(frame.header.angles.iter()) {
            out.push(value.to_bits());
        }
        out.push(frame.atom_data.len() as u64);
        for atom in &frame.atom_data {
            out.push(atom.x().to_bits());
            out.push(atom.y().to_bits());
            out.push(atom.z().to_bits());
            if let Some(velocity) = atom.velocity() {
                out.extend(velocity.map(|value| value.to_bits()));
            }
        }
    }
    out
}

fn trajectory(data: &[u8]) -> (Vec<ConFrame>, Vec<u8>, bool) {
    let frames_n = 1 + usize::from(data.first().copied().unwrap_or(0) % 3);
    let atoms = 1 + usize::from(data.get(1).copied().unwrap_or(0) % 4);
    let velocity = data.get(2).copied().unwrap_or(0) % 2 == 0;
    let mut frames = Vec::with_capacity(frames_n);
    for index in 0..frames_n {
        frames.push(frame(atoms, velocity, index as f64));
    }
    let plain = readcon_core::writer::write_frames_to_vec(&frames).expect("plain");
    (frames, plain, velocity)
}

fn mutate(bytes: &[u8], kind: u8, salt: u8) -> Vec<u8> {
    match kind % 6 {
        0 => bytes.to_vec(),
        1 => {
            let keep = usize::from(salt) % (bytes.len().saturating_add(1));
            bytes[..keep.min(bytes.len())].to_vec()
        }
        2 => {
            let mut out = bytes.to_vec();
            if out.len() >= 8 {
                let at = out.len() - 8 + usize::from(salt % 4);
                out[at] ^= 0xa5;
            }
            out
        }
        3 => {
            let mut out = bytes.to_vec();
            if out.len() >= 4 {
                let n = out.len();
                out[n - 4..].copy_from_slice(&u32::MAX.to_le_bytes());
            }
            out
        }
        4 => {
            let mut out = bytes.to_vec();
            let keep = 1 + usize::from(salt) % bytes.len().max(1);
            out.extend_from_slice(&bytes[..keep.min(bytes.len())]);
            out
        }
        _ => lie_about_plain_length(bytes, salt),
    }
}

/// Overwrite a stored plain length in an RCZ1 index, when one is present.
fn lie_about_plain_length(bytes: &[u8], salt: u8) -> Vec<u8> {
    let mut out = bytes.to_vec();
    let Some(at) = out.windows(4).position(|window| window == b"RCZ1") else {
        if !out.is_empty() {
            let index = usize::from(salt) % out.len();
            out[index] ^= 0x3c;
        }
        return out;
    };
    let count_at = at + 4;
    if out.len() < count_at + 2 {
        return out;
    }
    let count = u16::from_le_bytes([out[count_at], out[count_at + 1]]) as usize;
    let lens = count_at + 2 + 8 * count;
    if count == 0 || out.len() < lens + 8 {
        return out;
    }
    let claimed = (out.len() as u64)
        .saturating_mul(64)
        .saturating_add(u64::from(salt));
    out[lens..lens + 8].copy_from_slice(&claimed.to_le_bytes());
    out
}

fn inflate_pair(bytes: &[u8]) -> (Result<Vec<u8>, ()>, Result<Vec<u8>, ()>) {
    let serial = with_serial_decode(|| codec_inflate(bytes, 1)).map_err(|_| ());
    let parallel = codec_inflate(bytes, 4).map_err(|_| ());
    (serial, parallel)
}

fn check_stream(encoded: &[u8], plain: &[u8], kind: u8, salt: u8) {
    let unmodified = kind % 6 == 0;
    let bytes = mutate(encoded, kind, salt);
    let (serial, parallel) = inflate_pair(&bytes);
    match (&serial, &parallel) {
        (Ok(serial), Ok(parallel)) => {
            assert_eq!(serial, parallel, "serial and threaded inflate diverged");
            accept(serial, plain, unmodified);
        }
        (Ok(serial), Err(())) => accept(serial, plain, false),
        (Err(()), Ok(parallel)) => accept(parallel, plain, false),
        (Err(()), Err(())) => {}
    }
}

fn accept(inflated: &[u8], plain: &[u8], unmodified: bool) {
    assert!(
        inflated.len() <= plain.len().saturating_mul(2).max(64),
        "inflate grew past the plaintext: {} vs {}",
        inflated.len(),
        plain.len()
    );
    if unmodified {
        assert_eq!(inflated, plain);
    }
}

fn coord_file(declared: usize, rows: &str) -> Vec<u8> {
    format!(
        "\n{{\"con_spec_version\":2}}\n10.0 10.0 10.0\n90.0 90.0 90.0\n0 0\n0 0\n1\n{declared}\n63.546\nCu\nCoordinates of Component 1\n{rows}"
    )
    .into_bytes()
}

/// `push_xyz` stores a row into reserved capacity. A short reserve must
/// grow, a declared count the file cannot hold must not become that many
/// atoms, and a truncated row must fail.
fn stress_rows(salt: u8) {
    let row = "0.0 0.0 1.0 0 0\n1.5 -0.0 1.0 0 1\n";
    let cut = salt as usize % row.len().max(1);
    let mut mismatch = coord_file(1, "0.0 0.0 1.0 0 0\n");
    mismatch.extend(coord_file(4, "1.0 2.0 3.0 0 1\n"));
    let cases = [
        coord_file(2, row),
        coord_file(100_000, "0.0 0.0 1.0 0 0\n"),
        coord_file(1, "0.0 0."),
        coord_file(3, ""),
        coord_file(1 + usize::from(salt % 5), &row[..cut]),
        mismatch,
    ];
    for text in cases {
        let one = frames_from_bytes(&text, Some(1));
        let many = frames_from_bytes(&text, Some(4));
        match (&one, &many) {
            (Ok(one), Ok(many)) => {
                let atoms: usize = one.iter().map(|frame| frame.atom_data.len()).sum();
                assert!(atoms.saturating_mul(3) <= text.len());
                assert_eq!(bits(one), bits(many), "row threads diverged");
            }
            (Err(_), Err(_)) => {}
            _ => panic!("row readers disagree on success"),
        }
    }
}

fuzz_target!(|data: &[u8]| {
    if data.len() > 256 {
        return;
    }
    stress_rows(data.first().copied().unwrap_or(0));
    let (_frames, plain, velocity) = trajectory(data);
    let expect = bits(&frames_from_bytes(&plain, Some(1)).expect("plain parse"));
    let kind = data.get(3).copied().unwrap_or(0);
    let salt = data.get(4).copied().unwrap_or(1);
    // The gzip writer deflates each member on its own worker. The default
    // is one worker per core, which is the path h2h12 turned on.
    let parallel_members = 2 + usize::from(data.get(5).copied().unwrap_or(0) % 3);
    let Ok(dir) = tempfile::tempdir() else {
        return;
    };
    let produced = dir.path().join(if velocity {
        "parallel.convel.gz"
    } else {
        "parallel.con.gz"
    });
    if write_gzip_members_limited(
        &produced,
        &plain,
        parallel_members,
        default_deflate_threads(parallel_members),
    )
    .is_ok()
    {
        if let Ok(encoded) = std::fs::read(&produced) {
            check_stream(&encoded, &plain, kind, salt);
            if kind % 6 == 0 {
                let got = read_all_frames(&produced).expect("parallel gzip");
                assert_eq!(bits(&got), expect, "parallel-deflated gzip");
            }
        }
    }
    for gzip in [true, false] {
        for members in [1usize, 2] {
            let Ok(encoded) = codec_deflate(&plain, members, 2, gzip) else {
                continue;
            };
            check_stream(&encoded, &plain, kind, salt);
            if kind % 6 == 0 {
                let ext = match (gzip, velocity) {
                    (true, false) => "con.gz",
                    (true, true) => "convel.gz",
                    (false, false) => "con.zst",
                    (false, true) => "convel.zst",
                };
                let Ok(dir) = tempfile::tempdir() else {
                    continue;
                };
                let path = dir.path().join(format!("traj.{ext}"));
                if std::fs::write(&path, &encoded).is_err() {
                    continue;
                }
                let got = read_all_frames(&path).expect("valid compressed file");
                assert_eq!(bits(&got), expect, "{ext}");
            }
        }
    }
});
