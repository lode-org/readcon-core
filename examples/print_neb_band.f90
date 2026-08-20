! Print energy versus NEB bead for resources/examples/neb_band.con.
!
! Standalone ISO_C_BINDING client; no fpm module required:
!   gfortran -o print_neb_band examples/print_neb_band.f90 -lreadcon_core
!   ./print_neb_band
!   ./print_neb_band path/to/band.con
!
! TSV columns: bead, energy_eV, fmax.
! bead/energy from rkr_frame_neb_bead / rkr_frame_energy (UINT64_MAX / NaN
! => missing). fmax is the metadata JSON key when present, else
! rkr_frame_fmax.
program print_neb_band
  use, intrinsic :: iso_c_binding
  use, intrinsic :: iso_fortran_env, only: error_unit, int64, real64
  use, intrinsic :: ieee_arithmetic
  implicit none

  interface
    function rkr_read_all_frames(fn, nout) bind(C, name="rkr_read_all_frames")
      import :: c_char, c_ptr, c_size_t
      character(kind=c_char), intent(in) :: fn(*)
      integer(c_size_t), intent(out) :: nout
      type(c_ptr) :: rkr_read_all_frames
    end function
    subroutine free_rkr_frame_array(frames, n) bind(C, name="free_rkr_frame_array")
      import :: c_ptr, c_size_t
      type(c_ptr), value :: frames
      integer(c_size_t), value :: n
    end subroutine
    function rkr_frame_energy(f) bind(C, name="rkr_frame_energy")
      import :: c_ptr, c_double
      type(c_ptr), value :: f
      real(c_double) :: rkr_frame_energy
    end function
    function rkr_frame_neb_bead(f) bind(C, name="rkr_frame_neb_bead")
      import :: c_ptr, c_int64_t
      type(c_ptr), value :: f
      integer(c_int64_t) :: rkr_frame_neb_bead
    end function
    function rkr_frame_fmax(f) bind(C, name="rkr_frame_fmax")
      import :: c_ptr, c_double
      type(c_ptr), value :: f
      real(c_double) :: rkr_frame_fmax
    end function
    function rkr_frame_metadata_json(f) bind(C, name="rkr_frame_metadata_json")
      import :: c_ptr
      type(c_ptr), value :: f
      type(c_ptr) :: rkr_frame_metadata_json
    end function
    subroutine rkr_free_string(s) bind(C, name="rkr_free_string")
      import :: c_ptr
      type(c_ptr), value :: s
    end subroutine
    function c_strlen(s) bind(C, name="strlen")
      import :: c_ptr, c_size_t
      type(c_ptr), value :: s
      integer(c_size_t) :: c_strlen
    end function
  end interface

  character(len=:), allocatable :: path
  character(kind=c_char), allocatable :: cpath(:)
  character(len=:), allocatable :: js
  character(kind=c_char), pointer :: ch(:)
  type(c_ptr) :: arr, jp
  type(c_ptr), pointer :: ptrs(:)
  integer(c_size_t) :: n, i, jn, k
  integer(c_int64_t) :: bead
  real(c_double) :: energy, fmax_v
  integer :: arglen, p, ios
  logical :: have_fmax
  integer, parameter :: tab = 9

  if (command_argument_count() > 1) then
    write(error_unit, '(a)') "Usage: print_neb_band [input.con]"
    error stop 1
  end if
  if (command_argument_count() == 1) then
    call get_command_argument(1, length=arglen)
    allocate(character(len=arglen) :: path)
    call get_command_argument(1, value=path)
  else
    path = "resources/examples/neb_band.con"
  end if

  allocate(cpath(len_trim(path) + 1))
  do k = 1_c_size_t, int(len_trim(path), c_size_t)
    cpath(k) = path(int(k):int(k))
  end do
  cpath(len_trim(path) + 1) = c_null_char

  arr = rkr_read_all_frames(cpath, n)
  if (.not. c_associated(arr)) then
    write(error_unit, '(a)') "Error: failed to read " // path
    error stop 1
  end if

  write(*, '(a,1x,a,2x,a,i0)') "#", path, "n_frames=", int(n)
  write(*, '(a)') "bead" // achar(tab) // "energy_eV" // achar(tab) // "fmax"

  if (n > 0_c_size_t) then
    call c_f_pointer(arr, ptrs, [n])
    do k = 1_c_size_t, n
      bead = rkr_frame_neb_bead(ptrs(k))
      energy = rkr_frame_energy(ptrs(k))
      have_fmax = .false.
      jp = rkr_frame_metadata_json(ptrs(k))
      if (c_associated(jp)) then
        jn = c_strlen(jp)
        if (jn > 0_c_size_t) then
          call c_f_pointer(jp, ch, [jn])
          allocate(character(len=int(jn)) :: js)
          do i = 1_c_size_t, jn
            js(int(i):int(i)) = ch(i)
          end do
          p = index(js, '"fmax":')
          if (p > 0) then
            p = p + 7
            do while (p <= len(js) .and. (js(p:p) == ' ' .or. js(p:p) == achar(9)))
              p = p + 1
            end do
            read(js(p:), *, iostat=ios) fmax_v
            have_fmax = (ios == 0) .and. (.not. ieee_is_nan(real(fmax_v, real64)))
          end if
          deallocate(js)
        end if
        call rkr_free_string(jp)
      end if
      if (.not. have_fmax) then
        fmax_v = rkr_frame_fmax(ptrs(k))
        have_fmax = .not. ieee_is_nan(real(fmax_v, real64))
      end if

      if (bead /= -1_c_int64_t) then
        write(*, '(i0)', advance='no') int(bead, int64)
      end if
      write(*, '(a)', advance='no') achar(tab)
      if (.not. ieee_is_nan(real(energy, real64))) then
        write(*, '(g0)', advance='no') real(energy, real64)
      end if
      write(*, '(a)', advance='no') achar(tab)
      if (have_fmax) then
        write(*, '(g0)', advance='no') real(fmax_v, real64)
      end if
      write(*, '(a)')
    end do
  end if

  call free_rkr_frame_array(arr, n)
end program print_neb_band
