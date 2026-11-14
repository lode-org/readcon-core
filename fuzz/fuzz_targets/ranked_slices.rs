//! Single-process ranked publish.
//!
//! Arbitrary slice layouts, including empty ranks, go through
//! `publish_ranked_slices` (the `begin_shared_store` / `commit_shared_store`
//! path, and the opt-in spare). The file that comes back is the
//! concatenation of those slices.

#![no_main]

use libfuzzer_sys::fuzz_target;
use readcon_core::writer::publish_ranked_slices;

fn layout(data: &[u8]) -> (Vec<Vec<u8>>, bool, bool) {
    let rewrite = data.first().copied().unwrap_or(0) % 2 == 0;
    let keep_spare = data.get(1).copied().unwrap_or(0) % 2 == 0;
    let ranks = 1 + usize::from(data.get(2).copied().unwrap_or(0) % 24);
    let payload = if data.len() > 3 { &data[3..] } else { &[] };
    let payload = &payload[..payload.len().min(4096)];
    let mut slices = Vec::with_capacity(ranks);
    let mut at = 0usize;
    for rank in 0..ranks {
        if at >= payload.len() {
            slices.push(Vec::new());
            continue;
        }
        let spec = data.get(rank % data.len()).copied().unwrap_or(1);
        let take = match spec % 6 {
            0 => 0,
            1 => 1,
            2 => payload.len() - at,
            _ => 1 + usize::from(spec) % 48,
        };
        let end = if rank + 1 == ranks {
            payload.len()
        } else {
            (at + take).min(payload.len())
        };
        slices.push(payload[at..end].to_vec());
        at = end;
    }
    if at < payload.len() {
        slices.push(payload[at..].to_vec());
    }
    (slices, rewrite, keep_spare)
}

fn concat(slices: &[Vec<u8>]) -> Vec<u8> {
    let mut out = Vec::new();
    for slice in slices {
        out.extend_from_slice(slice);
    }
    out
}

fn spare_path(path: &std::path::Path) -> std::path::PathBuf {
    path.with_file_name(format!(
        "{}.rewrite",
        path.file_name().unwrap().to_string_lossy()
    ))
}

fn round_trip(path: &std::path::Path, slices: &[Vec<u8>], rewrite: bool, keep_spare: bool) {
    let refs: Vec<&[u8]> = slices.iter().map(|slice| slice.as_slice()).collect();
    publish_ranked_slices(path, &refs, rewrite, keep_spare).expect("publish");
    let got = std::fs::read(path).unwrap_or_default();
    assert_eq!(got, concat(slices), "ranked file is not the slices");
}

fn round_trip_mode(path: &std::path::Path, slices: &[Vec<u8>], mode: &str) {
    let previous = std::fs::read(path).unwrap_or_default();
    unsafe { std::env::set_var("READCON_RANKED_WRITE", mode) };
    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        round_trip(path, slices, false, false);
    }));
    unsafe { std::env::remove_var("READCON_RANKED_WRITE") };
    match result {
        Ok(()) => {}
        Err(payload) => std::panic::resume_unwind(payload),
    }
    let _ = previous;
}

fuzz_target!(|data: &[u8]| {
    if data.len() > 2048 {
        return;
    }
    let (slices, rewrite, keep_spare) = layout(data);
    let Ok(dir) = tempfile::tempdir() else {
        return;
    };
    let path = dir.path().join("ranked.bin");
    round_trip_mode(&path, &slices, "parallel");
    round_trip_mode(&path, &slices, "sequential");
    unsafe { std::env::remove_var("READCON_RANKED_WRITE") };
    round_trip(&path, &slices, false, false);
    assert!(
        !spare_path(&path).exists(),
        "default ranked publish left a spare"
    );
    let before = std::fs::read(&path).unwrap_or_default();
    unsafe { std::env::set_var("READCON_RANKED_WRITE", "ext4") };
    let rejected = publish_ranked_slices(&path, &[], false, false);
    unsafe { std::env::remove_var("READCON_RANKED_WRITE") };
    assert!(
        rejected.is_err(),
        "a bad ranked-store override was accepted"
    );
    assert_eq!(std::fs::read(&path).unwrap_or_default(), before);
    let (next, _, _) = layout(&data.iter().rev().copied().collect::<Vec<_>>());
    round_trip(&path, &next, rewrite, keep_spare);
    let spare = spare_path(&path);
    if rewrite && keep_spare {
        assert!(spare.exists(), "opt-in spare was not parked");
    } else {
        assert!(!spare.exists(), "spare left behind");
    }
});
