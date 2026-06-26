program test_read_con
  use readcon
  use, intrinsic :: iso_c_binding, only: c_ptr, c_associated
  use, intrinsic :: iso_fortran_env, only: real64, int64
  implicit none
  character(len=*), parameter :: tiny = "/home/rgoswami/Git/Github/LODE/readcon-core/resources/test/tiny_cuh2.con"
  character(len=*), parameter :: water = "/home/rgoswami/Git/Github/LODE/readcon-core/resources/test/water_min.xyz"
  type(frame_t) :: fr, fr2, frx
  type(builder_t) :: bd
  real(real64) :: cell(3), ang(3), pos(3, 8), masses(8)
  integer(int64) :: prim(32), shape0, shape1
  integer :: nfail, st, nmatch, nw, ndim, bits
  type(c_ptr) :: dlt, mts
  logical :: ok
  character(len=:), allocatable :: meta

  nfail = 0
  print *, "lib=", library_version(), " chemfiles=", has_chemfiles_support()

  fr = read_first_frame(tiny)
  if (.not. fr%valid()) error stop "read tiny"
  if (fr%natoms() /= 4) nfail = nfail + 1

  cell = 10.0_real64; ang = 90.0_real64
  bd = new_builder(cell, ang)
  st = bd%add_atom("O", 0.0_real64, 0.0_real64, 0.0_real64, 0_int64, 15.999_real64, &
       .false., .false., .false.)
  st = bd%add_atom("H", 1.0_real64, 0.0_real64, 0.0_real64, 1_int64, 1.008_real64, &
       .true., .false., .false.)
  st = bd%set_energy(-42.5_real64)
  st = bd%copy_positions(pos)
  if (st /= 0) nfail = nfail + 1

  st = bd%positions_dlpack(dlt)
  call dlpack_inspect(dlt, ndim, shape0, shape1, bits, ok)
  print *, "positions_dlpack st=", st, " ok=", ok, " ndim=", ndim, " shape=", shape0, shape1, " bits=", bits
  if (st /= 0 .or. .not. ok .or. ndim /= 2 .or. shape0 /= 2_int64 .or. shape1 /= 3_int64) nfail = nfail + 1
  if (c_associated(dlt)) call bd%dlpack_delete(dlt)

  st = bd%masses_dlpack(dlt)
  call dlpack_inspect(dlt, ndim, shape0, shape1, bits, ok)
  print *, "masses_dlpack st=", st, " ndim=", ndim, " shape0=", shape0
  if (st /= 0 .or. .not. ok) nfail = nfail + 1
  if (c_associated(dlt)) call bd%dlpack_delete(dlt)

  st = bd%atom_ids_dlpack(dlt)
  print *, "atom_ids_dlpack st=", st
  if (st /= 0) nfail = nfail + 1
  if (c_associated(dlt)) call bd%dlpack_delete(dlt)

  ! optional sections absent on builder without velocities declared
  st = bd%velocities_dlpack(dlt)
  print *, "velocities_dlpack (expect absent) st=", st, " null=", .not. c_associated(dlt)
  if (st == 0) nfail = nfail + 1
  st = bd%forces_dlpack(dlt)
  print *, "forces_dlpack (expect absent) st=", st
  if (st == 0) nfail = nfail + 1
  st = bd%atom_energies_dlpack(dlt)
  print *, "atom_energies_dlpack (expect absent) st=", st
  if (st == 0) nfail = nfail + 1

  fr2 = bd%build()
  if (.not. fr2%valid()) then
    nfail = nfail + 1
  else
    print *, "energy=", fr2%energy()
    if (abs(fr2%energy() + 42.5_real64) > 1.0e-6_real64) nfail = nfail + 1
    st = frame_metatensor_positions_block(fr2, mts)
    print *, "metatensor_positions st=", st, " block=", c_associated(mts)
    ! Without linking metatensor into this binary the symbol may be missing at
    ! runtime if lib built without feature; with chemfiles-only build expect non-success
    if (st == 0 .and. c_associated(mts)) call mts_block_free_rkr(mts)
    call fr2%free()
  end if

  if (has_chemfiles_support()) then
    frx = read_chemfiles_first(water)
    if (.not. frx%valid()) then
      nfail = nfail + 1
    else
      st = frx%select("name O", nmatch)
      if (st /= 0 .or. nmatch < 1) nfail = nfail + 1
      st = frx%select_primary("name H", prim, nw)
      if (st /= 0 .or. nw < 1) nfail = nfail + 1
      call frx%free()
    end if
  end if

  call fr%free()
  if (nfail /= 0) then
    print *, "FAIL", nfail
    error stop nfail
  end if
  print *, "OK full parity suite"
end program
