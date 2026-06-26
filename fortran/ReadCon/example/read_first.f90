program read_first
  use readcon
  implicit none
  type(frame_t) :: fr
  character(len=*), parameter :: path = &
    "/home/rgoswami/Git/Github/LODE/readcon-core/resources/test/tiny_cuh2.con"
  fr = read_first_frame(path)
  if (fr%valid()) then
    print *, "atoms:", fr%natoms()
    print *, "metadata:", fr%metadata_json()
    call fr%free()
  else
    error stop "read failed"
  end if
end program read_first
