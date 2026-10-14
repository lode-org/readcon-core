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

/* Open MPI and MPICH include the deprecated C++ bindings from mpi.h.
 * Those headers fail -Werror=cast-function-type on current g++. This
 * shim uses the C API only. */
#ifdef __cplusplus
#ifndef OMPI_SKIP_MPICXX
#define OMPI_SKIP_MPICXX 1
#endif
#ifndef MPICH_SKIP_MPICXX
#define MPICH_SKIP_MPICXX 1
#endif
#endif
#include <mpi.h>

#ifdef __cplusplus
/* readcon-core.h puts its C types in namespace readcon under C++. */
using readcon::RKRConFrame;
#endif
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

#define RKR_MPI_WRITE_AUTO 0   /* currently MPI-IO */
#define RKR_MPI_WRITE_MPIIO 1  /* Exscan offsets + MPI_File_write_at_all */
#define RKR_MPI_WRITE_GATHER 2 /* rank 0 gathers and writes (no MPI-IO) */

/*
 * Exported by libreadcon_core built with the `mpi` feature.
 * Writes every rank's frames to `path` in rank order; the bytes equal a
 * serial write of the concatenated frames. Ranks may pass zero frames
 * (frames may then be NULL). precision < 0 uses the writer default.
 * Also writes the checked `path.rcidx` sidecar (best effort).
 * Collective: returns 0 on every rank or -1 on every rank.
 */
int rkr_mpi_write_block_f(MPI_Fint comm_f, const char *path,
                          const struct RKRConFrame *const *frames,
                          size_t num_frames, int mode, int precision,
                          uint64_t *total_bytes);

static inline int rkr_mpi_write_block(MPI_Comm comm, const char *path,
                                      const struct RKRConFrame *const *frames,
                                      size_t num_frames, int mode,
                                      int precision, uint64_t *total_bytes) {
  return rkr_mpi_write_block_f(MPI_Comm_c2f(comm), path, frames, num_frames,
                               mode, precision, total_bytes);
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

#include <cstddef>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

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

namespace mpi {

/* This rank's block of frames from a distributed read. Owns the frame
 * handles and frees them on destruction; move-only. */
class Frames {
public:
  Frames() = default;
  Frames(const Frames &) = delete;
  Frames &operator=(const Frames &) = delete;
  Frames(Frames &&o) noexcept { swap(o); }
  Frames &operator=(Frames &&o) noexcept {
    if (this != &o) {
      reset();
      swap(o);
    }
    return *this;
  }
  ~Frames() { reset(); }

  /* Collective over `comm`; throws std::runtime_error on every rank if
   * any rank fails. */
  static Frames read(MPI_Comm comm, const std::string &path,
                     int mode = RKR_MPI_READ_AUTO, std::size_t n_threads = 0) {
    Frames f;
    f.frames_ = rkr_mpi_read_block(comm, path.c_str(), mode, n_threads, &f.n_,
                                   &f.first_, &f.total_);
    if (f.frames_ == nullptr)
      throw std::runtime_error("readcon: distributed read failed: " + path);
    return f;
  }

  std::size_t size() const { return n_; }
  bool empty() const { return n_ == 0; }
  /* Global index of frame 0 of this rank, and the total across ranks. */
  uint64_t first() const { return first_; }
  uint64_t total() const { return total_; }
  const RKRConFrame *operator[](std::size_t i) const { return frames_[i]; }
  const RKRConFrame *const *data() const {
    return const_cast<const RKRConFrame *const *>(frames_);
  }
  const RKRConFrame *const *begin() const { return data(); }
  const RKRConFrame *const *end() const { return data() + n_; }

  void reset() {
    if (frames_ != nullptr)
      free_rkr_frame_array(frames_, n_);
    frames_ = nullptr;
    n_ = 0;
    first_ = total_ = 0;
  }

private:
  void swap(Frames &o) noexcept {
    std::swap(frames_, o.frames_);
    std::swap(n_, o.n_);
    std::swap(first_, o.first_);
    std::swap(total_, o.total_);
  }
  RKRConFrame **frames_ = nullptr;
  std::size_t n_ = 0;
  uint64_t first_ = 0;
  uint64_t total_ = 0;
};

/* Collective write of every rank's frames in rank order; returns the
 * file size. Throws std::runtime_error on every rank if any rank fails. */
inline uint64_t write(MPI_Comm comm, const std::string &path,
                      const RKRConFrame *const *frames, std::size_t n,
                      int mode = RKR_MPI_WRITE_AUTO, int precision = -1) {
  uint64_t total = 0;
  if (rkr_mpi_write_block(comm, path.c_str(), frames, n, mode, precision,
                          &total) != 0)
    throw std::runtime_error("readcon: collective write failed: " + path);
  return total;
}

inline uint64_t write(MPI_Comm comm, const std::string &path,
                      const Frames &frames, int mode = RKR_MPI_WRITE_AUTO,
                      int precision = -1) {
  return write(comm, path, frames.data(), frames.size(), mode, precision);
}

inline uint64_t write(MPI_Comm comm, const std::string &path,
                      const std::vector<const RKRConFrame *> &frames,
                      int mode = RKR_MPI_WRITE_AUTO, int precision = -1) {
  return write(comm, path, frames.data(), frames.size(), mode, precision);
}

} // namespace mpi
} // namespace readcon
#endif /* __cplusplus */

#endif /* READCON_CORE_MPI_H */
