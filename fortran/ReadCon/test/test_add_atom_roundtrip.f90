! Write a frame through the public module and read it back with the C reader.
! add_atom covers the fixed mask. add_atom_full covers velocities.
! A repeated atom id must keep the underlying message, not only status -4.
program test_add_atom_roundtrip
  use readcon
  use, intrinsic :: iso_fortran_env, only: real64, int64
  use, intrinsic :: iso_c_binding, only: c_associated, c_char, c_int, c_null_char, c_ptr
  use, intrinsic :: ieee_arithmetic, only: ieee_value, ieee_negative_zero
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
  real(real64) :: neg0, subnormal
  character(len=:), allocatable :: work

  nfail = 0
  neg0 = ieee_value(0.0_real64, ieee_negative_zero)
  subnormal = transfer(1_int64, 0.0_real64)

  call make_work_dir(work)
  if (.not. allocated(work)) error stop 1
  call check_repeated_id(work)
  call check_roundtrip(work)
  call remove_work_dir(work)

  if (nfail /= 0) then
    print *, "FAIL", nfail
    error stop nfail
  end if
  print *, "OK add_atom fixed mask and velocity roundtrip"
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

  subroutine check_mask(at, fx, fy, fz, id, mass, z, what)
    type(catom_t), intent(in) :: at
    logical, intent(in) :: fx, fy, fz
    integer(int64), intent(in) :: id, z
    real(real64), intent(in) :: mass
    character(len=*), intent(in) :: what
    logical :: gx, gy, gz, gfixed
    gx = at%fixed_x
    gy = at%fixed_y
    gz = at%fixed_z
    gfixed = at%is_fixed
    if (gx .neqv. fx .or. gy .neqv. fy .or. gz .neqv. fz) then
      nfail = nfail + 1
      print *, "FAIL mask ", what, gx, gy, gz
    end if
    if ((gx .or. gy .or. gz) .neqv. gfixed) then
      nfail = nfail + 1
      print *, "FAIL is_fixed ", what
    end if
    if (int(at%atom_id, int64) /= id) then
      nfail = nfail + 1
      print *, "FAIL atom_id ", what, at%atom_id, id
    end if
    if (int(at%atomic_number, int64) /= z) then
      nfail = nfail + 1
      print *, "FAIL Z ", what, at%atomic_number
    end if
    call check_bits(real(at%mass, real64), mass, trim(what) // " mass")
  end subroutine

  subroutine check_repeated_id(work)
    character(len=*), intent(in) :: work
    type(builder_t) :: bd
    type(writer_t) :: wr
    type(frame_t) :: fr
    real(real64) :: cell(3), ang(3)
    integer :: st
    character(len=:), allocatable :: detail, generic
    cell = 10.0_real64
    ang = 90.0_real64
    bd = new_builder(cell, ang)
    if (.not. bd%valid()) then
      nfail = nfail + 1
      print *, "FAIL dup builder"
      return
    end if
    ! fixed_z is false. The old binding stored that flag as the atom id.
    st = bd%add_atom("H", 0.0_real64, 0.0_real64, 0.0_real64, 1_int64, 1.008_real64, &
         .true., .false., .false.)
    call require_ok(st, "dup add 1")
    st = bd%add_atom("H", 1.0_real64, 0.0_real64, 0.0_real64, 1_int64, 1.008_real64, &
         .false., .true., .false.)
    call require_ok(st, "dup add 2")
    fr = bd%build()
    if (.not. fr%valid()) then
      nfail = nfail + 1
      print *, "FAIL dup build"
      call bd%free()
      return
    end if
    wr = open_writer(work // "/dup.con")
    if (.not. wr%valid()) then
      nfail = nfail + 1
      print *, "FAIL dup writer"
      call fr%free()
      call bd%free()
      return
    end if
    st = wr%extend_one(fr)
    detail = last_error_message()
    generic = status_message(st)
    print *, "repeated-id st=", st, " generic=", trim(generic)
    print *, "repeated-id detail=", detail
    if (st /= rkr_status_io_error) then
      nfail = nfail + 1
      print *, "FAIL expected status -4"
    end if
    if (index(detail, "atom id 1 is repeated") == 0) then
      nfail = nfail + 1
      print *, "FAIL missing underlying repeated-id message"
    end if
    if (trim(generic) /= "I/O error") then
      nfail = nfail + 1
      print *, "FAIL generic status message changed"
    end if
    call wr%free()
    call fr%free()
    call bd%free()
  end subroutine

  subroutine check_roundtrip(work)
    character(len=*), intent(in) :: work
    type(builder_t) :: bd
    type(writer_t) :: wr
    type(frame_t) :: built, got
    type(catom_t) :: at
    real(real64) :: cell(3), ang(3), cell_out(3)
    real(real64) :: cu_x, cu_y, cu_z, cu_m
    real(real64) :: h_x, h_y, h_z, h_m, vel(3)
    real(real64) :: pos(3, 2), vbuf(3, 2)
    integer :: st, icu, ih
    integer(int64) :: id_cu, id_h
    character(len=160) :: units
    character(len=:), allocatable :: detail
    units = '{"units":{"length":"angstrom","energy":"eV","mass":"amu",' // &
         '"time":"(amu*angstrom^2/eV)^0.5"}}'
    cell = 10.0_real64
    ang = 90.0_real64
    cu_x = 1.2345678901234567_real64
    cu_y = neg0
    cu_z = subnormal
    cu_m = 63.546_real64
    h_x = -0.1_real64
    h_y = 2.5_real64
    h_z = 4.0_real64
    h_m = 1.008_real64
    vel = [neg0, subnormal, -3.5_real64]
    id_cu = 4_int64
    id_h = 9_int64

    bd = new_builder(cell, ang)
    st = bd%add_atom("Cu", cu_x, cu_y, cu_z, id_cu, cu_m, .true., .false., .true.)
    call require_ok(st, "add_atom Cu")
    st = bd%add_atom_full("H", h_x, h_y, h_z, id_h, h_m, .false., .true., .false., velocity=vel)
    call require_ok(st, "add_atom_full H")
    st = bd%set_metadata_json(trim(units))
    call require_ok(st, "units")
    built = bd%build()
    if (.not. built%valid()) then
      nfail = nfail + 1
      print *, "FAIL build"
      call bd%free()
      return
    end if
    wr = open_writer(work // "/rt.con")
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
    if (len(detail) /= 0) then
      nfail = nfail + 1
      print *, "FAIL stale error after success: ", detail
    end if
    call wr%free()
    call built%free()

    got = read_first_frame(work // "/rt.con")
    if (.not. got%valid()) then
      nfail = nfail + 1
      print *, "FAIL read"
      return
    end if
    if (got%natoms() /= 2) then
      nfail = nfail + 1
      print *, "FAIL natoms", got%natoms()
    end if
    if (.not. got%has_velocities()) then
      nfail = nfail + 1
      print *, "FAIL missing velocities"
    end if
    if (got%has_forces()) then
      nfail = nfail + 1
      print *, "FAIL unexpected forces"
    end if
    st = got%copy_positions(pos)
    call require_ok(st, "copy_positions")
    st = got%copy_velocities(vbuf)
    call require_ok(st, "copy_velocities")
    call got%cell_lengths(cell_out)
    call check_bits(cell_out(1), 10.0_real64, "cell x")
    call check_bits(cell_out(2), 10.0_real64, "cell y")
    call check_bits(cell_out(3), 10.0_real64, "cell z")

    icu = find_id(got, id_cu)
    ih = find_id(got, id_h)
    if (icu < 1 .or. ih < 1) then
      nfail = nfail + 1
      print *, "FAIL atom ids not found", icu, ih
      call got%free()
      return
    end if
    call check_bits(pos(1, icu), cu_x, "Cu x")
    call check_bits(pos(2, icu), cu_y, "Cu y")
    call check_bits(pos(3, icu), cu_z, "Cu z")
    call check_bits(vbuf(1, icu), 0.0_real64, "Cu vx")
    call check_bits(vbuf(2, icu), 0.0_real64, "Cu vy")
    call check_bits(vbuf(3, icu), 0.0_real64, "Cu vz")
    call check_bits(pos(1, ih), h_x, "H x")
    call check_bits(pos(2, ih), h_y, "H y")
    call check_bits(pos(3, ih), h_z, "H z")
    call check_bits(vbuf(1, ih), vel(1), "H vx")
    call check_bits(vbuf(2, ih), vel(2), "H vy")
    call check_bits(vbuf(3, ih), vel(3), "H vz")

    at = got%atom(icu)
    call check_mask(at, .true., .false., .true., id_cu, cu_m, 29_int64, "Cu")
    call check_bits(real(at%x, real64), cu_x, "Cu catom x")
    call check_bits(real(at%y, real64), cu_y, "Cu catom y")
    call check_bits(real(at%z, real64), cu_z, "Cu catom z")
    call check_bits(real(at%vx, real64), 0.0_real64, "Cu catom vx")
    if (.not. at%has_velocity) then
      nfail = nfail + 1
      print *, "FAIL Cu has_velocity"
    end if
    at = got%atom(ih)
    call check_mask(at, .false., .true., .false., id_h, h_m, 1_int64, "H")
    call check_bits(real(at%vx, real64), vel(1), "H catom vx")
    call check_bits(real(at%vy, real64), vel(2), "H catom vy")
    call check_bits(real(at%vz, real64), vel(3), "H catom vz")
    if (.not. at%has_velocity) then
      nfail = nfail + 1
      print *, "FAIL H has_velocity"
    end if
    if (at%has_forces) then
      nfail = nfail + 1
      print *, "FAIL H has_forces"
    end if
    call got%free()
  end subroutine

  subroutine make_work_dir(dir)
    character(len=:), allocatable, intent(out) :: dir
    character(len=*), parameter :: raw = "/tmp/readcon_fortran_add_atom_XXXXXX"
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
    call unlink_path(dir // "/dup.con")
    call unlink_path(dir // "/rt.con")
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
    if (n >= 256) then
      nfail = nfail + 1
      print *, "FAIL path too long ", path
      return
    end if
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
