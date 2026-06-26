! ReadCon — first-class Fortran 2003/2008 bindings over include/readcon-core.h
! Full ISO_C_BINDING types for CAtom/CFrame + ergonomic metadata helpers.
module readcon
  use, intrinsic :: iso_c_binding
  use, intrinsic :: iso_fortran_env, only: real64, int64
  implicit none
  private

  public :: rkr_status_success, rkr_status_null_pointer, rkr_status_internal_error
  public :: catom_t, cframe_t
  public :: rkr_con_spec_version, rkr_library_version
  public :: frame_t
  public :: read_first_frame, read_all_frame_count
  public :: c_string_to_f, f_to_c_string

  integer(c_int), parameter :: rkr_status_success = 0
  integer(c_int), parameter :: rkr_status_null_pointer = -1
  integer(c_int), parameter :: rkr_status_internal_error = -7

  ! Transparent C layout (must match include/readcon-core.h CAtom / CFrame)
  type, bind(C), public :: catom_t
    integer(c_int64_t) :: atomic_number = 0
    real(c_double) :: x = 0, y = 0, z = 0
    integer(c_int64_t) :: atom_id = 0
    real(c_double) :: mass = 0
    logical(c_bool) :: is_fixed = .false.
    logical(c_bool) :: fixed_x = .false., fixed_y = .false., fixed_z = .false.
    real(c_double) :: vx = 0, vy = 0, vz = 0
    logical(c_bool) :: has_velocity = .false.
    real(c_double) :: fx = 0, fy = 0, fz = 0
    logical(c_bool) :: has_forces = .false.
    real(c_double) :: energy = 0
    logical(c_bool) :: has_energy = .false.
  end type catom_t

  type, bind(C), public :: cframe_t
    type(c_ptr) :: atoms = c_null_ptr
    integer(c_size_t) :: num_atoms = 0_c_size_t
    real(c_double) :: cell(3) = 0
    real(c_double) :: angles(3) = 0
    logical(c_bool) :: has_velocities = .false.
    logical(c_bool) :: has_forces = .false.
    logical(c_bool) :: has_energies = .false.
  end type cframe_t

  ! High-level Fortran frame: owns opaque RKRConFrame* + optional CFrame view
  type :: frame_t
    private
    type(c_ptr) :: handle = c_null_ptr
    type(c_ptr) :: cview = c_null_ptr
  contains
    procedure :: valid => frame_valid
    procedure :: free => frame_free
    procedure :: natoms => frame_natoms
    procedure :: ensure_cview => frame_ensure_cview
    procedure :: atom => frame_atom
    procedure :: cell_lengths => frame_cell
    procedure :: cell_angles => frame_angles
    procedure :: metadata_json => frame_metadata_json
    procedure :: energy => frame_energy
    procedure :: potential_type => frame_potential_type
    procedure :: frame_index => frame_frame_index
    procedure :: sim_time => frame_time
    procedure :: timestep => frame_timestep
    ! No FINAL: callers must call %free() (avoids double-free with explicit cleanup)
  end type frame_t

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
    function rkr_read_all_frames_c(filename, num_frames) bind(C, name="rkr_read_all_frames")
      import :: c_char, c_ptr, c_size_t
      character(kind=c_char), intent(in) :: filename(*)
      integer(c_size_t), intent(out) :: num_frames
      type(c_ptr) :: rkr_read_all_frames_c
    end function
    subroutine free_rkr_frame_c(frame) bind(C, name="free_rkr_frame")
      import :: c_ptr
      type(c_ptr), value :: frame
    end subroutine
    subroutine free_rkr_frame_array_c(frames, n) bind(C, name="free_rkr_frame_array")
      import :: c_ptr, c_size_t
      type(c_ptr), value :: frames
      integer(c_size_t), value :: n
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
    function rkr_frame_metadata_json_c(frame) bind(C, name="rkr_frame_metadata_json")
      import :: c_ptr
      type(c_ptr), value :: frame
      type(c_ptr) :: rkr_frame_metadata_json_c
    end function
    function rkr_frame_energy_c(frame) bind(C, name="rkr_frame_energy")
      import :: c_ptr, c_double
      type(c_ptr), value :: frame
      real(c_double) :: rkr_frame_energy_c
    end function
    function rkr_frame_potential_type_c(frame) bind(C, name="rkr_frame_potential_type")
      import :: c_ptr
      type(c_ptr), value :: frame
      type(c_ptr) :: rkr_frame_potential_type_c
    end function
    function rkr_frame_frame_index_c(frame) bind(C, name="rkr_frame_frame_index")
      import :: c_ptr, c_int64_t
      type(c_ptr), value :: frame
      integer(c_int64_t) :: rkr_frame_frame_index_c
    end function
    function rkr_frame_time_c(frame) bind(C, name="rkr_frame_time")
      import :: c_ptr, c_double
      type(c_ptr), value :: frame
      real(c_double) :: rkr_frame_time_c
    end function
    function rkr_frame_timestep_c(frame) bind(C, name="rkr_frame_timestep")
      import :: c_ptr, c_double
      type(c_ptr), value :: frame
      real(c_double) :: rkr_frame_timestep_c
    end function
    subroutine rkr_free_string_c(s) bind(C, name="rkr_free_string")
      import :: c_ptr
      type(c_ptr), value :: s
    end subroutine
  end interface

