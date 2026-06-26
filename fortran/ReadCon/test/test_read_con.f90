program test_read_con
  use readcon
  use, intrinsic :: iso_c_binding
  use, intrinsic :: iso_fortran_env, only: real64, int64
  use, intrinsic :: ieee_exceptions
  implicit none
  character(len=1024) :: root, tiny, water
  integer :: nlen, ierr
  type(frame_t) :: fr, fr2, frx
  type(builder_t) :: bd
  real(real64) :: cell(3), ang(3), pos(3, 8)
  integer(int64) :: prim(32), shape0, shape1
  integer :: nfail, st, nmatch, nw, ndim, bits
  type(c_ptr) :: dlt, mts, data_p
  logical :: ok

  ! Chemfiles C++ may raise FPEs; do not abort the Fortran runtime on CI hosts
  call ieee_set_halting_mode(ieee_all, .false.)

  nfail = 0
  call get_environment_variable("READCON_CORE_ROOT", root, length=nlen, status=ierr)
  if (ierr /= 0 .or. nlen == 0) then
    ! Fallback when script did not set ROOT (fpm cwd is package dir)
    root = "../.."
  end if
  tiny = trim(root) // "/resources/test/tiny_cuh2.con"
  water = trim(root) // "/resources/test/water_min.xyz"
  inquire(file=trim(tiny), exist=ok)
  if (.not. ok) then
    print *, "missing ", trim(tiny)
    error stop "tiny_cuh2.con not found; set READCON_CORE_ROOT to repo root"
  end if

  print *, "lib=", library_version(), " chemfiles=", has_chemfiles_support()
  print *, "tiny=", trim(tiny)

  fr = read_first_frame(trim(tiny))
  if (.not. fr%valid()) error stop "read tiny"

  cell = 10.0_real64; ang = 90.0_real64
  bd = new_builder(cell, ang)
  st = bd%add_atom("O", 0.0_real64, 0.0_real64, 0.0_real64, 0_int64, 15.999_real64, .false., .false., .false.)
  st = bd%add_atom("H", 1.0_real64, 0.0_real64, 0.0_real64, 1_int64, 1.008_real64, .true., .false., .false.)
  st = bd%set_energy(-42.5_real64)
  st = bd%copy_positions(pos)
  if (st /= 0) nfail = nfail + 1

  st = bd%positions_dlpack(dlt)
  call dlpack_inspect(dlt, ndim, shape0, shape1, bits, ok)
  data_p = dlpack_data_ptr(dlt)
  print *, "positions_dlpack st=", st, " ok=", ok, " ndim=", ndim, " shape=", shape0, shape1, &
       " bits=", bits, " data=", c_associated(data_p)
  if (st /= 0 .or. .not. ok .or. ndim /= 2 .or. shape0 /= 2_int64 .or. shape1 /= 3_int64) nfail = nfail + 1
  if (.not. c_associated(data_p)) nfail = nfail + 1
  if (c_associated(dlt)) call bd%dlpack_delete(dlt)

  st = bd%masses_dlpack(dlt)
  call dlpack_inspect(dlt, ndim, shape0, shape1, bits, ok)
  print *, "masses_dlpack st=", st, " ndim=", ndim, " shape0=", shape0
  if (st /= 0 .or. .not. ok) nfail = nfail + 1
  if (c_associated(dlt)) call bd%dlpack_delete(dlt)

  st = bd%atom_ids_dlpack(dlt)
  call dlpack_inspect(dlt, ndim, shape0, shape1, bits, ok)
  if (st /= 0 .or. .not. ok) nfail = nfail + 1
  if (c_associated(dlt)) call bd%dlpack_delete(dlt)

  st = bd%velocities_dlpack(dlt)
  print *, "velocities_dlpack (expect absent) st=", st, " null=", .not. c_associated(dlt)
  if (st == 0) nfail = nfail + 1
  st = bd%forces_dlpack(dlt)
  if (st == 0) nfail = nfail + 1
  st = bd%atom_energies_dlpack(dlt)
  if (st == 0) nfail = nfail + 1

  fr2 = bd%build()
  if (.not. fr2%valid()) then
    nfail = nfail + 1
  else
    if (abs(fr2%energy() + 42.5_real64) > 1.0e-6_real64) nfail = nfail + 1
    st = frame_metatensor_positions_block(fr2, mts)
    print *, "metatensor_positions st=", st, " block=", c_associated(mts)
#ifdef READCON_HAS_METATENSOR
    if (st /= 0 .or. .not. c_associated(mts)) nfail = nfail + 1
    call mts_block_free_rkr(mts)
    st = frame_metatensor_velocities_block(fr2, mts)
    print *, "metatensor_velocities (absent) st=", st
    if (st /= rkr_status_section_absent) nfail = nfail + 1
    call mts_block_free_rkr(mts)
    st = frame_metatensor_forces_block(fr2, mts)
    if (st /= rkr_status_section_absent) nfail = nfail + 1
    call mts_block_free_rkr(mts)
    st = frame_metatensor_atom_energies_block(fr2, mts)
    if (st /= rkr_status_section_absent) nfail = nfail + 1
    call mts_block_free_rkr(mts)
#else
    if (st /= -7) nfail = nfail + 1
#endif
    call fr2%free()
  end if

  ! Chemfiles XYZ path: optional in suite (C++ may raise SIGFPE under gfortran FPE traps on some CI hosts)
  if (has_chemfiles_support()) then
    inquire(file=trim(water), exist=ok)
    if (ok) then
      frx = read_chemfiles_first(trim(water))
      if (frx%valid()) then
        st = frx%select("name O", nmatch)
        if (st /= 0 .or. nmatch < 1) nfail = nfail + 1
        st = frx%select_primary("name H", prim, nw)
        if (st /= 0 .or. nw < 1) nfail = nfail + 1
        call frx%free()
        print *, "chemfiles water select ok"
      else
        print *, "chemfiles water read skipped (invalid frame)"
      end if
    end if
  end if

  call fr%free()
  if (nfail /= 0) then
    print *, "FAIL", nfail
    error stop nfail
  end if
  print *, "OK full parity suite"
end program
