! Fortran 2008 drift driver. Uses only the C-interoperable ReadCon API
! (read_all_frames / open_writer / extend_one, which bind to readcon-core.h).
!
!   drift_fortran FILE...
! CSV: file,fortran,sha_fortran,rewrite_stable_fortran
program drift_fortran
  use, intrinsic :: iso_c_binding
  use, intrinsic :: iso_fortran_env, only: int8
  use readcon
  implicit none

  integer :: narg, i, ios
  character(len=4096) :: path
  character(len=16) :: decision, digest, stable

  print '(a)', 'file,fortran,sha_fortran,rewrite_stable_fortran'
  narg = command_argument_count()
  do i = 1, narg
    call get_command_argument(i, path)
    call classify(trim(path), decision, digest, stable)
    print '(a)', trim(basename(trim(path))) // ',' // trim(decision) // ',' // &
         trim(digest) // ',' // trim(stable)
  end do
  if (narg == 0) stop 2

contains

  function basename(path) result(name)
    character(len=*), intent(in) :: path
    character(len=:), allocatable :: name
    integer :: slash
    slash = index(path, '/', back=.true.)
    if (slash == 0) then
      name = trim(path)
    else
      name = trim(path(slash+1:))
    end if
  end function

  subroutine classify(path, decision, digest, stable)
    character(len=*), intent(in) :: path
    character(len=*), intent(out) :: decision, digest, stable
    type(frame_t), allocatable :: frames(:), again(:)
    character(len=:), allocatable :: first, second
    integer :: n, st
    logical :: same

    decision = 'reject'
    digest = '-'
    stable = '-'
    frames = read_all_frames(trim(path))
    n = 0
    if (allocated(frames)) n = size(frames)
    if (n <= 0) return
    if (.not. frames(1)%valid()) return

    decision = 'accept'
    first = trim(path) // '.drift1.con'
    second = trim(path) // '.drift2.con'
    st = write_frames(first, frames)
    if (st /= 0) then
      digest = 'error'
      stable = 'no'
      call frames_free(frames)
      return
    end if
    digest = sha12_file(first)
    again = read_all_frames(first)
    if (.not. allocated(again) .or. size(again) /= n) then
      stable = 'no'
    else
      st = write_frames(second, again)
      if (st /= 0) then
        stable = 'no'
      else
        same = files_equal(first, second)
        if (same) then
          stable = 'yes'
        else
          stable = 'no'
        end if
      end if
      call frames_free(again)
    end if
    call frames_free(frames)
    open(newunit=ios, file=first, status='old', iostat=st)
    if (st == 0) close(ios, status='delete')
    open(newunit=ios, file=second, status='old', iostat=st)
    if (st == 0) close(ios, status='delete')
  end subroutine

  subroutine frames_free(frames)
    type(frame_t), allocatable, intent(inout) :: frames(:)
    integer :: i
    if (.not. allocated(frames)) return
    do i = 1, size(frames)
      call frames(i)%free()
    end do
  end subroutine

  integer function write_frames(path, frames)
    character(len=*), intent(in) :: path
    type(frame_t), intent(in) :: frames(:)
    type(writer_t) :: writer
    integer :: i, st
    write_frames = -1
    writer = open_writer(trim(path))
    if (.not. writer%valid()) return
    do i = 1, size(frames)
      st = writer%extend_one(frames(i))
      if (st /= 0) then
        call writer%free()
        write_frames = st
        return
      end if
    end do
    call writer%free()
    write_frames = 0
  end function

  function sha12_file(path) result(hex12)
    character(len=*), intent(in) :: path
    character(len=12) :: hex12
    integer(c_int8_t), allocatable, target :: buf(:)
    integer(c_int8_t), target :: md(32)
    integer :: unit, st, i, n
    integer(c_size_t) :: nbytes
    character(len=2) :: pair
    character(len=64) :: full
    interface
      function c_sha256(data, n, md) bind(C, name="SHA256")
        import :: c_ptr, c_size_t
        type(c_ptr), value :: data, md
        integer(c_size_t), value :: n
        type(c_ptr) :: c_sha256
      end function
    end interface

    hex12 = '------------'
    open(newunit=unit, file=trim(path), access='stream', form='unformatted', &
         status='old', action='read', iostat=st)
    if (st /= 0) return
    inquire(unit=unit, size=n)
    allocate(buf(n))
    read(unit, iostat=st) buf
    close(unit)
    if (st /= 0) return
    nbytes = int(n, c_size_t)
    if (c_associated(c_sha256(c_loc(buf), nbytes, c_loc(md)))) then
      full = ''
      do i = 1, 32
        write(pair, '(z2.2)') md(i)
        full(2*i-1:2*i) = pair
      end do
      hex12 = full(1:12)
      do i = 1, 12
        if (hex12(i:i) >= 'A' .and. hex12(i:i) <= 'F') then
          hex12(i:i) = achar(iachar(hex12(i:i)) + 32)
        end if
      end do
    end if
  end function

  logical function files_equal(a, b)
    character(len=*), intent(in) :: a, b
    integer :: ua, ub, sa, sb, na, nb, i
    integer(c_int8_t), allocatable :: ba(:), bb(:)
    files_equal = .false.
    open(newunit=ua, file=trim(a), access='stream', form='unformatted', &
         status='old', action='read', iostat=sa)
    open(newunit=ub, file=trim(b), access='stream', form='unformatted', &
         status='old', action='read', iostat=sb)
    if (sa /= 0 .or. sb /= 0) then
      if (sa == 0) close(ua)
      if (sb == 0) close(ub)
      return
    end if
    inquire(unit=ua, size=na)
    inquire(unit=ub, size=nb)
    if (na /= nb) then
      close(ua); close(ub)
      return
    end if
    allocate(ba(na), bb(nb))
    read(ua) ba
    read(ub) bb
    close(ua); close(ub)
    do i = 1, na
      if (ba(i) /= bb(i)) return
    end do
    files_equal = .true.
  end function

end program drift_fortran
