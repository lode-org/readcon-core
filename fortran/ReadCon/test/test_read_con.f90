program test_read_con
  use readcon
  use, intrinsic :: iso_c_binding
  use, intrinsic :: iso_fortran_env, only: real64, int64
  use, intrinsic :: ieee_exceptions
  implicit none
  character(len=1024) :: root, tiny
  integer :: nlen, ierr
  type(frame_t) :: fr, fr2
  type(writer_t) :: wg
  type(builder_t) :: bd
  real(real64) :: cell(3), ang(3), pos(3, 8)
  integer(int64) :: shape0, shape1
  integer :: nfail, st, ndim, bits
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
  inquire(file=trim(tiny), exist=ok)
  if (.not. ok) then
    print *, "missing ", trim(tiny)
    error stop "tiny_cuh2.con not found; set READCON_CORE_ROOT to repo root"
  end if

  print *, "lib=", library_version(), " chemfiles=", has_chemfiles_support()
  print *, "tiny=", trim(tiny)

  fr = read_first_frame(trim(tiny))
  if (.not. fr%valid()) error stop "read tiny"
  ! section buffer without CFrame AoS (positions + velocities/forces/masses)
  block
    real(real64), allocatable :: pbuf(:,:), vbuf(:,:), fbuf(:,:), mbuf(:)
    integer :: na, st2
    na = int(fr%atom_count())
    allocate(pbuf(3, na), vbuf(3, na), fbuf(3, na), mbuf(na))
    st2 = fr%copy_positions(pbuf)
    if (st2 /= 0) nfail = nfail + 1
    print *, "frame_copy_positions st=", st2, " natoms=", na
    ! tiny_cuh2 has no velocities/forces; expect SECTION_ABSENT (-8) or success
    st2 = fr%copy_velocities(vbuf)
    if (st2 /= 0 .and. st2 /= -8) nfail = nfail + 1
    print *, "frame_copy_velocities st=", st2
    st2 = fr%copy_forces(fbuf)
    if (st2 /= 0 .and. st2 /= -8) nfail = nfail + 1
    print *, "frame_copy_forces st=", st2
    st2 = fr%copy_masses(mbuf)
    if (st2 /= 0 .and. st2 /= -8) nfail = nfail + 1
    print *, "frame_copy_masses st=", st2
  end block
  block
    type(frame_t), allocatable :: allf(:)
    integer :: ia
    allf = read_all_frames(trim(tiny))
    if (.not. allocated(allf) .or. size(allf) < 1) then
      nfail = nfail + 1
    else if (.not. allf(1)%valid()) then
      nfail = nfail + 1
    else if (int(allf(1)%atom_count()) < 1) then
      nfail = nfail + 1
    else
      print *, "read_all_frames n=", size(allf), " atoms0=", int(allf(1)%atom_count())
    end if
    if (allocated(allf)) then
      do ia = 1, size(allf)
        call allf(ia)%free()
      end do
    end if
  end block

  ! Lazy multi-frame iterator (C ABI: read_con_file_iterator / next)
  block
    character(len=1024) :: multi
    type(iterator_t) :: it
    type(frame_t) :: fiter
    integer :: nframes
    multi = trim(root) // "/resources/test/tiny_multi_cuh2.con"
    inquire(file=trim(multi), exist=ok)
    if (.not. ok) then
      print *, "missing ", trim(multi)
      nfail = nfail + 1
    else
      it = open_iterator(trim(multi))
      if (.not. it%valid()) then
        nfail = nfail + 1
        print *, "open_iterator failed"
      else
        nframes = 0
        do
          fiter = it%next()
          if (.not. fiter%valid()) exit
          nframes = nframes + 1
          if (int(fiter%atom_count()) < 1) nfail = nfail + 1
          call fiter%free()
        end do
        call it%free()
        print *, "iterator frames=", nframes
        if (nframes /= 2) nfail = nfail + 1
      end if
    end if
  end block

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

  block
    real(real64) :: masses(2)
    integer :: st3
    st3 = bd%copy_masses(masses)
    if (st3 /= 0) nfail = nfail + 1
    print *, "builder_copy_masses st=", st3, " m0=", masses(1), " m1=", masses(2)
  end block

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
    if (st == 0) then
      if (.not. c_associated(mts)) nfail = nfail + 1
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
    else if (st == rkr_status_feature_disabled) then
      print *, "metatensor lean FEATURE_DISABLED ok"
      if (c_associated(mts)) nfail = nfail + 1
    else
      nfail = nfail + 1
    end if
    call fr2%free()
  end if

  ! Chemfiles exercised in Rust CI; avoid calling into chemfiles C++ from gfortran on runners
  ! (SIGFPE in chfl_trajectory_open under trapped FP on ubuntu-22.04 + gfortran).
  print *, "chemfiles_support=", has_chemfiles_support()

  ! gzip compressed writer (always exported from C)
  wg = open_writer_gzip(trim(root) // "/target/tmp_fortran_gzip_test.con.gz")
  if (.not. wg%valid()) then
    print *, "open_writer_gzip failed"
    nfail = nfail + 1
  else
    print *, "open_writer_gzip ok"
    call wg%free()
  end if
  wg = open_writer_zstd(trim(root) // "/target/tmp_fortran_zstd_test.con.zst")
  if (wg%valid()) then
    print *, "open_writer_zstd ok (zstd feature)"
    call wg%free()
  else
    print *, "open_writer_zstd null (lean stub or error)"
  end if

  call fr%free()
  if (nfail /= 0) then
    print *, "FAIL", nfail
    error stop nfail
  end if
  print *, "OK full parity suite"
end program
