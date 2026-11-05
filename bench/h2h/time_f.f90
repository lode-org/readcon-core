program time_f
  use iso_c_binding
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
    do i = 1, repeats
      call wall(t0)
      frames = read_all_frames(trim(path), 1)
      call wall(t1)
      write(*, "(A,1X,F16.9)") "read", t1 - t0
    end do
  else
    frames = read_all_frames(trim(path), 1)
    do i = 1, repeats
      call wall(t0)
      writer = open_writer(trim(out))
      stat = writer%extend_one(frames(1))
      call writer%free()
      call wall(t1)
      if (stat /= 0) stop 1
      write(*, "(A,1X,F16.9)") "write", t1 - t0
    end do
  end if
  hwm = vm_hwm()
  write(*, "(A,1X,I0)") "hwm_kib", hwm
contains
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
end program
