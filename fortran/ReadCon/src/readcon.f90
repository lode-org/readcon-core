! ReadCon — production Fortran bindings (ISO_C_BINDING) over include/readcon-core.h
! fpm package: fortran/ReadCon  |  Tests: fpm test  |  Link libreadcon_core
module readcon
  use, intrinsic :: iso_c_binding
  use, intrinsic :: iso_fortran_env, only: real64, int64, int32
  implicit none
  private

  public :: rkr_status_success, rkr_status_null_pointer, rkr_status_selection_error
  public :: catom_t, cframe_t
  public :: dl_tensor_t, dl_managed_tensor_versioned_t
  public :: dlpack_inspect
  public :: frame_metatensor_positions_block, mts_block_free_rkr
  public :: library_version, con_spec_version, has_chemfiles_support, status_message
  public :: symbol_to_z, z_to_symbol
  public :: frame_t, iterator_t, builder_t, writer_t
  public :: read_first_frame, open_iterator, new_builder, open_writer
  public :: read_chemfiles_first
  public :: rkr_status_section_absent

  integer(c_int), parameter :: rkr_status_success = 0
  integer(c_int), parameter :: rkr_status_null_pointer = -1
  integer(c_int), parameter :: rkr_status_selection_error = -10
  integer(c_int), parameter :: rkr_status_section_absent = -8

  type, bind(C), public :: catom_t
    integer(c_int64_t) :: atomic_number = 0_c_int64_t
    real(c_double) :: x = 0.0_c_double, y = 0.0_c_double, z = 0.0_c_double
    integer(c_int64_t) :: atom_id = 0_c_int64_t
    real(c_double) :: mass = 0.0_c_double
    logical(c_bool) :: is_fixed = .false._c_bool
    logical(c_bool) :: fixed_x = .false._c_bool, fixed_y = .false._c_bool, fixed_z = .false._c_bool
    real(c_double) :: vx = 0.0_c_double, vy = 0.0_c_double, vz = 0.0_c_double
    logical(c_bool) :: has_velocity = .false._c_bool
    real(c_double) :: fx = 0.0_c_double, fy = 0.0_c_double, fz = 0.0_c_double
    logical(c_bool) :: has_forces = .false._c_bool
    real(c_double) :: energy = 0.0_c_double
    logical(c_bool) :: has_energy = .false._c_bool
  end type


  ! DLPack C layout (dlpack.h DLManagedTensorVersioned / DLTensor) — field access
  type, bind(C), public :: dl_device_t
    integer(c_int32_t) :: device_type = 1_c_int32_t  ! kDLCPU
    integer(c_int32_t) :: device_id = 0_c_int32_t
  end type

  type, bind(C), public :: dl_data_type_t
    integer(c_int8_t) :: code = 0_c_int8_t
    integer(c_int8_t) :: bits = 0_c_int8_t
    integer(c_int16_t) :: lanes = 0_c_int16_t
  end type

  type, bind(C), public :: dl_tensor_t
    type(c_ptr) :: data = c_null_ptr
    type(dl_device_t) :: device
    integer(c_int32_t) :: ndim = 0_c_int32_t
    type(dl_data_type_t) :: dtype
    type(c_ptr) :: shape = c_null_ptr   ! int64_t*
    type(c_ptr) :: strides = c_null_ptr
    integer(c_int64_t) :: byte_offset = 0_c_int64_t
  end type

  type, bind(C), public :: dl_pack_version_t
    integer(c_int32_t) :: major = 0_c_int32_t
    integer(c_int32_t) :: minor = 0_c_int32_t
  end type

  type, bind(C), public :: dl_managed_tensor_versioned_t
    type(dl_pack_version_t) :: version
    type(c_ptr) :: manager_ctx = c_null_ptr
    type(c_funptr) :: deleter = c_null_funptr
    integer(c_int64_t) :: flags = 0_c_int64_t
    type(dl_tensor_t) :: dl_tensor
  end type

  type, bind(C), public :: cframe_t
    type(c_ptr) :: atoms = c_null_ptr
    integer(c_size_t) :: num_atoms = 0_c_size_t
    real(c_double) :: cell(3) = 0.0_c_double
    real(c_double) :: angles(3) = 0.0_c_double
    logical(c_bool) :: has_velocities = .false._c_bool
    logical(c_bool) :: has_forces = .false._c_bool
    logical(c_bool) :: has_energies = .false._c_bool
  end type

  type :: frame_t
    private
    type(c_ptr) :: handle = c_null_ptr
    type(c_ptr) :: cview = c_null_ptr
  contains
    procedure :: valid => fr_valid
    procedure :: free => fr_free
    procedure :: natoms => fr_natoms
    procedure :: atom => fr_atom
    procedure :: cell_lengths => fr_cell
    procedure :: cell_angles => fr_angles
    procedure :: has_velocities => fr_has_vel
    procedure :: has_forces => fr_has_frc
    procedure :: metadata_json => fr_meta
    procedure :: energy => fr_energy
    procedure :: potential_type => fr_pot
    procedure :: frame_index => fr_fidx
    procedure :: sim_time => fr_time
    procedure :: timestep => fr_dt
    procedure :: neb_bead => fr_neb_bead
    procedure :: neb_band => fr_neb_band
    procedure :: bond_count => fr_nbonds
    procedure :: bond_at => fr_bond_at
    procedure :: atom_index_by_id => fr_id_index
    procedure :: spec_version => fr_spec
    procedure :: select => fr_select
    procedure :: select_primary => fr_select_primary
    procedure :: write_path => fr_write_path
    procedure :: handle_ptr => fr_handle
  end type

  type :: iterator_t
    private
    type(c_ptr) :: it = c_null_ptr
  contains
    procedure :: valid => it_valid
    procedure :: next => it_next
    procedure :: free => it_free
  end type

  type :: builder_t
    private
    type(c_ptr) :: b = c_null_ptr
  contains
    procedure :: valid => bd_valid
    procedure :: free => bd_free
    procedure :: add_atom => bd_add_atom
    procedure :: set_energy => bd_set_energy
    procedure :: set_metadata_json => bd_set_meta
    procedure :: set_frame_index => bd_set_fidx
    procedure :: build => bd_build
    procedure :: copy_positions => bd_copy_positions
    procedure :: copy_masses => bd_copy_masses
    procedure :: positions_dlpack => bd_positions_dlpack
    procedure :: velocities_dlpack => bd_velocities_dlpack
    procedure :: forces_dlpack => bd_forces_dlpack
    procedure :: atom_energies_dlpack => bd_atom_energies_dlpack
    procedure :: masses_dlpack => bd_masses_dlpack
    procedure :: atom_ids_dlpack => bd_atom_ids_dlpack
    procedure :: dlpack_delete => bd_dlpack_delete
  end type

  type :: writer_t
    private
    type(c_ptr) :: w = c_null_ptr
  contains
    procedure :: valid => wr_valid
    procedure :: free => wr_free
    procedure :: extend_one => wr_extend_one
  end type

  interface
    function c_rkr_con_spec_version() bind(C, name="rkr_con_spec_version")
      import :: c_int32_t
      integer(c_int32_t) :: c_rkr_con_spec_version
    end function
    function c_rkr_library_version() bind(C, name="rkr_library_version")
      import :: c_ptr
      type(c_ptr) :: c_rkr_library_version
    end function
    function c_rkr_has_chemfiles_support() bind(C, name="rkr_has_chemfiles_support")
      import :: c_int8_t
      integer(c_int8_t) :: c_rkr_has_chemfiles_support
    end function
    function c_rkr_status_message(st) bind(C, name="rkr_status_message")
      import :: c_int, c_ptr
      integer(c_int), value :: st
      type(c_ptr) :: c_rkr_status_message
    end function
    function c_rkr_read_first_frame(fn) bind(C, name="rkr_read_first_frame")
      import :: c_char, c_ptr
      character(kind=c_char), intent(in) :: fn(*)
      type(c_ptr) :: c_rkr_read_first_frame
    end function
    subroutine c_free_rkr_frame(f) bind(C, name="free_rkr_frame")
      import :: c_ptr
      type(c_ptr), value :: f
    end subroutine
    function c_rkr_frame_to_c_frame(f) bind(C, name="rkr_frame_to_c_frame")
      import :: c_ptr
      type(c_ptr), value :: f
      type(c_ptr) :: c_rkr_frame_to_c_frame
    end function
    subroutine c_free_c_frame(f) bind(C, name="free_c_frame")
      import :: c_ptr
      type(c_ptr), value :: f
    end subroutine
    function c_rkr_frame_metadata_json(f) bind(C, name="rkr_frame_metadata_json")
      import :: c_ptr
      type(c_ptr), value :: f
      type(c_ptr) :: c_rkr_frame_metadata_json
    end function
    function c_rkr_frame_energy(f) bind(C, name="rkr_frame_energy")
      import :: c_ptr, c_double
      type(c_ptr), value :: f
      real(c_double) :: c_rkr_frame_energy
    end function
    function c_rkr_frame_potential_type(f) bind(C, name="rkr_frame_potential_type")
      import :: c_ptr
      type(c_ptr), value :: f
      type(c_ptr) :: c_rkr_frame_potential_type
    end function
    function c_rkr_frame_frame_index(f) bind(C, name="rkr_frame_frame_index")
      import :: c_ptr, c_int64_t
      type(c_ptr), value :: f
      integer(c_int64_t) :: c_rkr_frame_frame_index
    end function
    function c_rkr_frame_time(f) bind(C, name="rkr_frame_time")
      import :: c_ptr, c_double
      type(c_ptr), value :: f
      real(c_double) :: c_rkr_frame_time
    end function
    function c_rkr_frame_timestep(f) bind(C, name="rkr_frame_timestep")
      import :: c_ptr, c_double
      type(c_ptr), value :: f
      real(c_double) :: c_rkr_frame_timestep
    end function
    function c_rkr_frame_neb_bead(f) bind(C, name="rkr_frame_neb_bead")
      import :: c_ptr, c_int64_t
      type(c_ptr), value :: f
      integer(c_int64_t) :: c_rkr_frame_neb_bead
    end function
    function c_rkr_frame_neb_band(f) bind(C, name="rkr_frame_neb_band")
      import :: c_ptr, c_int64_t
      type(c_ptr), value :: f
      integer(c_int64_t) :: c_rkr_frame_neb_band
    end function
    function c_rkr_frame_bond_count(f) bind(C, name="rkr_frame_bond_count")
      import :: c_ptr, c_int64_t
      type(c_ptr), value :: f
      integer(c_int64_t) :: c_rkr_frame_bond_count
    end function
    function c_rkr_frame_bond_at(f, idx, i, j, has_o, ord) bind(C, name="rkr_frame_bond_at")
      import :: c_ptr, c_int, c_int32_t, c_int64_t, c_int8_t
      type(c_ptr), value :: f
      integer(c_int64_t), value :: idx
      integer(c_int32_t), intent(out) :: i, j, ord
      integer(c_int8_t), intent(out) :: has_o
      integer(c_int) :: c_rkr_frame_bond_at
    end function
    function c_rkr_frame_atom_index_by_id(f, aid) bind(C, name="rkr_frame_atom_index_by_id")
      import :: c_ptr, c_int64_t
      type(c_ptr), value :: f
      integer(c_int64_t), value :: aid
      integer(c_int64_t) :: c_rkr_frame_atom_index_by_id
    end function
    function c_rkr_frame_spec_version(f) bind(C, name="rkr_frame_spec_version")
      import :: c_ptr, c_int32_t
      type(c_ptr), value :: f
      integer(c_int32_t) :: c_rkr_frame_spec_version
    end function
    function c_rkr_symbol_to_z(s) bind(C, name="rkr_symbol_to_z")
      import :: c_char, c_int64_t
      character(kind=c_char), intent(in) :: s(*)
      integer(c_int64_t) :: c_rkr_symbol_to_z
    end function
    function c_rkr_z_to_symbol(z) bind(C, name="rkr_z_to_symbol")
      import :: c_ptr, c_int64_t
      integer(c_int64_t), value :: z
      type(c_ptr) :: c_rkr_z_to_symbol
    end function
    function c_read_con_file_iterator(fn) bind(C, name="read_con_file_iterator")
      import :: c_char, c_ptr
      character(kind=c_char), intent(in) :: fn(*)
      type(c_ptr) :: c_read_con_file_iterator
    end function
    function c_con_frame_iterator_next(it) bind(C, name="con_frame_iterator_next")
      import :: c_ptr
      type(c_ptr), value :: it
      type(c_ptr) :: c_con_frame_iterator_next
    end function
    subroutine c_free_con_frame_iterator(it) bind(C, name="free_con_frame_iterator")
      import :: c_ptr
      type(c_ptr), value :: it
    end subroutine
    function c_create_writer_from_path_c(fn) bind(C, name="create_writer_from_path_c")
      import :: c_char, c_ptr
      character(kind=c_char), intent(in) :: fn(*)
      type(c_ptr) :: c_create_writer_from_path_c
    end function
    subroutine c_free_rkr_writer(w) bind(C, name="free_rkr_writer")
      import :: c_ptr
      type(c_ptr), value :: w
    end subroutine
    function c_rkr_writer_extend(w, frames, n) bind(C, name="rkr_writer_extend")
      import :: c_ptr, c_int, c_size_t
      type(c_ptr), value :: w
      type(c_ptr), intent(in) :: frames(*)
      integer(c_size_t), value :: n
      integer(c_int) :: c_rkr_writer_extend
    end function
    function c_rkr_frame_new(cell, angles, pb0, pb1, pob0, pob1) bind(C, name="rkr_frame_new")
      import :: c_ptr, c_double, c_char
      real(c_double), intent(in) :: cell(*)
      real(c_double), intent(in) :: angles(*)
      type(c_ptr), value :: pb0, pb1, pob0, pob1
      type(c_ptr) :: c_rkr_frame_new
    end function
    function c_rkr_frame_add_atom_with_fixed_mask(b, sym, x, y, z, aid, mass, fx, fy, fz) &
         bind(C, name="rkr_frame_add_atom_with_fixed_mask")
      import :: c_ptr, c_char, c_double, c_int64_t, c_bool, c_int
      type(c_ptr), value :: b
      character(kind=c_char), intent(in) :: sym(*)
      real(c_double), value :: x, y, z, mass
      integer(c_int64_t), value :: aid
      logical(c_bool), value :: fx, fy, fz
      integer(c_int) :: c_rkr_frame_add_atom_with_fixed_mask
    end function
    function c_rkr_frame_builder_set_energy(b, e) bind(C, name="rkr_frame_builder_set_energy")
      import :: c_ptr, c_double, c_int
      type(c_ptr), value :: b
      real(c_double), value :: e
      integer(c_int) :: c_rkr_frame_builder_set_energy
    end function
    function c_rkr_frame_builder_set_metadata_json(b, j) bind(C, name="rkr_frame_builder_set_metadata_json")
      import :: c_ptr, c_char, c_int
      type(c_ptr), value :: b
      character(kind=c_char), intent(in) :: j(*)
      integer(c_int) :: c_rkr_frame_builder_set_metadata_json
    end function
    function c_rkr_frame_builder_set_frame_index(b, i) bind(C, name="rkr_frame_builder_set_frame_index")
      import :: c_ptr, c_int64_t, c_int
      type(c_ptr), value :: b
      integer(c_int64_t), value :: i
      integer(c_int) :: c_rkr_frame_builder_set_frame_index
    end function
    function c_rkr_frame_builder_build(b) bind(C, name="rkr_frame_builder_build")
      import :: c_ptr
      type(c_ptr), value :: b
      type(c_ptr) :: c_rkr_frame_builder_build
    end function
    subroutine c_free_rkr_frame_builder(b) bind(C, name="free_rkr_frame_builder")
      import :: c_ptr
      type(c_ptr), value :: b
    end subroutine
    function c_rkr_frame_select(f, sel, out) bind(C, name="rkr_frame_select")
      import :: c_ptr, c_char, c_int
      type(c_ptr), value :: f
      character(kind=c_char), intent(in) :: sel(*)
      type(c_ptr), intent(out) :: out
      integer(c_int) :: c_rkr_frame_select
    end function
    function c_rkr_selection_result_match_count(r) bind(C, name="rkr_selection_result_match_count")
      import :: c_ptr, c_int64_t
      type(c_ptr), value :: r
      integer(c_int64_t) :: c_rkr_selection_result_match_count
    end function
    subroutine c_rkr_selection_result_free(r) bind(C, name="rkr_selection_result_free")
      import :: c_ptr
      type(c_ptr), value :: r
    end subroutine

    function c_rkr_read_chemfiles_first(fn) bind(C, name="rkr_read_chemfiles_first")
      import :: c_char, c_ptr
      character(kind=c_char), intent(in) :: fn(*)
      type(c_ptr) :: c_rkr_read_chemfiles_first
    end function
    function c_rkr_frame_builder_positions_data(b) bind(C, name="rkr_frame_builder_positions_data")
      import :: c_ptr
      type(c_ptr), value :: b
      type(c_ptr) :: c_rkr_frame_builder_positions_data
    end function
    function c_rkr_frame_builder_masses_data(b) bind(C, name="rkr_frame_builder_masses_data")
      import :: c_ptr
      type(c_ptr), value :: b
      type(c_ptr) :: c_rkr_frame_builder_masses_data
    end function
    function c_rkr_frame_builder_atom_count(b) bind(C, name="rkr_frame_builder_atom_count")
      import :: c_ptr, c_size_t
      type(c_ptr), value :: b
      integer(c_size_t) :: c_rkr_frame_builder_atom_count
    end function
    function c_rkr_frame_builder_positions_dlpack(b, out) bind(C, name="rkr_frame_builder_positions_dlpack")
      import :: c_ptr, c_int
      type(c_ptr), value :: b
      type(c_ptr), intent(out) :: out
      integer(c_int) :: c_rkr_frame_builder_positions_dlpack
    end function
    function c_rkr_frame_builder_masses_dlpack(b, out) bind(C, name="rkr_frame_builder_masses_dlpack")
      import :: c_ptr, c_int
      type(c_ptr), value :: b
      type(c_ptr), intent(out) :: out
      integer(c_int) :: c_rkr_frame_builder_masses_dlpack
    end function

    function c_rkr_frame_builder_velocities_dlpack(b, out) bind(C, name="rkr_frame_builder_velocities_dlpack")
      import :: c_ptr, c_int
      type(c_ptr), value :: b
      type(c_ptr), intent(out) :: out
      integer(c_int) :: c_rkr_frame_builder_velocities_dlpack
    end function
    function c_rkr_frame_builder_forces_dlpack(b, out) bind(C, name="rkr_frame_builder_forces_dlpack")
      import :: c_ptr, c_int
      type(c_ptr), value :: b
      type(c_ptr), intent(out) :: out
      integer(c_int) :: c_rkr_frame_builder_forces_dlpack
    end function
    function c_rkr_frame_builder_atom_energies_dlpack(b, out) bind(C, name="rkr_frame_builder_atom_energies_dlpack")
      import :: c_ptr, c_int
      type(c_ptr), value :: b
      type(c_ptr), intent(out) :: out
      integer(c_int) :: c_rkr_frame_builder_atom_energies_dlpack
    end function
    function c_rkr_frame_builder_atom_ids_dlpack(b, out) bind(C, name="rkr_frame_builder_atom_ids_dlpack")
      import :: c_ptr, c_int
      type(c_ptr), value :: b
      type(c_ptr), intent(out) :: out
      integer(c_int) :: c_rkr_frame_builder_atom_ids_dlpack
    end function
