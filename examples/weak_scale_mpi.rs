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

use mpi::collective::SystemOperation;
use mpi::traits::*;
use readcon_core::distrib::block_range;
use readcon_core::distrib::Comm;
use readcon_core::distrib_read::{ReadMode, read_block};
use readcon_core::hostlabel::cpu_model;
use readcon_core::iterators::{parse_frames_at_offsets, ConFrameIterator};
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

fn stat_field(name_index: usize) -> i64 {
    let Ok(text) = fs::read_to_string("/proc/self/stat") else {
        return 0;
    };
    let Some((_, rest)) = text.rsplit_once(')') else {
        return 0;
    };
    // Fields after `comm`: state is the first. `majflt` is field 12 of the
    // whole line, which is index 9 here. `minflt` is index 7.
    rest.split_whitespace()
        .nth(name_index)
        .and_then(|text| text.parse().ok())
        .unwrap_or(0)
}

fn majflt() -> i64 {
    stat_field(9)
}

fn minflt() -> i64 {
    stat_field(7)
}

fn cpus_allowed() -> String {
    let Ok(text) = fs::read_to_string("/proc/self/status") else {
        return "unknown".to_string();
    };
    for line in text.lines() {
        if let Some(rest) = line.strip_prefix("Cpus_allowed_list:") {
            return rest.trim().to_string();
        }
    }
    "unknown".to_string()
}

fn sum_i64(world: &mpi::topology::SimpleCommunicator, value: i64) -> i64 {
    let mut out = 0i64;
    world.all_reduce_into(&value, &mut out, SystemOperation::sum());
    out
}

fn fmt_f64s(values: &[f64]) -> String {
    let mut listed = String::new();
    for (index, sample) in values.iter().enumerate() {
        if index > 0 {
            listed.push_str(", ");
        }
        listed.push_str(&format!("{sample:.9}"));
    }
    listed
}

fn fmt_i64s(values: &[i64]) -> String {
    let mut listed = String::new();
    for (index, sample) in values.iter().enumerate() {
        if index > 0 {
            listed.push_str(", ");
        }
        listed.push_str(&format!("{sample}"));
    }
    listed
}

