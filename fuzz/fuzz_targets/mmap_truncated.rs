//! Mapped and indexed reads of a truncated last frame, and of a trajectory
//! whose frames do not share one atom count.
//!
//! The files are padded to `MMAP_THRESHOLD` so the plain reader maps them.
//! A header that declares far more atoms than the body contains must fail
//! without reserving that count.

#![no_main]

use libfuzzer_sys::fuzz_target;
use readcon_core::compression::MMAP_THRESHOLD;
use readcon_core::frame_index::frame_start_offsets_checked;
use readcon_core::iterators::{
    frames_from_bytes, read_all_frames, read_all_frames_indexed, read_all_frames_with_threads,
    read_positions_with_threads,
};
use std::path::Path;

const ONE_ATOM: &str = "\
conformance: one atom
{\"con_spec_version\":2}
10.000000 10.000000 10.000000
90.000000 90.000000 90.000000


1
1
63.546000
Cu
Coordinates of Component 1
0.000000 0.000000 0.000000 7 0
";

const TWO_ATOMS: &str = "\
conformance: two atoms
{\"con_spec_version\":2}
10.000000 10.000000 10.000000
90.000000 90.000000 90.000000


1
2
63.546000
Cu
Coordinates of Component 1
0.000000 0.000000 0.000000 7 0
1.000000 0.000000 0.000000 7 1
";

fn pad_full(bytes: &[u8]) -> Vec<u8> {
    let need = MMAP_THRESHOLD as usize;
    if bytes.is_empty() {
        return vec![b'\n'; need];
    }
    let mut out = Vec::with_capacity(need + bytes.len());
    while out.len() < need {
        out.extend_from_slice(bytes);
    }
    out
}

fn read_mapped(path: &Path, bytes: &[u8]) {
    if let Ok(text) = std::str::from_utf8(bytes) {
        let _ = frame_start_offsets_checked(text);
    }
    let _ = read_all_frames(path);
    let _ = read_all_frames_with_threads(path, Some(1));
    let _ = read_all_frames_with_threads(path, Some(2));
    let _ = read_all_frames_indexed(path, Some(1));
    let _ = read_all_frames_indexed(path, Some(2));
    let _ = read_positions_with_threads(path, Some(1));
    let _ = read_positions_with_threads(path, Some(2));
}

fn write(dir: &std::path::Path, name: &str, bytes: &[u8]) -> Option<std::path::PathBuf> {
    let path = dir.join(name);
    std::fs::write(&path, bytes).ok()?;
    Some(path)
}

fuzz_target!(|data: &[u8]| {
    if data.len() > 8 * 1024 {
        return;
    }
    let disagree = format!("{ONE_ATOM}{TWO_ATOMS}");
    let parsed = frames_from_bytes(disagree.as_bytes(), Some(2)).expect("pair parses");
    assert!(parsed.len() >= 2);
    assert_ne!(parsed[0].atom_data.len(), parsed[1].atom_data.len());

    let padded = pad_full(disagree.as_bytes());
    let Ok(dir) = tempfile::tempdir() else {
        return;
    };
    let Some(path) = write(dir.path(), "disagree.con", &padded) else {
        return;
    };
    let mapped = read_all_frames_with_threads(&path, Some(1)).expect("disagree maps");
    assert!(mapped.iter().any(|frame| frame.atom_data.len() == 1));
    assert!(mapped.iter().any(|frame| frame.atom_data.len() == 2));
    read_mapped(&path, &padded);

    let cut = 1 + usize::from(data.first().copied().unwrap_or(0) % 80);
    let partial = &ONE_ATOM.as_bytes()[..cut.min(ONE_ATOM.len() - 1)];
    let mut truncated = padded.clone();
    truncated.extend_from_slice(partial);
    if let Some(path) = write(dir.path(), "truncated.con", &truncated) {
        let indexed = read_all_frames_indexed(&path, Some(2));
        assert!(indexed.is_err(), "truncated last frame parsed");
        read_mapped(&path, &truncated);
    }

    let declared = 50_000_000u64 + u64::from(data.get(1).copied().unwrap_or(0)) * 1_000_000;
    let huge = format!(
        "conformance: declared count exceeds the body\n\
{{\"con_spec_version\":2}}\n\
10.000000 10.000000 10.000000\n\
90.000000 90.000000 90.000000\n\
\n\
\n\
1\n\
{declared}\n\
63.546000\n\
Cu\n\
Coordinates of Component 1\n\
0.000000 0.000000 0.000000 7 0\n"
    );
    let huge = pad_full(huge.as_bytes());
    if let Some(path) = write(dir.path(), "huge-count.con", &huge) {
        let read = read_all_frames_with_threads(&path, Some(2));
        assert!(read.is_err(), "huge declared count was reserved");
        read_mapped(&path, &huge);
    }

    if !data.is_empty() {
        let mut raw = data.to_vec();
        if raw.len() >= 4 {
            raw.truncate(raw.len() - 1 - usize::from(raw[0] % 3));
        }
        if let Some(path) = write(dir.path(), "raw.con", &pad_full(&raw)) {
            read_mapped(&path, &raw);
        }
    }
});