contains

  integer function rkr_con_spec_version()
    rkr_con_spec_version = int(rkr_con_spec_version_c())
  end function

  function rkr_library_version() result(ver)
    character(len=:), allocatable :: ver
    ver = c_string_to_f(rkr_library_version_c(), owned=.false.)
  end function

  function c_string_to_f(p, owned) result(s)
    type(c_ptr), intent(in) :: p
    logical, intent(in), optional :: owned
    character(len=:), allocatable :: s
    character(kind=c_char), pointer :: fp(:)
    integer :: n, i
    logical :: do_free
    do_free = .false.
    if (present(owned)) do_free = owned
    if (.not. c_associated(p)) then
      s = ""
      return
    end if
    call c_f_pointer(p, fp, [65536])
    n = 0
    do i = 1, 65536
      if (fp(i) == c_null_char) exit
      n = n + 1
    end do
    allocate(character(len=n) :: s)
    do i = 1, n
      s(i:i) = fp(i)
    end do
    if (do_free) call rkr_free_string_c(p)
  end function

  subroutine f_to_c_string(f, cpath)
    character(len=*), intent(in) :: f
    character(kind=c_char), allocatable, intent(out) :: cpath(:)
    integer :: n, i
    n = len_trim(f)
    allocate(cpath(n + 1))
    do i = 1, n
      cpath(i) = f(i:i)
    end do
    cpath(n + 1) = c_null_char
  end subroutine

  function read_first_frame(path) result(fr)
    character(len=*), intent(in) :: path
    type(frame_t) :: fr
    character(kind=c_char), allocatable :: cpath(:)
    call f_to_c_string(path, cpath)
    fr%handle = rkr_read_first_frame_c(cpath)
    fr%cview = c_null_ptr
  end function

  !> Count frames via rkr_read_all_frames (allocates then frees).
  integer function read_all_frame_count(path)
    character(len=*), intent(in) :: path
    character(kind=c_char), allocatable :: cpath(:)
    type(c_ptr) :: arr
    integer(c_size_t) :: n
    call f_to_c_string(path, cpath)
    arr = rkr_read_all_frames_c(cpath, n)
    if (c_associated(arr)) then
      call free_rkr_frame_array_c(arr, n)
      read_all_frame_count = int(n)
    else
      read_all_frame_count = -1
    end if
  end function

  logical function frame_valid(self)
    class(frame_t), intent(in) :: self
    frame_valid = c_associated(self%handle)
  end function

  subroutine frame_free(self)
    class(frame_t), intent(inout) :: self
    if (c_associated(self%cview)) then
      call free_c_frame_c(self%cview)
      self%cview = c_null_ptr
    end if
    if (c_associated(self%handle)) then
      call free_rkr_frame_c(self%handle)
      self%handle = c_null_ptr
    end if
  end subroutine

  subroutine frame_ensure_cview(self)
    class(frame_t), intent(inout) :: self
    if (.not. c_associated(self%handle)) return
    if (.not. c_associated(self%cview)) then
      self%cview = rkr_frame_to_c_frame_c(self%handle)
    end if
  end subroutine

  integer function frame_natoms(self)
    class(frame_t), intent(inout) :: self
    type(cframe_t), pointer :: cf
    call self%ensure_cview()
    frame_natoms = 0
    if (.not. c_associated(self%cview)) return
    call c_f_pointer(self%cview, cf)
    frame_natoms = int(cf%num_atoms)
  end function

  function frame_atom(self, i) result(a)
    class(frame_t), intent(inout) :: self
    integer, intent(in) :: i
    type(catom_t) :: a
    type(cframe_t), pointer :: cf
    type(catom_t), pointer :: atoms(:)
    call self%ensure_cview()
    a = catom_t()
    if (.not. c_associated(self%cview)) return
    call c_f_pointer(self%cview, cf)
    if (i < 1 .or. i > int(cf%num_atoms)) return
    if (.not. c_associated(cf%atoms)) return
    call c_f_pointer(cf%atoms, atoms, [int(cf%num_atoms)])
    a = atoms(i)
  end function

  subroutine frame_cell(self, lengths)
    class(frame_t), intent(inout) :: self
    real(real64), intent(out) :: lengths(3)
    type(cframe_t), pointer :: cf
    call self%ensure_cview()
    lengths = 0
    if (.not. c_associated(self%cview)) return
    call c_f_pointer(self%cview, cf)
    lengths = real(cf%cell, kind=real64)
  end subroutine

  subroutine frame_angles(self, ang)
    class(frame_t), intent(inout) :: self
    real(real64), intent(out) :: ang(3)
    type(cframe_t), pointer :: cf
    call self%ensure_cview()
    ang = 0
    if (.not. c_associated(self%cview)) return
    call c_f_pointer(self%cview, cf)
    ang = real(cf%angles, kind=real64)
  end subroutine

  function frame_metadata_json(self) result(s)
    class(frame_t), intent(in) :: self
    character(len=:), allocatable :: s
    type(c_ptr) :: p
    s = ""
    if (.not. c_associated(self%handle)) return
    p = rkr_frame_metadata_json_c(self%handle)
    s = c_string_to_f(p, owned=.true.)
  end function

  real(real64) function frame_energy(self)
    class(frame_t), intent(in) :: self
    frame_energy = 0
    if (.not. c_associated(self%handle)) return
    frame_energy = real(rkr_frame_energy_c(self%handle), kind=real64)
  end function

  function frame_potential_type(self) result(s)
    class(frame_t), intent(in) :: self
    character(len=:), allocatable :: s
    type(c_ptr) :: p
    s = ""
    if (.not. c_associated(self%handle)) return
    p = rkr_frame_potential_type_c(self%handle)
    s = c_string_to_f(p, owned=.true.)
  end function

  integer(int64) function frame_frame_index(self)
    class(frame_t), intent(in) :: self
    frame_frame_index = -1_int64
    if (.not. c_associated(self%handle)) return
    frame_frame_index = rkr_frame_frame_index_c(self%handle)
  end function

  real(real64) function frame_time(self)
    class(frame_t), intent(in) :: self
    frame_time = 0
    if (.not. c_associated(self%handle)) return
    frame_time = real(rkr_frame_time_c(self%handle), kind=real64)
  end function

  real(real64) function frame_timestep(self)
    class(frame_t), intent(in) :: self
    frame_timestep = 0
    if (.not. c_associated(self%handle)) return
    frame_timestep = real(rkr_frame_timestep_c(self%handle), kind=real64)
  end function

end module readcon
