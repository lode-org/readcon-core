//! The same frames through every reader.
//!
//! The core reader, the C reader, the phased reader the Python bindings
//! call, the threaded reader, and an in-process split of the frame index
//! must agree bit for bit. That still holds for gzip and zstd, and for the
//! indexed read after a rewrite that leaves the previous sidecar in place.
//!
//! `read_con` in the Python module calls `read_all_frames_phased`. The
//! pyo3 crate is built as an extension module, so the fuzzer calls that
//! function directly.

#![no_main]

use std::ffi::CString;
use std::os::raw::c_char;

use libfuzzer_sys::fuzz_target;
use readcon_core::compression::{
    codec_deflate, default_deflate_threads, write_gzip_members_limited,
};
use readcon_core::ffi::{free_rkr_frame_array, rkr_read_all_frames, rkr_read_all_frames_n_threads};
use readcon_core::frame_index::{self, FrameIndex};
use readcon_core::iterators::{
    frames_from_bytes, read_all_frames, read_all_frames_indexed, read_all_frames_phased,
    read_all_frames_with_threads,
};
use readcon_core::types::{ConFrame, ConFrameBuilder};
use readcon_core::units::NATURAL_TIME_UNIT;
use readcon_core::writer::{
    publish_ranked_slices, rewrite_frame_refs_to_path, write_frame_refs_to_path,
};

fn frame(atoms: usize, velocity: bool, tag: f64) -> ConFrame {
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
            tag + index as f64 * 0.5,
            if index % 2 == 0 { -0.0 } else { 0.25 },
            1.0,
            [false, false, false],
            index as u64,
            63.546,
        );
        if velocity {
            builder.with_velocity([0.01, tag, -0.5]);
        }
    }
    builder.build().expect("frame")
}

fn bits(frames: &[ConFrame]) -> Vec<u64> {
    let mut out = Vec::new();
    for frame in frames {
        out.push(frame.atom_data.len() as u64);
        for value in frame.header.boxl.iter().chain(&frame.header.angles) {
            out.push(value.to_bits());
        }
        for atom in &frame.atom_data {
            out.push(atom.x().to_bits());
            out.push(atom.y().to_bits());
            out.push(atom.z().to_bits());
            out.push(atom.atom_id);
            match atom.velocity() {
                Some(velocity) => out.extend(velocity.map(|value| value.to_bits())),
                None => out.push(0),
            }
        }
    }
    out
}

fn frames_of(data: &[u8]) -> Vec<ConFrame> {
    let n = 1 + usize::from(data.first().copied().unwrap_or(0) % 3);
    let atoms = 1 + usize::from(data.get(1).copied().unwrap_or(0) % 4);
    let velocity = data.get(2).copied().unwrap_or(0) % 2 == 0;
    (0..n)
        .map(|index| frame(atoms, velocity, index as f64))
        .collect()
}

fn ffi_bits(path: &std::path::Path, threads: Option<usize>) -> Option<Vec<u64>> {
    let text = CString::new(path.to_string_lossy().as_bytes()).ok()?;
    let mut count = 0usize;
    let ptr = unsafe {
        match threads {
            None => rkr_read_all_frames(text.as_ptr() as *const c_char, &mut count),
            Some(threads) => {
                rkr_read_all_frames_n_threads(text.as_ptr() as *const c_char, &mut count, threads)
            }
        }
    };
    if ptr.is_null() {
        return None;
    }
    let frames = unsafe {
        let handles = std::slice::from_raw_parts(ptr, count);
        let mut frames = Vec::with_capacity(count);
        for handle in handles {
            let frame = (*handle as *const ConFrame).as_ref().expect("frame");
            frames.push(frame.clone());
        }
        free_rkr_frame_array(ptr, count);
        frames
    };
    Some(bits(&frames))
}

fn ranked_bits(text: &str, ranks: usize) -> Option<Vec<u64>> {
    let index = FrameIndex::scan(text).ok()?;
    if index.is_empty() {
        return frames_from_bytes(text.as_bytes(), Some(1))
            .ok()
            .map(|frames| bits(&frames));
    }
    let ranks = ranks.clamp(1, index.len());
    let mut frames = Vec::new();
    let mut slices: Vec<&[u8]> = Vec::new();
    let per = index.len().div_ceil(ranks);
    for rank in 0..ranks {
        let start_i = rank * per;
        if start_i >= index.len() {
            slices.push(b"");
            continue;
        }
        let end_i = (start_i + per).min(index.len());
        let start = index.range(start_i)?.start;
        let end = index.range(end_i - 1)?.end;
        let piece = &text.as_bytes()[start..end];
        slices.push(piece);
        frames.extend(frames_from_bytes(piece, Some(1)).ok()?);
    }
    let whole = frame_index::content_hash(text.as_bytes());
    assert_eq!(
        frame_index::ranked_content_hash(&slices),
        whole,
        "ranked split hash"
    );
    Some(bits(&frames))
}

