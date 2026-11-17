! A NaN or infinite cell makes rkr_frame_new return NULL. new_builder must
! hand back an invalid builder, not crash, and the C error channel must name
! the field. Every later call on that builder must report a null pointer.
program test_non_finite_cell
  use readcon
  use, intrinsic :: iso_fortran_env, only: real64, int64
  use, intrinsic :: ieee_arithmetic, only: ieee_value, ieee_quiet_nan, ieee_positive_inf, &
       ieee_negative_inf
  implicit none
  integer :: nfail
  real(real64) :: nan, pinf, ninf

  nfail = 0
  nan = ieee_value(1.0_real64, ieee_quiet_nan)
  pinf = ieee_value(1.0_real64, ieee_positive_inf)
  ninf = ieee_value(1.0_real64, ieee_negative_inf)

  call refuses([nan, 10.0_real64, 10.0_real64], [90.0_real64, 90.0_real64, 90.0_real64], &
       "cell field cell[0] is NaN")
  call refuses([10.0_real64, pinf, 10.0_real64], [90.0_real64, 90.0_real64, 90.0_real64], &
       "cell field cell[1] is inf")
  call refuses([10.0_real64, 10.0_real64, ninf], [90.0_real64, 90.0_real64, 90.0_real64], &
       "cell field cell[2] is -inf")
  call refuses([10.0_real64, 10.0_real64, 10.0_real64], [nan, 90.0_real64, 90.0_real64], &
       "cell field angles[0] is NaN")
  call refuses([10.0_real64, 10.0_real64, 10.0_real64], [90.0_real64, pinf, 90.0_real64], &
       "cell field angles[1] is inf")
  call refuses([10.0_real64, 10.0_real64, 10.0_real64], [90.0_real64, 90.0_real64, ninf], &
       "cell field angles[2] is -inf")
  call accepts_finite()
  call reads_a_nan_file()

  if (nfail /= 0) then
    print *, "FAIL", nfail
    error stop nfail
  end if
  print *, "OK non-finite cell"
contains
  subroutine fail(what)
    character(len=*), intent(in) :: what
    nfail = nfail + 1
    print *, "FAIL ", what
  end subroutine

  subroutine refuses(cell, ang, field)
    real(real64), intent(in) :: cell(3), ang(3)
    character(len=*), intent(in) :: field
    type(builder_t) :: bd
    type(frame_t) :: fr
    character(len=:), allocatable :: detail
    integer :: st

    call clear_error()
    bd = new_builder(cell, ang, header="frame")
    if (bd%valid()) then
      call fail("builder is valid for " // field)
      call bd%free()
      return
    end if
    if (last_error_code() /= rkr_status_parse_error) then
      call fail("error code for " // field)
    end if
    detail = last_error_message()
    if (index(detail, "NonFiniteValue") == 0 .or. index(detail, field) == 0) then
      call fail("error message for " // field // ": " // detail)
    end if
    st = bd%add_atom("Cu", 0.0_real64, 0.0_real64, 0.0_real64, .false., .false., .false., &
         1_int64, 63.546_real64)
    if (st /= rkr_status_null_pointer) call fail("add_atom status for " // field)
    st = bd%set_energy(1.0_real64)
    if (st /= rkr_status_null_pointer) call fail("set_energy status for " // field)
    fr = bd%build()
    if (fr%valid()) then
      call fail("build returned a frame for " // field)
      call fr%free()
    end if
    call bd%free()
  end subroutine

  subroutine accepts_finite()
    type(builder_t) :: bd
    type(frame_t) :: fr
    integer :: st

    bd = new_builder([10.0_real64, 11.0_real64, 12.0_real64], &
         [90.0_real64, 90.0_real64, 90.0_real64], header="frame")
    if (.not. bd%valid()) then
      call fail("a finite cell is refused")
      return
    end if
    st = bd%add_atom("Cu", 0.0_real64, 0.0_real64, 0.0_real64, .false., .false., .false., &
         1_int64, 63.546_real64)
    if (st /= rkr_status_success) call fail("add_atom on a finite cell")
    fr = bd%build()
    if (.not. fr%valid()) call fail("build on a finite cell")
    call fr%free()
    call bd%free()
  end subroutine

  subroutine reads_a_nan_file()
    character(len=*), parameter :: path = "readcon_non_finite_cell_test.con"
    type(iterator_t) :: it
    type(frame_t) :: fr
    character(len=:), allocatable :: detail
    integer :: unit, ios

    open(newunit=unit, file=path, status="replace", action="write", iostat=ios)
    if (ios /= 0) then
      call fail("cannot write the scratch file")
      return
    end if
    write (unit, "(a)") "frame"
    write (unit, "(a)") '{"con_spec_version":2}'
    write (unit, "(a)") "10.0 NaN 10.0"
    write (unit, "(a)") "90.0 90.0 90.0"
    write (unit, "(a)") "0 0"
    write (unit, "(a)") "0 0 0"
    write (unit, "(a)") "1"
    write (unit, "(a)") "1"
    write (unit, "(a)") "63.546"
    write (unit, "(a)") "Cu"
    write (unit, "(a)") "Coordinates of Component 1"
    write (unit, "(a)") "0.0 0.0 0.0 0 1"
    close(unit)

    call clear_error()
    it = open_iterator(path)
    fr = it%next()
    if (fr%valid()) then
      call fail("the iterator returned a frame with a NaN cell")
      call fr%free()
    end if
    if (last_error_code() /= rkr_status_parse_error) call fail("read error code")
    detail = last_error_message()
    if (index(detail, "NonFiniteValue") == 0 .or. &
        index(detail, "cell field boxl[1] of frame 0 is NaN") == 0) then
      call fail("read error message: " // detail)
    end if
    call it%free()

    call clear_error()
    fr = read_first_frame(path)
    if (fr%valid()) then
      call fail("read_first_frame returned a frame with a NaN cell")
      call fr%free()
    end if
    if (last_error_code() /= rkr_status_parse_error) call fail("read_first_frame error code")

    open(newunit=unit, file=path, status="old", iostat=ios)
    if (ios == 0) close(unit, status="delete")
  end subroutine
end program
