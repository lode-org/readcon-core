//! Wall-time sequential vs Rayon scale + write-path harness.
//!
//! Usage (on a builder, never the laptop):
//!
//! ```text
//! cargo run --release --example wall_scale_harness --features parallel -- \
//!     benches/results/wall_scale.json
//! ```
//!
//! Writes JSON with host, date, commit, ncpus. Does not invent numbers.

use readcon_core::iterators::{
    frame_start_offsets, frames_from_text, parse_frames_parallel_with_threads,
    read_nth_frame_from_text, ConFrameIterator,
};
use readcon_core::writer::ConFrameWriter;
use std::env;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::Instant;

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn fixture_text(name: &str) -> String {
    fs::read_to_string(repo_root().join("resources/test").join(name)).expect("fixture")
}

fn repeat_text(one: &str, n: usize) -> String {
    let mut buf = String::with_capacity(one.len() * n);
    for _ in 0..n {
        buf.push_str(one);
    }
    buf
}

fn median_ms(mut samples: Vec<f64>) -> f64 {
    samples.sort_by(|a, b| a.partial_cmp(b).unwrap());
    samples[samples.len() / 2]
}

fn time_ms<F: FnMut()>(repeat: usize, mut f: F) -> f64 {
    let mut samples = Vec::with_capacity(repeat);
    for _ in 0..repeat {
        let t0 = Instant::now();
        f();
        samples.push(t0.elapsed().as_secs_f64() * 1.0e3);
    }
    median_ms(samples)
}

fn git_commit() -> String {
    Command::new("git")
        .args(["rev-parse", "--short=8", "HEAD"])
        .current_dir(repo_root())
        .output()
        .ok()
        .and_then(|o| String::from_utf8(o.stdout).ok())
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .unwrap_or_else(|| "unknown".into())
}

fn hostname() -> String {
    Command::new("hostname")
        .output()
        .ok()
        .and_then(|o| String::from_utf8(o.stdout).ok())
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .unwrap_or_else(|| "unknown".into())
}

fn main() {
    let out_path = env::args()
        .nth(1)
        .map(PathBuf::from)
        .unwrap_or_else(|| repo_root().join("benches/results/wall_scale.json"));

    let repeats = 5usize;
    let n_frames = 100usize;
    let one = fixture_text("cuh2.con");
    let text = repeat_text(&one, n_frames);
    let n_atoms = frames_from_text(&one, Some(1))
        .expect("parse one")
        [0]
        .atom_data
        .len();

    let seq_ms = time_ms(repeats, || {
        let frames = frames_from_text(&text, Some(1)).expect("seq");
        assert_eq!(frames.len(), n_frames);
        std::hint::black_box(frames);
    });

    let workers = [2usize, 4, 8, 16];
    let mut scale = Vec::new();
    for n in workers {
        let ms = time_ms(repeats, || {
            let parts = parse_frames_parallel_with_threads(&text, Some(n));
            assert_eq!(parts.len(), n_frames);
            std::hint::black_box(parts);
        });
        scale.push((n, ms));
    }

    let auto_ms = time_ms(repeats, || {
        let frames = frames_from_text(&text, None).expect("auto");
        assert_eq!(frames.len(), n_frames);
        std::hint::black_box(frames);
    });

    let skip_ms = time_ms(repeats, || {
        let mut it = ConFrameIterator::new(&text);
        let mut n = 0usize;
        while let Some(Ok(())) = it.forward() {
            n += 1;
        }
        assert_eq!(n, n_frames);
        std::hint::black_box(n);
    });

    let nth_last_ms = time_ms(repeats, || {
        let f = read_nth_frame_from_text(&text, n_frames - 1).expect("nth last");
        std::hint::black_box(f);
    });

    let span_ms = time_ms(repeats, || {
        let s = frame_start_offsets(&text);
        assert_eq!(s.len(), n_frames);
        std::hint::black_box(s);
    });

    let frames = frames_from_text(&text, Some(1)).expect("write payload");
    let write_ms = time_ms(repeats, || {
        let mut buf = Vec::with_capacity(text.len());
        {
            let mut w = ConFrameWriter::new(&mut buf);
            for frame in &frames {
                w.write_frame(frame).expect("write");
            }
        }
        std::hint::black_box(buf);
    });

    let ncpus = std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(1);
    let date = chrono_like_utc();

    let mut json = String::new();
    json.push_str("{\n");
    json.push_str("  \"protocol\": \"sequential vs Rayon n-thread parse of repeated cuh2.con; write-path is ConFrameWriter to an in-memory buffer; skip/nth/span use the same payload\",\n");
    json.push_str(&format!("  \"host\": \"{}\",\n", hostname()));
    json.push_str(&format!("  \"date_utc\": \"{}\",\n", date));
    json.push_str(&format!("  \"commit\": \"{}\",\n", git_commit()));
    json.push_str("  \"features\": \"parallel\",\n");
    json.push_str(&format!("  \"ncpus\": {},\n", ncpus));
    json.push_str(&format!("  \"n_frames\": {},\n", n_frames));
    json.push_str(&format!("  \"n_atoms\": {},\n", n_atoms));
    json.push_str(&format!("  \"repeats\": {},\n", repeats));
    json.push_str("  \"fixture\": \"resources/test/cuh2.con\",\n");
    json.push_str(&format!("  \"payload_bytes\": {},\n", text.len()));
    json.push_str(&format!("  \"sequential_ms\": {:.6},\n", seq_ms));
    json.push_str(&format!("  \"auto_ms\": {:.6},\n", auto_ms));
    json.push_str(&format!("  \"write_100_frames_ms\": {:.6},\n", write_ms));
    json.push_str(&format!("  \"skip_100_frames_ms\": {:.6},\n", skip_ms));
    json.push_str(&format!("  \"read_nth_last_ms\": {:.6},\n", nth_last_ms));
    json.push_str(&format!("  \"frame_start_offsets_ms\": {:.6},\n", span_ms));
    json.push_str("  \"parallel\": {\n");
    for (i, (n, ms)) in scale.iter().enumerate() {
        let comma = if i + 1 == scale.len() { "" } else { "," };
        json.push_str(&format!("    \"n{}\": {:.6}{}\n", n, ms, comma));
    }
    json.push_str("  }\n");
    json.push_str("}\n");

    if let Some(parent) = out_path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    let mut f = fs::File::create(&out_path).expect("create json");
    f.write_all(json.as_bytes()).expect("write json");
    println!("wrote {}", Path::new(&out_path).display());
    print!("{json}");
}

fn chrono_like_utc() -> String {
    // RFC3339 minute precision without pulling chrono.
    let out = Command::new("date")
        .args(["-u", "+%Y-%m-%dT%H:%MZ"])
        .output()
        .ok()
        .and_then(|o| String::from_utf8(o.stdout).ok())
        .map(|s| s.trim().to_string())
        .unwrap_or_else(|| "unknown".into());
    out
}
