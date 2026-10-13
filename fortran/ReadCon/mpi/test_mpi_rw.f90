! mpirun -n N test_mpi_rw IN OUT
! Distributed read of IN through the mpi_f08 interface, collective write
! to OUT.f08 (MPI-IO) and, through the INTEGER interface on a split
! communicator, to OUT.fint (gather). Rank 0 writes OUT.serial with the
! serial writer; compare the three with sha256sum.
program test_mpi_rw
  use, intrinsic :: iso_c_binding, only: c_int64_t
  use mpi_f08
  use readcon
  use readcon_mpi
  implicit none
  type(MPI_Comm) :: comm, sub
  type(frame_t), allocatable :: mine(:), all(:)
  type(writer_t) :: w
  character(len=4096) :: inp, outp
  integer(c_int64_t) :: first, total, nb1, nb2, s
  integer :: rank, nranks, stat, i, ierr, fsub
  call MPI_Init()
  call get_command_argument(1, inp)
  call get_command_argument(2, outp)
  call MPI_Comm_dup(MPI_COMM_WORLD, comm)
  call MPI_Comm_rank(comm, rank)
  call MPI_Comm_size(comm, nranks)

  call mpi_read_block(comm, trim(inp), mine, first, total, stat, n_threads=2)
  call check(stat == 0, 'read')
  s = size(mine, kind=c_int64_t)
  call MPI_Allreduce(MPI_IN_PLACE, s, 1, MPI_INTEGER8, MPI_SUM, comm, ierr)
  call check(s == total, 'blocks cover all frames')

  call mpi_write_block(comm, trim(outp)//'.f08', mine, stat, &
                       mode=rkr_mpi_write_mpiio, total=nb1)
  call check(stat == 0, 'f08 write')

  ! Legacy INTEGER handle, on a communicator that is not the world.
  call MPI_Comm_split(comm, 0, rank, sub)
  fsub = sub%MPI_VAL
  call mpi_write_block(fsub, trim(outp)//'.fint', mine, stat, &
                       mode=rkr_mpi_write_gather, total=nb2)
  call check(stat == 0 .and. nb1 == nb2, 'fint write')

  ! An unreadable path fails on every rank.
  do i = 1, size(mine)
    call mine(i)%free()
  end do
  call mpi_read_block(sub, '/nonexistent/x.con', mine, first, total, stat)
  call check(stat /= 0 .and. size(mine) == 0, 'collective failure')

  if (rank == 0) then
    all = read_all_frames(trim(inp))
    w = open_writer(trim(outp)//'.serial')
    call check(w%valid(), 'serial writer')
    do i = 1, size(all)
      call check(w%extend_one(all(i)) == rkr_status_success, 'serial extend')
      call all(i)%free()
    end do
    call w%free()
    print '(a,i0,a,i0,a)', 'test_mpi_rw ok on ', nranks, ' ranks, ', nb1, ' bytes'
  end if
  call MPI_Comm_free(sub)
  call MPI_Comm_free(comm)
  call MPI_Finalize()
contains
  subroutine check(ok, what)
    logical, intent(in) :: ok
    character(len=*), intent(in) :: what
    if (.not. ok) then
      print '(a,a)', 'check failed: ', what
      call MPI_Abort(MPI_COMM_WORLD, 1)
    end if
  end subroutine
end program
