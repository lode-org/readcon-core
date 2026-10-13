//! `mpirun -n N mpi_read_check FILE MODE OUT [THREADS]`
//!
//! MODE is `auto`, `shared` or `scatter`. Every rank reads its block,
//! writes its frames with the serial writer, and sends the bytes to
//! rank 0 in rank order. Rank 0 writes `OUT.mpi` (concatenated ranks)
//! and `OUT.serial` (serial read of the same file, same writer) and
//! exits non-zero if they differ; compare them with `sha256sum`.
use mpi::traits::*;
use readcon_core::distrib::Comm;
use readcon_core::distrib_read::{ReadMode, read_block};
use readcon_core::types::ConFrame;
use readcon_core::writer::ConFrameWriter;
use std::path::Path;
use std::time::Instant;

fn write_all(frames: &[ConFrame]) -> Vec<u8> {
    let mut out = Vec::new();
    {
        let mut w = ConFrameWriter::new(&mut out);
        for f in frames {
            w.write_frame(f).unwrap();
        }
        w.flush().unwrap();
    }
    out
}

fn main() {
    let a: Vec<String> = std::env::args().collect();
    let path = Path::new(&a[1]);
    let mode = match a[2].as_str() {
        "auto" => ReadMode::Auto,
        "shared" => ReadMode::Shared,
        "scatter" => ReadMode::Scatter,
        m => panic!("unknown mode {m}"),
    };
    let threads = a.get(4).map(|t| t.parse().unwrap());
    let universe = mpi::initialize().unwrap();
    let world = universe.world();
    let comm = Comm::dup_of(&world);

    world.barrier();
    let t0 = Instant::now();
    let rf = read_block(&comm, path, mode, threads).unwrap();
    world.barrier();
    let dt = t0.elapsed().as_secs_f64() * 1e3;
    assert_eq!(rf.first, comm.my_frames(rf.n_total).start);

    let mine = write_all(&rf.frames);
    if comm.rank() == 0 {
        let mut cat = mine;
        for k in 1..comm.size() {
            let (bytes, _) = world.process_at_rank(k as i32).receive_vec::<u8>();
            cat.extend_from_slice(&bytes);
        }
        let t1 = Instant::now();
        let serial = readcon_core::iterators::read_all_frames(path).unwrap();
        let ds = t1.elapsed().as_secs_f64() * 1e3;
        let ser = write_all(&serial);
        std::fs::write(format!("{}.mpi", a[3]), &cat).unwrap();
        std::fs::write(format!("{}.serial", a[3]), &ser).unwrap();
        println!(
            "ranks={} mode={} frames={} distributed_ms={dt:.1} serial_ms={ds:.1} identical={}",
            comm.size(),
            a[2],
            rf.n_total,
            cat == ser
        );
        if cat != ser {
            std::process::exit(1);
        }
    } else {
        world.process_at_rank(0).send(&mine[..]);
    }
}
