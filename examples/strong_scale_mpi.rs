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

/// One rank's strided coordinate slices, in file order.
///
/// Slice `w` is global group `w * nranks + rank`. Writing wave `w` on every
/// rank, in rank order, lays the groups down in file order. The `pwrite` of
/// wave `w` runs while wave `w + 1` is formatted.
struct RankPieces {
    header: Vec<u8>,
    pieces: Vec<RankAtoms>,
}

fn pwrite_all(file: &std::fs::File, buf: &[u8], mut offset: u64) -> std::io::Result<()> {
    use std::os::unix::io::AsRawFd;
    if buf.is_empty() {
        return Ok(());
    }
    let fd = file.as_raw_fd();
    let mut written = 0usize;
    while written < buf.len() {
        let n = unsafe {
            libc::pwrite(
                fd,
                buf[written..].as_ptr() as *const libc::c_void,
                buf.len() - written,
                offset as libc::off_t,
            )
        };
        if n < 0 {
            let err = std::io::Error::last_os_error();
            if err.kind() == std::io::ErrorKind::Interrupted {
                continue;
            }
            return Err(err);
        }
        if n == 0 {
            return Err(std::io::Error::new(std::io::ErrorKind::WriteZero, "pwrite"));
        }
        written += n as usize;
        offset += n as u64;
    }
    Ok(())
}

fn write_split_overlapped(comm: &Comm, path: &std::path::Path, prepared: &RankPieces) {
    let world = comm.raw();
    if comm.rank() == 0 {
        let _ = std::fs::File::create(path);
    }
    world.barrier();
    let file = std::fs::OpenOptions::new()
        .write(true)
        .open(path)
        .expect("open");
    let mut cursor = 0u64;
    // The previous wave's bytes are written on a side thread while this wave
    // is formatted. `mpirun --bind-to core` pins that thread to the rank's
    // core, so the overlap is the kernel copy yielding to the formatter only
    // when the copy stalls. The scan is per wave, not per byte.
    let mut inflight: Option<std::thread::JoinHandle<std::io::Result<()>>> = None;
    for (wave, piece) in prepared.pieces.iter().enumerate() {
        let mut buf = readcon_core::writer::format_coordinate_lines(&piece.atoms).expect("format");
        if wave == 0 && comm.rank() == 0 && !prepared.header.is_empty() {
            let mut with_header = Vec::with_capacity(prepared.header.len() + buf.len());
            with_header.extend_from_slice(&prepared.header);
            with_header.extend_from_slice(&buf);
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
            // Rank 0's exclusive-scan result is undefined.
            local_off = 0;
        }
        let mut wave_bytes = 0u64;
        world.all_reduce_into(
            &len,
            &mut wave_bytes,
            mpi::collective::SystemOperation::sum(),
        );
        let file_off = cursor + local_off;
        if let Some(handle) = inflight.take() {
            handle.join().expect("pwrite").expect("pwrite");
        }
        if !buf.is_empty() {
            let cloned = file.try_clone().expect("dup");
            inflight = Some(std::thread::spawn(move || {
                let wrote = pwrite_all(&cloned, &buf, file_off);
                readcon_core::writer::recycle_format_buffer(buf);
                wrote
            }));
        }
        cursor += wave_bytes;
    }
    if let Some(handle) = inflight.take() {
        handle.join().expect("pwrite").expect("pwrite");
    }
    if std::env::var_os("READCON_MPI_SYNC").is_some() {
        world.barrier();
        if comm.rank() == 0 {
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
    let split = held.n_total == 1 && comm.size() > 1;
    let prepared = if split {
        let (start, end) = frame_coord_span(&file_bytes).expect("coordinates");
        let symbol = component_symbol(&file_bytes);
        // Two waves. Group `w * nranks + rank` is this rank's slice of wave
        // `w`, so a wave written in rank order is the next run of atoms.
        // A third wave was an extra exclusive scan and did not hide any more
        // of the format.
        let waves = 2usize;
        let groups = comm.size() * waves;
        let mut pieces = Vec::with_capacity(waves);
        for wave in 0..waves {
            let group = wave * comm.size() + comm.rank();
            let range = rank_line_range(&file_bytes, start, end, group, groups);
            pieces.push(atoms_from_lines(&file_bytes[range], &symbol));
        }
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
            write_split_overlapped(&comm, out, pieces);
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
                write_split_overlapped(&comm, out, pieces);
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
