//! Stage timings for the CPC evidence pack.
//!
//! `scan` times the file read and the boundary walk separately.
//! `parse` times `read_all_frames_with_threads`, which is the Rust parse
//! eOn's C++ wrapper calls. A thread count of 0 is the automatic policy,
//! 1 is sequential, and 2 or more pins a Rayon pool of that size.

use readcon_core::iterators::{frame_start_offsets, read_all_frames_with_threads};
use std::env;
use std::fs;
use std::hint::black_box;
use std::path::Path;
use std::process::ExitCode;
use std::time::Instant;

fn main() -> ExitCode {
    let mut args = env::args().skip(1);
    let cmd = args.next().unwrap_or_default();
    let path = args.next().unwrap_or_default();
    if path.is_empty() {
        eprintln!("usage: e2-bench scan|parse PATH [threads]");
        return ExitCode::from(2);
    }
    let result = match cmd.as_str() {
        "scan" => scan(&path),
        "parse" => {
            let threads: usize = args.next().unwrap_or_else(|| "0".to_string()).parse().unwrap_or(0);
            parse(&path, threads)
        }
        other => Err(format!("unknown command {other}")),
    };
    match result {
        Ok(line) => {
            println!("{line}");
            ExitCode::SUCCESS
        }
        Err(err) => {
            eprintln!("{err}");
            ExitCode::from(1)
        }
    }
}

fn scan(path: &str) -> Result<String, String> {
    let start = Instant::now();
    let text = fs::read_to_string(path).map_err(|e| e.to_string())?;
    let read_s = start.elapsed().as_secs_f64();
    let bytes = text.len();
    let start = Instant::now();
    let offsets = frame_start_offsets(&text);
    let scan_s = start.elapsed().as_secs_f64();
    let n = offsets.len();
    black_box(&offsets);
    Ok(format!(
        "{{\"read_seconds\":{read_s:.9},\"scan_seconds\":{scan_s:.9},\"bytes\":{bytes},\"frames\":{n}}}"
    ))
}

fn parse(path: &str, threads: usize) -> Result<String, String> {
    let bytes = fs::metadata(path).map_err(|e| e.to_string())?.len();
    let n_threads = if threads == 0 { None } else { Some(threads) };
    let start = Instant::now();
    let frames = read_all_frames_with_threads(Path::new(path), n_threads).map_err(|e| e.to_string())?;
    let seconds = start.elapsed().as_secs_f64();
    let mut tag: u64 = frames.len() as u64;
    if let Some(frame) = frames.first() {
        if let Some(atom) = frame.atom_data.first() {
            tag ^= atom.x.to_bits();
        }
        if let Some(atom) = frame.atom_data.last() {
            tag ^= atom.z.to_bits();
        }
    }
    let n = frames.len();
    black_box(&frames);
    black_box(tag);
    Ok(format!(
        "{{\"seconds\":{seconds:.9},\"bytes\":{bytes},\"frames\":{n},\"tag\":{tag},\"threads\":{threads}}}"
    ))
}
