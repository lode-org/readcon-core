! Rewrite one CON file through the Fortran writer.
! read_all_frames + writer_t%extend_one rebuilds each frame, so the
! CON metadata line includes con_spec_minor.
program rewrite_corpus
  use readcon
  use, intrinsic :: iso_fortran_env, only: error_unit
  implicit none
  character(len=4096) :: in_path, out_path
  type(frame_t), allocatable :: frames(:)
  type(writer_t) :: writer
  integer :: argc, i, stat

  argc = command_argument_count()
  if (argc /= 2) then
    write (error_unit, *) "usage: rewrite_corpus input.con output.con"
    error stop 2
  end if
  call get_command_argument(1, in_path)
  call get_command_argument(2, out_path)

  frames = read_all_frames(trim(in_path))
  writer = open_writer(trim(out_path))
  if (.not. writer%valid()) then
    write (error_unit, *) "writer failed: ", trim(out_path)
    error stop 1
  end if
  do i = 1, size(frames)
    if (.not. frames(i)%valid()) then
      write (error_unit, *) "read failed: ", trim(in_path)
      error stop 1
    end if
    stat = writer%extend_one(frames(i))
    if (stat /= 0) then
      write (error_unit, *) "extend failed: ", stat
      error stop 1
    end if
    call frames(i)%free()
  end do
  call writer%free()
end program rewrite_corpus
