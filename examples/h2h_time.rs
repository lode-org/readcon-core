//! Timed read and write of one CON or convel file.
//!
//! One sample is one call on the calling thread. The clock starts after the
//! path is opened by that call and stops after every stored coordinate has
//! been mixed into the checksum, so a release build cannot drop the parse.
//!
//! ```text
//! h2h_time read PATH REPEATS
//! h2h_time positions PATH REPEATS
//! h2h_time write PATH REPEATS OUT
//! ```
//!
//! Each sample is one stdout line:
//! `sample kind=read seconds=0.1 frames=2 atoms=4 pos=1 vel=2 mass=3 cell=4`

use readcon_core::iterators::{read_all_frames_with_threads, read_positions_with_threads};
use readcon_core::types::ConFrame;
use readcon_core::writer::ConFrameWriter;
use std::env;
use std::hint::black_box;
use std::path::Path;
use std::process::ExitCode;
use std::time::Instant;

fn mix(acc: u64, bits: u64) -> u64 {
    acc.wrapping_mul(0x9E3779B97F4A7C15).wrapping_add(bits)
}

fn checksum(frames: &[ConFrame]) -> (u64, u64, u64, u64, usize, usize) {
    let mut pos = 0u64;
    let mut vel = 0u64;
    let mut mass = 0u64;
    let mut cell = 0u64;
    let mut atoms = 0usize;
    for frame in frames {
        atoms += frame.atom_data.len();
        for atom in &frame.atom_data {
            pos = mix(pos, atom.x.to_bits());
            pos = mix(pos, atom.y.to_bits());
            pos = mix(pos, atom.z.to_bits());
            if let Some(v) = atom.velocity() {
                vel = mix(vel, v[0].to_bits());
                vel = mix(vel, v[1].to_bits());
                vel = mix(vel, v[2].to_bits());
            }
        }
        for value in &frame.header.masses_per_type {
            mass = mix(mass, value.to_bits());
        }
        for value in frame.header.boxl.iter().chain(frame.header.angles.iter()) {
            cell = mix(cell, value.to_bits());
        }
    }
    (pos, vel, mass, cell, frames.len(), atoms)
}

fn checksum_positions(values: &[f64], n_frames: usize, n_atoms: usize) -> u64 {
    let mut pos = 0u64;
    for value in values {
        pos = mix(pos, value.to_bits());
    }
    let _ = (n_frames, n_atoms);
    pos
}

fn emit(
    kind: &str,
    seconds: f64,
    frames: usize,
    atoms: usize,
    pos: u64,
    vel: u64,
    mass: u64,
    cell: u64,
) {
    println!(
        "sample kind={kind} seconds={seconds:.9} frames={frames} atoms={atoms} pos={pos} vel={vel} mass={mass} cell={cell}"
    );
}

fn read_frames(path: &Path) -> Vec<ConFrame> {
    read_all_frames_with_threads(path, Some(1)).expect("read")
}

fn time_read(path: &Path, repeats: usize) {
    let warm = read_frames(path);
    black_box(checksum(&warm));
    for _ in 0..repeats {
        let started = Instant::now();
        let frames = read_frames(path);
        let (pos, vel, mass, cell, n_frames, atoms) = checksum(&frames);
        let seconds = started.elapsed().as_secs_f64();
        black_box(pos);
        emit("read", seconds, n_frames, atoms, pos, vel, mass, cell);
    }
}

fn time_positions(path: &Path, repeats: usize) {
    let warm = read_positions_with_threads(path, Some(1)).expect("positions");
    black_box(checksum_positions(
        &warm.values,
        warm.n_frames,
        warm.n_atoms,
    ));
    for _ in 0..repeats {
        let started = Instant::now();
        let block = read_positions_with_threads(path, Some(1)).expect("positions");
        let pos = checksum_positions(&block.values, block.n_frames, block.n_atoms);
        let seconds = started.elapsed().as_secs_f64();
        black_box(pos);
        let atoms = block.n_frames.saturating_mul(block.n_atoms);
        emit("positions", seconds, block.n_frames, atoms, pos, 0, 0, 0);
    }
}

fn time_write(path: &Path, repeats: usize, out: &Path) {
    let frames = read_frames(path);
    let (pos, vel, mass, cell, n_frames, atoms) = checksum(&frames);
    black_box(pos);
    for _ in 0..repeats {
        let started = Instant::now();
        {
            let mut writer = ConFrameWriter::from_path(out).expect("create");
            writer.extend(frames.iter()).expect("write");
            writer.flush().expect("flush");
        }
        let seconds = started.elapsed().as_secs_f64();
        emit("write", seconds, n_frames, atoms, pos, vel, mass, cell);
    }
}

fn main() -> ExitCode {
    let args: Vec<String> = env::args().skip(1).collect();
    let Some(kind) = args.first().map(String::as_str) else {
        eprintln!("usage: h2h_time read|positions|write PATH REPEATS [OUT]");
        return ExitCode::from(2);
    };
    if args.len() < 3 {
        eprintln!("usage: h2h_time read|positions|write PATH REPEATS [OUT]");
        return ExitCode::from(2);
    }
    let path = Path::new(&args[1]);
    let repeats: usize = args[2].parse().expect("repeats");
    match kind {
        "read" => time_read(path, repeats),
        "positions" => time_positions(path, repeats),
        "write" => {
            let Some(out) = args.get(3) else {
                eprintln!("write needs OUT");
                return ExitCode::from(2);
            };
            time_write(path, repeats, Path::new(out));
        }
        _ => {
            eprintln!("unknown kind {kind}");
            return ExitCode::from(2);
        }
    }
    ExitCode::SUCCESS
}
