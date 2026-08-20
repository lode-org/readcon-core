program print_neb_band
  use readcon
  use, intrinsic :: iso_fortran_env, only: real64
  implicit none
  character(len=1024) :: path, root
  integer :: nlen, ierr, i
  type(frame_t), allocatable :: frames(:)
  logical :: ok

  if (command_argument_count() >= 1) then
    call get_command_argument(1, path)
  else
    call get_environment_variable("READCON_CORE_ROOT", root, length=nlen, status=ierr)
    if (ierr /= 0 .or. nlen == 0) root = "../../.."
    path = trim(root) // "/resources/examples/neb_band.con"
  end if

  inquire(file=trim(path), exist=ok)
  if (.not. ok) then
    print *, "missing ", trim(path)
    error stop "neb_band.con not found"
  end if

  frames = read_all_frames(trim(path))
  if (.not. allocated(frames) .or. size(frames) < 1) then
    error stop "read_all_frames returned no frames"
  end if

  print '(a,1x,a,1x,a,i0)', "#", trim(path), "n_frames=", size(frames)
  print '(a)', "bead	energy_eV	fmax"
  do i = 1, size(frames)
    print '(i0,1x,f0.6,1x,f0.6)', int(frames(i)%neb_bead()), frames(i)%energy(), frames(i)%fmax()
    call frames(i)%free()
  end do
end program print_neb_band
