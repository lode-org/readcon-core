//! Coordinate rows that `push_xyz` stores with `set_len`.
//!
//! Truncated lines, oversized declared counts, and malformed tokens must
//! not panic or reserve the lie. A complete row still comes back with the
//! same bits on one thread and on four.

#![no_main]

use libfuzzer_sys::fuzz_target;
use readcon_core::iterators::{frames_from_bytes, read_all_frames};
use readcon_core::types::ConFrame;

fn header(declared: u64) -> String {
    format!(
        "\n{{\"con_spec_version\":2}}\n10.0 10.0 10.0\n90.0 90.0 90.0\n0 0\n0 0\n1\n{declared}\n63.546\nCu\nCoordinates of Component 1\n"
    )
}

fn bits(frames: &[ConFrame]) -> Vec<u64> {
    let mut out = Vec::new();
    for frame in frames {
        out.push(frame.atom_data.len() as u64);
        for atom in &frame.atom_data {
            out.push(atom.x().to_bits());
            out.push(atom.y().to_bits());
            out.push(atom.z().to_bits());
        }
    }
    out
}

fn check(text: &[u8]) {
    let one = frames_from_bytes(text, Some(1));
    let many = frames_from_bytes(text, Some(4));
    match (&one, &many) {
        (Ok(one), Ok(many)) => {
            let atoms: usize = one.iter().map(|frame| frame.atom_data.len()).sum();
            assert!(
                atoms.saturating_mul(3) <= text.len(),
                "reserved more atoms than the text can hold"
            );
            assert_eq!(bits(one), bits(many), "push_xyz threads diverged");
        }
        (Err(_), Err(_)) => {}
        _ => panic!("row readers disagree on success"),
    }
}

fn malformed(kind: u8, salt: u8) -> String {
    match kind % 8 {
        0 => "0.0 0.".into(),
        1 => format!("{:0width$} 1 2 0 0\n", 1, width = 400 + usize::from(salt)),
        2 => "1.2.3 - 4 5 0 0\n".into(),
        3 => "nan inf -inf 0 0\n".into(),
        4 => "\t1\t2\t3\t0\t1\n".into(),
        5 => "1 2 3 0 1\r\n".into(),
        6 => format!("1 2 3 0 {}\n", u64::from(salt)),
        _ => String::new(),
    }
}

fuzz_target!(|data: &[u8]| {
    if data.len() > 512 {
        return;
    }
    let declared = match data.first().copied().unwrap_or(0) % 5 {
        0 => 0,
        1 => 1,
        2 => 2,
        3 => 10_000 + u64::from(data.get(1).copied().unwrap_or(0)),
        _ => u64::from(data.get(1).copied().unwrap_or(1)),
    };
    let body = malformed(
        data.get(2).copied().unwrap_or(0),
        data.get(3).copied().unwrap_or(0),
    );
    let mut text = header(declared).into_bytes();
    text.extend(body.as_bytes());
    if data.len() > 4 {
        let cut = 4 + usize::from(data[4]) % data[4..].len().max(1);
        text.extend(&data[4..4 + cut.min(data.len() - 4)]);
    }
    check(&text);

    let valid = header(1) + "0.5 -0.0 1.25 0 3\n";
    let parsed = frames_from_bytes(valid.as_bytes(), Some(1)).expect("one row");
    assert_eq!(parsed.len(), 1);
    assert_eq!(parsed[0].atom_data.len(), 1);
    assert_eq!(parsed[0].atom_data[0].x().to_bits(), 0.5f64.to_bits());
    assert_eq!(parsed[0].atom_data[0].y().to_bits(), (-0.0f64).to_bits());
    assert_eq!(parsed[0].atom_data[0].z().to_bits(), 1.25f64.to_bits());

    let Ok(dir) = tempfile::tempdir() else {
        return;
    };
    let path = dir.path().join("rows.con");
    if std::fs::write(&path, &text).is_err() {
        return;
    }
    match read_all_frames(&path) {
        Ok(frames) => {
            let atoms: usize = frames.iter().map(|frame| frame.atom_data.len()).sum();
            assert!(atoms.saturating_mul(3) <= text.len());
        }
        Err(_) => {}
    }
});
