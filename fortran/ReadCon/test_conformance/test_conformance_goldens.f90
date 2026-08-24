! Phase A corpus lock: Fortran reads the same goldens as the Python harness.
! Valid fixtures match symbols, atom_ids, fixed, and positions.
! Invalid fixtures must fail to parse.
module conformance_golden_mod
  use readcon
  use, intrinsic :: iso_fortran_env, only: real64, int64
  implicit none
  private
  public :: case_t, slurp, parse_manifest, check_valid, check_invalid

  type :: case_t
    character(len=128) :: id = ""
    character(len=256) :: path = ""
    logical :: valid = .true.
  end type

contains

  function slurp(path) result(s)
    character(len=*), intent(in) :: path
    character(len=:), allocatable :: s
    integer :: u, n, ios
    inquire (file=path, size=n)
    if (n < 0) then
      s = ""
      return
    end if
    allocate (character(len=n) :: s)
    open (newunit=u, file=path, access="stream", form="unformatted", &
          status="old", action="read", iostat=ios)
    if (ios /= 0) then
      s = ""
      return
    end if
    if (n > 0) read (u) s
    close (u)
  end function

  subroutine parse_manifest(text, cases, ncases)
    character(len=*), intent(in) :: text
    type(case_t), allocatable, intent(out) :: cases(:)
    integer, intent(out) :: ncases
    integer :: pos, eol, nalloc, klen
    character(len=512) :: line
    character(len=64) :: key
    character(len=256) :: val
    type(case_t), allocatable :: tmp(:)
    type(case_t) :: cur
    logical :: have

    ncases = 0
    nalloc = 16
    allocate (cases(nalloc))
    have = .false.
    pos = 1
    do while (pos <= len(text))
      eol = index(text(pos:), new_line("a"))
      if (eol == 0) then
        line = text(pos:)
        pos = len(text) + 1
      else
        line = text(pos:pos + eol - 2)
        pos = pos + eol
      end if
      line = adjustl(line)
      klen = len_trim(line)
      if (klen == 0 .or. line(1:1) == "#") cycle
      if (line(1:klen) == "[[valid]]" .or. line(1:klen) == "[[invalid]]") then
        if (have) call push_case(cases, ncases, nalloc, cur)
        cur = case_t()
        cur%valid = (line(1:klen) == "[[valid]]")
        have = .true.
        cycle
      end if
      if (.not. have) cycle
      call split_kv(trim(line), key, val)
      if (trim(key) == "id") cur%id = unquote(trim(val))
      if (trim(key) == "path") cur%path = unquote(trim(val))
    end do
    if (have) call push_case(cases, ncases, nalloc, cur)
    if (ncases > 0) then
      allocate (tmp(ncases))
      tmp = cases(1:ncases)
      call move_alloc(tmp, cases)
    end if
  end subroutine

  subroutine push_case(cases, ncases, nalloc, cur)
    type(case_t), allocatable, intent(inout) :: cases(:)
    integer, intent(inout) :: ncases, nalloc
    type(case_t), intent(in) :: cur
    type(case_t), allocatable :: grow(:)
    if (ncases >= nalloc) then
      nalloc = nalloc * 2
      allocate (grow(nalloc))
      grow(1:ncases) = cases(1:ncases)
      call move_alloc(grow, cases)
    end if
    ncases = ncases + 1
    cases(ncases) = cur
  end subroutine

  subroutine split_kv(line, key, val)
    character(len=*), intent(in) :: line
    character(len=*), intent(out) :: key, val
    integer :: eq
    key = ""
    val = ""
    eq = index(line, "=")
    if (eq == 0) return
    key = adjustl(line(1:eq - 1))
    val = adjustl(line(eq + 1:))
  end subroutine

  function unquote(raw) result(s)
    character(len=*), intent(in) :: raw
    character(len=:), allocatable :: s
    integer :: n
    n = len_trim(raw)
    if (n >= 2 .and. raw(1:1) == '"' .and. raw(n:n) == '"') then
      s = raw(2:n - 1)
    else
      s = trim(raw)
    end if
  end function

  integer function check_valid(root, c) result(nfail)
    character(len=*), intent(in) :: root
    type(case_t), intent(in) :: c
    character(len=:), allocatable :: gtext
    character(len=1024) :: fixture, gpath
    type(frame_t) :: fr
    type(catom_t) :: at
    integer :: n_atoms, spec, i, na
    logical, allocatable :: fx(:,:)
    real(real64), allocatable :: pos(:,:)
    integer(int64), allocatable :: ids(:)
    character(len=8), allocatable :: syms(:)
    character(len=128) :: gid, got_sym
    logical :: exists
    nfail = 0
    fixture = trim(root) // "/resources/conformance/" // trim(c%path)
    gpath = trim(root) // "/resources/conformance/golden/" // trim(c%id) // ".json"
    inquire (file=trim(gpath), exist=exists)
    if (.not. exists) then
      print *, "FAIL ", trim(c%id), ": missing golden"
      nfail = 1
      return
    end if
    fr = read_first_frame(trim(fixture))
    if (.not. fr%valid()) then
      print *, "FAIL ", trim(c%id), ": valid fixture failed to parse"
      nfail = 1
      return
    end if
    gtext = slurp(trim(gpath))
    call parse_golden(gtext, gid, n_atoms, spec, fx, pos, ids, syms)
    if (trim(gid) /= trim(c%id)) then
      print *, "FAIL ", trim(c%id), ": golden id ", trim(gid)
      nfail = nfail + 1
    end if
    na = int(fr%atom_count())
    if (n_atoms /= na) then
      print *, "FAIL ", trim(c%id), ": n_atoms", n_atoms, na
      nfail = nfail + 1
    end if
    if (spec /= int(fr%spec_version())) then
      print *, "FAIL ", trim(c%id), ": spec_version", spec, int(fr%spec_version())
      nfail = nfail + 1
    end if
    if (n_atoms /= na) then
      call fr%free()
      return
    end if
    do i = 1, na
      at = fr%atom(i)
      got_sym = z_to_symbol(int(at%atomic_number, int64))
      if (trim(got_sym) /= trim(syms(i))) then
        print *, "FAIL ", trim(c%id), ": symbol", trim(syms(i)), trim(got_sym)
        nfail = nfail + 1
      end if
      if (at%atom_id /= ids(i)) then
        print *, "FAIL ", trim(c%id), ": atom_id", ids(i), at%atom_id
        nfail = nfail + 1
      end if
      if (logical(at%fixed_x) .neqv. fx(1, i) .or. &
          logical(at%fixed_y) .neqv. fx(2, i) .or. &
          logical(at%fixed_z) .neqv. fx(3, i)) then
        print *, "FAIL ", trim(c%id), ": fixed atom", i
        nfail = nfail + 1
      end if
      if (abs(at%x - pos(1, i)) > 1.0e-12_real64 .or. &
          abs(at%y - pos(2, i)) > 1.0e-12_real64 .or. &
          abs(at%z - pos(3, i)) > 1.0e-12_real64) then
        print *, "FAIL ", trim(c%id), ": positions atom", i
        nfail = nfail + 1
      end if
    end do
    call fr%free()
  end function

  integer function check_invalid(root, c) result(nfail)
    character(len=*), intent(in) :: root
    type(case_t), intent(in) :: c
    character(len=1024) :: fixture, extra
    type(frame_t) :: fr
    logical :: exists
    nfail = 0
    extra = trim(root) // "/resources/conformance/golden/" // trim(c%id) // ".json"
    inquire (file=trim(extra), exist=exists)
    if (exists) then
      print *, "FAIL ", trim(c%id), ": invalid case must not have a golden"
      nfail = nfail + 1
    end if
    fixture = trim(root) // "/resources/conformance/" // trim(c%path)
    fr = read_first_frame(trim(fixture))
    if (fr%valid()) then
      print *, "FAIL ", trim(c%id), ": invalid fixture parsed"
      nfail = nfail + 1
      call fr%free()
    end if
  end function

  subroutine parse_golden(json, gid, n_atoms, spec, fx, pos, ids, syms)
    character(len=*), intent(in) :: json
    character(len=*), intent(out) :: gid
    integer, intent(out) :: n_atoms, spec
    logical, allocatable, intent(out) :: fx(:,:)
    real(real64), allocatable, intent(out) :: pos(:,:)
    integer(int64), allocatable, intent(out) :: ids(:)
    character(len=8), allocatable, intent(out) :: syms(:)
    integer :: p
    gid = json_string(json, "id")
    n_atoms = json_int(json, "n_atoms")
    spec = json_int(json, "spec_version")
    allocate (fx(3, n_atoms), pos(3, n_atoms), ids(n_atoms), syms(n_atoms))
    p = key_pos(json, "fixed")
    call parse_bool_rows(json, p, n_atoms, fx)
    p = key_pos(json, "positions")
    call parse_f64_rows(json, p, n_atoms, pos)
    p = key_pos(json, "atom_ids")
    call parse_int_list(json, p, n_atoms, ids)
    p = key_pos(json, "symbols")
    call parse_str_list(json, p, n_atoms, syms)
  end subroutine

  integer function key_pos(json, key) result(p)
    character(len=*), intent(in) :: json, key
    character(len=:), allocatable :: pat
    integer :: colon
    pat = '"' // trim(key) // '"'
    p = index(json, pat)
    if (p == 0) return
    colon = index(json(p:), ":")
    if (colon == 0) then
      p = 0
      return
    end if
    p = p + colon
  end function

  function json_string(json, key) result(s)
    character(len=*), intent(in) :: json, key
    character(len=128) :: s
    integer :: p, q1, q2
    s = ""
    p = key_pos(json, key)
    if (p == 0) return
    q1 = index(json(p:), '"')
    if (q1 == 0) return
    q1 = p + q1 - 1
    q2 = index(json(q1 + 1:), '"')
    if (q2 == 0) return
    q2 = q1 + q2
    s = json(q1 + 1:q2 - 1)
  end function

  integer function json_int(json, key) result(v)
    character(len=*), intent(in) :: json, key
    integer :: p
    integer(int64) :: tmp
    v = 0
    p = key_pos(json, key)
    if (p == 0) return
    call parse_int64_at(json, p, tmp)
    v = int(tmp)
  end function

  subroutine parse_int64_at(s, p, val)
    character(len=*), intent(in) :: s
    integer, intent(inout) :: p
    integer(int64), intent(out) :: val
    integer :: sign
    val = 0_int64
    sign = 1
    call skip_ws_idx(s, p)
    if (p > len(s)) return
    if (s(p:p) == "-") then
      sign = -1
      p = p + 1
    else if (s(p:p) == "+") then
      p = p + 1
    end if
    do while (p <= len(s))
      if (s(p:p) < "0" .or. s(p:p) > "9") exit
      val = val * 10_int64 + int(ichar(s(p:p)) - ichar("0"), int64)
      p = p + 1
    end do
    val = val * int(sign, int64)
  end subroutine

  subroutine parse_f64_at(s, p, val)
    character(len=*), intent(in) :: s
    integer, intent(inout) :: p
    real(real64), intent(out) :: val
    integer :: q, ios
    val = 0.0_real64
    call skip_ws_idx(s, p)
    q = p
    if (q <= len(s) .and. (s(q:q) == "+" .or. s(q:q) == "-")) q = q + 1
    do while (q <= len(s))
      if ((s(q:q) >= "0" .and. s(q:q) <= "9") .or. s(q:q) == "." .or. &
          s(q:q) == "e" .or. s(q:q) == "E" .or. s(q:q) == "+" .or. s(q:q) == "-") then
        q = q + 1
      else
        exit
      end if
    end do
    if (q <= p) return
    read (s(p:q - 1), *, iostat=ios) val
    p = q
  end subroutine

  subroutine skip_ws_idx(s, p)
    character(len=*), intent(in) :: s
    integer, intent(inout) :: p
    do while (p <= len(s))
      if (s(p:p) /= " " .and. s(p:p) /= achar(9) .and. s(p:p) /= new_line("a") &
          .and. s(p:p) /= achar(13)) exit
      p = p + 1
    end do
  end subroutine

  subroutine parse_bool_rows(json, start, n, fx)
    character(len=*), intent(in) :: json
    integer, intent(in) :: start, n
    logical, intent(out) :: fx(3, n)
    integer :: p, i, k
    p = start
    if (p < 1) return
    call skip_ws_idx(json, p)
    if (p <= len(json) .and. json(p:p) == "[") p = p + 1
    do i = 1, n
      call skip_ws_idx(json, p)
      if (p <= len(json) .and. json(p:p) == ",") p = p + 1
      call skip_ws_idx(json, p)
      if (p <= len(json) .and. json(p:p) == "[") p = p + 1
      do k = 1, 3
        call skip_ws_idx(json, p)
        if (p <= len(json) .and. json(p:p) == ",") p = p + 1
        call skip_ws_idx(json, p)
        if (p + 3 <= len(json) .and. json(p:p + 3) == "true") then
          fx(k, i) = .true.
          p = p + 4
        else if (p + 4 <= len(json) .and. json(p:p + 4) == "false") then
          fx(k, i) = .false.
          p = p + 5
        else
          fx(k, i) = .false.
        end if
      end do
      call skip_ws_idx(json, p)
      if (p <= len(json) .and. json(p:p) == "]") p = p + 1
    end do
  end subroutine

  subroutine parse_f64_rows(json, start, n, pos)
    character(len=*), intent(in) :: json
    integer, intent(in) :: start, n
    real(real64), intent(out) :: pos(3, n)
    integer :: p, i, k
    p = start
    if (p < 1) return
    call skip_ws_idx(json, p)
    if (p <= len(json) .and. json(p:p) == "[") p = p + 1
    do i = 1, n
      call skip_ws_idx(json, p)
      if (p <= len(json) .and. json(p:p) == ",") p = p + 1
      call skip_ws_idx(json, p)
      if (p <= len(json) .and. json(p:p) == "[") p = p + 1
      do k = 1, 3
        call skip_ws_idx(json, p)
        if (p <= len(json) .and. json(p:p) == ",") p = p + 1
        call skip_ws_idx(json, p)
        call parse_f64_at(json, p, pos(k, i))
      end do
      call skip_ws_idx(json, p)
      if (p <= len(json) .and. json(p:p) == "]") p = p + 1
    end do
  end subroutine

  subroutine parse_int_list(json, start, n, ids)
    character(len=*), intent(in) :: json
    integer, intent(in) :: start, n
    integer(int64), intent(out) :: ids(n)
    integer :: p, i
    p = start
    if (p < 1) return
    call skip_ws_idx(json, p)
    if (p <= len(json) .and. json(p:p) == "[") p = p + 1
    do i = 1, n
      call skip_ws_idx(json, p)
      if (p <= len(json) .and. json(p:p) == ",") p = p + 1
      call skip_ws_idx(json, p)
      call parse_int64_at(json, p, ids(i))
    end do
  end subroutine

  subroutine parse_str_list(json, start, n, syms)
    character(len=*), intent(in) :: json
    integer, intent(in) :: start, n
    character(len=*), intent(out) :: syms(n)
    integer :: p, i, q2
    p = start
    if (p < 1) return
    call skip_ws_idx(json, p)
    if (p <= len(json) .and. json(p:p) == "[") p = p + 1
    do i = 1, n
      call skip_ws_idx(json, p)
      if (p <= len(json) .and. json(p:p) == ",") p = p + 1
      call skip_ws_idx(json, p)
      if (p <= len(json) .and. json(p:p) == '"') then
        q2 = index(json(p + 1:), '"')
        if (q2 > 0) then
          syms(i) = json(p + 1:p + q2 - 1)
          p = p + q2 + 1
        else
          syms(i) = ""
        end if
      else
        syms(i) = ""
      end if
    end do
  end subroutine

