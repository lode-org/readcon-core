! Build a restart frame only through builder%add_atom, write it, read it back.
! Every atom has a distinct id, a per-axis fixed mask and a velocity.
! A second frame uses the nine-argument call and must carry no velocities.
! The first frame sets line 1 with new_builder's header; the second leaves it empty.
program test_add_atom_restart
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
    function c_rmdir(path) bind(C, name="rmdir") result(rc)
      import :: c_char, c_int
      character(kind=c_char), intent(in) :: path(*)
      integer(c_int) :: rc
    end function
  end interface
  integer, parameter :: n = 8
  character(len=2), parameter :: sym(n) = ["Pt", "Pt", "Pt", "Pt", "Cu", "Cu", "H ", "H "]
  integer(int64), parameter :: z(n) = [78, 78, 78, 78, 29, 29, 1, 1]
  integer(int64), parameter :: ids(n) = [17, 3, 11, 5, 23, 2, 13, 7]
  logical, parameter :: fx(n) = [.true., .true., .true., .false., .false., .true., .false., .false.]
  logical, parameter :: fy(n) = [.true., .true., .false., .true., .false., .false., .true., .false.]
  logical, parameter :: fz(n) = [.true., .false., .true., .true., .true., .false., .false., .false.]
  real(real64) :: mass(n), pos(3, n), vel(3, n), cell(3), ang(3), energy
  integer :: nfail, i
  character(len=:), allocatable :: work

  nfail = 0
  mass = [195.084_real64, 195.084_real64, 195.084_real64, 195.084_real64, &
          63.546_real64, 63.546_real64, 2.01410177812_real64, 2.01410177812_real64]
  do i = 1, n
    pos(:, i) = [0.1_real64 * i + 1.0e-13_real64, 2.7742_real64 * mod(i, 3), &
                 -1.25_real64 + 3.0_real64 * i / 7.0_real64]
    vel(:, i) = [1.0e-3_real64 * i, -2.5e-2_real64 / i, 7.0_real64 / 3.0_real64 - i]
  end do
  pos(2, 1) = ieee_value(0.0_real64, ieee_negative_zero)
  vel(1, 8) = ieee_value(0.0_real64, ieee_negative_zero)
  vel(3, 7) = transfer(1_int64, 0.0_real64)
  cell = [8.3196_real64, 8.3196_real64, 25.0000000001_real64]
  ang = [90.0_real64, 90.0_real64, 120.0_real64]
  energy = -1.2345678901234567e2_real64

  call make_work_dir(work)
  if (.not. allocated(work)) error stop 1
  call check_restart(work // "/restart.con")
  call check_no_velocity(work // "/plain.con")
  call remove(work // "/restart.con")
  call remove(work // "/plain.con")
  if (c_rmdir(cstr(work)) /= 0) then
    nfail = nfail + 1
    print *, "FAIL rmdir ", work
  end if

  if (nfail /= 0) then
    print *, "FAIL", nfail
    error stop nfail
  end if
  print *, "OK add_atom restart frame roundtrip"
contains
  subroutine require_ok(st, what)
    integer, intent(in) :: st
    character(len=*), intent(in) :: what
    if (st == 0) return
    nfail = nfail + 1
    print *, "FAIL ", what, " st=", st, " ", trim(status_message(st)), " ", last_error_message()
  end subroutine

  subroutine check_bits(got, expect, what)
    real(real64), intent(in) :: got, expect
    character(len=*), intent(in) :: what
    if (transfer(got, 0_int64) == transfer(expect, 0_int64)) return
    nfail = nfail + 1
    print *, "FAIL bits ", what, got, expect
  end subroutine

  subroutine check_true(cond, what)
    logical, intent(in) :: cond
    character(len=*), intent(in) :: what
    if (cond) return
    nfail = nfail + 1
    print *, "FAIL ", what
  end subroutine

  subroutine write_one(bd, path)
    type(builder_t), intent(inout) :: bd
    character(len=*), intent(in) :: path
    type(frame_t) :: fr
    type(writer_t) :: wr
    fr = bd%build()
    call check_true(fr%valid(), "build")
    if (.not. fr%valid()) return
    wr = open_writer(path)
    call check_true(wr%valid(), "open_writer")
    if (wr%valid()) then
      call require_ok(wr%extend_one(fr), "extend_one")
      call wr%free()
    end if
    call fr%free()
  end subroutine

  subroutine check_restart(path)
    character(len=*), intent(in) :: path
    type(builder_t) :: bd
    type(frame_t) :: got
    type(catom_t) :: at
    real(real64) :: lens(3), angs(3)
    character(len=:), allocatable :: md
    integer(int64) :: seen(n)
    integer :: i, j, k
    bd = new_builder(cell, ang, header="image 3")
    call check_true(bd%valid(), "new_builder")
    do i = 1, n
      call require_ok(bd%add_atom(trim(sym(i)), pos(1, i), pos(2, i), pos(3, i), ids(i), &
           mass(i), fx(i), fy(i), fz(i), velocity=vel(:, i)), "add_atom " // trim(sym(i)))
    end do
    ! set_metadata_json replaces the whole object, so the energy goes in after it.
    call require_ok(bd%set_metadata_json('{"units":{"length":"angstrom","energy":"eV",' // &
         '"mass":"amu","time":"(amu*angstrom^2/eV)^0.5"}}'), "set_metadata_json")
    call require_ok(bd%set_energy(energy), "set_energy")
    call write_one(bd, path)
    call check_true(first_line(path) == "image 3", "header line 1")

    got = read_first_frame(path)
    call check_true(got%valid(), "read_first_frame")
    if (.not. got%valid()) return
    call check_true(got%natoms() == n, "natoms")
    call check_true(got%has_velocities(), "has_velocities")
    call check_true(.not. got%has_forces(), "no forces")
    call got%cell_lengths(lens)
    call got%cell_angles(angs)
    do k = 1, 3
      call check_bits(lens(k), cell(k), "cell")
      call check_bits(angs(k), ang(k), "angle")
    end do
    call check_bits(got%energy(), energy, "energy")
    md = got%metadata_json()
    call check_true(index(md, '"time":"(amu*angstrom^2/eV)^0.5"') > 0, "units.time")
    seen = -1_int64
    do j = 1, min(n, got%natoms())
      at = got%atom(j)
      seen(j) = int(at%atom_id, int64)
      i = findloc(ids, seen(j), dim=1)
      call check_true(i > 0, "atom id present")
      if (i == 0) cycle
      call check_true(int(at%atomic_number, int64) == z(i), "Z")
      call check_true(z_to_symbol(at%atomic_number) == trim(sym(i)), "symbol")
      call check_bits(real(at%mass, real64), mass(i), "mass")
      call check_bits(real(at%x, real64), pos(1, i), "x")
      call check_bits(real(at%y, real64), pos(2, i), "y")
      call check_bits(real(at%z, real64), pos(3, i), "z")
      call check_bits(real(at%vx, real64), vel(1, i), "vx")
      call check_bits(real(at%vy, real64), vel(2, i), "vy")
      call check_bits(real(at%vz, real64), vel(3, i), "vz")
      call check_true(logical(at%has_velocity), "atom has_velocity")
      call check_true((at%fixed_x .eqv. fx(i)) .and. (at%fixed_y .eqv. fy(i)) .and. &
           (at%fixed_z .eqv. fz(i)), "fixed mask")
      call check_true(at%is_fixed .eqv. (fx(i) .or. fy(i) .or. fz(i)), "is_fixed")
    end do
    do i = 1, n
      call check_true(count(seen == ids(i)) == 1, "id unique")
    end do
    call got%free()
  end subroutine

  subroutine check_no_velocity(path)
    character(len=*), intent(in) :: path
    type(builder_t) :: bd
    type(frame_t) :: got
    type(catom_t) :: at
    bd = new_builder(cell, ang)
    call require_ok(bd%add_atom("Cu", 0.5_real64, 0.25_real64, 0.125_real64, 41_int64, &
         63.546_real64, .false., .true., .false.), "plain add_atom 1")
    call require_ok(bd%add_atom("Cu", 1.5_real64, 1.25_real64, 1.125_real64, 9_int64, &
         63.546_real64, .true., .false., .true.), "plain add_atom 2")
    call write_one(bd, path)
    call check_true(len(first_line(path)) == 0, "plain line 1 empty")
    got = read_first_frame(path)
    call check_true(got%valid(), "plain read")
    if (.not. got%valid()) return
    call check_true(got%natoms() == 2, "plain natoms")
    call check_true(.not. got%has_velocities(), "plain has no velocities")
    at = got%atom(1)
    call check_true(at%atom_id == 41 .and. .not. at%fixed_x .and. at%fixed_y .and. &
         .not. at%fixed_z, "plain atom 1")
    at = got%atom(2)
    call check_true(at%atom_id == 9 .and. at%fixed_x .and. .not. at%fixed_y .and. &
         at%fixed_z, "plain atom 2")
    call got%free()
  end subroutine

  function first_line(path) result(line)
    character(len=*), intent(in) :: path
    character(len=:), allocatable :: line
    character(len=256) :: buf
    integer :: u, ios, sz
    line = "<unreadable>"
    open(newunit=u, file=path, status="old", action="read", iostat=ios)
    if (ios /= 0) return
    read(u, '(A)', advance="no", size=sz, iostat=ios) buf
    close(u)
    if (ios > 0) return
    line = buf(:sz)
  end function

  subroutine remove(path)
    character(len=*), intent(in) :: path
    integer :: u, ios
    open(newunit=u, file=path, status="old", iostat=ios)
    if (ios == 0) close(u, status="delete")
  end subroutine

  function cstr(s) result(c)
    character(len=*), intent(in) :: s
    character(kind=c_char) :: c(len(s) + 1)
    integer :: k
    do k = 1, len(s)
      c(k) = s(k:k)
    end do
    c(len(s) + 1) = c_null_char
  end function

  subroutine make_work_dir(dir)
    character(len=:), allocatable, intent(out) :: dir
    character(len=:), allocatable :: base, raw
    character(kind=c_char), allocatable :: tmpl(:)
    integer :: k, n, st
    call get_environment_variable("TMPDIR", length=n, status=st)
    if (st == 0 .and. n > 0) then
      allocate(character(len=n) :: base)
      call get_environment_variable("TMPDIR", value=base)
    else
      base = "/tmp"
    end if
    raw = base // "/readcon_fortran_restart_XXXXXX"
    tmpl = cstr(raw)
    if (.not. c_associated(c_mkdtemp(tmpl))) then
      print *, "FAIL mkdtemp"
      return
    end if
    allocate(character(len=len(raw)) :: dir)
    do k = 1, len(raw)
      dir(k:k) = tmpl(k)
    end do
  end subroutine
end program
