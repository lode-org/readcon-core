//! `mpirun -n N strong_scale_mpi read|write FILE [repeats]`
//!
//! Times a collective read or write of one fixed file. One warmup, then
//! `repeats` samples. Rank 0 prints the samples. The timer is inside the
//! process, after `mpirun` has started.

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
    let held = read_block(&comm, path, ReadMode::Shared, Some(1)).expect("read");
    // Default stays on /tmp. READCON_MPI_OUT points the same collective at
    // another directory so a tmpfs and a disk can be timed apart.
    let out_buf = std::env::var("READCON_MPI_OUT")
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|_| std::path::PathBuf::from("/tmp/readcon-r7-mpi.con"));
    let out = out_buf.as_path();
    let file_bytes = std::fs::read(path).expect("map");
    let split = held.n_total == 1 && comm.size() > 1;
    let prepared = if split {
        let (start, end) = frame_coord_span(&file_bytes).expect("coordinates");
        let range = rank_line_range(&file_bytes, start, end, comm.rank(), comm.size());
        let symbol = component_symbol(&file_bytes);
        let rows = atoms_from_lines(&file_bytes[range], &symbol);
        let header = if comm.rank() == 0 {
            file_bytes[..start].to_vec()
        } else {
            Vec::new()
        };
        Some((header, rows, start, end))
    } else {
        None
    };
    world.barrier();
    if op == "write" {
        if let Some((header, rows, _, _)) = &prepared {
            let mut body = header.clone();
            body.extend(
                readcon_core::writer::format_coordinate_lines(&rows.atoms).expect("format"),
            );
            write_ranked_bytes(&comm, out, &body).expect("warmup write");
        } else {
            write_block(&comm, out, &held.frames, WriteMode::MpiIo, None).expect("warmup write");
        }
    } else if let Some((_, rows, _, _)) = &prepared {
        std::hint::black_box(rows.atoms.len());
    } else {
        let _ = read_block(&comm, path, ReadMode::Shared, Some(1)).expect("warmup read");
    }
    world.barrier();
    let mut samples = Vec::with_capacity(repeats);
    for _ in 0..repeats {
        world.barrier();
        let started = Instant::now();
        if op == "write" {
            if let Some((header, rows, _, _)) = &prepared {
                let mut body = header.clone();
                body.extend(
                    readcon_core::writer::format_coordinate_lines(&rows.atoms).expect("format"),
                );
                write_ranked_bytes(&comm, out, &body).expect("write");
            } else {
                write_block(&comm, out, &held.frames, WriteMode::MpiIo, None).expect("write");
            }
        } else if let Some((_, _, start, end)) = &prepared {
            let range = rank_line_range(&file_bytes, *start, *end, comm.rank(), comm.size());
            let coords = parse_coord_lines(&file_bytes[range]).expect("coords");
            std::hint::black_box(coords.len());
        } else {
            let got = read_block(&comm, path, ReadMode::Shared, Some(1)).expect("read");
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
        println!(
            "op={op} ranks={} frames={} samples={text}",
            comm.size(),
            held.n_total
        );
    }
}
