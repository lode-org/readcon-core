! Call builder%add_atom in the rkr_frame_add_atom_full order, write the
! frame, and read it back. The C order is
! symbol, x, y, z, fixed_x, fixed_y, fixed_z, atom_id, mass,
! then an optional velocity. add_atom_full adds an optional force.
program test_add_atom_frame
  use readcon
  use, intrinsic :: iso_fortran_env, only: real64, int64
  use, intrinsic :: iso_c_binding, only: c_associated, c_char, c_int, c_null_char, c_ptr
  implicit none
  interface
    function c_mkdtemp(template) bind(C, name="mkdtemp") result(p)
      import :: c_char, c_ptr
      character(kind=c_char), intent(inout) :: template(*)
      type(c_ptr) :: p
    end function
    function c_unlink(path) bind(C, name="unlink") result(rc)
      import :: c_char, c_int
      character(kind=c_char), intent(in) :: path(*)
      integer(c_int) :: rc
    end function
    function c_rmdir(path) bind(C, name="rmdir") result(rc)
      import :: c_char, c_int
      character(kind=c_char), intent(in) :: path(*)
      integer(c_int) :: rc
    end function
  end interface
  integer :: nfail
  character(len=:), allocatable :: work

  nfail = 0
  call make_work_dir(work)
  if (.not. allocated(work)) error stop 1
  call check_frame(work)
  call remove_work_dir(work)
  if (nfail /= 0) then
    print *, "FAIL", nfail
    error stop nfail
  end if
  print *, "OK add_atom frame roundtrip"
