//! A corrupt, truncated, or swapped `.rcidx` must not change the frames
//! a valid CON file parses to. The reader rejects the table and scans.

#![no_main]

use libfuzzer_sys::fuzz_target;
use readcon_core::frame_index::{self, FrameIndex};
use readcon_core::iterators::{frames_from_bytes, read_all_frames_indexed};
use readcon_core::types::{ConFrame, ConFrameBuilder};
use readcon_core::writer::write_frames_to_vec;

fn frame(atoms: usize, tag: f64) -> ConFrame {
    let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
    for index in 0..atoms {
        builder.add_atom(
            "Cu",
            tag + index as f64,
            0.0,
            1.0,
            [false, false, false],
            index as u64,
            63.546,
        );
    }
    builder.build().expect("frame")
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

fn read_indexed(dir: &std::path::Path, name: &str, bytes: &[u8]) -> Vec<ConFrame> {
    let path = dir.join(name);
    std::fs::write(&path, bytes).expect("write");
    read_all_frames_indexed(&path, Some(2)).expect("indexed")
}

fn gather_matches(data: &[u8]) {
    let whole = frame_index::content_hash(data);
    assert_eq!(frame_index::ranked_content_hash(&[data]), whole);
    if data.len() < 2 {
        assert_eq!(frame_index::ranked_content_hash(&[&[], data, &[]]), whole);
        return;
    }
    let ranks = 2 + usize::from(data[0] % 6);
    let mut parts: Vec<&[u8]> = Vec::new();
    let mut at = 0usize;
    for rank in 0..ranks {
        if data.get(rank).copied().unwrap_or(0) % 4 == 0 {
            parts.push(&[]);
        }
        if at >= data.len() {
            continue;
        }
        let len = 1 + usize::from(data.get(rank).copied().unwrap_or(1) % 80);
        let end = (at + len).min(data.len());
        parts.push(&data[at..end]);
        at = end;
    }
    if at < data.len() {
        parts.push(&data[at..]);
    }
    assert_eq!(frame_index::ranked_content_hash(&parts), whole, "gather");
    let short: [&[u8]; 3] = [&data[..1], &[], &data[1..]];
    assert_eq!(
        frame_index::ranked_content_hash(&short),
        whole,
        "short rank"
    );
    let mut flipped = data.to_vec();
    let index = usize::from(data[0]) % flipped.len();
    flipped[index] ^= 0x5a;
    assert_ne!(
        frame_index::ranked_content_hash(&[&flipped]),
        whole,
        "a flipped byte kept the gathered hash"
    );
}

fuzz_target!(|data: &[u8]| {
    if data.is_empty() || data.len() > 4096 {
        return;
    }
    gather_matches(data);
    let frames = vec![
        frame(1 + usize::from(data[0] % 3), 0.0),
        frame(1 + usize::from(data[0] % 5), 10.0),
    ];
    let text = write_frames_to_vec(&frames).expect("text");
    let expect = frames_from_bytes(&text, Some(1)).expect("parse");
    let expect_bits = bits(&expect);

    let Ok(dir) = tempfile::tempdir() else {
        return;
    };
    let path = dir.path().join("traj.con");
    std::fs::write(&path, &text).expect("file");
    let index = FrameIndex::scan(std::str::from_utf8(&text).expect("utf8")).expect("scan");
    frame_index::write_sidecar(&path, &index).expect("sidecar");
    let sidecar = frame_index::sidecar_path(&path);
    let mut raw = std::fs::read(&sidecar).expect("read sidecar");

    let clean = read_all_frames_indexed(&path, Some(2)).expect("clean index");
    assert_eq!(bits(&clean), expect_bits);

    if raw.is_empty() {
        return;
    }
    let at = usize::from(data[0]) % raw.len();
    raw[at] ^= data.get(1).copied().unwrap_or(0x5a) | 1;
    std::fs::write(&sidecar, &raw).expect("corrupt");
    let got = read_all_frames_indexed(&path, Some(1)).expect("corrupt falls back");
    assert_eq!(bits(&got), expect_bits);

    let keep = (raw.len() * usize::from(data.get(2).copied().unwrap_or(1) % 4 + 1)) / 4;
    std::fs::write(&sidecar, &raw[..keep.min(raw.len())]).expect("truncate");
    let got = read_all_frames_indexed(&path, Some(2)).expect("truncated falls back");
    assert_eq!(bits(&got), expect_bits);

    let other = write_frames_to_vec(&[frame(4, 3.0)]).expect("other");
    let other_path = dir.path().join("other.con");
    std::fs::write(&other_path, &other).expect("other file");
    let other_index =
        FrameIndex::scan(std::str::from_utf8(&other).expect("utf8")).expect("other scan");
    frame_index::write_sidecar(&other_path, &other_index).expect("other sidecar");
    std::fs::copy(frame_index::sidecar_path(&other_path), &sidecar).expect("swap");
    let got = read_indexed(dir.path(), "traj.con", &text);
    assert_eq!(bits(&got), expect_bits);
    assert_ne!(
        bits(&got),
        bits(&frames_from_bytes(&other, Some(1)).expect("other parse"))
    );
});
