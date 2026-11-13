program time_f
  use iso_c_binding
  use iso_fortran_env, only: real64
  use readcon
  implicit none
  character(len=16) :: op
  character(len=1024) :: path, out, count
  integer :: repeats, i, stat, narg
  type(frame_t), allocatable :: frames(:)
  type(writer_t) :: writer
  real(c_double) :: t0, t1
  integer(c_long) :: hwm

  narg = command_argument_count()
  if (narg /= 4) stop 2
  call get_command_argument(1, op)
  call get_command_argument(2, path)
  call get_command_argument(3, out)
  call get_command_argument(4, count)
  read(count, *) repeats

  if (trim(op) == "read") then
    ! Coordinate column, same work as the C and Rust position reads.
    ! One warmup is printed, then `repeats` samples.
    block
      type(position_block_t) :: block
      real(c_double), pointer :: xyz(:, :, :)
      integer :: nf, na
      do i = 0, repeats
        call wall(t0)
        block = read_positions(trim(path), 1)
        call block%xyz_ptr(xyz, nf, na)
        if (.not. associated(xyz)) stop 1
        if (xyz(1, 1, 1) /= xyz(1, 1, 1)) stop 1
        call block%free()
        call wall(t1)
        if (i == 0) then
          write(*, "(A,1X,F16.9)") "warmup", t1 - t0
        else
          write(*, "(A,1X,F16.9)") "read", t1 - t0
        end if
      end do
    end block
  else
    frames = read_all_frames(trim(path), 1)
    do i = 0, repeats
      call wall(t0)
      call unlink_path(trim(out))
      writer = open_writer(trim(out))
      stat = writer%extend_one(frames(1))
      call writer%free()
      call wall(t1)
      if (stat /= 0) stop 1
      if (i == 0) then
        write(*, "(A,1X,F16.9)") "warmup", t1 - t0
      else
        write(*, "(A,1X,F16.9)") "write", t1 - t0
      end if
    end do
    block
      type(frame_t), allocatable :: written(:)
      written = read_all_frames(trim(out), 1)
      call report(written, trim(path))
    end block
  end if
  hwm = vm_hwm()
  write(*, "(A,1X,I0)") "hwm_kib", hwm
contains
  subroutine release_frames(frames)
    type(frame_t), allocatable, intent(inout) :: frames(:)
    integer :: j
    if (.not. allocated(frames)) return
    do j = 1, size(frames)
      call frames(j)%free()
    end do
    deallocate(frames)
  end subroutine

  subroutine unlink_path(path)
    character(len=*), intent(in) :: path
    interface
      function c_unlink(name) bind(C, name="unlink")
        import :: c_char, c_int
        character(kind=c_char), intent(in) :: name(*)
        integer(c_int) :: c_unlink
      end function
    end interface
    character(kind=c_char), allocatable :: name(:)
    integer :: n, j
    n = len_trim(path)
    allocate(name(n + 1))
    do j = 1, n
      name(j) = path(j:j)
    end do
    name(n + 1) = c_null_char
    ! A missing destination is the usual case. The status is not an error.
    if (c_unlink(name) /= 0) then
      return
    end if
  end subroutine

  subroutine wall(t)
    real(c_double), intent(out) :: t
    integer(c_int64_t) :: ticks, rate
    call system_clock(ticks, rate)
    t = real(ticks, c_double) / real(rate, c_double)
  end subroutine

  integer(c_long) function vm_hwm()
    integer :: unit, ios
    character(len=256) :: line
    integer(c_long) :: value
    vm_hwm = 0
    open(newunit=unit, file="/proc/self/status", status="old", action="read")
    do
      read(unit, "(A)", iostat=ios) line
      if (ios /= 0) exit
      if (line(1:6) == "VmHWM:") then
        read(line(7:), *) value
        vm_hwm = value
        exit
      end if
    end do
    close(unit)
  end function

  subroutine report(frames, source)
    type(frame_t), intent(inout) :: frames(:)
    character(len=*), intent(in) :: source
    integer :: i, n, n0, mismatch, unit, ios
    integer :: ref_frames, ref_atoms
    real(real64) :: cell(3), ang(3), worst, delta
    real(real64) :: ref_cell(6)
    real(real64), allocatable :: ref(:, :, :)
    real(c_double), pointer :: xyz(:, :)
    n0 = int(frames(1)%atom_count())
    call frames(1)%cell_lengths(cell)
    call frames(1)%cell_angles(ang)
    mismatch = 0
    worst = 0.0_real64
    open(newunit=unit, file=trim(source)//".ref.bin", access="stream", status="old", iostat=ios)
    if (ios /= 0) then
      worst = 1.0e300_real64
    else
      read(unit) ref_frames, ref_atoms
      read(unit) ref_cell
      if (ref_frames /= size(frames) .or. ref_atoms /= n0) mismatch = 1
      allocate(ref(3, ref_atoms, ref_frames))
      read(unit) ref
      close(unit)
      do i = 1, size(frames)
        n = int(frames(i)%atom_count())
        if (n /= n0) mismatch = 1
        call frames(i)%xyz_ptr(xyz, n)
        if (.not. associated(xyz)) then
          worst = 1.0e300_real64
        else if (i <= ref_frames .and. n == ref_atoms) then
          delta = maxval(abs(xyz(:, 1:n) - ref(:, :, i)))
          if (delta > worst) worst = delta
        else
          mismatch = 1
        end if
      end do
    end if
    write(*, "(A,1X,I0)") "n_frames", size(frames)
    write(*, "(A,1X,I0)") "n_atoms", n0
    write(*, "(A,1X,I0)") "atom_count_mismatch", mismatch
    write(*, "(A,6(1X,ES24.16))") "cell", cell(1), cell(2), cell(3), ang(1), ang(2), ang(3)
    write(*, "(A,1X,ES24.16)") "max_abs", worst
  end subroutine
end program
