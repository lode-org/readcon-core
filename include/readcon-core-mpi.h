#ifndef READCON_CORE_MPI_H
#define READCON_CORE_MPI_H

/*
 * Shared MPI shim for readcon-core and its dependants (readcon-db,
 * readcon-ops, eOn, LAMMPS plugins, mpi4py extensions).
 *
 * Header-only: it is compiled in the caller's translation unit against
 * the caller's MPI, so libreadcon_core never hard-links an MPI ABI.
 *
 * Contract (every helper here and every future readcon MPI entry point):
 *   - `comm` is the caller's communicator (a LAMMPS world or sub-comm, an
 *     mpi4py Comm, a Split or Dup). Nothing here names the process-wide
 *     world communicator.
 *   - Nothing here calls MPI_Init or MPI_Finalize.
 *   - Each `*_f` variant takes a Fortran INTEGER handle (MPI_Fint) and
 *     converts it with MPI_Comm_f2c.
 *   - Frame ownership is the block partition from rkr_block_range: the
 *     same pure function of (n_frames, n_ranks, rank) on every rank.
 *   - Failures are collective: if any rank fails, every rank returns the
 *     same negative code and owns no buffer.
 */

#include "readcon-core.h"

#include <mpi.h>
#include <stdint.h>
#include <stdlib.h>

#define RKR_MPI_OK 0
#define RKR_MPI_ERR_NULL (-1)
#define RKR_MPI_ERR_MPI (-2)
#define RKR_MPI_ERR_ALLOC (-3)
#define RKR_MPI_ERR_TOO_BIG (-4)

#define RKR_MPI_READ_AUTO 0    /* scatter for gzip/zstd, shared otherwise */
#define RKR_MPI_READ_SHARED 1  /* every rank maps the file, uses .rcidx */
#define RKR_MPI_READ_SCATTER 2 /* rank 0 reads, MPI_Scatterv per block */

