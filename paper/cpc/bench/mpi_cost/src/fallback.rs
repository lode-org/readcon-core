//! Scatter when only rank 0 can open the file.
//!
//! Other ranks change to an empty directory, so their open fails. Rank 0
//! scans the file. The others wait in the blocking broadcast.

use readcon_core::distrib::Comm;
use readcon_core::distrib_read::{ReadMode, read_block};
use std::env;
use std::fs;
use std::io::{BufRead, BufReader};
use std::time::Instant;

fn read_bytes() -> u64 {
    let file = fs::File::open("/proc/self/io").expect("io");
    for line in BufReader::new(file).lines() {
        let line = line.expect("io line");
        if let Some(rest) = line.strip_prefix("read_bytes:") {
            return rest.trim().parse().expect("read_bytes");
        }
    }
    0
}

fn main() {
    let universe = mpi::initialize().unwrap();
    let world = universe.world();
    let comm = Comm::dup_of(&world);
    let visible = env::args().nth(1).expect("visible dir");
    let empty = env::args().nth(2).expect("empty dir");
    if comm.rank() == 0 {
        env::set_current_dir(&visible).expect("visible");
    } else {
        env::set_current_dir(&empty).expect("empty");
    }
    let open_ok = fs::File::open("frames.con").is_ok();
    let before = read_bytes();
    let start = Instant::now();
    let got = read_block(&comm, "frames.con".as_ref(), ReadMode::Scatter, Some(1)).expect("read");
    let elapsed = start.elapsed().as_nanos();
    let scanned = read_bytes().saturating_sub(before);
    println!(
        "rank {} open_ok {} scanned_bytes {} frames {} local {} ns {}",
        comm.rank(),
        u8::from(open_ok),
        scanned,
        got.n_total,
        got.frames.len(),
        elapsed
    );
}
