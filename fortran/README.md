# Fortran `ReadCon` (fpm)

Production **ISO_C_BINDING** bindings over `include/readcon-core.h`, managed with [fpm](https://fpm.fortran-lang.org/).

## Types

| Type | Role |
|------|------|
| `catom_t` / `cframe_t` | `bind(C)` layouts (= `CAtom` / `CFrame`), incl. **fixed_x/y/z** |
| `frame_t` | Owns `RKRConFrame*`; atoms, cell, **metadata_json**, energy, potential, time, NEB, bonds, **select** |
| `iterator_t` | Lazy multi-frame via `read_con_file_iterator` |
| `builder_t` | `rkr_frame_new` + add_atom (per-axis fixed) + set_energy / metadata_json / build |
| `writer_t` | `create_writer_from_path_c` + extend |

Always `call obj%free()` when done (no FINAL — avoids double-free).

## Test

```bash
scripts/run_fortran_tests.sh
# or: cargo build --release && cd fortran/ReadCon && fpm test ...
```

CI: **Fortran (fpm)** workflow on PRs touching `fortran/` or the C ABI.

## DLPack (builder)

```fortran
type(c_ptr) :: tensor
st = bd%positions_dlpack(tensor)   ! owned DLManagedTensorVersioned*
! ... pass tensor to a C/C++/Python consumer that speaks DLPack ...
call bd%dlpack_delete(tensor)      ! rkr_dlpack_delete
```

Or copy into Fortran arrays without DLPack: `bd%copy_positions(pos)` / `bd%copy_masses(masses)` (row-major C buffers transposed into `pos(3,n)`).

## Chemfiles (feature-enabled lib)

Build with `cargo build --release --features chemfiles`, then:

```fortran
fr = read_chemfiles_first("water.xyz")
st = fr%select("name O", nmatch)
st = fr%select_primary("name H", indices, nwritten)
```

C API: `rkr_read_chemfiles_first`, `rkr_read_chemfiles_memory`, `rkr_has_chemfiles_support`.
