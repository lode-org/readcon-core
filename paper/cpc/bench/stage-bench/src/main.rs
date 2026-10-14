//! Wall-clock stages of a CON read.
//!
//! `full` times `read_all_frames_with_threads` only.
//! `parts` times the pieces used to account for that read:
//! string load, mmap open, UTF-8 check, page touch, boundary scan,
//! token walk, numeric parse, in-memory parse, and frame assembly.

use fast_float2::parse_partial;
use memmap2::Mmap;
use rayon::prelude::*;
use readcon_core::compression::read_file_contents;
use readcon_core::iterators::{frame_start_offsets, frames_from_text, read_all_frames_with_threads};
use readcon_core::parser::parse_line_of_range_f64_stack;
use readcon_core::types::con_frame_from_atom_data_with_positions;
use std::env;
use std::fs::{self, File};
use std::hint::black_box;
use std::path::Path;
use std::process::ExitCode;
use std::time::Instant;

fn main() -> ExitCode {
    let mut args = env::args().skip(1);
    let cmd = args.next().unwrap_or_default();
    let path = args.next().unwrap_or_default();
    if path.is_empty() {
        eprintln!("usage: stage-bench full|parts PATH [threads]");
        return ExitCode::from(2);
    }
    let threads: usize = args
        .next()
        .unwrap_or_else(|| "1".into())
        .parse()
        .unwrap_or(1);
    let threads = threads.max(1);
    let result = match cmd.as_str() {
        "full" => full(&path, threads),
        "parts" => parts(&path, threads),
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

fn threads_arg(threads: usize) -> Option<usize> {
    Some(threads)
}

fn full(path: &str, threads: usize) -> Result<String, String> {
    let bytes = fs::metadata(path).map_err(|e| e.to_string())?.len();
    let start = Instant::now();
    let frames =
        read_all_frames_with_threads(Path::new(path), threads_arg(threads)).map_err(|e| e.to_string())?;
    let seconds = start.elapsed().as_secs_f64();
    let tag = tag_frames(&frames);
    let n = frames.len();
    black_box(&frames);
    Ok(format!(
        "{{\"kind\":\"full\",\"seconds\":{seconds:.9},\"bytes\":{bytes},\"frames\":{n},\"tag\":{tag},\"threads\":{threads}}}"
    ))
}

fn tag_frames(frames: &[readcon_core::types::ConFrame]) -> u64 {
    let mut tag = frames.len() as u64;
    if let Some(frame) = frames.first() {
        if let Some(atom) = frame.atom_data.first() {
            tag ^= atom.x.to_bits();
        }
        if let Some(atom) = frame.atom_data.last() {
            tag ^= atom.z.to_bits();
        }
    }
    if let Some(frame) = frames.last() {
        if let Some(atom) = frame.atom_data.first() {
            tag ^= atom.y.to_bits();
        }
    }
    black_box(tag)
}

fn with_threads<T>(threads: usize, body: impl FnOnce() -> T + Send) -> T
where
    T: Send,
{
    if threads <= 1 {
        return body();
    }
    let pool = rayon::ThreadPoolBuilder::new()
        .num_threads(threads)
        .build()
        .unwrap_or_else(|_| rayon::ThreadPoolBuilder::new().build().expect("pool"));
    pool.install(body)
}

fn parts(path: &str, threads: usize) -> Result<String, String> {
    let bytes = fs::metadata(path).map_err(|e| e.to_string())?.len();

    let start = Instant::now();
    let text = fs::read_to_string(path).map_err(|e| e.to_string())?;
    let string_load_s = start.elapsed().as_secs_f64();
    black_box(text.len());

    let start = Instant::now();
    let boundaries = frame_start_offsets(&text);
    let boundary_s = start.elapsed().as_secs_f64();
    black_box(boundaries.len());

    let start = Instant::now();
    let file = File::open(path).map_err(|e| e.to_string())?;
    let mmap = unsafe { Mmap::map(&file).map_err(|e| e.to_string())? };
    let mmap_open_s = start.elapsed().as_secs_f64();

    let start = Instant::now();
    let utf8 = std::str::from_utf8(&mmap).map_err(|e| e.to_string())?;
    let utf8_s = start.elapsed().as_secs_f64();
    black_box(utf8.len());

    let page_touch_s = page_touch(mmap.as_ref(), threads);

    let tokenize_s = tokenize(&text, &boundaries, threads);
    let numeric_s = numeric_parse(&text, &boundaries, threads);

    let start = Instant::now();
    let frames = frames_from_text(&text, threads_arg(threads)).map_err(|e| e.to_string())?;
    let in_memory_s = start.elapsed().as_secs_f64();
    let tag = tag_frames(&frames);
    let n = frames.len();

    let assemble_s = assemble(&frames, threads);
    black_box(&frames);

    // Library entry used by the full read, timed again so parts and full
    // share one process only for the breakdown. The paired sweep uses `full`.
    let start = Instant::now();
    let contents = read_file_contents(Path::new(path)).map_err(|e| e.to_string())?;
    let lib_text = contents.as_str().map_err(|e| e.to_string())?;
    let lib_load_s = start.elapsed().as_secs_f64();
    black_box(lib_text.len());

    Ok(format!(
        "{{\"kind\":\"parts\",\"threads\":{threads},\"bytes\":{bytes},\"frames\":{n},\"tag\":{tag},\
\"string_load_s\":{string_load_s:.9},\"boundary_s\":{boundary_s:.9},\
\"mmap_open_s\":{mmap_open_s:.9},\"utf8_s\":{utf8_s:.9},\"page_touch_s\":{page_touch_s:.9},\
\"tokenize_s\":{tokenize_s:.9},\"numeric_parse_s\":{numeric_s:.9},\
\"in_memory_s\":{in_memory_s:.9},\"assemble_s\":{assemble_s:.9},\"lib_load_s\":{lib_load_s:.9}}}"
    ))
}

fn page_touch(bytes: &[u8], threads: usize) -> f64 {
    let page = 4096usize;
    let n_pages = bytes.len().div_ceil(page);
    let start = Instant::now();
    let sum = with_threads(threads, || {
        if threads <= 1 {
            let mut acc = 0u64;
            let mut i = 0usize;
            while i < bytes.len() {
                acc = acc.wrapping_add(bytes[i] as u64);
                i += page;
            }
            acc
        } else {
            (0..n_pages)
                .into_par_iter()
                .map(|p| {
                    let i = p * page;
                    if i < bytes.len() {
                        bytes[i] as u64
                    } else {
                        0
                    }
                })
                .sum::<u64>()
        }
    });
    black_box(sum);
    start.elapsed().as_secs_f64()
}

fn tokenize(text: &str, boundaries: &[usize], threads: usize) -> f64 {
    let n = boundaries.len();
    let start = Instant::now();
    let count = with_threads(threads, || {
        let fold = |i: usize| {
            let begin = boundaries[i];
            let end = if i + 1 < n {
                boundaries[i + 1]
            } else {
                text.len()
            };
            let mut acc = 0u64;
            for line in text[begin..end].split('\n') {
                for token in line.split_ascii_whitespace() {
                    acc = acc.wrapping_add(token.len() as u64);
                }
            }
            acc
        };
        if threads <= 1 {
            (0..n).map(fold).fold(0u64, u64::wrapping_add)
        } else {
            (0..n).into_par_iter().map(fold).sum::<u64>()
        }
    });
    black_box(count);
    start.elapsed().as_secs_f64()
}

fn numeric_parse(text: &str, boundaries: &[usize], threads: usize) -> f64 {
    let n = boundaries.len();
    let defaults = [0.0f64; 5];
    let start = Instant::now();
    let count = with_threads(threads, || {
        let fold = |i: usize| {
            let begin = boundaries[i];
            let end = if i + 1 < n {
                boundaries[i + 1]
            } else {
                text.len()
            };
            let mut acc = 0u64;
            let mut buf = [0.0f64; 5];
            for line in text[begin..end].split('\n') {
                let trimmed = line.trim_start();
                if trimmed.is_empty() {
                    continue;
                }
                let b = trimmed.as_bytes()[0];
                if !(b.is_ascii_digit() || b == b'-' || b == b'+' || b == b'.') {
                    continue;
                }
                if parse_line_of_range_f64_stack(trimmed, 1, 5, &defaults, &mut buf).is_ok() {
                    acc = acc.wrapping_add(buf[0].to_bits());
                } else if let Ok((value, _)) = parse_partial::<f64, _>(trimmed.as_bytes()) {
                    acc = acc.wrapping_add(value.to_bits());
                }
            }
            acc
        };
        if threads <= 1 {
            (0..n).map(fold).fold(0u64, u64::wrapping_add)
        } else {
            (0..n).into_par_iter().map(fold).sum::<u64>()
        }
    });
    black_box(count);
    start.elapsed().as_secs_f64()
}

fn assemble(frames: &[readcon_core::types::ConFrame], threads: usize) -> f64 {
    let inputs: Vec<_> = frames
        .iter()
        .map(|frame| {
            (
                frame.header.clone(),
                frame.atom_data.clone(),
                frame.positions.clone(),
            )
        })
        .collect();
    let start = Instant::now();
    let count = with_threads(threads, || {
        let build = |(header, atoms, positions)| {
            let built = con_frame_from_atom_data_with_positions(header, atoms, positions);
            built.atom_data.len()
        };
        if threads <= 1 {
            inputs.into_iter().map(build).sum::<usize>()
        } else {
            inputs.into_par_iter().map(build).sum::<usize>()
        }
    });
    black_box(count);
    start.elapsed().as_secs_f64()
}
