/* mpirun -n N ./test_mpi_write IN OUT: distributed read of IN, then
 * rkr_mpi_write_block to OUT.mpiio and OUT.gather; rank 0 compares both
 * against a serial write. Needs libreadcon_core with the `mpi` feature. */
#include "readcon-core-mpi.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHECK(c)                                                               \
  do {                                                                         \
    if (!(c)) {                                                                \
      fprintf(stderr, "check failed line %d: %s\n", __LINE__, #c);             \
      MPI_Abort(MPI_COMM_WORLD, 1);                                            \
    }                                                                          \
  } while (0)

static char *slurp(const char *p, long *n) {
  FILE *f = fopen(p, "rb");
  CHECK(f != NULL);
  fseek(f, 0, SEEK_END);
  *n = ftell(f);
  fseek(f, 0, SEEK_SET);
  char *b = (char *)malloc((size_t)*n + 1);
  CHECK(fread(b, 1, (size_t)*n, f) == (size_t)*n);
  fclose(f);
  return b;
}

int main(int argc, char **argv) {
  MPI_Init(&argc, &argv);
  CHECK(argc == 3);
  MPI_Comm sub;
  MPI_Comm_dup(MPI_COMM_WORLD, &sub);
  int rank;
  MPI_Comm_rank(sub, &rank);

  size_t n = 0;
  uint64_t first = 0, total = 0;
  struct RKRConFrame **fr = rkr_mpi_read_block(sub, argv[1], RKR_MPI_READ_AUTO,
                                               0, &n, &first, &total);
  CHECK(fr != NULL);

  char out[2][4096];
  int modes[2] = {RKR_MPI_WRITE_MPIIO, RKR_MPI_WRITE_GATHER};
  snprintf(out[0], sizeof out[0], "%s.mpiio", argv[2]);
  snprintf(out[1], sizeof out[1], "%s.gather", argv[2]);
  uint64_t bytes[2] = {0, 0};
  for (int m = 0; m < 2; ++m)
    CHECK(rkr_mpi_write_block(sub, out[m],
                              (const struct RKRConFrame *const *)fr, n,
                              modes[m], -1, &bytes[m]) == 0);
  CHECK(bytes[0] == bytes[1]);

  /* An unwritable path fails on every rank. */
  uint64_t junk = 0;
  CHECK(rkr_mpi_write_block_f(MPI_Comm_c2f(sub), "/nonexistent/dir/x.con",
                              (const struct RKRConFrame *const *)fr, n,
                              RKR_MPI_WRITE_GATHER, -1, &junk) == -1);
  free_rkr_frame_array(fr, n);

  if (rank == 0) {
    size_t ns = 0;
    struct RKRConFrame **s = rkr_read_all_frames(argv[1], &ns);
    CHECK(s != NULL && ns == total);
    char sp[4096];
    snprintf(sp, sizeof sp, "%s.serial", argv[2]);
    struct RKRConFrameWriter *w = create_writer_from_path_c(sp);
    CHECK(w != NULL);
    /* Collective write rebuilds frames and stamps con_spec_minor. */
    struct RKRConFrame **rebuilt = (struct RKRConFrame **)calloc(ns ? ns : 1, sizeof(*rebuilt));
    CHECK(rebuilt != NULL);
    for (size_t i = 0; i < ns; i++) {
      rebuilt[i] = rkr_frame_binding_rewrite(s[i]);
      CHECK(rebuilt[i] != NULL);
    }
    CHECK(rkr_writer_extend(w, (const struct RKRConFrame *const *)rebuilt, ns) ==
          RKR_STATUS_SUCCESS);
    for (size_t i = 0; i < ns; i++)
      free_rkr_frame(rebuilt[i]);
    free(rebuilt);
    free_rkr_writer(w);
    free_rkr_frame_array(s, ns);
    long a, b, c;
    char *x = slurp(sp, &a), *y = slurp(out[0], &b), *z = slurp(out[1], &c);
    CHECK(a == b && a == c && (uint64_t)a == bytes[0]);
    CHECK(memcmp(x, y, (size_t)a) == 0 && memcmp(x, z, (size_t)a) == 0);
    free(x);
    free(y);
    free(z);
    int size;
    MPI_Comm_size(sub, &size);
    printf("test_mpi_write ok on %d ranks, %llu bytes\n", size,
           (unsigned long long)bytes[0]);
  }
  MPI_Comm_free(&sub);
  MPI_Finalize();
  return 0;
}
