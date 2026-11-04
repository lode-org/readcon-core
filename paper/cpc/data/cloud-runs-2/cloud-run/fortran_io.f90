! Fortran round trip through the public ReadCon module.
!
! The writer builds every frame with builder%add_atom, the procedure a
! Fortran user calls, and passes velocities through its optional argument.
! Line 1 of each frame is "image N", as in the C, C++, Python and Julia
! writers.
!
!   fortran_io write BAND.txt DIR
!   fortran_io read  DIR BAND.txt
program fortran_io
  use, intrinsic :: iso_c_binding
  use, intrinsic :: iso_fortran_env, only: real64, int64
  use readcon
  implicit none
  character(len=16) :: mode
  character(len=1024) :: src, dst
  if (command_argument_count() /= 3) then
    write(0, *) "usage: fortran_io write|read SRC DST"
    stop 2
  end if
  call get_command_argument(1, mode)
  call get_command_argument(2, src)
  call get_command_argument(3, dst)
  if (trim(mode) == "write") then
    call do_write(trim(src), trim(dst))
  else if (trim(mode) == "read") then
    call do_read(trim(src), trim(dst))
  else
    write(0, *) "mode must be write or read"
    stop 2
  end if

contains

  subroutine die(msg)
    character(len=*), intent(in) :: msg
    write(0, *) msg
    error stop 1
  end subroutine

  subroutine do_write(band, dir)
    character(len=*), intent(in) :: band, dir
    integer :: u, stat, nframes, i, natoms, a, fx, fy, fz, hv, ios
    integer(int64) :: id
    real(real64) :: cell(3), angles(3), x, y, z, mass, vx, vy, vz
    character(len=16) :: tag, sym
    character(len=1024) :: meta, path
    character(len=8) :: idx
    character(len=32) :: pre
    type(builder_t) :: bld
    type(frame_t) :: fr
    type(writer_t) :: wr
    open(newunit=u, file=band, status="old", action="read", iostat=ios)
    if (ios /= 0) call die("cannot open band")
    read(u, *) tag, nframes
    if (tag /= "NFRAMES") call die("bad band header")
    call execute_command_line("mkdir -p "//dir, exitstat=stat)
    if (stat /= 0) call die("mkdir failed")
    open(newunit=stat, file=trim(dir)//"/manifest.txt", status="replace")
    write(stat, *) nframes
    close(stat)
    do i = 1, nframes
      read(u, *) tag
      if (tag /= "FRAME") call die("expected FRAME")
      read(u, *) tag, natoms
      read(u, *) tag, cell(1), cell(2), cell(3)
      read(u, *) tag, angles(1), angles(2), angles(3)
      read(u, *) tag, fx, fy, fz
      read(u, '(A)') meta
      if (meta(1:5) == "META ") meta = meta(6:)
      read(u, *) tag
      write(pre, '(A,1X,I0)') "image", i - 1
      bld = new_builder(cell, angles, header=trim(pre))
      if (.not. bld%valid()) call die("new_builder failed")
      stat = bld%set_metadata_json(trim(meta))
      if (stat /= 0) then
        write(0, *) "meta stat", stat
        call die("set_metadata_json failed")
      end if
      do a = 1, natoms
        read(u, *) sym, x, y, z, id, mass, fx, fy, fz, vx, vy, vz, hv
        if (hv /= 0) then
          stat = bld%add_atom(trim(sym), x, y, z, id, mass, fx /= 0, fy /= 0, fz /= 0, &
               velocity=[vx, vy, vz])
        else
          stat = bld%add_atom(trim(sym), x, y, z, id, mass, fx /= 0, fy /= 0, fz /= 0)
        end if
        if (stat /= 0) then
          write(0, *) "add stat", stat, trim(sym), id
          call die("builder%add_atom failed")
        end if
      end do
      read(u, *) tag
      fr = bld%build()
      if (.not. fr%valid()) call die("build failed")
      write(idx, '(I3.3)') i - 1
      path = trim(dir)//"/frame_"//trim(idx)//".con"
      wr = open_writer(trim(path))
      if (.not. wr%valid()) call die("open_writer failed")
      stat = wr%extend_one(fr)
      if (stat /= 0) write(0, *) "extend stat", stat, trim(path), " ", last_error_message()
      call wr%free()
      call fr%free()
      if (stat /= 0) call die("extend_one failed")
    end do
    close(u)
  end subroutine

  subroutine do_read(dir, band)
    character(len=*), intent(in) :: dir, band
    integer :: u, man, nframes, i, a, nat, ios
    character(len=8) :: idx
    character(len=1024) :: path
    character(len=:), allocatable :: sym, md
    type(frame_t), allocatable :: frames(:)
    type(frame_t) :: fr
    type(catom_t) :: at
    real(real64) :: cell(3), angles(3)
    integer :: pbc(3)
    open(newunit=man, file=trim(dir)//"/manifest.txt", status="old", action="read", iostat=ios)
    if (ios /= 0) call die("missing manifest")
    read(man, *) nframes
    close(man)
    open(newunit=u, file=band, status="replace", action="write")
    write(u, '(A,1X,I0)') "NFRAMES", nframes
    do i = 1, nframes
      write(idx, '(I3.3)') i - 1
      path = trim(dir)//"/frame_"//trim(idx)//".con"
      frames = read_all_frames(trim(path), 1)
      if (size(frames) /= 1) call die("expected one frame")
      fr = frames(1)
      nat = fr%natoms()
      call fr%cell_lengths(cell)
      call fr%cell_angles(angles)
      md = fr%metadata_json()
      pbc = pbc_of(md)
      write(u, '(A)') "FRAME"
      write(u, '(A,1X,I0)') "NATOMS", nat
      write(u, '(A,1X,ES24.16E3,1X,ES24.16E3,1X,ES24.16E3)') "CELL", cell
      write(u, '(A,1X,ES24.16E3,1X,ES24.16E3,1X,ES24.16E3)') "ANGLES", angles
      write(u, '(A,1X,I0,1X,I0,1X,I0)') "PBC", pbc
      write(u, '(A)') "META "//trim(md)
      write(u, '(A)') "ATOMS"
      do a = 1, nat
        at = fr%atom(a)
        sym = z_to_symbol(at%atomic_number)
        write(u, *) trim(sym), at%x, at%y, at%z, at%atom_id, at%mass, &
          merge(1, 0, logical(at%fixed_x)), merge(1, 0, logical(at%fixed_y)), &
          merge(1, 0, logical(at%fixed_z)), at%vx, at%vy, at%vz, &
          merge(1, 0, logical(at%has_velocity))
      end do
      write(u, '(A)') "ENDFRAME"
      call fr%free()
    end do
    close(u)
  end subroutine

  function pbc_of(md) result(p)
    character(len=*), intent(in) :: md
    integer :: p(3), k, n
    p = -1
    k = index(md, '"pbc"')
    if (k == 0) return
    n = 0
    k = index(md(k:), '[') + k - 1
    do while (n < 3 .and. k < len(md))
      if (md(k:k+3) == "true") then
        n = n + 1
        p(n) = 1
        k = k + 4
      else if (md(k:min(len(md), k+4)) == "false") then
        n = n + 1
        p(n) = 0
        k = k + 5
      else
        k = k + 1
      end if
    end do
  end function
end program