#ifdef READCON_HAS_METATENSOR
    function c_rkr_frame_metatensor_positions_block(f, out) bind(C, name="rkr_frame_metatensor_positions_block")
      import :: c_ptr, c_int
      type(c_ptr), value :: f
      type(c_ptr), intent(out) :: out
      integer(c_int) :: c_rkr_frame_metatensor_positions_block
    end function
    subroutine c_rkr_mts_block_free(b) bind(C, name="rkr_mts_block_free")
      import :: c_ptr
      type(c_ptr), value :: b
    end subroutine
#endif
    subroutine c_rkr_dlpack_delete(tensor) bind(C, name="rkr_dlpack_delete")
      import :: c_ptr
      type(c_ptr), value :: tensor
    end subroutine
    function c_rkr_selection_result_primary_indices(r, out_idx, capacity, out_written) &
         bind(C, name="rkr_selection_result_primary_indices")
      import :: c_ptr, c_int, c_int64_t
      type(c_ptr), value :: r
      integer(c_int64_t), intent(out) :: out_idx(*)
      integer(c_int64_t), value :: capacity
      integer(c_int64_t), intent(out) :: out_written
      integer(c_int) :: c_rkr_selection_result_primary_indices
    end function
    subroutine c_rkr_free_string(s) bind(C, name="rkr_free_string")
      import :: c_ptr
      type(c_ptr), value :: s
    end subroutine
  end interface

