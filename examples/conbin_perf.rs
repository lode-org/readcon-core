//! One fresh-process sample of a warm-cache CON-bin read.
//!
//! `conbin_perf <map|copy> <seed> <frames> <atoms> <path>`
//!
//! The process always writes `path` from `seed` before the clock starts, so
//! the timed read is served from the page cache. It prints one tab-separated
//! line and exits.

#[cfg(unix)]
use std::path::PathBuf;
#[cfg(unix)]
use std::time::Instant;

#[cfg(unix)]
use readcon_core::conbin;

#[cfg(not(unix))]
fn main() {
    eprintln!("conbin_perf uses pread and is built for Unix only");
    std::process::exit(0);
}

#[cfg(unix)]
fn main() {
    let mut args = std::env::args().skip(1);
    let mode = args.next().expect("mode");
    let seed: u64 = args.next().expect("seed").parse().expect("seed");
    let frames: u64 = args.next().expect("frames").parse().expect("frames");
    let atoms: u64 = args.next().expect("atoms").parse().expect("atoms");
    let path = PathBuf::from(args.next().expect("path"));
    let header = conbin::write_uniform(&path, frames, atoms, seed).expect("write");
    let n = header.position_len().expect("length");
    let started = Instant::now();
    let checksum = match mode.as_str() {
        "map" => {
            let mapped = conbin::map_file(&path, 1).expect("map");
            let pos = mapped.positions_f64().expect("positions");
            let vel = mapped.velocities_f64().expect("velocities");
            fold(pos) ^ fold(vel)
        }
        "copy" => {
            let mut pos = vec![0.0; n];
            let mut vel = vec![0.0; n];
            conbin::read_into(&path, &mut pos, Some(&mut vel)).expect("copy");
            fold(&pos) ^ fold(&vel)
        }
        other => panic!("mode {other} is map or copy"),
    };
    let secs = started.elapsed().as_secs_f64();
    println!("{mode}\t{seed}\t{frames}\t{atoms}\t{secs:.6}\t{n}\t{checksum:016x}");
}

#[cfg(unix)]
fn fold(values: &[f64]) -> u64 {
    values.iter().fold(0u64, |acc, value| acc ^ value.to_bits())
}
