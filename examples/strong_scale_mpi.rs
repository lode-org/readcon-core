//! `mpirun -n N strong_scale_mpi read|write FILE [repeats]`
//!
//! Times a collective read or write of one fixed file. One warmup, then
//! `repeats` samples. Rank 0 prints the samples. The timer is inside the
//! process, after `mpirun` has started.
//!
//! A single wide frame is formatted per rank. The library writes a fresh
//! temporary and renames it onto the destination, so no `.rewrite` file
//! remains. `READCON_MPI_REWRITE=1` opts into that spare.
//! `READCON_MPI_SYNC` fdatasyncs on rank 0 before the sample ends.

use mpi::traits::*;
use readcon_core::distrib::Comm;
use readcon_core::distrib_read::{
    ReadMode, frame_coord_span, parse_coord_lines, rank_line_range, read_block,
};
use readcon_core::distrib_write::{WriteMode, write_block, write_ranked_bytes};
use std::time::Instant;

struct RankAtoms {
    _coords: Vec<f64>,
    atoms: Vec<readcon_core::types::AtomDatum>,
}

fn atoms_from_lines(slice: &[u8], symbol: &std::sync::Arc<str>) -> RankAtoms {
    let (coords, atoms) = readcon_core::distrib_read::slab_atoms(slice, symbol).expect("coord");
    RankAtoms {
        _coords: coords,
        atoms,
    }
}

fn component_symbol(bytes: &[u8]) -> std::sync::Arc<str> {
    let marker = b"\nCoordinates of Component 1\n";
    let at = memchr::memmem::find(bytes, marker).unwrap_or(0);
    let start = bytes[..at]
        .iter()
        .rposition(|byte| *byte == b'\n')
        .map(|index| index + 1)
        .unwrap_or(0);
    let symbol = std::str::from_utf8(&bytes[start..at]).unwrap_or("X");
    std::sync::Arc::from(symbol)
}

fn read_mode() -> ReadMode {
    match std::env::var("READCON_MPI_READ").ok().as_deref() {
        Some("scatter") => ReadMode::Scatter,
        Some("shared") | None => ReadMode::Shared,
        Some(other) => {
            eprintln!("READCON_MPI_READ must be shared or scatter, got {other}");
            std::process::exit(2);
        }
    }
}

fn rewrite_flags() -> (bool, bool) {
    let rewrite = std::env::var_os("READCON_MPI_REWRITE").is_some();
    let keep_spare = std::env::var("READCON_MPI_KEEP_SPARE")
        .map(|value| value != "0")
        .unwrap_or(true);
    (rewrite, keep_spare)
}

fn write_rank(comm: &Comm, out: &std::path::Path, body: &[u8]) {
    let (rewrite, keep_spare) = rewrite_flags();
    write_ranked_bytes(comm, out, body, rewrite, keep_spare).expect("pwrite");
    maybe_sync(comm, out);
}

fn window_is_steady(samples: &[f64]) -> bool {
    if samples.len() < 4 {
        return false;
    }
    let w = &samples[samples.len() - 3..];
    let mut ordered = [w[0], w[1], w[2]];
    ordered.sort_by(|left, right| left.partial_cmp(right).unwrap_or(std::cmp::Ordering::Equal));
    let median = ordered[1];
    median > 0.0 && ordered[2] - ordered[0] <= median * 0.10
}

