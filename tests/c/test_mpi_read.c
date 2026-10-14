/* mpirun -n N ./test_mpi_read FILE: rkr_mpi_read_block over the C ABI.
 * Needs libreadcon_core built with the `mpi` feature. Checks that the
 * blocks tile [0, total) in rank order in every mode, that the total
 * matches the serial reader, and that a bad path fails on every rank. */
#include "readcon-core-mpi.h"
#include <stdio.h>

#define CHECK(c)                                                               \
  do {                                                                         \
    if (!(c)) {                                                                \
      fprintf(stderr, "check failed line %d: %s\n", __LINE__, #c);             \
      MPI_Abort(MPI_COMM_WORLD, 1);                                            \
    }                                                                          \
  } while (0)

int main(int argc, char **argv) {
  MPI_Init(&argc, &argv);
  CHECK(argc == 2);
  MPI_Comm sub;
  MPI_Comm_dup(MPI_COMM_WORLD, &sub);
  int rank, size;
  MPI_Comm_rank(sub, &rank);
  MPI_Comm_size(sub, &size);

  size_t n_serial = 0;
  struct RKRConFrame **serial = rkr_read_all_frames(argv[1], &n_serial);
  CHECK(serial != NULL);
  free_rkr_frame_array(serial, n_serial);

  int modes[] = {RKR_MPI_READ_AUTO, RKR_MPI_READ_SHARED, RKR_MPI_READ_SCATTER};
  for (int m = 0; m < 3; ++m) {
    size_t n = 0;
    uint64_t first = 0, total = 0, s = 0, e = 0;
    struct RKRConFrame **fr =
        rkr_mpi_read_block(sub, argv[1], modes[m], 2, &n, &first, &total);
    CHECK(fr != NULL);
    CHECK(total == n_serial);
    CHECK(rkr_mpi_my_frames(sub, total, &s, &e) == RKR_MPI_OK);
    CHECK(first == s && first + n == e);
    uint64_t sum = 0, mine = n;
    MPI_Allreduce(&mine, &sum, 1, MPI_UINT64_T, MPI_SUM, sub);
    CHECK(sum == total);
    free_rkr_frame_array(fr, n);
  }

  size_t n = 7;
  uint64_t first = 0, total = 0;
  const char *bad = rank == size - 1 ? "/nonexistent/x.con" : argv[1];
  CHECK(rkr_mpi_read_block_f(MPI_Comm_c2f(sub), bad, RKR_MPI_READ_SHARED, 0,
                             &n, &first, &total) == NULL);

  MPI_Comm_free(&sub);
  if (rank == 0)
    printf("test_mpi_read ok on %d ranks, %zu frames\n", size, n_serial);
  MPI_Finalize();
  return 0;
}
