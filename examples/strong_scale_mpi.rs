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

fn format_coords(coords: &[f64], id0: u64) -> Vec<u8> {
    let mut out = Vec::with_capacity(coords.len().saturating_mul(8));
    for (index, xyz) in coords.chunks(3).enumerate() {
        for (slot, value) in xyz.iter().enumerate() {
            if slot > 0 {
                out.push(b' ');
            }
            readcon_core::extxyz_scan::append_extxyz_number(&mut out, *value);
        }
        out.push(b' ');
        out.push(b'0');
        out.push(b' ');
        let id = id0 + index as u64;
        out.extend_from_slice(id.to_string().as_bytes());
        out.push(b'\n');
    }
    out
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
    let out = std::path::Path::new("/tmp/readcon-r7-mpi.con");
    let file_bytes = std::fs::read(path).expect("map");
    let split = held.n_total == 1 && comm.size() > 1;
    let (coord_start, coord_end, id0) = if split {
        let (start, end) = frame_coord_span(&file_bytes).expect("coordinates");
        let range = rank_line_range(&file_bytes, start, end, comm.rank(), comm.size());
        let mine = parse_coord_lines(&file_bytes[range]).expect("coords").len() as u64 / 3;
        let mut offset = 0u64;
        world.exclusive_scan_into(&mine, &mut offset, mpi::collective::SystemOperation::sum());
        if comm.rank() == 0 {
            offset = 0;
        }
        (start, end, offset)
    } else {
        (0, 0, 0)
    };
    world.barrier();
    if op == "write" {
        if split {
            let (start, _) = (coord_start, coord_end);
            let range = rank_line_range(&file_bytes, start, coord_end, comm.rank(), comm.size());
            let coords = parse_coord_lines(&file_bytes[range]).expect("coords");
            let mut body = if comm.rank() == 0 {
                file_bytes[..start].to_vec()
            } else {
                Vec::new()
            };
            body.extend(format_coords(&coords, id0));
            write_ranked_bytes(&comm, out, &body).expect("warmup write");
        } else {
            write_block(&comm, out, &held.frames, WriteMode::MpiIo, None).expect("warmup write");
        }
    } else if split {
        let range = rank_line_range(
            &file_bytes,
            coord_start,
            coord_end,
            comm.rank(),
            comm.size(),
        );
        let coords = parse_coord_lines(&file_bytes[range]).expect("coords");
        std::hint::black_box(coords.len());
    } else {
        let _ = read_block(&comm, path, ReadMode::Shared, Some(1)).expect("warmup read");
    }
    world.barrier();
    let mut samples = Vec::with_capacity(repeats);
    for _ in 0..repeats {
        world.barrier();
        let started = Instant::now();
        if op == "write" {
            if split {
                let range = rank_line_range(
                    &file_bytes,
                    coord_start,
                    coord_end,
                    comm.rank(),
                    comm.size(),
                );
                let coords = parse_coord_lines(&file_bytes[range]).expect("coords");
                let mut body = if comm.rank() == 0 {
                    file_bytes[..coord_start].to_vec()
                } else {
                    Vec::new()
                };
                body.extend(format_coords(&coords, id0));
                write_ranked_bytes(&comm, out, &body).expect("write");
            } else {
                write_block(&comm, out, &held.frames, WriteMode::MpiIo, None).expect("write");
            }
        } else if split {
            let range = rank_line_range(
                &file_bytes,
                coord_start,
                coord_end,
                comm.rank(),
                comm.size(),
            );
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
