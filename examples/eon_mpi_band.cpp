// eOn-style use of the MPI bindings: an NEB band where each rank owns a
// contiguous block of images.
//
//   mpicxx -std=c++17 -Iinclude examples/eon_mpi_band.cpp
//          -Ltarget/debug -lreadcon_core -o eon_mpi_band
//   mpirun -n 4 ./eon_mpi_band neb.con band_out.con
//
// The host owns MPI (init, finalize, and which communicator to use);
// readcon only sees the communicator it is handed. eOn would pass its
// band communicator here instead of a duplicate of the world.
//
// Rank 0 also writes `band_out.con.serial` with the serial C writer, so
// `sha256sum band_out.con band_out.con.serial` checks the round trip.
#include "readcon-core-mpi.h"

#include <cstdio>

int main(int argc, char **argv) {
  MPI_Init(&argc, &argv);
  if (argc != 3) {
    std::fprintf(stderr, "usage: %s IN.con OUT.con\n", argv[0]);
    MPI_Abort(MPI_COMM_WORLD, 2);
  }
  MPI_Comm band;
  MPI_Comm_dup(MPI_COMM_WORLD, &band);
  int rank = 0;
  MPI_Comm_rank(band, &rank);
  int rc = 0;
  try {
    // Each rank parses only its images (block partition, rank order).
    auto images = readcon::mpi::Frames::read(band, argv[1]);
    std::printf("rank %d: images [%llu, %llu) of %llu\n", rank,
                (unsigned long long)images.first(),
                (unsigned long long)(images.first() + images.size()),
                (unsigned long long)images.total());

    // ... a force call per local image would go here ...

    // Write the band back in image order, collectively.
    uint64_t bytes = readcon::mpi::write(band, argv[2], images,
                                         RKR_MPI_WRITE_MPIIO);

    if (rank == 0) {
      size_t n = 0;
      readcon::RKRConFrame **all = readcon::rkr_read_all_frames(argv[1], &n);
      std::string ser = std::string(argv[2]) + ".serial";
      readcon::RKRConFrameWriter *w = readcon::create_writer_from_path_c(ser.c_str());
      if (all == nullptr || w == nullptr ||
          readcon::rkr_writer_extend(w, all, n) != readcon::RKR_STATUS_SUCCESS)
        throw std::runtime_error("serial reference write failed");
      readcon::free_rkr_writer(w);
      readcon::free_rkr_frame_array(all, n);
      std::printf("wrote %llu bytes, %zu images\n", (unsigned long long)bytes,
                  n);
    }
  } catch (const std::exception &e) {
    std::fprintf(stderr, "rank %d: %s\n", rank, e.what());
    rc = 1;
  }
  MPI_Comm_free(&band);
  MPI_Finalize();
  return rc;
}
