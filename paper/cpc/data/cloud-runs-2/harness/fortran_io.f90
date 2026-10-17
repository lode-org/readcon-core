! Fortran round trip through the C ABI.
!
! The public ReadCon module procedure add_atom binds
! rkr_frame_add_atom_with_fixed_mask with the argument order
! (x, y, z, atom_id, mass, fixed_x, fixed_y, fixed_z). The C function
! is (x, y, z, fixed_x, fixed_y, fixed_z, atom_id, mass). On the
! System V ABI that places the z fixed flag in the atom-id register,
! so every atom id becomes 0 or 1 and the writer returns
! RKR_STATUS_IO_ERROR (-4): "atom id 1 is repeated in the frame".
! This program declares the prototype from readcon-core.h and calls
! rkr_frame_add_atom_full, which also carries a velocity.
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

  subroutine to_c(s, c)
    character(len=*), intent(in) :: s
    character(kind=c_char), allocatable, intent(out) :: c(:)
    integer :: i, n
    n = len_trim(s)
    allocate(c(n + 1))
    do i = 1, n
      c(i) = s(i:i)
    end do
    c(n + 1) = c_null_char
  end subroutine

  subroutine do_write(band, dir)
    character(len=*), intent(in) :: band, dir
    interface
      function c_frame_new(cell, angles, p0, p1, q0, q1) bind(C, name="rkr_frame_new")
        import :: c_ptr, c_double, c_char
        real(c_double), intent(in) :: cell(*), angles(*)
        type(c_ptr), value :: p0, p1, q0, q1
        type(c_ptr) :: c_frame_new
      end function
      function c_set_meta(b, j) bind(C, name="rkr_frame_builder_set_metadata_json")
        import :: c_ptr, c_char, c_int
        type(c_ptr), value :: b
        character(kind=c_char), intent(in) :: j(*)
        integer(c_int) :: c_set_meta
      end function
      function c_add_full(b, sym, x, y, z, fx, fy, fz, aid, mass, vel, frc) &
           bind(C, name="rkr_frame_add_atom_full")
        import :: c_ptr, c_char, c_double, c_bool, c_int64_t, c_int
        type(c_ptr), value :: b, vel, frc
        character(kind=c_char), intent(in) :: sym(*)
        real(c_double), value :: x, y, z, mass
        logical(c_bool), value :: fx, fy, fz
        integer(c_int64_t), value :: aid
        integer(c_int) :: c_add_full
      end function
      function c_build(b) bind(C, name="rkr_frame_builder_build")
        import :: c_ptr
        type(c_ptr), value :: b
        type(c_ptr) :: c_build
      end function
      function c_writer(path) bind(C, name="create_writer_from_path_c")
        import :: c_ptr, c_char
        character(kind=c_char), intent(in) :: path(*)
        type(c_ptr) :: c_writer
      end function
      function c_extend(w, frames, n) bind(C, name="rkr_writer_extend")
        import :: c_ptr, c_size_t, c_int
        type(c_ptr), value :: w
        type(c_ptr), intent(in) :: frames(*)
        integer(c_size_t), value :: n
        integer(c_int) :: c_extend
      end function
      subroutine c_free_writer(w) bind(C, name="free_rkr_writer")
        import :: c_ptr
        type(c_ptr), value :: w
      end subroutine
      subroutine c_free_frame(f) bind(C, name="free_rkr_frame")
        import :: c_ptr
        type(c_ptr), value :: f
      end subroutine
    end interface
    integer :: u, stat, nframes, i, natoms, a, fx, fy, fz, hv, ios
    integer(int64) :: id
    real(real64) :: cell(3), angles(3), x, y, z, mass, vx, vy, vz
    real(c_double), target :: ccell(3), cangles(3), vel(3)
    character(len=16) :: tag, sym
    character(len=1024) :: meta, path
    character(len=32) :: pre
    character(len=8) :: idx
    character(kind=c_char), allocatable :: csym(:), cmeta(:), cpath(:)
    character(kind=c_char), target :: cpre(64)
    type(c_ptr) :: bld, fr, wr, handles(1)
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
      ccell = real(cell, c_double)
      cangles = real(angles, c_double)
      write(pre, '(A,1X,I0)') "image", i - 1
      cpre = c_null_char
      do a = 1, len_trim(pre)
        cpre(a) = pre(a:a)
      end do
      bld = c_frame_new(ccell, cangles, c_loc(cpre), c_null_ptr, c_null_ptr, c_null_ptr)
      if (.not. c_associated(bld)) call die("rkr_frame_new failed")
      call to_c(trim(meta), cmeta)
      stat = c_set_meta(bld, cmeta)
      if (stat /= 0) then
        write(0, *) "meta stat", stat
        call die("set_metadata_json failed")
      end if
      do a = 1, natoms
        read(u, *) sym, x, y, z, id, mass, fx, fy, fz, vx, vy, vz, hv
        call to_c(trim(sym), csym)
        if (hv /= 0) then
          vel(1) = real(vx, c_double)
          vel(2) = real(vy, c_double)
          vel(3) = real(vz, c_double)
          stat = c_add_full(bld, csym, real(x, c_double), real(y, c_double), real(z, c_double), &
               logical(fx /= 0, c_bool), logical(fy /= 0, c_bool), logical(fz /= 0, c_bool), &
               int(id, c_int64_t), real(mass, c_double), c_loc(vel), c_null_ptr)
        else
          stat = c_add_full(bld, csym, real(x, c_double), real(y, c_double), real(z, c_double), &
               logical(fx /= 0, c_bool), logical(fy /= 0, c_bool), logical(fz /= 0, c_bool), &
               int(id, c_int64_t), real(mass, c_double), c_null_ptr, c_null_ptr)
        end if
        if (stat /= 0) then
          write(0, *) "add stat", stat, trim(sym), id
          call die("rkr_frame_add_atom_full failed")
        end if
      end do
      read(u, *) tag
      fr = c_build(bld)
      if (.not. c_associated(fr)) call die("build failed")
      write(idx, '(I3.3)') i - 1
      path = trim(dir)//"/frame_"//trim(idx)//".con"
      call to_c(trim(path), cpath)
      wr = c_writer(cpath)
      if (.not. c_associated(wr)) call die("create_writer failed")
      handles(1) = fr
      stat = c_extend(wr, handles, 1_c_size_t)
      call c_free_writer(wr)
      call c_free_frame(fr)
      if (stat /= 0) then
        write(0, *) "extend stat", stat, trim(path)
        call die("rkr_writer_extend failed")
      end if
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