contains
  subroutine require_ok(st, what)
    integer, intent(in) :: st
    character(len=*), intent(in) :: what
    character(len=:), allocatable :: detail
    if (st == 0) return
    nfail = nfail + 1
    detail = last_error_message()
    print *, "FAIL ", what, " st=", st, " status=", trim(status_message(st))
    if (len(detail) > 0) print *, "  detail=", detail
  end subroutine

  subroutine check_bits(got, expect, what)
    real(real64), intent(in) :: got, expect
    character(len=*), intent(in) :: what
    if (transfer(got, 0_int64) == transfer(expect, 0_int64)) return
    nfail = nfail + 1
    print *, "FAIL bits ", what
    print *, "  got   ", got, transfer(got, 0_int64)
    print *, "  expect", expect, transfer(expect, 0_int64)
  end subroutine

  integer function find_id(fr, id)
    type(frame_t), intent(inout) :: fr
    integer(int64), intent(in) :: id
    integer :: i
    type(catom_t) :: at
    find_id = 0
    do i = 1, fr%natoms()
      at = fr%atom(i)
      if (int(at%atom_id, int64) == id) then
        find_id = i
        return
      end if
    end do
  end function

  subroutine check_frame(work)
    character(len=*), intent(in) :: work
    type(builder_t) :: bd
    type(writer_t) :: wr
    type(frame_t) :: built, got
    type(catom_t) :: at
    real(real64) :: cell(3), ang(3)
    real(real64) :: cu_x, cu_y, cu_z, cu_m
    real(real64) :: h_x, h_y, h_z, h_m, vel(3), frc(3)
    real(real64) :: o_x, o_y, o_z, o_m
    real(real64) :: pos(3, 3), vbuf(3, 3), fbuf(3, 3)
    integer :: st, icu, ih, io
    integer(int64) :: id_cu, id_h, id_o
    character(len=:), allocatable :: detail
    cell = [12.0_real64, 12.0_real64, 12.0_real64]
    ang = [90.0_real64, 90.0_real64, 90.0_real64]
    cu_x = 0.25_real64
    cu_y = 0.5_real64
    cu_z = 0.75_real64
    cu_m = 63.546_real64
    h_x = 1.5_real64
    h_y = -0.25_real64
    h_z = 2.0_real64
    h_m = 1.008_real64
    o_x = 3.0_real64
    o_y = 1.0_real64
    o_z = -1.0_real64
    o_m = 15.999_real64
    vel = [0.1_real64, -0.2_real64, 0.3_real64]
    frc = [-0.4_real64, 0.5_real64, -0.6_real64]
    id_cu = 4_int64
    id_h = 9_int64
    id_o = 15_int64

    bd = new_builder(cell, ang, header="frame")
    if (.not. bd%valid()) then
      nfail = nfail + 1
      print *, "FAIL builder"
      return
    end if
    ! Documented C order: fixed flags, then atom id, then mass.
    st = bd%add_atom("Cu", cu_x, cu_y, cu_z, .true., .false., .true., id_cu, cu_m)
    call require_ok(st, "add_atom Cu")
    st = bd%add_atom_full("H", h_x, h_y, h_z, .false., .true., .false., id_h, h_m, &
         velocity=vel, force=frc)
    call require_ok(st, "add_atom_full H")
    st = bd%add_atom("O", o_x, o_y, o_z, .false., .false., .false., id_o, o_m)
    call require_ok(st, "add_atom O")
    ! A velocities section on minor >= 1 requires units.time.
    st = bd%set_metadata_json('{"units":{"length":"angstrom","energy":"eV",' // &
         '"mass":"amu","time":"(amu*angstrom^2/eV)^0.5"}}')
    call require_ok(st, "units")
    built = bd%build()
    if (.not. built%valid()) then
      nfail = nfail + 1
      print *, "FAIL build"
      call bd%free()
      return
    end if
    wr = open_writer(work // "/frame.con")
    if (.not. wr%valid()) then
      nfail = nfail + 1
      print *, "FAIL writer"
      call built%free()
      return
    end if
    st = wr%extend_one(built)
    detail = last_error_message()
    if (st /= 0) then
      nfail = nfail + 1
      print *, "FAIL write st=", st, " ", trim(status_message(st))
      print *, "  detail=", detail
      call wr%free()
      call built%free()
      return
    end if
    call wr%free()
    call built%free()

    got = read_first_frame(work // "/frame.con")
    if (.not. got%valid()) then
      nfail = nfail + 1
      print *, "FAIL read"
      return
    end if
    if (got%natoms() /= 3) then
      nfail = nfail + 1
      print *, "FAIL natoms", got%natoms()
    end if
    if (.not. got%has_velocities()) then
      nfail = nfail + 1
      print *, "FAIL missing velocities"
    end if
    if (.not. got%has_forces()) then
      nfail = nfail + 1
      print *, "FAIL missing forces"
    end if
    st = got%copy_positions(pos)
    call require_ok(st, "copy_positions")
    st = got%copy_velocities(vbuf)
    call require_ok(st, "copy_velocities")
    st = got%copy_forces(fbuf)
    call require_ok(st, "copy_forces")
    icu = find_id(got, id_cu)
    ih = find_id(got, id_h)
    io = find_id(got, id_o)
    if (icu < 1 .or. ih < 1 .or. io < 1) then
      nfail = nfail + 1
      print *, "FAIL atom ids", icu, ih, io
      call got%free()
      return
    end if
    call check_bits(pos(1, icu), cu_x, "Cu x")
    call check_bits(pos(2, icu), cu_y, "Cu y")
    call check_bits(pos(3, icu), cu_z, "Cu z")
    call check_bits(pos(1, ih), h_x, "H x")
    call check_bits(pos(2, ih), h_y, "H y")
    call check_bits(pos(3, ih), h_z, "H z")
    call check_bits(pos(1, io), o_x, "O x")
    call check_bits(pos(2, io), o_y, "O y")
    call check_bits(pos(3, io), o_z, "O z")
    call check_bits(vbuf(1, ih), vel(1), "H vx")
    call check_bits(vbuf(2, ih), vel(2), "H vy")
    call check_bits(vbuf(3, ih), vel(3), "H vz")
    call check_bits(fbuf(1, ih), frc(1), "H fx")
    call check_bits(fbuf(2, ih), frc(2), "H fy")
    call check_bits(fbuf(3, ih), frc(3), "H fz")
    at = got%atom(icu)
    call check_bits(real(at%mass, real64), cu_m, "Cu mass")
    if (int(at%atomic_number, int64) /= 29_int64) then
      nfail = nfail + 1
      print *, "FAIL Cu Z", at%atomic_number
    end if
    if (.not. (at%fixed_x .and. .not. at%fixed_y .and. at%fixed_z)) then
      nfail = nfail + 1
      print *, "FAIL Cu mask", at%fixed_x, at%fixed_y, at%fixed_z
    end if
    at = got%atom(ih)
    call check_bits(real(at%mass, real64), h_m, "H mass")
    if (int(at%atomic_number, int64) /= 1_int64) then
      nfail = nfail + 1
      print *, "FAIL H Z", at%atomic_number
    end if
    if (.not. (.not. at%fixed_x .and. at%fixed_y .and. .not. at%fixed_z)) then
      nfail = nfail + 1
      print *, "FAIL H mask", at%fixed_x, at%fixed_y, at%fixed_z
    end if
    if (.not. at%has_velocity .or. .not. at%has_forces) then
      nfail = nfail + 1
      print *, "FAIL H sections", at%has_velocity, at%has_forces
    end if
    at = got%atom(io)
    call check_bits(real(at%mass, real64), o_m, "O mass")
    if (int(at%atomic_number, int64) /= 8_int64) then
      nfail = nfail + 1
      print *, "FAIL O Z", at%atomic_number
    end if
    if (at%fixed_x .or. at%fixed_y .or. at%fixed_z) then
      nfail = nfail + 1
      print *, "FAIL O mask", at%fixed_x, at%fixed_y, at%fixed_z
    end if
    call got%free()
  end subroutine

  subroutine make_work_dir(dir)
    character(len=:), allocatable, intent(out) :: dir
    character(len=*), parameter :: raw = "/tmp/readcon_add_atom_frame_XXXXXX"
    character(kind=c_char) :: tmpl(len(raw) + 1)
    type(c_ptr) :: p
    integer :: i
    do i = 1, len(raw)
      tmpl(i) = raw(i:i)
    end do
    tmpl(len(raw) + 1) = c_null_char
    p = c_mkdtemp(tmpl)
    if (.not. c_associated(p)) then
      nfail = nfail + 1
      print *, "FAIL mkdtemp"
      return
    end if
    allocate(character(len=len(raw)) :: dir)
    do i = 1, len(raw)
      dir(i:i) = tmpl(i)
    end do
  end subroutine

  subroutine remove_work_dir(dir)
    character(len=*), intent(in) :: dir
    integer(c_int) :: rc
    call unlink_path(dir // "/frame.con")
    rc = rmdir_path(dir)
    if (rc /= 0) then
      nfail = nfail + 1
      print *, "FAIL rmdir ", dir
    end if
  end subroutine

  subroutine unlink_path(path)
    character(len=*), intent(in) :: path
    character(kind=c_char) :: buf(256)
    integer(c_int) :: rc
    integer :: i, n
    n = len(path)
    if (n >= 256) return
    do i = 1, n
      buf(i) = path(i:i)
    end do
    buf(n + 1) = c_null_char
    rc = c_unlink(buf)
  end subroutine

  function rmdir_path(path) result(rc)
    character(len=*), intent(in) :: path
    character(kind=c_char) :: buf(256)
    integer(c_int) :: rc
    integer :: i, n
    n = len(path)
    rc = 1
    if (n >= 256) return
    do i = 1, n
      buf(i) = path(i:i)
    end do
    buf(n + 1) = c_null_char
    rc = c_rmdir(buf)
  end function
end program
