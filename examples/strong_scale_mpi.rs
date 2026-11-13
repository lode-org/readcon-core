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

fn atoms_from_lines(
    slice: &[u8],
    symbol: &std::sync::Arc<str>,
) -> Vec<readcon_core::types::AtomDatum> {
    let mut atoms = Vec::new();
    let mut cursor = 0usize;
    while cursor < slice.len() {
        let start = cursor;
        while cursor < slice.len() && slice[cursor] != b'\n' {
            cursor += 1;
        }
        let line = &slice[start..cursor];
        if cursor < slice.len() {
            cursor += 1;
        }
        if line.iter().all(|byte| byte.is_ascii_whitespace()) {
            continue;
        }
        let mut index = 0usize;
        let mut xyz = [0.0f64; 3];
        for value in &mut xyz {
            while index < line.len() && line[index].is_ascii_whitespace() {
                index += 1;
            }
            let (parsed, used) =
                fast_float2::parse_partial::<f64, _>(&line[index..]).expect("coord");
            *value = parsed;
            index += used;
        }
        while index < line.len() && line[index].is_ascii_whitespace() {
            index += 1;
        }
        let mut fixed_bits = 0u8;
        let mut id = atoms.len() as u64;
        if index < line.len() {
            let (value, used) = parse_u64(&line[index..]);
            fixed_bits = value as u8;
            index += used;
            while index < line.len() && line[index].is_ascii_whitespace() {
                index += 1;
            }
            if index < line.len() {
                let (value, _) = parse_u64(&line[index..]);
                id = value;
            }
        }
        let fixed = [
            fixed_bits & 1 != 0,
            fixed_bits & 2 != 0,
            fixed_bits & 4 != 0,
        ];
        atoms.push(readcon_core::types::AtomDatum::coords(
            std::sync::Arc::clone(symbol),
            xyz[0],
            xyz[1],
            xyz[2],
            fixed,
            id,
        ));
    }
    atoms
}

fn parse_u64(bytes: &[u8]) -> (u64, usize) {
    let mut value = 0u64;
    let mut used = 0usize;
    for byte in bytes {
        if !byte.is_ascii_digit() {
            break;
        }
        value = value * 10 + u64::from(byte - b'0');
        used += 1;
    }
    (value, used)
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
    let out = std::path::Path::new("/tmp/readcon-r7-mpi.con");
    let file_bytes = std::fs::read(path).expect("map");
    let split = held.n_total == 1 && comm.size() > 1;
    let prepared = if split {
        let (start, end) = frame_coord_span(&file_bytes).expect("coordinates");
        let range = rank_line_range(&file_bytes, start, end, comm.rank(), comm.size());
        let symbol = component_symbol(&file_bytes);
        let atoms = atoms_from_lines(&file_bytes[range], &symbol);
        let header = if comm.rank() == 0 {
            file_bytes[..start].to_vec()
        } else {
            Vec::new()
        };
        Some((header, atoms, start, end))
    } else {
        None
    };
    world.barrier();
    if op == "write" {
        if let Some((header, atoms, _, _)) = &prepared {
            let mut body = header.clone();
            body.extend(readcon_core::writer::format_coordinate_lines(atoms).expect("format"));
            write_ranked_bytes(&comm, out, &body).expect("warmup write");
        } else {
            write_block(&comm, out, &held.frames, WriteMode::MpiIo, None).expect("warmup write");
        }
    } else if let Some((_, atoms, _, _)) = &prepared {
        std::hint::black_box(atoms.len());
    } else {
        let _ = read_block(&comm, path, ReadMode::Shared, Some(1)).expect("warmup read");
    }
    world.barrier();
    let mut samples = Vec::with_capacity(repeats);
    for _ in 0..repeats {
        world.barrier();
        let started = Instant::now();
        if op == "write" {
            if let Some((header, atoms, _, _)) = &prepared {
                let mut body = header.clone();
                body.extend(readcon_core::writer::format_coordinate_lines(atoms).expect("format"));
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
