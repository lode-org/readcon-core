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
use readcon_core::distrib::Comm;
use readcon_core::distrib::block_range;
use readcon_core::distrib_read::{ReadMode, read_block};
use readcon_core::hostlabel::cpu_model;
use readcon_core::iterators::ConFrameIterator;
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
    match (lscpu_usize("Core(s) per socket"), lscpu_usize("Socket(s)")) {
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

fn page_size() -> usize {
    let page = unsafe { libc::sysconf(libc::_SC_PAGESIZE) };
    if page <= 0 { 4096 } else { page as usize }
}

/// First-frame length when that length tiles the file.
fn frame_span(path: &Path) -> Option<usize> {
    let file = fs::File::open(path).ok()?;
    // SAFETY: the file is not truncated while this map is alive.
    let map = unsafe { memmap2::Mmap::map(&file).ok()? };
    let mut iter = ConFrameIterator::from_bytes(&map);
    match iter.forward_fast() {
        Some(Ok(())) => {
            let span = iter.byte_pos();
            if span >= 2 && !map.is_empty() && map.len() % span == 0 {
                Some(span)
            } else {
                None
            }
        }
        _ => None,
    }
}

struct RankSample {
    wall_s: f64,
    open_s: f64,
    map_s: f64,
    fault_s: f64,
    parse_s: f64,
    unmap_s: f64,
    release_s: f64,
    barrier_s: f64,
    majflt: i64,
    minflt: i64,
    n_ok: usize,
}

/// One clock for this rank: open, map, fault, parse, release, and unmap
/// of its own span, then the barrier. Nothing is touched before `wall0`.
fn time_span(
    world: &mpi::topology::SimpleCommunicator,
    path: &Path,
    lo: usize,
    hi: usize,
    offsets: &[usize],
) -> RankSample {
    world.barrier();
    let fault0 = majflt();
    let touch0 = minflt();
    let wall0 = Instant::now();

    let t = Instant::now();
    let file = fs::File::open(path).expect("open");
    let open_s = t.elapsed().as_secs_f64();

    let page = page_size();
    let map_lo = lo - (lo % page);
    let map_len = hi - map_lo;
    let t = Instant::now();
    // SAFETY: the file is not truncated while this map is alive.
    let map = unsafe {
        memmap2::MmapOptions::new()
            .offset(map_lo as u64)
            .len(map_len)
            .map(&file)
            .expect("map")
    };
    let map_s = t.elapsed().as_secs_f64();
    let local = lo - map_lo;
    let slice = &map[local..local + (hi - lo)];

    let t = Instant::now();
    // Sequential advice is inside the clock. It keeps the fault walk of
    // a cold span from stalling the rank that did not read the file first.
    let _ = unsafe {
        libc::posix_fadvise(
            std::os::fd::AsRawFd::as_raw_fd(&file),
            map_lo as i64,
            map_len as i64,
            libc::POSIX_FADV_SEQUENTIAL,
        )
    };
    let _ = unsafe {
        libc::posix_fadvise(
            std::os::fd::AsRawFd::as_raw_fd(&file),
            map_lo as i64,
            map_len as i64,
            libc::POSIX_FADV_WILLNEED,
        )
    };
    let mut acc = 0u8;
    let mut at = 0usize;
    while at < slice.len() {
        acc ^= slice[at];
        at = at.saturating_add(page);
    }
    if !slice.is_empty() {
        acc ^= slice[slice.len() - 1];
    }
    std::hint::black_box(acc);
    let fault_s = t.elapsed().as_secs_f64();

    let t = Instant::now();
    let text = std::str::from_utf8(slice).expect("utf8");
    // Drop each frame before the next one is built. Holding every frame
    // and freeing them together made the slowest rank's release grow
    // once several ranks freed at the same time.
    let mut n_ok = 0usize;
    let mut release_s = 0.0_f64;
    for (index, &start) in offsets.iter().enumerate() {
        let end = if index + 1 < offsets.len() {
            offsets[index + 1]
        } else {
            text.len()
        };
        let mut iter = ConFrameIterator::new(&text[start..end]);
        let frame = iter.next();
        let ok = frame.as_ref().is_some_and(|item| item.is_ok());
        let t_rel = Instant::now();
        drop(frame);
        release_s += t_rel.elapsed().as_secs_f64();
        if ok {
            n_ok += 1;
        }
    }
    let parse_s = (t.elapsed().as_secs_f64() - release_s).max(0.0);

    let t = Instant::now();
    drop(map);
    drop(file);
    let unmap_s = t.elapsed().as_secs_f64();

    let t = Instant::now();
    world.barrier();
    let barrier_s = t.elapsed().as_secs_f64();
    let wall_s = wall0.elapsed().as_secs_f64();
    let fault1 = majflt();
    let touch1 = minflt();
    RankSample {
        wall_s,
        open_s,
        map_s,
        fault_s,
        parse_s,
        unmap_s,
        release_s,
        barrier_s,
        majflt: fault1.saturating_sub(fault0),
        minflt: touch1.saturating_sub(touch0),
        n_ok,
    }
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
    let repeats = args
        .get(3)
        .map(|text| text.parse::<usize>().expect("repeats"))
        .unwrap_or(6);

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
            write_refusal(
                out_path,
                "frame count is not a positive multiple of the rank count",
            );
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

    // One clock. Each rank opens, maps, faults, parses, and unmaps its
    // own span inside the timer. Rank 0 does not scan the whole file.
    // `mpirun` has already returned by `booted`. It is not in this timer.
    let mut span_b = if comm.rank() == 0 {
        frame_span(path).unwrap_or(0) as u64
    } else {
        0
    };
    world.process_at_rank(0).broadcast_into(&mut span_b);
    let span = span_b as usize;
    let file_len = fs::metadata(path)
        .map(|meta| meta.len() as usize)
        .unwrap_or(0);
    if span < 2 || file_len % span != 0 || file_len / span != total {
        if comm.rank() == 0 {
            write_refusal(out_path, "frames do not share one byte length");
        }
        std::process::exit(2);
    }
    let owned = block_range(total, ranks, comm.rank());
    let lo = owned.start * span;
    let hi = owned.end * span;
    let offsets: Vec<usize> = (0..owned.len()).map(|i| i * span).collect();

    // One untimed call, same work as the timed calls. It is not a sample.
    let warmup = time_span(&world, path, lo, hi, &offsets);
    assert_eq!(warmup.n_ok, frames_per_worker);
    let init_to_clock_s = booted.elapsed().as_secs_f64();

    let mut samples = Vec::with_capacity(repeats);
    let mut samples_maj = Vec::with_capacity(repeats);
    let mut samples_min = Vec::with_capacity(repeats);
    let mut open_s = Vec::with_capacity(repeats);
    let mut map_s = Vec::with_capacity(repeats);
    let mut fault_s = Vec::with_capacity(repeats);
    let mut parse_s = Vec::with_capacity(repeats);
    let mut unmap_s = Vec::with_capacity(repeats);
    let mut release_s = Vec::with_capacity(repeats);
    let mut barrier_s = Vec::with_capacity(repeats);
    for _ in 0..repeats {
        let sample = time_span(&world, path, lo, hi, &offsets);
        assert_eq!(sample.n_ok, frames_per_worker);
        let maj = sum_i64(&world, sample.majflt);
        let minr = sum_i64(&world, sample.minflt);
        // Local phases, barrier excluded. Every rank contributes.
        let local = [
            sample.open_s,
            sample.map_s,
            sample.fault_s,
            sample.parse_s,
            sample.release_s,
            sample.unmap_s,
            sample.open_s
                + sample.map_s
                + sample.fault_s
                + sample.parse_s
                + sample.release_s
                + sample.unmap_s,
        ];
        let mut gathered = vec![0.0_f64; local.len() * ranks];
        world.all_gather_into(&local[..], &mut gathered[..]);
        if comm.rank() == 0 {
            let mut slow_at = 0usize;
            let mut slow_local = 0.0_f64;
            for rank in 0..ranks {
                let base = rank * local.len();
                let local_s = gathered[base + 6];
                if rank == 0 || local_s > slow_local {
                    slow_local = local_s;
                    slow_at = rank;
                }
            }
            let base = slow_at * local.len();
            // The sample is the slowest rank's own phase sum. Rank 0's
            // barrier wait is recorded separately and is not this clock.
            samples.push(slow_local);
            samples_maj.push(maj);
            samples_min.push(minr);
            // Phases are the slowest rank's own timers, not rank 0's wait.
            open_s.push(gathered[base]);
            map_s.push(gathered[base + 1]);
            fault_s.push(gathered[base + 2]);
            parse_s.push(gathered[base + 3]);
            release_s.push(gathered[base + 4]);
            unmap_s.push(gathered[base + 5]);
            barrier_s.push(sample.barrier_s);
        }
    }

    if comm.rank() == 0 {
        let mpi = env::var("READCON_WEAK_MPI_IMPL").unwrap_or_else(|_| "unrecorded".to_string());
        let samples_s = fmt_f64s(&samples);
        let maj_s = fmt_i64s(&samples_maj);
        let min_s = fmt_i64s(&samples_min);
        let open_txt = fmt_f64s(&open_s);
        let map_txt = fmt_f64s(&map_s);
        let fault_txt = fmt_f64s(&fault_s);
        let parse_txt = fmt_f64s(&parse_s);
        let unmap_txt = fmt_f64s(&unmap_s);
        let release_txt = fmt_f64s(&release_s);
        let barrier_txt = fmt_f64s(&barrier_s);
        let host = json_escape(&record_cpu());
        let mpi_name = json_escape(mpi.trim());
        let body = format!(
            "{{\n  \"kind\": \"ranks\",\n  \"measured\": true,\n  \"relation\": \"n_frames = frames_per_worker * workers\",\n  \"workers\": {ranks},\n  \"n_frames\": {total},\n  \"frames_per_worker\": {frames_per_worker},\n  \"bytes\": {bytes},\n  \"repeats\": {repeats},\n  \"samples_s\": [{samples_s}],\n  \"samples_majflt\": [{maj_s}],\n  \"samples_minflt\": [{min_s}],\n  \"open_s\": [{open_txt}],\n  \"map_s\": [{map_txt}],\n  \"fault_s\": [{fault_txt}],\n  \"parse_s\": [{parse_txt}],\n  \"unmap_s\": [{unmap_txt}],\n  \"release_s\": [{release_txt}],\n  \"barrier_s\": [{barrier_txt}],\n  \"clock\": \"map-fault-span\",\n  \"mpirun_in_clock\": false,\n  \"init_to_clock_s\": {init_to_clock_s:.9},\n  \"span\": {span},\n  \"page_size\": {},\n  \"cpus_allowed\": [{allowed_list}],\n  \"identical\": true,\n  \"host\": \"{host}\",\n  \"physical_cores\": {physical},\n  \"mpi\": \"{mpi_name}\"\n}}\n",
            page_size()
        );
        if let Some(parent) = out_path.parent() {
            let _ = fs::create_dir_all(parent);
        }
        fs::write(out_path, &body).expect("write json");
        print!("{body}");
    }
}
