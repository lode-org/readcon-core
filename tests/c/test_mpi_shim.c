/* mpicc -Iinclude tests/c/test_mpi_shim.c -Ltarget/debug -lreadcon_core
 * then mpirun -n N ./a.out. Uses a Split sub-communicator on purpose so
 * the shim is exercised on something other than the world handle. */
#include "readcon-core-mpi.h"
#include <stdio.h>
#include <string.h>

#define CHECK(c)                                                               \
  do {                                                                         \
    if (!(c)) {                                                                \
      fprintf(stderr, "check failed line %d: %s\n", __LINE__, #c);             \
      MPI_Abort(MPI_COMM_WORLD, 1);                                            \
    }                                                                          \
  } while (0)

int main(int argc, char **argv) {
  MPI_Init(&argc, &argv);
  int wrank, wsize;
  MPI_Comm_rank(MPI_COMM_WORLD, &wrank);
  MPI_Comm_size(MPI_COMM_WORLD, &wsize);
  MPI_Comm sub;
  MPI_Comm_split(MPI_COMM_WORLD, 0, wsize - wrank, &sub); /* reversed order */
  int rank, size;
  MPI_Comm_rank(sub, &rank);
  MPI_Comm_size(sub, &size);

  uint64_t s, e, total = 0, mine;
  CHECK(rkr_mpi_my_frames(sub, 1001, &s, &e) == RKR_MPI_OK);
  mine = e - s;
  MPI_Allreduce(&mine, &total, 1, MPI_UINT64_T, MPI_SUM, sub);
  CHECK(total == 1001);
  CHECK(rkr_mpi_my_frames_f(MPI_Comm_c2f(sub), 1001, &s, &e) == RKR_MPI_OK);
  CHECK(e - s == mine);

  for (int root = 0; root < size; ++root) {
    uint8_t src[300];
    int64_t n = root * 50;
    for (int i = 0; i < 300; ++i)
      src[i] = (uint8_t)(i * 7 + root);
    uint8_t *out = NULL;
    int64_t got = -1;
    CHECK(rkr_mpi_bcast_blob(sub, root, 0, rank == root ? src : NULL,
                             rank == root ? n : 0, &out, &got) == RKR_MPI_OK);
    CHECK(got == n);
    CHECK(n == 0 ? out == NULL : memcmp(out, src, (size_t)n) == 0);
    free(out);
  }

  /* A root-side error reaches every rank and nobody gets a buffer. */
  uint8_t *out = (uint8_t *)1;
  int64_t got = 0;
  CHECK(rkr_mpi_bcast_blob_f(MPI_Comm_c2f(sub), 0, -42, NULL, 0, &out, &got) ==
        -42);
  CHECK(out == NULL);

  MPI_Comm_free(&sub);
  if (wrank == 0)
    printf("test_mpi_shim ok on %d ranks\n", wsize);
  MPI_Finalize();
  return 0;
}