end module conformance_golden_mod

program test_conformance_goldens
  use readcon
  use conformance_golden_mod
  implicit none

  character(len=1024) :: root
  character(len=:), allocatable :: manifest
  integer :: nlen, ierr, nfail, nvalid, ninvalid, i, ncases
  logical :: ok
  type(case_t), allocatable :: cases(:)

  nfail = 0
  nvalid = 0
  ninvalid = 0
  call get_environment_variable("READCON_CORE_ROOT", root, length=nlen, status=ierr)
  if (ierr /= 0 .or. nlen == 0) then
    root = "../.."
  end if
  inquire (file=trim(root) // "/resources/conformance/manifest.toml", exist=ok)
  if (.not. ok) then
    print *, "missing manifest under ", trim(root)
    error stop "set READCON_CORE_ROOT to repo root"
  end if

  manifest = slurp(trim(root) // "/resources/conformance/manifest.toml")
  call parse_manifest(manifest, cases, ncases)
  if (ncases < 1) error stop "manifest.toml lists no cases"

  do i = 1, ncases
    if (cases(i)%valid) then
      nvalid = nvalid + 1
      nfail = nfail + check_valid(trim(root), cases(i))
    else
      ninvalid = ninvalid + 1
      nfail = nfail + check_invalid(trim(root), cases(i))
    end if
  end do

  if (nvalid < 1 .or. ninvalid < 1) then
    print *, "expected both valid and invalid cases"
    nfail = nfail + 1
  end if
  if (nfail /= 0) then
    print *, "FAIL", nfail, " valid=", nvalid, " invalid=", ninvalid
    error stop nfail
  end if
  print *, "OK fortran conformance goldens  valid=", nvalid, " invalid=", ninvalid
end program
