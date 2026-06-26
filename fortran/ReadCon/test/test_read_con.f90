program test_read_con
  use readcon
  use, intrinsic :: iso_fortran_env, only: output_unit, error_unit, real64, int64
  implicit none
  character(len=*), parameter :: tiny = &
    "/home/rgoswami/Git/Github/LODE/readcon-core/resources/test/tiny_cuh2.con"
  character(len=*), parameter :: multi = &
    "/home/rgoswami/Git/Github/LODE/readcon-core/resources/test/tiny_multi_cuh2.con"
  type(frame_t) :: fr, fr2
  type(iterator_t) :: it
  type(builder_t) :: bd
  type(catom_t) :: a
  character(len=:), allocatable :: meta
  real(real64) :: cell(3), ang(3)
  integer :: n, nfail, nmatch, st, i, nf
  integer(int64) :: z
  character(len=:), allocatable :: sym

  nfail = 0
  print *, "version=", library_version(), " spec=", con_spec_version()
  print *, "chemfiles_support=", has_chemfiles_support()

  z = symbol_to_z("Cu")
  sym = z_to_symbol(z)
  print *, "Cu Z=", z, " symbol=", trim(sym)
  if (z <= 0) nfail = nfail + 1

  fr = read_first_frame(tiny)
  if (.not. fr%valid()) then
    print *, "FAIL read_first"
    error stop 1
  end if
  n = fr%natoms()
  if (n /= 4) nfail = nfail + 1
  call fr%cell_lengths(cell)
  meta = fr%metadata_json()
  print *, "natoms=", n, " meta=", trim(meta)
  a = fr%atom(1)
  if (.not. (a%fixed_x .or. a%fixed_y .or. a%fixed_z .or. .not. a%is_fixed)) then
    continue
  end if
  ! is_fixed consistency
  do i = 1, n
    a = fr%atom(i)
    if (logical(a%is_fixed) .neqv. (logical(a%fixed_x) .or. logical(a%fixed_y) .or. logical(a%fixed_z))) then
      nfail = nfail + 1
    end if
  end do

  ! iterator multi-frame
  it = open_iterator(multi)
  nf = 0
  if (it%valid()) then
    do
      fr2 = it%next()
      if (.not. fr2%valid()) exit
      nf = nf + 1
      call fr2%free()
    end do
    call it%free()
  end if
  print *, "iterator frames=", nf
  if (nf < 1) nfail = nfail + 1

  ! builder + writer roundtrip to temp would need writable path — build only
  cell = [10.0_real64, 10.0_real64, 10.0_real64]
  ang = [90.0_real64, 90.0_real64, 90.0_real64]
  bd = new_builder(cell, ang)
  if (bd%valid()) then
    st = bd%add_atom("H", 0.0_real64, 0.0_real64, 0.0_real64, 0_int64, 1.008_real64, &
         .false., .false., .false.)
    st = bd%set_energy(-1.23_real64)
    st = bd%set_metadata_json('{"con_spec_version":2,"note":"fortran-test"}')
    fr2 = bd%build()
    if (fr2%valid()) then
      print *, "built natoms=", fr2%natoms(), " energy=", fr2%energy()
      if (fr2%natoms() /= 1) nfail = nfail + 1
      call fr2%free()
    else
      nfail = nfail + 1
    end if
  else
    nfail = nfail + 1
  end if

  ! selection (may fail without chemfiles — that's OK)
  st = fr%select("all", nmatch)
  print *, "select all status=", st, " nmatch=", nmatch, " msg=", status_message(st)

  call fr%free()
  if (nfail /= 0) then
    print *, "FAIL nfail=", nfail
    error stop nfail
  end if
  print *, "OK"
end program
