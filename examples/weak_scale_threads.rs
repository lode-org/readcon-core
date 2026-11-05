//! Weak-scaling thread parse.
//!
//! The file for `w` workers holds `frames_per_worker * w` frames of
//! `resources/test/cuh2.con`. That is the relation in `benchmarks/weak_scale.py`.
//! `n_threads == 1` stays on the calling thread. `n_threads >= 2` uses a
//! Rayon pool of that size.
//!
//! ```text
//! cargo run --release --example weak_scale_threads --features parallel -- \
//!     OUT.json [FRAMES_PER_WORKER]
//! ```
//!
//! The default ladder is 1, 2, 4, 8, 16, 32 and the default repeat count is 6.
//! A ladder that does not fit in the online CPU count exits 2 and writes
//! `"complete": false` with no samples. The host string matches
//! `benches/cpu_model.py`. The machine name is not recorded.

use readcon_core::hostlabel::cpu_model;
use readcon_core::iterators::frames_from_text;
use std::env;
use std::fs;
use std::path::PathBuf;
use std::process::Command;
use std::time::Instant;

const LADDER: [usize; 6] = [1, 2, 4, 8, 16, 32];
const REPEATS: usize = 6;
const RELATION: &str = "n_frames = frames_per_worker * workers";

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn online_cpus() -> usize {
    if let Ok(text) = fs::read_to_string("/proc/cpuinfo") {
        let count = text
            .lines()
            .filter(|line| line.to_ascii_lowercase().starts_with("processor"))
            .count();
        if count > 0 {
            return count;
        }
    }
    std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(1)
}

fn record_cpu() -> String {
    let raw = cpu_model();
    let cleaned = raw.replace("(R)", "").replace("(TM)", "").replace('®', "");
    let cleaned = cleaned.split_whitespace().collect::<Vec<_>>().join(" ");
    if cleaned.contains("Xeon") {
        "Intel Xeon Processor".to_string()
    } else if cleaned.is_empty() {
        "unknown".to_string()
    } else {
        cleaned
    }
}

fn json_escape(text: &str) -> String {
    let mut out = String::new();
    for ch in text.chars() {
        match ch {
            '\\' => out.push_str("\\\\"),
            '"' => out.push_str("\\\""),
            '\n' => out.push_str("\\n"),
            c => out.push(c),
        }
    }
    out
}

fn git_head() -> String {
    Command::new("git")
        .args(["rev-parse", "HEAD"])
        .current_dir(repo_root())
        .output()
        .ok()
        .and_then(|out| String::from_utf8(out.stdout).ok())
        .map(|text| text.trim().to_string())
        .filter(|text| !text.is_empty())
        .unwrap_or_else(|| "unknown".to_string())
}

fn date_utc() -> String {
    Command::new("date")
        .args(["-u", "+%Y-%m-%dT%H:%MZ"])
        .output()
        .ok()
        .and_then(|out| String::from_utf8(out.stdout).ok())
        .map(|text| text.trim().to_string())
        .filter(|text| !text.is_empty())
        .unwrap_or_else(|| "unknown".to_string())
}

fn repeat_text(one: &str, n: usize) -> String {
    let mut buf = String::with_capacity(one.len() * n);
    for _ in 0..n {
        buf.push_str(one);
    }
    buf
}

fn time_one(text: &str, workers: usize, n_frames: usize) -> f64 {
    let started = Instant::now();
    let frames = frames_from_text(text, Some(workers)).expect("parse");
    assert_eq!(frames.len(), n_frames);
    std::hint::black_box(frames);
    started.elapsed().as_secs_f64()
}

fn write_refusal(path: &PathBuf, reason: &str) {
    let body = format!(
        "{{\n  \"kind\": \"threads\",\n  \"relation\": \"{RELATION}\",\n  \"complete\": false,\n  \"reason\": \"{}\",\n  \"host\": \"{}\",\n  \"ncpus\": {},\n  \"points\": []\n}}\n",
        json_escape(reason),
        json_escape(&record_cpu()),
        online_cpus(),
    );
    if let Some(parent) = path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    fs::write(path, body).expect("write refusal");
}

fn main() {
    let mut args = env::args().skip(1);
    let out_path = args
        .next()
        .map(PathBuf::from)
        .unwrap_or_else(|| repo_root().join("results/weak/threads-rust.json"));
    let frames_per_worker = args
        .next()
        .map(|text| text.parse::<usize>().expect("frames_per_worker"))
        .unwrap_or(64);
    if frames_per_worker < 1 {
        write_refusal(&out_path, "frames_per_worker must be positive");
        std::process::exit(2);
    }
    let ncpus = online_cpus();
    if LADDER.iter().any(|workers| *workers > ncpus) {
        write_refusal(
            &out_path,
            "the ladder 1,2,4,8,16,32 does not fit in the online CPUs",
        );
        std::process::exit(2);
    }

    let one = fs::read_to_string(repo_root().join("resources/test/cuh2.con")).expect("fixture");
    let mut points = String::new();
    for (index, workers) in LADDER.iter().copied().enumerate() {
        let n_frames = frames_per_worker * workers;
        let text = repeat_text(&one, n_frames);
        let _ = time_one(&text, workers, n_frames);
        let mut samples = Vec::with_capacity(REPEATS);
        for _ in 0..REPEATS {
            samples.push(time_one(&text, workers, n_frames));
        }
        if index > 0 {
            points.push_str(",\n");
        }
        points.push_str("    {\n");
        points.push_str(&format!("      \"workers\": {workers},\n"));
        points.push_str(&format!("      \"n_frames\": {n_frames},\n"));
        points.push_str(&format!("      \"bytes\": {},\n", text.len()));
        points.push_str("      \"samples_s\": [");
        for (sample_index, sample) in samples.iter().enumerate() {
            if sample_index > 0 {
                points.push_str(", ");
            }
            points.push_str(&format!("{sample:.9}"));
        }
        points.push_str("]\n    }");
    }

    let body = format!(
        "{{\n  \"kind\": \"threads\",\n  \"relation\": \"{RELATION}\",\n  \"frames_per_worker\": {frames_per_worker},\n  \"fixture\": \"resources/test/cuh2.con\",\n  \"repeats\": {REPEATS},\n  \"host\": \"{}\",\n  \"ncpus\": {ncpus},\n  \"mpi\": \"absent\",\n  \"gpu\": \"absent\",\n  \"commit\": \"{}\",\n  \"date_utc\": \"{}\",\n  \"complete\": true,\n  \"points\": [\n{points}\n  ]\n}}\n",
        json_escape(&record_cpu()),
        json_escape(&git_head()),
        json_escape(&date_utc()),
    );
    if let Some(parent) = out_path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    fs::write(&out_path, &body).expect("write json");
    print!("{body}");
}
