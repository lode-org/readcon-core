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
