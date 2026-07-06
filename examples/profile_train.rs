//! Train / measure harness for perf + LLVM PGO on the multi-frame parse path.
//! Usage:
//!   cargo run --release --example profile_train -- train
//!   cargo run --release --example profile_train -- measure [label] [out.json]
//!   cargo run --release --example profile_train -- once

use readcon_core::iterators::{read_all_frames, read_frame_coordinates_str, ConFrameIterator};
use std::env;
use std::fs;
use std::hint::black_box;
use std::path::PathBuf;
use std::time::Instant;

fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn fixture(name: &str) -> String {
    fs::read_to_string(root().join("resources/test").join(name)).expect(name)
}

/// Representative corpus: multi-atom multi-frame + tiny multi-frame + skip path.
fn corpus() -> Vec<(String, String, usize)> {
    let cuh2 = fixture("cuh2.con");
    let tiny = fixture("tiny_cuh2.con");
    vec![
        ("cuh2_x50".into(), cuh2.repeat(50), 50),
        ("cuh2_x100".into(), cuh2.repeat(100), 100),
        ("tiny_x200".into(), tiny.repeat(200), 200),
        ("cuh2_x30".into(), cuh2.repeat(30), 30),
    ]
}

fn train() {
    // Heavy enough for PGO counters on atom-line + header + parallel paths.
    let cases = corpus();
    for _round in 0..8 {
        for (name, text, _n) in &cases {
            let frames = read_all_frames_from_str(text);
            let _ = black_box((name, frames.len()));
            // sequential iterator path (non-parallel entry)
            let n: usize = ConFrameIterator::new(text)
                .map(|f| black_box(f).expect("frame").atom_data.len())
                .sum();
            let _ = black_box(n);
            // forward skip path (memchr)
            let mut it = ConFrameIterator::new(text);
            let mut skips = 0usize;
            while it.forward().transpose().expect("forward").is_some() {
                skips += 1;
            }
            let _ = black_box(skips);
        }
    }
    // also hit single-frame multi-atom
    let one = fixture("cuh2.con");
    for _ in 0..200 {
        let frames: Vec<_> = ConFrameIterator::new(&one)
            .map(|r| r.expect("frame"))
            .collect();
        let _ = black_box(frames);
    }
    eprintln!("train_done");
}

fn read_all_frames_from_str(text: &str) -> Vec<readcon_core::types::ConFrame> {
    // Prefer public multi-frame API used by bindings when path-based; string path
    // uses the same iterator/parallel gate via temp is not needed — collect from iterator
    // and also exercise read_all_frames via a temp file for the real entry point.
    ConFrameIterator::new(text)
        .map(|r| r.expect("frame"))
        .collect()
}

fn measure_once(text: &str) -> f64 {
    let t0 = Instant::now();
    let frames = read_all_frames_from_str(text);
    let elapsed = t0.elapsed().as_secs_f64();
    let _ = black_box(frames.len());
    elapsed
}

