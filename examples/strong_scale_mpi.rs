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
use readcon_core::distrib_write::{WriteMode, write_block};
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

/// Rank 0's header plus that rank's coordinate slice.
struct RankPieces {
    header: Vec<u8>,
    pieces: Vec<RankAtoms>,
}

fn write_mapped(comm: &Comm, path: &std::path::Path, prepared: &RankPieces) {
    let world = comm.raw();
    // One contiguous slice per rank. The formatted length is the byte count;
    // a second counting pass would format twice.
    let piece = prepared.pieces.first().expect("rank slice");
    let mut buf = readcon_core::writer::format_coordinate_lines(&piece.atoms).expect("format");
    if comm.rank() == 0 && !prepared.header.is_empty() {
        let mut with_header = Vec::with_capacity(prepared.header.len() + buf.len());
        with_header.extend_from_slice(&prepared.header);
        with_header.append(&mut buf);
        readcon_core::writer::recycle_format_buffer(buf);
        buf = with_header;
    }
    let len = buf.len() as u64;
    let mut local_off = 0u64;
    world.exclusive_scan_into(
        &len,
        &mut local_off,
        mpi::collective::SystemOperation::sum(),
    );
    if comm.rank() == 0 {
        local_off = 0;
    }
    let mut total = 0u64;
    world.all_reduce_into(&len, &mut total, mpi::collective::SystemOperation::sum());
    if comm.rank() == 0 {
        let file = std::fs::OpenOptions::new()
            .write(true)
            .create(true)
            .truncate(true)
            .open(path)
            .expect("create");
        file.set_len(total).expect("truncate");
    }
    world.barrier();
    if !buf.is_empty() {
        let file = std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .open(path)
            .expect("open");
        // Map only this rank's bytes. The offset has to be page aligned.
        let page = 4096u64;
        let aligned = local_off & !(page - 1);
        let delta = (local_off - aligned) as usize;
        let span = delta + buf.len();
        let mut map = unsafe {
            memmap2::MmapOptions::new()
                .offset(aligned)
                .len(span)
                .map_mut(&file)
                .expect("mmap")
        };
        map[delta..delta + buf.len()].copy_from_slice(&buf);
        drop(map);
        drop(file);
    }
    readcon_core::writer::recycle_format_buffer(buf);
    if std::env::var_os("READCON_MPI_SYNC").is_some() {
        world.barrier();
        if comm.rank() == 0 {
            let file = std::fs::OpenOptions::new()
                .write(true)
                .open(path)
                .expect("sync open");
            file.sync_data().expect("sync");
        }
    }
    world.barrier();
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
    // One rank keeps the serial writer. The shared mapping was slower there.
    let split = held.n_total == 1 && comm.size() > 1;
    let prepared = if split {
        let (start, end) = frame_coord_span(&file_bytes).expect("coordinates");
        let symbol = component_symbol(&file_bytes);
        let range = rank_line_range(&file_bytes, start, end, comm.rank(), comm.size());
        let pieces = vec![atoms_from_lines(&file_bytes[range], &symbol)];
        let header = if comm.rank() == 0 {
            file_bytes[..start].to_vec()
        } else {
            Vec::new()
        };
        Some((RankPieces { header, pieces }, start, end))
    } else {
        None
    };
    world.barrier();
    if op == "write" {
        if let Some((pieces, _, _)) = &prepared {
            write_mapped(&comm, out, pieces);
        } else {
            write_block(&comm, out, &held.frames, WriteMode::MpiIo, None).expect("warmup write");
        }
    } else if let Some((pieces, _, _)) = &prepared {
        std::hint::black_box(pieces.pieces.len());
    } else {
        let _ = read_block(&comm, path, ReadMode::Shared, Some(1)).expect("warmup read");
    }
    world.barrier();
    let mut samples = Vec::with_capacity(repeats);
    for _ in 0..repeats {
        world.barrier();
        let started = Instant::now();
        if op == "write" {
            if let Some((pieces, _, _)) = &prepared {
                write_mapped(&comm, out, pieces);
            } else {
                write_block(&comm, out, &held.frames, WriteMode::MpiIo, None).expect("write");
            }
        } else if let Some((_, start, end)) = &prepared {
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