contains

  subroutine to_c(f, c)
    character(len=*), intent(in) :: f
    character(kind=c_char), allocatable, intent(out) :: c(:)
    integer :: n, i
    n = len_trim(f)
    allocate(c(n+1))
    do i = 1, n
      c(i) = f(i:i)
    end do
    c(n+1) = c_null_char
  end subroutine

  function from_c(p, owned) result(s)
    type(c_ptr), intent(in) :: p
    logical, intent(in) :: owned
    character(len=:), allocatable :: s
    character(kind=c_char), pointer :: fp(:)
    integer :: n, i
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
    if (owned) call c_rkr_free_string(p)
  end function

  integer function con_spec_version()
    con_spec_version = int(c_rkr_con_spec_version())
  end function

  function library_version() result(s)
    character(len=:), allocatable :: s
    s = from_c(c_rkr_library_version(), .false.)
  end function

  logical function has_chemfiles_support()
    has_chemfiles_support = (c_rkr_has_chemfiles_support() /= 0_c_int8_t)
  end function

  function status_message(st) result(s)
    integer, intent(in) :: st
    character(len=:), allocatable :: s
    s = from_c(c_rkr_status_message(int(st, c_int)), .false.)
  end function

  integer(int64) function symbol_to_z(sym)
    character(len=*), intent(in) :: sym
    character(kind=c_char), allocatable :: c(:)
    call to_c(sym, c)
    symbol_to_z = c_rkr_symbol_to_z(c)
  end function

  function z_to_symbol(z) result(s)
    integer(int64), intent(in) :: z
    character(len=:), allocatable :: s
    s = from_c(c_rkr_z_to_symbol(int(z, c_int64_t)), .false.)
  end function

  function read_first_frame(path) result(fr)
    character(len=*), intent(in) :: path
    type(frame_t) :: fr
    character(kind=c_char), allocatable :: c(:)
    call to_c(path, c)
    fr%handle = c_rkr_read_first_frame(c)
    fr%cview = c_null_ptr
  end function

  function open_iterator(path) result(it)
    character(len=*), intent(in) :: path
    type(iterator_t) :: it
    character(kind=c_char), allocatable :: c(:)
    call to_c(path, c)
    it%it = c_read_con_file_iterator(c)
  end function

  logical function fr_valid(self)
    class(frame_t), intent(in) :: self
    fr_valid = c_associated(self%handle)
  end function

  subroutine fr_free(self)
    class(frame_t), intent(inout) :: self
    if (c_associated(self%cview)) then
      call c_free_c_frame(self%cview)
      self%cview = c_null_ptr
    end if
    if (c_associated(self%handle)) then
      call c_free_rkr_frame(self%handle)
      self%handle = c_null_ptr
    end if
  end subroutine

  type(c_ptr) function fr_handle(self)
    class(frame_t), intent(in) :: self
    fr_handle = self%handle
  end function

  subroutine ensure_view(self)
    class(frame_t), intent(inout) :: self
    if (c_associated(self%handle) .and. .not. c_associated(self%cview)) then
      self%cview = c_rkr_frame_to_c_frame(self%handle)
    end if
  end subroutine

  integer function fr_natoms(self)
    class(frame_t), intent(inout) :: self
    type(cframe_t), pointer :: cf
    fr_natoms = 0
    call ensure_view(self)
    if (.not. c_associated(self%cview)) return
    call c_f_pointer(self%cview, cf)
    fr_natoms = int(cf%num_atoms)
  end function

  function fr_atom(self, i) result(a)
    class(frame_t), intent(inout) :: self
    integer, intent(in) :: i
    type(catom_t) :: a
    type(cframe_t), pointer :: cf
    type(catom_t), pointer :: atoms(:)
    a = catom_t()
    call ensure_view(self)
    if (.not. c_associated(self%cview)) return
    call c_f_pointer(self%cview, cf)
    if (i < 1 .or. i > int(cf%num_atoms) .or. .not. c_associated(cf%atoms)) return
    call c_f_pointer(cf%atoms, atoms, [int(cf%num_atoms)])
    a = atoms(i)
  end function

  subroutine fr_cell(self, v)
    class(frame_t), intent(inout) :: self
    real(real64), intent(out) :: v(3)
    type(cframe_t), pointer :: cf
    v = 0.0_real64
    call ensure_view(self)
    if (.not. c_associated(self%cview)) return
    call c_f_pointer(self%cview, cf)
    v = real(cf%cell, real64)
  end subroutine

  subroutine fr_angles(self, v)
    class(frame_t), intent(inout) :: self
    real(real64), intent(out) :: v(3)
    type(cframe_t), pointer :: cf
    v = 0.0_real64
    call ensure_view(self)
    if (.not. c_associated(self%cview)) return
    call c_f_pointer(self%cview, cf)
    v = real(cf%angles, real64)
  end subroutine

  logical function fr_has_vel(self)
    class(frame_t), intent(inout) :: self
    type(cframe_t), pointer :: cf
    fr_has_vel = .false.
    call ensure_view(self)
    if (.not. c_associated(self%cview)) return
    call c_f_pointer(self%cview, cf)
    fr_has_vel = logical(cf%has_velocities)
  end function

  logical function fr_has_frc(self)
    class(frame_t), intent(inout) :: self
    type(cframe_t), pointer :: cf
    fr_has_frc = .false.
    call ensure_view(self)
    if (.not. c_associated(self%cview)) return
    call c_f_pointer(self%cview, cf)
    fr_has_frc = logical(cf%has_forces)
  end function

  function fr_meta(self) result(s)
    class(frame_t), intent(in) :: self
    character(len=:), allocatable :: s
    s = ""
    if (.not. c_associated(self%handle)) return
    s = from_c(c_rkr_frame_metadata_json(self%handle), .true.)
  end function

  real(real64) function fr_energy(self)
    class(frame_t), intent(in) :: self
    fr_energy = 0.0_real64
    if (.not. c_associated(self%handle)) return
    fr_energy = real(c_rkr_frame_energy(self%handle), real64)
  end function

  function fr_pot(self) result(s)
    class(frame_t), intent(in) :: self
    character(len=:), allocatable :: s
    s = ""
    if (.not. c_associated(self%handle)) return
    s = from_c(c_rkr_frame_potential_type(self%handle), .true.)
  end function

  integer(int64) function fr_fidx(self)
    class(frame_t), intent(in) :: self
    fr_fidx = -1_int64
    if (.not. c_associated(self%handle)) return
    fr_fidx = c_rkr_frame_frame_index(self%handle)
  end function

  real(real64) function fr_time(self)
    class(frame_t), intent(in) :: self
    fr_time = 0.0_real64
    if (.not. c_associated(self%handle)) return
    fr_time = real(c_rkr_frame_time(self%handle), real64)
  end function

  real(real64) function fr_dt(self)
    class(frame_t), intent(in) :: self
    fr_dt = 0.0_real64
    if (.not. c_associated(self%handle)) return
    fr_dt = real(c_rkr_frame_timestep(self%handle), real64)
  end function

  integer(int64) function fr_neb_bead(self)
    class(frame_t), intent(in) :: self
    fr_neb_bead = -1_int64
    if (.not. c_associated(self%handle)) return
    fr_neb_bead = c_rkr_frame_neb_bead(self%handle)
  end function

  integer(int64) function fr_neb_band(self)
    class(frame_t), intent(in) :: self
    fr_neb_band = -1_int64
    if (.not. c_associated(self%handle)) return
    fr_neb_band = c_rkr_frame_neb_band(self%handle)
  end function

  integer function fr_nbonds(self)
    class(frame_t), intent(in) :: self
    fr_nbonds = 0
    if (.not. c_associated(self%handle)) return
    fr_nbonds = int(c_rkr_frame_bond_count(self%handle))
  end function

  integer function fr_bond_at(self, idx0, i, j, order, has_order)
    class(frame_t), intent(in) :: self
    integer, intent(in) :: idx0
    integer, intent(out) :: i, j, order
    logical, intent(out) :: has_order
    integer(c_int32_t) :: ci, cj, co
    integer(c_int8_t) :: ho
    integer(c_int) :: st
    i = 0; j = 0; order = 0; has_order = .false.
    fr_bond_at = rkr_status_null_pointer
    if (.not. c_associated(self%handle)) return
    st = c_rkr_frame_bond_at(self%handle, int(idx0, c_int64_t), ci, cj, ho, co)
    fr_bond_at = int(st)
    if (st == 0) then
      i = int(ci); j = int(cj); order = int(co)
      has_order = (ho /= 0_c_int8_t)
    end if
  end function

  integer(int64) function fr_id_index(self, atom_id)
    class(frame_t), intent(in) :: self
    integer(int64), intent(in) :: atom_id
    fr_id_index = -1_int64
    if (.not. c_associated(self%handle)) return
    fr_id_index = c_rkr_frame_atom_index_by_id(self%handle, int(atom_id, c_int64_t))
    if (fr_id_index == huge(0_c_int64_t)) fr_id_index = -1_int64
  end function

  integer function fr_spec(self)
    class(frame_t), intent(in) :: self
    fr_spec = 0
    if (.not. c_associated(self%handle)) return
    fr_spec = int(c_rkr_frame_spec_version(self%handle))
  end function

  integer function fr_select(self, selection, nmatch)
    class(frame_t), intent(in) :: self
    character(len=*), intent(in) :: selection
    integer, intent(out) :: nmatch
    character(kind=c_char), allocatable :: csel(:)
    type(c_ptr) :: res
    integer(c_int) :: st
    nmatch = 0
    fr_select = rkr_status_null_pointer
    if (.not. c_associated(self%handle)) return
    call to_c(selection, csel)
    st = c_rkr_frame_select(self%handle, csel, res)
    fr_select = int(st)
    if (st == 0 .and. c_associated(res)) then
      nmatch = int(c_rkr_selection_result_match_count(res))
      call c_rkr_selection_result_free(res)
    end if
  end function

  integer function fr_write_path(self, path)
    class(frame_t), intent(in) :: self
    character(len=*), intent(in) :: path
    type(writer_t) :: w
    fr_write_path = rkr_status_null_pointer
    if (.not. c_associated(self%handle)) return
    w = open_writer(path)
    if (.not. w%valid()) return
    fr_write_path = w%extend_one(self)
    call w%free()
  end function

  logical function it_valid(self)
    class(iterator_t), intent(in) :: self
    it_valid = c_associated(self%it)
  end function

  function it_next(self) result(fr)
    class(iterator_t), intent(inout) :: self
    type(frame_t) :: fr
    fr%handle = c_null_ptr
    fr%cview = c_null_ptr
    if (.not. c_associated(self%it)) return
    fr%handle = c_con_frame_iterator_next(self%it)
  end function

  subroutine it_free(self)
    class(iterator_t), intent(inout) :: self
    if (c_associated(self%it)) then
      call c_free_con_frame_iterator(self%it)
      self%it = c_null_ptr
    end if
  end subroutine

  function new_builder(cell, angles) result(bd)
    real(real64), intent(in) :: cell(3), angles(3)
    type(builder_t) :: bd
    real(c_double) :: cc(3), aa(3)
    cc = real(cell, c_double)
    aa = real(angles, c_double)
    bd%b = c_rkr_frame_new(cc, aa, c_null_ptr, c_null_ptr, c_null_ptr, c_null_ptr)
  end function

  logical function bd_valid(self)
    class(builder_t), intent(in) :: self
    bd_valid = c_associated(self%b)
  end function

  subroutine bd_free(self)
    class(builder_t), intent(inout) :: self
    if (c_associated(self%b)) then
      call c_free_rkr_frame_builder(self%b)
      self%b = c_null_ptr
    end if
  end subroutine

  integer function bd_add_atom(self, symbol, x, y, z, atom_id, mass, fixed_x, fixed_y, fixed_z)
    class(builder_t), intent(inout) :: self
    character(len=*), intent(in) :: symbol
    real(real64), intent(in) :: x, y, z, mass
    integer(int64), intent(in) :: atom_id
    logical, intent(in) :: fixed_x, fixed_y, fixed_z
    character(kind=c_char), allocatable :: cs(:)
    bd_add_atom = rkr_status_null_pointer
    if (.not. c_associated(self%b)) return
    call to_c(symbol, cs)
    bd_add_atom = int(c_rkr_frame_add_atom_with_fixed_mask(self%b, cs, &
         real(x,c_double), real(y,c_double), real(z,c_double), int(atom_id,c_int64_t), &
         real(mass,c_double), logical(fixed_x,c_bool), logical(fixed_y,c_bool), logical(fixed_z,c_bool)))
  end function

  integer function bd_set_energy(self, energy)
    class(builder_t), intent(inout) :: self
    real(real64), intent(in) :: energy
    bd_set_energy = rkr_status_null_pointer
    if (.not. c_associated(self%b)) return
    bd_set_energy = int(c_rkr_frame_builder_set_energy(self%b, real(energy, c_double)))
  end function

  integer function bd_set_meta(self, json)
    class(builder_t), intent(inout) :: self
    character(len=*), intent(in) :: json
    character(kind=c_char), allocatable :: cj(:)
    bd_set_meta = rkr_status_null_pointer
    if (.not. c_associated(self%b)) return
    call to_c(json, cj)
    bd_set_meta = int(c_rkr_frame_builder_set_metadata_json(self%b, cj))
  end function

  integer function bd_set_fidx(self, idx)
    class(builder_t), intent(inout) :: self
    integer(int64), intent(in) :: idx
    bd_set_fidx = rkr_status_null_pointer
    if (.not. c_associated(self%b)) return
    bd_set_fidx = int(c_rkr_frame_builder_set_frame_index(self%b, int(idx, c_int64_t)))
  end function

  function bd_build(self) result(fr)
    class(builder_t), intent(inout) :: self
    type(frame_t) :: fr
    fr%handle = c_null_ptr
    fr%cview = c_null_ptr
    if (.not. c_associated(self%b)) return
    fr%handle = c_rkr_frame_builder_build(self%b)
    self%b = c_null_ptr  ! consumed
  end function

  function open_writer(path) result(w)
    character(len=*), intent(in) :: path
    type(writer_t) :: w
    character(kind=c_char), allocatable :: c(:)
    call to_c(path, c)
    w%w = c_create_writer_from_path_c(c)
  end function

  logical function wr_valid(self)
    class(writer_t), intent(in) :: self
    wr_valid = c_associated(self%w)
  end function

  subroutine wr_free(self)
    class(writer_t), intent(inout) :: self
    if (c_associated(self%w)) then
      call c_free_rkr_writer(self%w)
      self%w = c_null_ptr
    end if
  end subroutine

  integer function wr_extend_one(self, fr)
    class(writer_t), intent(inout) :: self
    class(frame_t), intent(in) :: fr
    type(c_ptr) :: arr(1)
    wr_extend_one = rkr_status_null_pointer
    if (.not. c_associated(self%w) .or. .not. c_associated(fr%handle)) return
    arr(1) = fr%handle
    wr_extend_one = int(c_rkr_writer_extend(self%w, arr, 1_c_size_t))
  end function

  function read_chemfiles_first(path) result(fr)
    character(len=*), intent(in) :: path
    type(frame_t) :: fr
    character(kind=c_char), allocatable :: c(:)
    fr%handle = c_null_ptr
    fr%cview = c_null_ptr
    call to_c(path, c)
    fr%handle = c_rkr_read_chemfiles_first(c)
  end function

  integer function fr_select_primary(self, selection, indices, nwritten)
    class(frame_t), intent(in) :: self
    character(len=*), intent(in) :: selection
    integer(int64), intent(out) :: indices(:)
    integer, intent(out) :: nwritten
    character(kind=c_char), allocatable :: csel(:)
    type(c_ptr) :: res
    integer(c_int) :: st
    integer(c_int64_t) :: written, i
    integer(c_int64_t), allocatable :: buf(:)
    nwritten = 0
    fr_select_primary = rkr_status_null_pointer
    if (.not. c_associated(self%handle)) return
    call to_c(selection, csel)
    st = c_rkr_frame_select(self%handle, csel, res)
    fr_select_primary = int(st)
    if (st /= 0 .or. .not. c_associated(res)) return
    allocate(buf(size(indices)))
    st = c_rkr_selection_result_primary_indices(res, buf, int(size(indices), c_int64_t), written)
    fr_select_primary = int(st)
    if (st == 0) then
      nwritten = int(written)
      do i = 1_c_int64_t, written
        indices(i) = buf(i)
      end do
    end if
    call c_rkr_selection_result_free(res)
  end function

  integer function bd_copy_positions(self, pos)
    class(builder_t), intent(inout) :: self
    real(real64), intent(out) :: pos(:,:)
    type(c_ptr) :: p
    real(c_double), pointer :: flat(:)
    integer :: n, i, j
    bd_copy_positions = rkr_status_null_pointer
    if (.not. c_associated(self%b)) return
    n = int(c_rkr_frame_builder_atom_count(self%b))
    if (n <= 0) return
    if (size(pos, 1) < 3 .or. size(pos, 2) < n) then
      bd_copy_positions = -6
      return
    end if
    p = c_rkr_frame_builder_positions_data(self%b)
    if (.not. c_associated(p)) return
    call c_f_pointer(p, flat, [3 * n])
    do i = 1, n
      do j = 1, 3
        pos(j, i) = real(flat((i - 1) * 3 + j), real64)
      end do
    end do
    bd_copy_positions = 0
  end function

  integer function bd_copy_masses(self, masses)
    class(builder_t), intent(inout) :: self
    real(real64), intent(out) :: masses(:)
    type(c_ptr) :: p
    real(c_double), pointer :: flat(:)
    integer :: n, i
    bd_copy_masses = rkr_status_null_pointer
    if (.not. c_associated(self%b)) return
    n = int(c_rkr_frame_builder_atom_count(self%b))
    if (n <= 0 .or. size(masses) < n) then
      bd_copy_masses = -6
      return
    end if
    p = c_rkr_frame_builder_masses_data(self%b)
    if (.not. c_associated(p)) return
    call c_f_pointer(p, flat, [n])
    do i = 1, n
      masses(i) = real(flat(i), real64)
    end do
    bd_copy_masses = 0
  end function

  integer function bd_positions_dlpack(self, tensor)
    class(builder_t), intent(inout) :: self
    type(c_ptr), intent(out) :: tensor
    bd_positions_dlpack = rkr_status_null_pointer
    tensor = c_null_ptr
    if (.not. c_associated(self%b)) return
    bd_positions_dlpack = int(c_rkr_frame_builder_positions_dlpack(self%b, tensor))
  end function

  integer function bd_masses_dlpack(self, tensor)
    class(builder_t), intent(inout) :: self
    type(c_ptr), intent(out) :: tensor
    bd_masses_dlpack = rkr_status_null_pointer
    tensor = c_null_ptr
    if (.not. c_associated(self%b)) return
    bd_masses_dlpack = int(c_rkr_frame_builder_masses_dlpack(self%b, tensor))
  end function

  subroutine bd_dlpack_delete(self, tensor)
    class(builder_t), intent(in) :: self
    type(c_ptr), intent(inout) :: tensor
    if (c_associated(self%b)) continue
    if (c_associated(tensor)) then
      call c_rkr_dlpack_delete(tensor)
      tensor = c_null_ptr
    end if
  end subroutine

  subroutine dlpack_inspect(tensor, ndim, shape0, shape1, dtype_bits, ok)
    type(c_ptr), intent(in) :: tensor
    integer, intent(out) :: ndim, dtype_bits
    integer(int64), intent(out) :: shape0, shape1
    logical, intent(out) :: ok
    type(dl_managed_tensor_versioned_t), pointer :: mt
    integer(c_int64_t), pointer :: shp(:)
    ok = .false.
    ndim = 0
    shape0 = 0_int64
    shape1 = 0_int64
    dtype_bits = 0
    if (.not. c_associated(tensor)) return
    call c_f_pointer(tensor, mt)
    ndim = int(mt%dl_tensor%ndim)
    dtype_bits = int(mt%dl_tensor%dtype%bits)
    if (ndim >= 1 .and. c_associated(mt%dl_tensor%shape)) then
      call c_f_pointer(mt%dl_tensor%shape, shp, [ndim])
      shape0 = shp(1)
      if (ndim >= 2) shape1 = shp(2)
    end if
    ok = .true.
  end subroutine

  integer function bd_velocities_dlpack(self, tensor)
    class(builder_t), intent(inout) :: self
    type(c_ptr), intent(out) :: tensor
    tensor = c_null_ptr
    bd_velocities_dlpack = rkr_status_null_pointer
    if (.not. c_associated(self%b)) return
    bd_velocities_dlpack = int(c_rkr_frame_builder_velocities_dlpack(self%b, tensor))
  end function

  integer function bd_forces_dlpack(self, tensor)
    class(builder_t), intent(inout) :: self
    type(c_ptr), intent(out) :: tensor
    tensor = c_null_ptr
    bd_forces_dlpack = rkr_status_null_pointer
    if (.not. c_associated(self%b)) return
    bd_forces_dlpack = int(c_rkr_frame_builder_forces_dlpack(self%b, tensor))
  end function

  integer function bd_atom_energies_dlpack(self, tensor)
    class(builder_t), intent(inout) :: self
    type(c_ptr), intent(out) :: tensor
    tensor = c_null_ptr
    bd_atom_energies_dlpack = rkr_status_null_pointer
    if (.not. c_associated(self%b)) return
    bd_atom_energies_dlpack = int(c_rkr_frame_builder_atom_energies_dlpack(self%b, tensor))
  end function

  integer function bd_atom_ids_dlpack(self, tensor)
    class(builder_t), intent(inout) :: self
    type(c_ptr), intent(out) :: tensor
    tensor = c_null_ptr
    bd_atom_ids_dlpack = rkr_status_null_pointer
    if (.not. c_associated(self%b)) return
    bd_atom_ids_dlpack = int(c_rkr_frame_builder_atom_ids_dlpack(self%b, tensor))
  end function

  integer function frame_metatensor_positions_block(fr, block)
    type(frame_t), intent(in) :: fr
    type(c_ptr), intent(out) :: block
    block = c_null_ptr
    frame_metatensor_positions_block = rkr_status_null_pointer
    if (.not. c_associated(fr%handle)) return
#ifdef READCON_HAS_METATENSOR
    frame_metatensor_positions_block = int(c_rkr_frame_metatensor_positions_block(fr%handle, block))
#else
    frame_metatensor_positions_block = rkr_status_internal_error
    block = c_null_ptr
#endif
  end function

  subroutine mts_block_free_rkr(block)
    type(c_ptr), intent(inout) :: block
#ifdef READCON_HAS_METATENSOR
    if (c_associated(block)) then
      call c_rkr_mts_block_free(block)
      block = c_null_ptr
    end if
#else
    block = c_null_ptr
#endif
  end subroutine


end module readcon