fn measure(label: &str, out: Option<&str>) {
    let cases = corpus();
    let mut rows = Vec::new();
    for (name, text, n_frames) in &cases {
        // warmup
        for _ in 0..6 {
            let _ = measure_once(text);
        }
        let mut samples = Vec::with_capacity(31);
        for _ in 0..31 {
            samples.push(measure_once(text));
        }
        samples.sort_by(|a, b| a.partial_cmp(b).unwrap());
        let med = samples[samples.len() / 2];
        let p10 = samples[(samples.len() as f64 * 0.1) as usize];
        let p90 = samples[(samples.len() as f64 * 0.9) as usize];
        eprintln!(
            "{label} {name} med={:.3}ms p10={:.3} p90={:.3} (n_frames={n_frames})",
            med * 1e3,
            p10 * 1e3,
            p90 * 1e3
        );
        rows.push(serde_json::json!({
            "case": name,
            "n_frames": n_frames,
            "bytes": text.len(),
            "median_s": med,
            "p10_s": p10,
            "p90_s": p90,
            "n_samples": samples.len(),
        }));
    }
    // path-based read_all_frames (parallel gate when feature on)
    let cuh2 = fixture("cuh2.con").repeat(100);
    let tmp = std::env::temp_dir().join(format!("readcon_pgo_measure_{}.con", std::process::id()));
    fs::write(&tmp, &cuh2).unwrap();
    for _ in 0..4 {
        let _ = black_box(read_all_frames(tmp.as_path()).unwrap().len());
    }
    let mut samples = Vec::new();
    for _ in 0..21 {
        let t0 = Instant::now();
        let n = read_all_frames(tmp.as_path()).unwrap().len();
        samples.push(t0.elapsed().as_secs_f64());
        let _ = black_box(n);
    }
    let _ = fs::remove_file(&tmp);
    samples.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let med = samples[samples.len() / 2];
    eprintln!("{label} path_cuh2_x100_read_all_frames med={:.3}ms", med * 1e3);
    rows.push(serde_json::json!({
        "case": "path_cuh2_x100_read_all_frames",
        "n_frames": 100,
        "bytes": cuh2.len(),
        "median_s": med,
        "p10_s": samples[(samples.len() as f64 * 0.1) as usize],
        "p90_s": samples[(samples.len() as f64 * 0.9) as usize],
        "n_samples": samples.len(),
    }));

    // Lean positions-only path (no AtomDatum) vs full-frame string collect on same corpus.
    for (name, text, n_frames) in &cases {
        for _ in 0..6 {
            let _ = black_box(read_frame_coordinates_str(text).unwrap().len());
        }
        let mut samples = Vec::with_capacity(31);
        for _ in 0..31 {
            let t0 = Instant::now();
            let n = read_frame_coordinates_str(text).unwrap().len();
            samples.push(t0.elapsed().as_secs_f64());
            let _ = black_box(n);
        }
        samples.sort_by(|a, b| a.partial_cmp(b).unwrap());
        let med = samples[samples.len() / 2];
        eprintln!(
            "{label} coords_only_{name} med={:.3}ms p10={:.3} p90={:.3} (n_frames={n_frames})",
            med * 1e3,
            samples[(samples.len() as f64 * 0.1) as usize] * 1e3,
            samples[(samples.len() as f64 * 0.9) as usize] * 1e3
        );
        rows.push(serde_json::json!({
            "case": format!("coords_only_{name}"),
            "n_frames": n_frames,
            "bytes": text.len(),
            "median_s": med,
            "p10_s": samples[(samples.len() as f64 * 0.1) as usize],
            "p90_s": samples[(samples.len() as f64 * 0.9) as usize],
            "n_samples": samples.len(),
        }));
    }

    let doc = serde_json::json!({
        "variant": label,
        "host": hostname(),
        "cases": rows,
    });
    let s = serde_json::to_string_pretty(&doc).unwrap();
    if let Some(path) = out {
        fs::write(path, s + "\n").unwrap();
    } else {
        println!("{s}");
    }
}

fn hostname() -> String {
    fs::read_to_string("/etc/hostname")
        .unwrap_or_else(|_| "unknown".into())
        .trim()
        .to_string()
}

fn once() {
    let text = fixture("cuh2.con").repeat(100);
    for _ in 0..40 {
        let frames = read_all_frames_from_str(&text);
        let _ = black_box(frames.len());
    }
}

fn main() {
    let mut args = env::args().skip(1);
    match args.next().as_deref() {
        Some("train") => train(),
        Some("measure") => {
            let label = args.next().unwrap_or_else(|| "measure".into());
            let out = args.next();
            measure(&label, out.as_deref());
        }
        Some("once") | None => once(),
        Some(other) => {
            eprintln!("unknown mode {other}; use train|measure|once");
            std::process::exit(2);
        }
    }
}