fn maybe_sync(comm: &Comm, out: &std::path::Path) {
    if std::env::var_os("READCON_MPI_SYNC").is_some() && comm.rank() == 0 {
        if let Ok(file) = std::fs::File::open(out) {
            let _ = file.sync_data();
        }
    }
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.len() < 2 {
        eprintln!("usage: strong_scale_mpi read|write FILE [repeats]");
        std::process::exit(2);
    }
    let op = &args[0];
    let path = std::path::Path::new(&args[1]);
    let repeats: usize = args.get(2).and_then(|text| text.parse().ok()).unwrap_or(6);
    let universe = mpi::initialize().expect("mpi");
    let world = universe.world();
    let comm = Comm::dup_of(&world);
    let mode = read_mode();
    let held = read_block(&comm, path, mode, Some(1)).expect("read");
    // READCON_MPI_OUT selects the collective output. The default is
    // build/bench/readcon-r7-mpi.con in this checkout, so a tmpfs and a
    // disk can be timed apart by pointing the variable at the other store.
    let out_buf = std::env::var("READCON_MPI_OUT")
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|_| {
            let path = std::path::PathBuf::from("build/bench/readcon-r7-mpi.con");
            if let Some(parent) = path.parent() {
                let _ = std::fs::create_dir_all(parent);
            }
            path
        });
    let out = out_buf.as_path();
    let file_bytes = std::fs::read(path).expect("map");
    let split = held.n_total == 1 && comm.size() > 1;
    let prepared = if split {
        let (start, end) = frame_coord_span(&file_bytes).expect("coordinates");
        let range = rank_line_range(&file_bytes, start, end, comm.rank(), comm.size());
        let symbol = component_symbol(&file_bytes);
        let rows = atoms_from_lines(&file_bytes[range], &symbol);
        // The one-rank path writes this frame with `write_frame_bound`,
        // which stamps the binding header. Copying the file's own header
        // left that stamp off every wider run (43 bytes on the million-atom
        // file). The coordinate lines already match.
        let header = if comm.rank() == 0 {
            readcon_core::writer::wide_frame_header(&held.frames[0]).expect("header")
        } else {
            Vec::new()
        };
        Some((header, rows, start, end))
    } else {
        None
    };
    let floor = op == "floor-fresh" || op == "floor-replace";
    // One pass is not enough: the first writes of a fresh inode are slower
    // than the later ones. Keep going until the last three agree within 10%,
    // after at least four passes, or twelve passes, and only then collect
    // the timed samples.
    let mut warm_times = Vec::new();
    let mut warmups = 0usize;
    loop {
        world.barrier();
        let started = Instant::now();
        if op == "read" {
            if let Some((_, _, start, end)) = &prepared {
                let range = rank_line_range(&file_bytes, *start, *end, comm.rank(), comm.size());
                let coords = parse_coord_lines(&file_bytes[range]).expect("coords");
                std::hint::black_box(coords.len());
            } else {
                let got = read_block(&comm, path, mode, Some(1)).expect("warmup read");
                std::hint::black_box(got.n_total);
            }
        } else if let Some((header, rows, _, _)) = &prepared {
            let mut body = header.clone();
            body.extend(
                readcon_core::writer::format_coordinate_lines(&rows.atoms).expect("format"),
            );
            write_rank(&comm, out, &body);
        } else {
            let (rewrite, keep_spare) = rewrite_flags();
            write_block(
                &comm,
                out,
                &held.frames,
                WriteMode::MpiIo,
                None,
                rewrite,
                keep_spare,
            )
            .expect("warmup write");
            maybe_sync(&comm, out);
        }
        world.barrier();
        warmups += 1;
        let mut stop = [0u8];
        if comm.rank() == 0 {
            warm_times.push(started.elapsed().as_secs_f64());
            if warmups >= 12 || window_is_steady(&warm_times) {
                stop[0] = 1;
            }
        }
        world.process_at_rank(0).broadcast_into(&mut stop);
        if stop[0] == 1 {
            break;
        }
    }
    // The floor copies the file the warmup writes just published. The read
    // of that file is outside the clock, the same way atom preparation is
    // outside the write clock. Fresh unlinks the destination before the
    // clock. Replace starts with a same-sized file already at the name.
    let payload = if floor && comm.rank() == 0 {
        std::fs::read(out).expect("floor bytes")
    } else {
        Vec::new()
    };
    let fresh_path = out.with_extension("fresh");
    let replace_path = out.with_extension("replace");
    if op == "floor-replace" && comm.rank() == 0 {
        std::fs::write(&replace_path, &payload).expect("seed replace");
    }
    let mut samples = Vec::with_capacity(repeats);
    for _ in 0..repeats {
        if op == "floor-fresh" && comm.rank() == 0 {
            let _ = std::fs::remove_file(&fresh_path);
        }
        world.barrier();
        let started = Instant::now();
        if op == "floor-fresh" || op == "floor-replace" {
            if comm.rank() == 0 {
                if op == "floor-fresh" {
                    let mut file = std::fs::File::create(&fresh_path).expect("fresh");
                    std::io::Write::write_all(&mut file, &payload).expect("fresh bytes");
                } else {
                    let tmp = replace_path.with_extension("tmp");
                    {
                        let mut file = std::fs::File::create(&tmp).expect("replace tmp");
                        std::io::Write::write_all(&mut file, &payload).expect("replace bytes");
                    }
                    std::fs::rename(&tmp, &replace_path).expect("replace");
                }
            }
        } else if op == "write" {
            if let Some((header, rows, _, _)) = &prepared {
                let mut body = header.clone();
                body.extend(
                    readcon_core::writer::format_coordinate_lines(&rows.atoms).expect("format"),
                );
                write_rank(&comm, out, &body);
            } else {
                let (rewrite, keep_spare) = rewrite_flags();
                write_block(
                    &comm,
                    out,
                    &held.frames,
                    WriteMode::MpiIo,
                    None,
                    rewrite,
                    keep_spare,
                )
                .expect("write");
                maybe_sync(&comm, out);
            }
        } else if let Some((_, _, start, end)) = &prepared {
            let range = rank_line_range(&file_bytes, *start, *end, comm.rank(), comm.size());
            let coords = parse_coord_lines(&file_bytes[range]).expect("coords");
            std::hint::black_box(coords.len());
        } else {
            let got = read_block(&comm, path, mode, Some(1)).expect("read");
            std::hint::black_box(got.n_total);
        }
        world.barrier();
        samples.push(started.elapsed().as_secs_f64());
    }
    if comm.rank() == 0 {
        let text = samples
            .iter()
            .map(|sample| format!("{sample:.6}"))
            .collect::<Vec<_>>()
            .join(",");
        let nbytes = std::fs::metadata(out).map(|meta| meta.len()).unwrap_or(0);
        let low = samples.iter().copied().fold(f64::MAX, f64::min);
        let high = samples.iter().copied().fold(0.0_f64, f64::max);
        println!(
            "op={op} ranks={} frames={} warmup={warmups} bytes={nbytes} range={:.6} samples={text}",
            comm.size(),
            held.n_total,
            high - low
        );
    }
}
