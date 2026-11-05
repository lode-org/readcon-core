//! Time one distributed CON read. Rank 0 prints the wall time and the
//! checksum of the frames this rank parsed. The parent repeats the launch.

use readcon_core::distrib::Comm;
use readcon_core::distrib_read::{ReadMode, read_block};
use std::env;
use std::time::Instant;

fn main() {
    let universe = mpi::initialize().unwrap();
    let world = universe.world();
    let comm = Comm::dup_of(&world);
    let path = env::args().nth(1).expect("path");
    let mode = match env::args().nth(2).as_deref() {
        Some("scatter") => ReadMode::Scatter,
        _ => ReadMode::Shared,
    };
    let start = Instant::now();
    let got = read_block(&comm, path.as_ref(), mode, Some(1)).expect("read");
    let elapsed = start.elapsed().as_nanos();
    let mut sum = 0.0f64;
    for frame in &got.frames {
        if let Some(values) = frame.positions.f64_slice() {
            for value in values {
                sum += *value;
            }
        }
    }
    if comm.rank() == 0 {
        println!(
            "ranks {} frames {} local {} ns {} sum {:.6}",
            comm.size(),
            got.n_total,
            got.frames.len(),
            elapsed,
            sum
        );
    }
}
