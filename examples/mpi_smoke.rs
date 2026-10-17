//! `mpirun -n N target/debug/examples/mpi_smoke`: checks the comm
//! conventions on N ranks and exits non-zero on any mismatch.
use mpi::traits::*;
use readcon_core::distrib::{Comm, block_range};

fn main() {
    let universe = mpi::initialize().expect("MPI already initialized");
    let world = universe.world();
    // The host owns `world`; the library only ever sees a duplicate.
    let comm = Comm::dup_of(&world);
    let (rank, size) = (comm.rank(), comm.size());
    assert_eq!(rank as i32, world.rank());

    // Every rank agrees on the partition and the blocks tile 0..n.
    for n in [0usize, 1, 7, 1000] {
        let mine = comm.my_frames(n);
        assert_eq!(mine, block_range(n, size, rank));
        let mut total = 0u64;
        world.all_reduce_into(
            &((mine.end - mine.start) as u64),
            &mut total,
            mpi::collective::SystemOperation::sum(),
        );
        assert_eq!(total as usize, n);
    }

    // Broadcast from every root, including an empty blob.
    for root in 0..size {
        let payload: Vec<u8> = (0..(root * 37) as u32).map(|x| (x % 251) as u8).collect();
        let got = comm.bcast_bytes(root, if rank == root { &payload } else { &[] });
        assert_eq!(got, payload);
    }

    // The Fortran-handle entry point sees the same size and rank.
    let (mut s, mut r) = (0i32, 0i32);
    let f = unsafe { mpi::ffi::RSMPI_Comm_c2f(world.as_raw()) };
    let rc = unsafe { readcon_core::distrib::rkr_mpi_comm_info_f(f, &mut s, &mut r) };
    assert_eq!((rc, s as usize, r as usize), (0, size, rank));

    world.barrier();
    if rank == 0 {
        println!("mpi_smoke ok on {size} ranks");
    }
}