fn agree(path: &std::path::Path, expect: &[u64], ranks: usize) {
    let core = read_all_frames(path).expect("core");
    assert_eq!(bits(&core), expect, "core");
    let threaded = read_all_frames_with_threads(path, Some(4)).expect("threaded");
    assert_eq!(bits(&threaded), expect, "threaded");
    let phased = read_all_frames_phased(path, Some(1)).expect("python path");
    assert_eq!(bits(&phased.frames), expect, "phased");
    let phased_threads = read_all_frames_phased(path, Some(4)).expect("phased threads");
    assert_eq!(bits(&phased_threads.frames), expect, "phased threads");
    let ffi = ffi_bits(path, None).expect("ffi");
    assert_eq!(ffi, expect, "ffi");
    let ffi_threads = ffi_bits(path, Some(4)).expect("ffi threads");
    assert_eq!(ffi_threads, expect, "ffi threads");
    let text = readcon_core::compression::read_file_bytes(path).expect("bytes");
    let text = std::str::from_utf8(&text).expect("utf8");
    let ranked = ranked_bits(text, ranks).expect("ranked");
    assert_eq!(ranked, expect, "ranked");
}

fn coord_file(declared: usize, rows: &str) -> Vec<u8> {
    format!(
        "\n{{\"con_spec_version\":2}}\n10.0 10.0 10.0\n90.0 90.0 90.0\n0 0\n0 0\n1\n{declared}\n63.546\nCu\nCoordinates of Component 1\n{rows}"
    )
    .into_bytes()
}

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
    if data.len() > 64 {
        return;
    }
    stress_rows(data.first().copied().unwrap_or(0));
    let frames = frames_of(data);
    let refs: Vec<&ConFrame> = frames.iter().collect();
    let expect = bits(
        &frames_from_bytes(
            &readcon_core::writer::write_frames_to_vec(&frames).expect("vec"),
            Some(1),
        )
        .expect("parse"),
    );
    let Ok(dir) = tempfile::tempdir() else {
        return;
    };
    let plain = dir.path().join("traj.con");
    write_frame_refs_to_path(&plain, &refs, 1, None, false, false).expect("write");
    let ranks = 1 + usize::from(data.get(3).copied().unwrap_or(0) % 4);
    agree(&plain, &expect, ranks);

    // Two frames, one worker: spelled into the fresh file via fallocate.
    let serial_frames = [frames[0].clone(), frames[0].clone()];
    let serial_refs = [&serial_frames[0], &serial_frames[1]];
    let serial_path = dir.path().join("serial.con");
    write_frame_refs_to_path(&serial_path, &serial_refs, 1, None, false, false)
        .expect("serial fresh file");
    let serial_expect = bits(&read_all_frames(&serial_path).expect("serial core"));
    agree(&serial_path, &serial_expect, ranks);

    let bytes = std::fs::read(&plain).expect("plain bytes");
    for (gzip, name) in [(true, "traj.con.gz"), (false, "traj.con.zst")] {
        let Ok(encoded) = codec_deflate(&bytes, 2, 2, gzip) else {
            continue;
        };
        let path = dir.path().join(name);
        if std::fs::write(&path, &encoded).is_err() {
            continue;
        }
        agree(&path, &expect, ranks);
    }
    let parallel_members = 2 + usize::from(data.get(5).copied().unwrap_or(0) % 3);
    let parallel_gz = dir.path().join("parallel.con.gz");
    if write_gzip_members_limited(
        &parallel_gz,
        &bytes,
        parallel_members,
        default_deflate_threads(parallel_members),
    )
    .is_ok()
    {
        agree(&parallel_gz, &expect, ranks);
    }

    let mut pieces = Vec::new();
    let mut at = 0usize;
    for rank in 0..ranks {
        let end = if rank + 1 == ranks {
            bytes.len()
        } else {
            (rank + 1) * bytes.len() / ranks
        };
        pieces.push(bytes[at..end].to_vec());
        at = end;
    }
    let refs: Vec<&[u8]> = pieces.iter().map(|piece| piece.as_slice()).collect();
    let spare = plain.with_file_name(format!(
        "{}.rewrite",
        plain.file_name().unwrap().to_string_lossy()
    ));
    publish_ranked_slices(&plain, &refs, false, false).expect("default ranked");
    assert!(!spare.exists(), "default ranked publish left a spare");
    agree(&plain, &expect, ranks);
    publish_ranked_slices(&plain, &refs, true, true).expect("ranked spare");
    assert!(spare.exists(), "opt-in ranked spare is missing");
    agree(&plain, &expect, ranks);
    publish_ranked_slices(&plain, &refs, true, false).expect("drop ranked spare");
    assert!(!spare.exists(), "keep_spare false left the ranked spare");
    agree(&plain, &expect, ranks);

    let index = FrameIndex::scan(std::str::from_utf8(&bytes).expect("utf8")).expect("scan");
    frame_index::write_sidecar(&plain, &index).expect("sidecar");
    let replacement = frame(
        frames[0].atom_data.len(),
        frames[0].atom_data[0].velocity().is_some(),
        4.5,
    );
    let keep_spare = data.get(4).copied().unwrap_or(0) % 2 == 0;
    rewrite_frame_refs_to_path(&plain, &[&replacement], 2, None, false, false, keep_spare)
        .expect("rewrite");
    let rewritten = bits(&read_all_frames(&plain).expect("rewritten core"));
    let indexed = read_all_frames_indexed(&plain, Some(2)).expect("indexed after rewrite");
    assert_eq!(bits(&indexed), rewritten, "stale sidecar after rewrite");
    let ffi = ffi_bits(&plain, Some(2)).expect("ffi after rewrite");
    assert_eq!(ffi, rewritten, "ffi after rewrite");
});
