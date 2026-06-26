! ReadCon — Fortran 2003 ISO_C_BINDING wrappers over include/readcon-core.h
! Implements https://github.com/lode-org/readcon-core/issues/6
!
! Link: -I<path>/include  and the readcon_core shared/static library
! (Meson, CMake+Corrosion, or cargo-c install layout).

module readcon
  use, intrinsic :: iso_c_binding
  implicit none
  private

  public :: rkr_status_success
  public :: rkr_con_spec_version, rkr_library_version
  public :: rkr_read_first_frame, free_rkr_frame
  public :: rkr_frame_to_c_frame, free_c_frame
  public :: catom_t, cframe_t

  integer(c_int), parameter :: rkr_status_success = 0

  ! Mirrors CAtom / CFrame (transparent layout from readcon-core.h)
  type, bind(C) :: catom_t
    integer(c_int64_t) :: atomic_number
    real(c_double) :: x, y, z
    integer(c_int64_t) :: atom_id
    real(c_double) :: mass
    logical(c_bool) :: is_fixed
    logical(c_bool) :: fixed_x, fixed_y, fixed_z
    real(c_double) :: vx, vy, vz
    logical(c_bool) :: has_velocity
    real(c_double) :: fx, fy, fz
    logical(c_bool) :: has_forces
    real(c_double) :: energy
    logical(c_bool) :: has_energy
  end type catom_t

  type, bind(C) :: cframe_t
    type(c_ptr) :: atoms          ! catom_t*
    integer(c_size_t) :: num_atoms
    real(c_double) :: cell(3)
    real(c_double) :: angles(3)
    logical(c_bool) :: has_velocities
    logical(c_bool) :: has_forces
    logical(c_bool) :: has_energies
  end type cframe_t

  interface
    function rkr_con_spec_version_c() bind(C, name="rkr_con_spec_version")
      import :: c_int32_t
      integer(c_int32_t) :: rkr_con_spec_version_c
    end function

    function rkr_library_version_c() bind(C, name="rkr_library_version")
      import :: c_ptr
      type(c_ptr) :: rkr_library_version_c
    end function

    function rkr_read_first_frame_c(filename) bind(C, name="rkr_read_first_frame")
      import :: c_char, c_ptr
      character(kind=c_char), intent(in) :: filename(*)
      type(c_ptr) :: rkr_read_first_frame_c
    end function

    subroutine free_rkr_frame_c(frame) bind(C, name="free_rkr_frame")
      import :: c_ptr
      type(c_ptr), value :: frame
    end subroutine

    function rkr_frame_to_c_frame_c(frame) bind(C, name="rkr_frame_to_c_frame")
      import :: c_ptr
      type(c_ptr), value :: frame
      type(c_ptr) :: rkr_frame_to_c_frame_c
    end function

    subroutine free_c_frame_c(cframe) bind(C, name="free_c_frame")
      import :: c_ptr
      type(c_ptr), value :: cframe
    end subroutine
  end interface

contains

  integer function rkr_con_spec_version()
    rkr_con_spec_version = int(rkr_con_spec_version_c())
  end function

  !> Return library version as a Fortran deferred-length string (copy of C static).
  function rkr_library_version() result(ver)
    character(len=:), allocatable :: ver
    type(c_ptr) :: p
    character(kind=c_char), pointer :: fp(:)
    integer :: n, i
    p = rkr_library_version_c()
    if (.not. c_associated(p)) then
      ver = ""
      return
    end if
    call c_f_pointer(p, fp, [4096])
    n = 0
    do i = 1, 4096
      if (fp(i) == c_null_char) exit
      n = n + 1
    end do
    allocate(character(len=n) :: ver)
    do i = 1, n
      ver(i:i) = fp(i)
    end do
  end function

  !> Read first frame; returns c_null_ptr on failure. Caller must free_rkr_frame.
  function rkr_read_first_frame(path) result(frame)
    character(len=*), intent(in) :: path
    type(c_ptr) :: frame
    character(kind=c_char), allocatable :: cpath(:)
    integer :: n, i
    n = len_trim(path)
    allocate(cpath(n + 1))
    do i = 1, n
      cpath(i) = path(i:i)
    end do
    cpath(n + 1) = c_null_char
    frame = rkr_read_first_frame_c(cpath)
  end function

  subroutine free_rkr_frame(frame)
    type(c_ptr), intent(inout) :: frame
    if (c_associated(frame)) then
      call free_rkr_frame_c(frame)
      frame = c_null_ptr
    end if
  end subroutine

  !> Lossy transparent CFrame (atoms + cell). Caller must free_c_frame.
  function rkr_frame_to_c_frame(frame) result(cframe)
    type(c_ptr), intent(in) :: frame
    type(c_ptr) :: cframe
    cframe = rkr_frame_to_c_frame_c(frame)
  end function

  subroutine free_c_frame(cframe)
    type(c_ptr), intent(inout) :: cframe
    if (c_associated(cframe)) then
      call free_c_frame_c(cframe)
      cframe = c_null_ptr
    end if
  end subroutine

end module readcon
