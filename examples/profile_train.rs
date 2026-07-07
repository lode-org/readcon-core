//! Workload for LLVM PGO train and optional `perf record` on multi-frame parse.
//!
//! Usage:
//!   cargo run --release --example profile_train --features parallel -- train
//!   cargo run --release --example profile_train --features parallel -- once
//!
//! No wall-clock timing, medians, or speedup reporting — only exercise the
//! full-frame parse path so the compiler / profiler see real code.

use readcon_core::iterators::{read_all_frames, ConFrameIterator};
use std::env;
use std::fs;
use std::hint::black_box;
use std::path::PathBuf;

fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn fixture(name: &str) -> String {
    fs::read_to_string(root().join("resources/test").join(name)).expect(name)
}

fn corpus() -> Vec<(String, String)> {
    let cuh2 = fixture("cuh2.con");
    let tiny = fixture("tiny_cuh2.con");
    vec![
        ("cuh2_x50".into(), cuh2.repeat(50)),
        ("cuh2_x100".into(), cuh2.repeat(100)),
        ("tiny_x200".into(), tiny.repeat(200)),
        ("cuh2_x30".into(), cuh2.repeat(30)),
    ]
}

fn read_all_frames_from_str(text: &str) -> Vec<readcon_core::types::ConFrame> {
    ConFrameIterator::new(text)
        .map(|r| r.expect("frame"))
        .collect()
}

fn train() {
    let cases = corpus();
    for _round in 0..8 {
        for (name, text) in &cases {
            let frames = read_all_frames_from_str(text);
            let _ = black_box((name, frames.len()));
            let n: usize = ConFrameIterator::new(text)
                .map(|f| black_box(f).expect("frame").atom_data.len())
                .sum();
            let _ = black_box(n);
            let mut it = ConFrameIterator::new(text);
            let mut skips = 0usize;
            while it.forward().transpose().expect("forward").is_some() {
                skips += 1;
            }
            let _ = black_box(skips);
        }
    }
    let one = fixture("cuh2.con");
    for _ in 0..200 {
        let frames: Vec<_> = ConFrameIterator::new(&one)
            .map(|r| r.expect("frame"))
            .collect();
        let _ = black_box(frames);
    }
    let multi = fixture("cuh2.con").repeat(100);
    let tmp = std::env::temp_dir().join(format!("readcon_pgo_train_{}.con", std::process::id()));
    fs::write(&tmp, &multi).unwrap();
    let n = read_all_frames(tmp.as_path()).unwrap().len();
    let _ = fs::remove_file(&tmp);
    let _ = black_box(n);
    eprintln!("train_done");
}

fn once() {
    let text = fixture("cuh2.con").repeat(100);
    for _ in 0..40 {
        let frames = read_all_frames_from_str(&text);
        let _ = black_box(frames.len());
    }
}

fn main() {
    match env::args().nth(1).as_deref() {
        Some("train") | None => train(),
        Some("once") => once(),
        Some(other) => {
            eprintln!("unknown mode {other}; use train|once");
            std::process::exit(2);
        }
    }
}