#ifdef __cplusplus
extern "C" {
#endif

/* Exported by libreadcon_core (no MPI needed). Writes [*start, *end). */
int rkr_block_range(uint64_t n_frames, uint32_t n_ranks, uint32_t rank,
                    uint64_t *start, uint64_t *end);

/*
 * Exported by libreadcon_core built with the `mpi` feature.
 * Reads this rank's block of frames (block partition of the whole file).
 * Concatenating every rank's frames in rank order gives the serial read.
 * Collective: returns NULL on every rank if any rank fails. Free the
 * result with free_rkr_frame_array(frames, *num_frames).
 */
struct RKRConFrame **rkr_mpi_read_block_f(MPI_Fint comm_f, const char *path,
                                          int mode, size_t n_threads,
                                          size_t *num_frames,
                                          uint64_t *first_frame,
                                          uint64_t *total_frames);

static inline struct RKRConFrame **
rkr_mpi_read_block(MPI_Comm comm, const char *path, int mode, size_t n_threads,
                   size_t *num_frames, uint64_t *first_frame,
                   uint64_t *total_frames) {
  return rkr_mpi_read_block_f(MPI_Comm_c2f(comm), path, mode, n_threads,
                              num_frames, first_frame, total_frames);
}

/**
 * Broadcast a byte blob from `root` of `comm`.
 *
 * On `root`, `root_status` is the producer's result (negative to abort
 * collectively) and `root_buf`/`root_nbytes` the blob; both are ignored
 * elsewhere. On success every rank gets a malloc'd copy in *out_buf
 * (caller free(); NULL when the blob is empty) and RKR_MPI_OK.
 *
 * This is the pattern readcon-db's rkrdb_bcast_packed_frame(s) use:
 * bcast the size or error, allocate, agree that everyone allocated,
 * then bcast the bytes.
 */
static inline int rkr_mpi_bcast_blob(MPI_Comm comm, int root, int root_status,
                                     const uint8_t *root_buf,
                                     int64_t root_nbytes, uint8_t **out_buf,
                                     int64_t *out_nbytes) {
  int rank = 0;
  int64_t n = 0;
  uint8_t *buf = NULL;
  int ok = 1, all_ok = 0;

  if (out_buf == NULL || out_nbytes == NULL)
    return RKR_MPI_ERR_NULL;
  *out_buf = NULL;
  *out_nbytes = 0;
  if (MPI_Comm_rank(comm, &rank) != MPI_SUCCESS)
    return RKR_MPI_ERR_MPI;

  if (rank == root) {
    if (root_status < 0)
      n = root_status;
    else if (root_nbytes < 0 || (root_nbytes > 0 && root_buf == NULL))
      n = RKR_MPI_ERR_NULL;
    else if (root_nbytes > INT32_MAX)
      n = RKR_MPI_ERR_TOO_BIG;
    else
      n = root_nbytes;
  }
  if (MPI_Bcast(&n, 1, MPI_INT64_T, root, comm) != MPI_SUCCESS)
    return RKR_MPI_ERR_MPI;
  if (n < 0)
    return (int)n;

  if (n > 0) {
    buf = (uint8_t *)malloc((size_t)n);
    ok = buf != NULL;
    if (ok && rank == root) {
      for (int64_t i = 0; i < n; ++i)
        buf[i] = root_buf[i];
    }
  }
  if (MPI_Allreduce(&ok, &all_ok, 1, MPI_INT, MPI_MIN, comm) != MPI_SUCCESS) {
    free(buf);
    return RKR_MPI_ERR_MPI;
  }
  if (!all_ok) {
    free(buf);
    return RKR_MPI_ERR_ALLOC;
  }
  if (n > 0 &&
      MPI_Bcast(buf, (int)n, MPI_BYTE, root, comm) != MPI_SUCCESS) {
    free(buf);
    return RKR_MPI_ERR_MPI;
  }
  *out_buf = buf;
  *out_nbytes = n;
  return RKR_MPI_OK;
}

static inline int rkr_mpi_bcast_blob_f(MPI_Fint comm_f, int root,
                                       int root_status,
                                       const uint8_t *root_buf,
                                       int64_t root_nbytes, uint8_t **out_buf,
                                       int64_t *out_nbytes) {
  return rkr_mpi_bcast_blob(MPI_Comm_f2c(comm_f), root, root_status, root_buf,
                            root_nbytes, out_buf, out_nbytes);
}

/** This rank's block of frames on `comm`. */
static inline int rkr_mpi_my_frames(MPI_Comm comm, uint64_t n_frames,
                                    uint64_t *start, uint64_t *end) {
  int rank = 0, size = 0;
  if (MPI_Comm_rank(comm, &rank) != MPI_SUCCESS ||
      MPI_Comm_size(comm, &size) != MPI_SUCCESS)
    return RKR_MPI_ERR_MPI;
  return rkr_block_range(n_frames, (uint32_t)size, (uint32_t)rank, start, end)
             ? RKR_MPI_ERR_NULL
             : RKR_MPI_OK;
}

static inline int rkr_mpi_my_frames_f(MPI_Fint comm_f, uint64_t n_frames,
                                      uint64_t *start, uint64_t *end) {
  return rkr_mpi_my_frames(MPI_Comm_f2c(comm_f), n_frames, start, end);
}

#ifdef __cplusplus
} /* extern "C" */

namespace readcon {
inline int mpi_bcast_blob(MPI_Comm comm, int root, int root_status,
                          const uint8_t *root_buf, int64_t root_nbytes,
                          uint8_t **out_buf, int64_t *out_nbytes) {
  return rkr_mpi_bcast_blob(comm, root, root_status, root_buf, root_nbytes,
                            out_buf, out_nbytes);
}
inline int mpi_my_frames(MPI_Comm comm, uint64_t n_frames, uint64_t *start,
                         uint64_t *end) {
  return rkr_mpi_my_frames(comm, n_frames, start, end);
}
} // namespace readcon
#endif /* __cplusplus */

#endif /* READCON_CORE_MPI_H */
