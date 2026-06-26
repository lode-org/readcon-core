program test_read_con
  use readcon
  use, intrinsic :: iso_fortran_env, only: output_unit, error_unit, real64
  implicit none
  type(frame_t) :: fr
  type(catom_t) :: a
  character(len=:), allocatable :: meta, pot, ver
  character(len=*), parameter :: conpath = &
    "/home/rgoswami/Git/Github/LODE/readcon-core/resources/test/tiny_cuh2.con"
  real(real64) :: cell(3)
  integer :: n, i
  integer :: nfail

  nfail = 0
  ver = rkr_library_version()
  write(output_unit, '(a,a)') "library: ", ver
  if (rkr_con_spec_version() < 1) then
    write(error_unit, *) "bad spec version"
    nfail = nfail + 1
  end if

  fr = read_first_frame(conpath)
  if (.not. fr%valid()) then
    write(error_unit, *) "failed to read ", conpath
    error stop 1
  end if

  n = fr%natoms()
  write(output_unit, '(a,i0)') "natoms=", n
  if (n /= 4) then
    write(error_unit, *) "expected 4 atoms in tiny_cuh2.con"
    nfail = nfail + 1
  end if

  call fr%cell_lengths(cell)
  write(output_unit, '(a,3(1x,es12.4))') "cell=", cell

  a = fr%atom(1)
  write(output_unit, '(a,3(1x,es12.4),a,3(1x,l1))') "atom1 xyz=", a%x, a%y, a%z, &
    " fixed=", a%fixed_x, a%fixed_y, a%fixed_z

  meta = fr%metadata_json()
  write(output_unit, '(a,a)') "metadata_json=", trim(meta)
  pot = fr%potential_type()
  write(output_unit, '(a,a)') "potential_type=", trim(pot)

  ! Per-axis fixed flags exist on type (issue #19 surface)
  do i = 1, n
    a = fr%atom(i)
    if (a%is_fixed .neqv. (a%fixed_x .or. a%fixed_y .or. a%fixed_z)) then
      write(error_unit, *) "is_fixed inconsistency atom", i
      nfail = nfail + 1
    end if
  end do

  call fr%free()
  if (nfail /= 0) error stop nfail
  write(output_unit, '(a)') "OK"
end program test_read_con
