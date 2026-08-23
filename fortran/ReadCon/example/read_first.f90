program read_first
  use readcon
  use, intrinsic :: iso_c_binding, only: c_double
  implicit none
  type(frame_t) :: fr
  real(c_double), pointer :: xyz(:,:)
  integer :: n
  character(len=*), parameter :: path = "resources/test/tiny_cuh2.con"
  fr = read_first_frame(path)
  if (fr%valid()) then
    print *, "atoms:", fr%natoms()
    print *, "metadata:", fr%metadata_json()
    call fr%xyz_ptr(xyz, n)
    if (associated(xyz)) print *, "xyz(:,1) =", xyz(:, 1)
    call fr%free()
  else
    error stop "read failed"
  end if
end program read_first