/// Touch every page and keep the map so the timed reads are not the
/// first fault of this file.
fn hold_resident(path: &Path) -> memmap2::Mmap {
    let file = fs::File::open(path).expect("map open");
    // SAFETY: the benchmark does not truncate the file while the map lives.
    let map = unsafe { memmap2::Mmap::map(&file).expect("map") };
    let mut acc = 0u8;
    let mut offset = 0usize;
    while offset < map.len() {
        acc ^= map[offset];
        offset = offset.saturating_add(4096);
    }
    if !map.is_empty() {
        acc ^= map[map.len() - 1];
    }
    std::hint::black_box(acc);
    map
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
    let booted = Instant::now();
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

    let allowed = cpus_allowed();
    let allowed_list = if comm.rank() == 0 {
        let mut parts = vec![format!("\"{}\"", json_escape(&allowed))];
        for rank in 1..ranks {
            let (chunk, _) = world.process_at_rank(rank as i32).receive_vec::<u8>();
            let text = String::from_utf8_lossy(&chunk).into_owned();
            parts.push(format!("\"{}\"", json_escape(&text)));
        }
        parts.join(", ")
    } else {
        world.process_at_rank(0).send(allowed.as_bytes());
        String::new()
    };

    // The old clock: one untimed `read_block`, then `read_block` inside
    // the timer. Rank 0 re-reads the whole file on every call, so the
    // first samples can fault pages the warmup already dropped.
    world.barrier();
    let _ = read_block(&comm, path, ReadMode::Shared, Some(1)).expect("warmup");
    world.barrier();
    let init_to_legacy_s = booted.elapsed().as_secs_f64();

    let mut legacy_samples = Vec::with_capacity(repeats);
    let mut legacy_maj = Vec::with_capacity(repeats);
    let mut legacy_min = Vec::with_capacity(repeats);
    for _ in 0..repeats {
        world.barrier();
        let fault0 = majflt();
        let touch0 = minflt();
        let started = Instant::now();
        let block = read_block(&comm, path, ReadMode::Shared, Some(1)).expect("timed read");
        world.barrier();
        let seconds = started.elapsed().as_secs_f64();
        let fault1 = majflt();
        let touch1 = minflt();
        assert_eq!(block.frames.len(), frames_per_worker);
        drop(block);
        let maj = sum_i64(&world, fault1.saturating_sub(fault0));
        let minr = sum_i64(&world, touch1.saturating_sub(touch0));
        if comm.rank() == 0 {
            legacy_samples.push(seconds);
            legacy_maj.push(maj);
            legacy_min.push(minr);
        }
    }

    // Equal-work clock. The map stays mapped, so these samples do not
    // pay the first fault. Each rank copies and parses only its block.
    // `mpirun` has already returned by `booted`; it is not in this timer.
    let map = hold_resident(path);
    let mut span_b = 0u64;
    if comm.rank() == 0 {
        let mut iter = ConFrameIterator::from_bytes(&map);
        if let Some(Ok(())) = iter.forward_fast() {
            span_b = iter.byte_pos() as u64;
        }
    }
    world.process_at_rank(0).broadcast_into(&mut span_b);
    let span = span_b as usize;
    if span < 2 || map.len() % span != 0 || map.len() / span != total {
        if comm.rank() == 0 {
            write_refusal(out_path, "frames do not share one byte length");
        }
        std::process::exit(2);
    }
    let owned = block_range(total, ranks, comm.rank());
    let lo = owned.start * span;
    let hi = owned.end * span;
    let offsets: Vec<usize> = (0..owned.len()).map(|i| i * span).collect();
    let mut buf = vec![0u8; hi - lo];
    buf.copy_from_slice(&map[lo..hi]);

    let mut samples = Vec::with_capacity(repeats);
    let mut samples_maj = Vec::with_capacity(repeats);
    let mut samples_min = Vec::with_capacity(repeats);
    for _ in 0..repeats {
        world.barrier();
        let fault0 = majflt();
        let touch0 = minflt();
        let started = Instant::now();
        buf.copy_from_slice(&map[lo..hi]);
        let text = std::str::from_utf8(&buf).expect("utf8");
        let parsed = parse_frames_at_offsets(text, &offsets, Some(1));
        let n_ok = parsed.iter().filter(|item| item.is_ok()).count();
        world.barrier();
        let seconds = started.elapsed().as_secs_f64();
        let fault1 = majflt();
        let touch1 = minflt();
        drop(parsed);
        assert_eq!(n_ok, frames_per_worker);
        let maj = sum_i64(&world, fault1.saturating_sub(fault0));
        let minr = sum_i64(&world, touch1.saturating_sub(touch0));
        if comm.rank() == 0 {
            samples.push(seconds);
            samples_maj.push(maj);
            samples_min.push(minr);
        }
    }
    // Keep the map until the samples are stored.
    drop(map);

    if comm.rank() == 0 {
        let mpi = env::var("READCON_WEAK_MPI_IMPL").unwrap_or_else(|_| "unrecorded".to_string());
        let samples_s = fmt_f64s(&samples);
        let legacy_s = fmt_f64s(&legacy_samples);
        let maj_s = fmt_i64s(&samples_maj);
        let legacy_maj_s = fmt_i64s(&legacy_maj);
        let min_s = fmt_i64s(&samples_min);
        let legacy_min_s = fmt_i64s(&legacy_min);
        let host = json_escape(&record_cpu());
        let mpi_name = json_escape(mpi.trim());
        let body = format!(
            "{{\n  \"kind\": \"ranks\",\n  \"measured\": true,\n  \"relation\": \"n_frames = frames_per_worker * workers\",\n  \"workers\": {ranks},\n  \"n_frames\": {total},\n  \"frames_per_worker\": {frames_per_worker},\n  \"bytes\": {bytes},\n  \"repeats\": {repeats},\n  \"samples_s\": [{samples_s}],\n  \"legacy_samples_s\": [{legacy_s}],\n  \"samples_majflt\": [{maj_s}],\n  \"legacy_majflt\": [{legacy_maj_s}],\n  \"samples_minflt\": [{min_s}],\n  \"legacy_minflt\": [{legacy_min_s}],\n  \"clock\": \"resident-span\",\n  \"legacy_clock\": \"read_block\",\n  \"mpirun_in_clock\": false,\n  \"init_to_legacy_s\": {init_to_legacy_s:.9},\n  \"span\": {span},\n  \"cpus_allowed\": [{allowed_list}],\n  \"identical\": true,\n  \"host\": \"{host}\",\n  \"physical_cores\": {physical},\n  \"mpi\": \"{mpi_name}\"\n}}\n"
        );
        if let Some(parent) = out_path.parent() {
            let _ = fs::create_dir_all(parent);
        }
        fs::write(out_path, &body).expect("write json");
        print!("{body}");
    }
}
