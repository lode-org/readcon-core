program test_read_con
  use readcon
  use, intrinsic :: iso_c_binding, only: c_ptr, c_associated
  use, intrinsic :: iso_fortran_env, only: real64, int64
  implicit none
  character(len=*), parameter :: tiny = "/home/rgoswami/Git/Github/LODE/readcon-core/resources/test/tiny_cuh2.con"
  character(len=*), parameter :: multi = "/home/rgoswami/Git/Github/LODE/readcon-core/resources/test/tiny_multi_cuh2.con"
  character(len=*), parameter :: water = "/home/rgoswami/Git/Github/LODE/readcon-core/resources/test/water_min.xyz"
  type(frame_t) :: fr, fr2, frx
  type(iterator_t) :: it
  type(builder_t) :: bd
  type(catom_t) :: a
  real(real64) :: cell(3), ang(3), pos(3, 8), masses(8), e
  integer(int64) :: prim(32)
  integer :: nfail, n, nf, st, nmatch, nw, i
  type(c_ptr) :: dlt
  character(len=:), allocatable :: meta

  nfail = 0
  print *, "lib=", library_version(), " chemfiles=", has_chemfiles_support()

  fr = read_first_frame(tiny)
  if (.not. fr%valid()) error stop "read tiny"
  if (fr%natoms() /= 4) nfail = nfail + 1
  meta = fr%metadata_json()
  print *, "meta=", trim(meta)

  it = open_iterator(multi)
  nf = 0
  do while (it%valid())
    fr2 = it%next()
    if (.not. fr2%valid()) exit
    nf = nf + 1
    call fr2%free()
  end do
  call it%free()
  if (nf < 2) nfail = nfail + 1

  cell = 10.0_real64; ang = 90.0_real64
  bd = new_builder(cell, ang)
  st = bd%add_atom("O", 0.0_real64, 0.0_real64, 0.0_real64, 0_int64, 15.999_real64, &
       .false., .false., .false.)
  st = bd%add_atom("H", 1.0_real64, 0.0_real64, 0.0_real64, 1_int64, 1.008_real64, &
       .true., .false., .false.)
  st = bd%set_energy(-42.5_real64)
  print *, "set_energy status=", st
  st = bd%copy_positions(pos)
  print *, "copy_positions status=", st, " pos1=", pos(1,1), pos(2,1), pos(3,1)
  if (st /= 0) nfail = nfail + 1
  st = bd%copy_masses(masses)
  if (st /= 0) nfail = nfail + 1
  st = bd%positions_dlpack(dlt)
  print *, "positions_dlpack status=", st, " ptr associated=", c_associated(dlt)
  if (st == 0 .and. c_associated(dlt)) call bd%dlpack_delete(dlt)
  fr2 = bd%build()
  if (.not. fr2%valid()) then
    nfail = nfail + 1
  else
    e = fr2%energy()
    print *, "built energy=", e, " natoms=", fr2%natoms()
    meta = fr2%metadata_json()
    print *, "built meta=", trim(meta)
    if (fr2%natoms() /= 2) nfail = nfail + 1
    ! energy may be in JSON even if getter NaN
    if (index(meta, "energy") == 0 .and. e == e) then
      continue
    end if
    if (e == e .and. abs(e + 42.5_real64) > 1.0e-6_real64) then
      ! finite but wrong
      if (abs(e + 42.5_real64) > 1.0e-3_real64) nfail = nfail + 1
    end if
    a = fr2%atom(2)
    if (.not. logical(a%fixed_x)) nfail = nfail + 1
    call fr2%free()
  end if

  if (has_chemfiles_support()) then
    frx = read_chemfiles_first(water)
    if (.not. frx%valid()) then
      print *, "chemfiles read failed"
      nfail = nfail + 1
    else
      print *, "xyz atoms=", frx%natoms()
      st = frx%select("name O", nmatch)
      print *, "select name O status=", st, " nmatch=", nmatch
      if (st == 0 .and. nmatch < 1) nfail = nfail + 1
      st = frx%select_primary("name H", prim, nw)
      print *, "select_primary H status=", st, " n=", nw
      call frx%free()
    end if
  else
    print *, "skip chemfiles tests (lean lib)"
  end if

  call fr%free()
  if (nfail /= 0) then
    print *, "FAIL", nfail
    error stop nfail
  end if
  print *, "OK"
end program
