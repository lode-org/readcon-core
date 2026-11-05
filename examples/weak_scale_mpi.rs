//! Weak-scaling MPI read.
//!
//! The file holds `frames_per_worker * ranks` frames. Each rank parses one
//! block, so the frames on a rank stay at `frames_per_worker`. Threads inside
//! a rank are 1. The relation is the one in `benchmarks/weak_scale.py`.
//!
//! ```text
//! mpirun -bind-to core -n RANKS \
//!     target/release/examples/weak_scale_mpi FILE OUT.json [REPEATS]
//! ```
//!
//! Open MPI uses `--bind-to core`. Repeats default to 6. Rank 0 writes the
//! JSON. A rank count above the physical core count, a repeat count below 6,
//! or a frame count that does not divide evenly exits 2 and writes no samples.
//! Physical cores are `lscpu` cores per socket times sockets.

use mpi::traits::*;
use readcon_core::distrib::Comm;
use readcon_core::distrib_read::{ReadMode, read_block};
use readcon_core::hostlabel::cpu_model;
use readcon_core::types::ConFrame;
use readcon_core::writer::ConFrameWriter;
use std::env;
use std::fs;
use std::path::Path;
use std::time::Instant;

fn record_cpu() -> String {
    if let Ok(given) = env::var("READCON_WEAK_CPU") {
        let given = given.trim();
        if !given.is_empty() {
            return given.to_string();
        }
    }
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

fn lscpu_usize(label: &str) -> Option<usize> {
    let output = std::process::Command::new("lscpu")
        .env("LC_ALL", "C")
        .output()
        .ok()?;
    let text = String::from_utf8(output.stdout).ok()?;
    for line in text.lines() {
        let Some((key, value)) = line.split_once(':') else {
            continue;
        };
        if !key.trim().eq_ignore_ascii_case(label) {
            continue;
        }
        let mut digits = String::new();
        for ch in value.chars() {
            if ch.is_ascii_digit() {
                digits.push(ch);
            } else if !digits.is_empty() {
                break;
            }
        }
        return digits.parse().ok();
    }
    None
}

fn physical_cores() -> usize {
    match (
        lscpu_usize("Core(s) per socket"),
        lscpu_usize("Socket(s)"),
    ) {
        (Some(cores), Some(sockets)) if cores >= 1 && sockets >= 1 => cores * sockets,
        _ => 0,
    }
}

fn write_all(frames: &[ConFrame]) -> Vec<u8> {
    let mut out = Vec::new();
    {
        let mut writer = ConFrameWriter::new(&mut out);
        for frame in frames {
            writer.write_frame(frame).expect("write");
        }
        writer.flush().expect("flush");
    }
    out
}

fn write_refusal(path: &Path, reason: &str) {
    let body = format!(
        "{{\n  \"kind\": \"ranks\",\n  \"measured\": false,\n  \"reason\": \"{}\",\n  \"samples_s\": []\n}}\n",
        json_escape(reason)
    );
    if let Some(parent) = path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    fs::write(path, body).expect("write refusal");
}

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() < 3 {
        eprintln!("usage: weak_scale_mpi FILE OUT.json [REPEATS]");
        std::process::exit(2);
    }
    let path = Path::new(&args[1]);
    let out_path = Path::new(&args[2]);
    let repeats = args.get(3).map(|text| text.parse::<usize>().expect("repeats")).unwrap_or(6);

    let universe = mpi::initialize().expect("mpi init");
    let world = universe.world();
    let comm = Comm::dup_of(&world);
    let ranks = comm.size();
    let physical = physical_cores();

    if comm.rank() == 0 && (repeats < 6 || physical < 1 || ranks > physical || ranks < 1) {
        let reason = if repeats < 6 {
            "repeats are below 6"
        } else if physical < 1 {
            "lscpu did not report physical cores"
        } else {
            "rank count is above the physical core count"
        };
        write_refusal(out_path, reason);
    }
    let refused = repeats < 6 || physical < 1 || ranks > physical;
    if refused {
        std::process::exit(2);
    }

    let bytes = fs::metadata(path).map(|meta| meta.len()).unwrap_or(0);
    let serial = if comm.rank() == 0 {
        readcon_core::iterators::read_all_frames(path).expect("serial read")
    } else {
        Vec::new()
    };
    let n_frames = serial.len();
    let mut total = n_frames as u64;
    world.process_at_rank(0).broadcast_into(&mut total);
    let total = total as usize;
    if total == 0 || total % ranks != 0 {
        if comm.rank() == 0 {
            write_refusal(out_path, "frame count is not a positive multiple of the rank count");
        }
        std::process::exit(2);
    }
    let frames_per_worker = total / ranks;
    let mut status: i32 = 0;
    if comm.rank() == 0 {
        let mine = read_block(&comm, path, ReadMode::Shared, Some(1)).expect("check read");
        let mut cat = write_all(&mine.frames);
        for rank in 1..ranks {
            let (chunk, _) = world.process_at_rank(rank as i32).receive_vec::<u8>();
            cat.extend_from_slice(&chunk);
        }
        let serial_bytes = write_all(&serial);
        if cat != serial_bytes {
            status = 1;
        }
    } else {
        let mine = read_block(&comm, path, ReadMode::Shared, Some(1)).expect("check read");
        let chunk = write_all(&mine.frames);
        world.process_at_rank(0).send(&chunk[..]);
    }
    world.process_at_rank(0).broadcast_into(&mut status);
    if status != 0 {
        if comm.rank() == 0 {
            write_refusal(out_path, "distributed bytes differ from the serial writer");
        }
        std::process::exit(1);
    }

    world.barrier();
    let _ = read_block(&comm, path, ReadMode::Shared, Some(1)).expect("warmup");
    world.barrier();

    let mut samples = Vec::with_capacity(repeats);
    for _ in 0..repeats {
        world.barrier();
        let started = Instant::now();
        let block = read_block(&comm, path, ReadMode::Shared, Some(1)).expect("timed read");
        world.barrier();
        let seconds = started.elapsed().as_secs_f64();
        assert_eq!(block.frames.len(), frames_per_worker);
        if comm.rank() == 0 {
            samples.push(seconds);
        }
    }

    if comm.rank() == 0 {
        let mpi = env::var("READCON_WEAK_MPI_IMPL").unwrap_or_else(|_| "unrecorded".to_string());
        let mut listed = String::new();
        for (index, sample) in samples.iter().enumerate() {
            if index > 0 {
                listed.push_str(", ");
            }
            listed.push_str(&format!("{sample:.9}"));
        }
        let body = format!(
            "{{\n  \"kind\": \"ranks\",\n  \"measured\": true,\n  \"relation\": \"n_frames = frames_per_worker * workers\",\n  \"workers\": {ranks},\n  \"n_frames\": {total},\n  \"frames_per_worker\": {frames_per_worker},\n  \"bytes\": {bytes},\n  \"repeats\": {repeats},\n  \"samples_s\": [{listed}],\n  \"identical\": true,\n  \"host\": \"{}\",\n  \"physical_cores\": {physical},\n  \"mpi\": \"{}\"\n}}\n",
            json_escape(&record_cpu()),
            json_escape(mpi.trim()),
        );
        if let Some(parent) = out_path.parent() {
            let _ = fs::create_dir_all(parent);
        }
        fs::write(out_path, &body).expect("write json");
        print!("{body}");
    }
}
