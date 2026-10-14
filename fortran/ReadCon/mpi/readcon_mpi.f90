! readcon_mpi: distributed read and collective write over a communicator
! the host passes in. Build with an MPI Fortran compiler (mpifort) next to
! module readcon, linking libreadcon_core built with the `mpi` feature.
!
! Every procedure accepts either an mpi_f08 type(MPI_Comm) or a legacy
! INTEGER communicator (MPI_Fint). The module never calls MPI_Init or
! MPI_Finalize and never assumes MPI_COMM_WORLD.
!
! Ownership follows readcon: frames from mpi_read_block are owned by the
! caller (call frames(i)%free()). Both calls are collective; on failure
! stat is nonzero on every rank.
module readcon_mpi
  use, intrinsic :: iso_c_binding
  use mpi_f08, only: MPI_Comm
  use readcon, only: frame_t, frames_from_handle_array, frame_c_handle
  implicit none
  private

  public :: mpi_read_block, mpi_write_block
  public :: rkr_mpi_read_auto, rkr_mpi_read_shared, rkr_mpi_read_scatter
  public :: rkr_mpi_write_auto, rkr_mpi_write_mpiio, rkr_mpi_write_gather

  ! Mirror include/readcon-core-mpi.h
  integer(c_int), parameter :: rkr_mpi_read_auto = 0
  integer(c_int), parameter :: rkr_mpi_read_shared = 1
  integer(c_int), parameter :: rkr_mpi_read_scatter = 2
  integer(c_int), parameter :: rkr_mpi_write_auto = 0
  integer(c_int), parameter :: rkr_mpi_write_mpiio = 1
  integer(c_int), parameter :: rkr_mpi_write_gather = 2

  interface mpi_read_block
    module procedure read_block_fint, read_block_f08
  end interface

  interface mpi_write_block
    module procedure write_block_fint, write_block_f08
  end interface

  interface
    function c_rkr_mpi_read_block_f(comm_f, path, mode, n_threads, n, first, &
                                    total) bind(C, name="rkr_mpi_read_block_f")
      import :: c_int, c_char, c_size_t, c_ptr, c_int64_t
      integer(c_int), value :: comm_f
      character(kind=c_char), intent(in) :: path(*)
      integer(c_int), value :: mode
      integer(c_size_t), value :: n_threads
      integer(c_size_t), intent(out) :: n
      integer(c_int64_t), intent(out) :: first, total
      type(c_ptr) :: c_rkr_mpi_read_block_f
    end function

    integer(c_int) function c_rkr_mpi_write_block_f(comm_f, path, frames, n, &
        mode, precision, total) bind(C, name="rkr_mpi_write_block_f")
      import :: c_int, c_char, c_size_t, c_ptr, c_int64_t
      integer(c_int), value :: comm_f
      character(kind=c_char), intent(in) :: path(*)
      type(c_ptr), value :: frames
      integer(c_size_t), value :: n
      integer(c_int), value :: mode, precision
      integer(c_int64_t), intent(out) :: total
    end function
  end interface

contains

  pure function to_c(s) result(c)
    character(len=*), intent(in) :: s
    character(kind=c_char) :: c(len_trim(s) + 1)
    integer :: i
    do i = 1, len_trim(s)
      c(i) = s(i:i)
    end do
    c(len_trim(s) + 1) = c_null_char
  end function

  !> Read this rank's block of frames. `first` is the 0-based global index
  !> of frames(1), `total` the frame count over all ranks.
  subroutine read_block_fint(comm, path, frames, first, total, stat, mode, &
                             n_threads)
    integer, intent(in) :: comm
    character(len=*), intent(in) :: path
    type(frame_t), allocatable, intent(out) :: frames(:)
    integer(c_int64_t), intent(out) :: first, total
    integer, intent(out) :: stat
    integer, intent(in), optional :: mode, n_threads
    integer(c_int) :: m
    integer(c_size_t) :: nt, n
    type(c_ptr) :: arr
    m = rkr_mpi_read_auto
    if (present(mode)) m = int(mode, c_int)
    nt = 0_c_size_t
    if (present(n_threads)) nt = int(max(n_threads, 0), c_size_t)
    arr = c_rkr_mpi_read_block_f(int(comm, c_int), to_c(path), m, nt, n, &
                                 first, total)
    if (.not. c_associated(arr)) then
      allocate(frames(0))
      first = 0
      total = 0
      stat = 1
      return
    end if
    frames = frames_from_handle_array(arr, n)
    stat = 0
  end subroutine

  subroutine read_block_f08(comm, path, frames, first, total, stat, mode, &
                            n_threads)
    type(MPI_Comm), intent(in) :: comm
    character(len=*), intent(in) :: path
    type(frame_t), allocatable, intent(out) :: frames(:)
    integer(c_int64_t), intent(out) :: first, total
    integer, intent(out) :: stat
    integer, intent(in), optional :: mode, n_threads
    call read_block_fint(comm%MPI_VAL, path, frames, first, total, stat, &
                         mode, n_threads)
  end subroutine

  !> Write every rank's frames to `path` in rank order. `total` is the
  !> file size in bytes. A rank may pass a zero-length array.
  subroutine write_block_fint(comm, path, frames, stat, mode, precision, total)
    integer, intent(in) :: comm
    character(len=*), intent(in) :: path
    type(frame_t), intent(in) :: frames(:)
    integer, intent(out) :: stat
    integer, intent(in), optional :: mode, precision
    integer(c_int64_t), intent(out), optional :: total
    type(c_ptr), allocatable, target :: handles(:)
    type(c_ptr) :: p
    integer(c_int) :: m, prec
    integer(c_int64_t) :: t
    integer :: i
    m = rkr_mpi_write_auto
    if (present(mode)) m = int(mode, c_int)
    prec = -1
    if (present(precision)) prec = int(precision, c_int)
    allocate(handles(max(size(frames), 1)))
    do i = 1, size(frames)
      handles(i) = frame_c_handle(frames(i))
    end do
    p = c_null_ptr
    if (size(frames) > 0) p = c_loc(handles(1))
    stat = c_rkr_mpi_write_block_f(int(comm, c_int), to_c(path), p, &
                                   int(size(frames), c_size_t), m, prec, t)
    stat = abs(stat)
    if (present(total)) total = t
  end subroutine

  subroutine write_block_f08(comm, path, frames, stat, mode, precision, total)
    type(MPI_Comm), intent(in) :: comm
    character(len=*), intent(in) :: path
    type(frame_t), intent(in) :: frames(:)
    integer, intent(out) :: stat
    integer, intent(in), optional :: mode, precision
    integer(c_int64_t), intent(out), optional :: total
    call write_block_fint(comm%MPI_VAL, path, frames, stat, mode, precision, &
                          total)
  end subroutine

end module readcon_mpi
