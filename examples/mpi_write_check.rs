//! `mpirun -n N mpi_write_check IN OUT MODE [THREADS]`
//!
//! Round trip: distributed read of IN (auto mode), then a collective
//! write of each rank's frames to `OUT.mpi` with MODE (`mpiio` or
//! `gather`). Rank 0 also writes `OUT.serial` with the serial writer
//! from a serial read of IN and exits non-zero unless the two files are
//! byte-identical and the `.rcidx` written beside `OUT.mpi` matches a
//! fresh scan. Compare the two files with `sha256sum`.
use mpi::traits::*;
use readcon_core::distrib::Comm;
use readcon_core::distrib_read::{ReadMode, read_block};
use readcon_core::distrib_write::{WriteMode, write_block};
use readcon_core::frame_index::{FrameIndex, read_sidecar};
use readcon_core::writer::{ConFrameWriter, binding_rewrite_frame};
use std::path::Path;
use std::time::Instant;

fn main() {
    let a: Vec<String> = std::env::args().collect();
    let input = Path::new(&a[1]);
    let mode = match a[3].as_str() {
        "auto" => WriteMode::Auto,
        "mpiio" => WriteMode::MpiIo,
        "gather" => WriteMode::Gather,
        m => panic!("unknown mode {m}"),
    };
    let threads = a.get(4).map(|t| t.parse().unwrap());
    let universe = mpi::initialize().unwrap();
    let world = universe.world();
    let comm = Comm::dup_of(&world);
    let out_mpi = format!("{}.mpi", a[2]);

    let rf = read_block(&comm, input, ReadMode::Auto, threads).unwrap();
    // Leave a longer stale file in place: set_size must trim it.
    if comm.rank() == 0 {
        std::fs::write(&out_mpi, vec![b'x'; 4 << 20]).unwrap();
    }
    world.barrier();
    let t0 = Instant::now();
    let total = write_block(&comm, Path::new(&out_mpi), &rf.frames, mode, None).unwrap();
    let dt = t0.elapsed().as_secs_f64() * 1e3;

    if comm.rank() == 0 {
        let serial = readcon_core::iterators::read_all_frames(input).unwrap();
        // Collective write rebuilds each frame and stamps con_spec_minor.
        let serial: Vec<_> = serial
            .iter()
            .map(|frame| binding_rewrite_frame(frame).unwrap())
            .collect();
        let ser_path = format!("{}.serial", a[2]);
        let t1 = Instant::now();
        {
            let mut w = ConFrameWriter::from_path(&ser_path).unwrap();
            for f in &serial {
                w.write_frame(f).unwrap();
            }
            w.flush().unwrap();
        }
        let ds = t1.elapsed().as_secs_f64() * 1e3;
        let m = std::fs::read(&out_mpi).unwrap();
        let s = std::fs::read(&ser_path).unwrap();
        let text = std::str::from_utf8(&m).unwrap();
        let side_ok = match read_sidecar(Path::new(&out_mpi)).unwrap() {
            Some(idx) => idx == FrameIndex::scan(text).unwrap(),
            None => serial.is_empty(),
        };
        let same = m == s && total as usize == m.len();
        println!(
            "ranks={} mode={} frames={} bytes={} write_ms={dt:.1} serial_write_ms={ds:.1} identical={same} sidecar_ok={side_ok}",
            comm.size(),
            a[3],
            rf.n_total,
            m.len()
        );
        if !(same && side_ok) {
            std::process::exit(1);
        }
    }
}
