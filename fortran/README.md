# Fortran `ReadCon` (fpm)

Production **ISO_C_BINDING** bindings over `include/readcon-core.h`, managed with [fpm](https://fpm.fortran-lang.org/).

## Types

| Type | Role |
|------|------|
| `catom_t` / `cframe_t` | `bind(C)` layouts (= `CAtom` / `CFrame`), incl. **fixed_x/y/z** |
| `dl_managed_tensor_versioned_t` / `dl_tensor_t` | DLPack C header layout (`dlpack.h`) for field inspect |
| `frame_t` | Owns `RKRConFrame*`; atoms, cell, **metadata_json**, energy, potential, time, NEB, bonds, **select** |
| `iterator_t` | Lazy multi-frame via `read_con_file_iterator` |
| `builder_t` | `rkr_frame_new` + add_atom (per-axis fixed) + set_energy / metadata_json / build / **DLPack** |
| `writer_t` | `create_writer_from_path_c` + extend |

Always `call obj%free()` when done (no FINAL — avoids double-free).

## Test

```bash
# From repo root — sets READCON_CORE_ROOT, always passes -cpp
READCON_FORTRAN_FEATURES=chemfiles scripts/run_fortran_tests.sh
READCON_FORTRAN_FEATURES=chemfiles,metatensor scripts/run_fortran_tests.sh
```

CI: **Fortran (fpm)** workflow runs both lean and metatensor-enabled jobs via the same script.

## DLPack (builder, full C ABI parity)

All six owned exports plus delete; inspect primary fields without a second metadata API:

| Method | C symbol | Notes |
|--------|----------|--------|
| `bd%positions_dlpack` | `rkr_frame_builder_positions_dlpack` | `[N,3]` f64 |
| `bd%velocities_dlpack` | `…_velocities_dlpack` | `SECTION_ABSENT` if unset |
| `bd%forces_dlpack` | `…_forces_dlpack` | same |
| `bd%atom_energies_dlpack` | `…_atom_energies_dlpack` | same |
| `bd%masses_dlpack` | `…_masses_dlpack` | `[N]` |
| `bd%atom_ids_dlpack` | `…_atom_ids_dlpack` | `[N]` u64 |
| `bd%dlpack_delete` | `rkr_dlpack_delete` | calls tensor deleter; NULL-safe |
| `dlpack_inspect` / `dlpack_data_ptr` | (Fortran only) | `ndim`, `shape[0..]`, `dtype.bits`, `data` |

```fortran
type(c_ptr) :: tensor, data_p
integer :: st, ndim, bits
integer(int64) :: shape0, shape1
logical :: ok
st = bd%positions_dlpack(tensor)
call dlpack_inspect(tensor, ndim, shape0, shape1, bits, ok)
data_p = dlpack_data_ptr(tensor)
call bd%dlpack_delete(tensor)
```

Or copy into Fortran arrays without DLPack: `bd%copy_positions(pos)` / `bd%copy_masses(masses)` (row-major C buffers transposed into `pos(3,n)`).

## Metatensor TensorBlocks (optional fat lib — option A)

**Boundary:** pointers are metatensor-sys `mts_block_t*` (same as `metatensor.h`). Rust builds `TensorBlock` in `metatensor_export`, transfers once (`tensor_block_into_raw_mts`), frees only via `rkr_mts_block_free` → `mts_block_free`.

| Build | Cargo features | Fortran flags | Link | Helper behaviour |
|-------|----------------|---------------|------|------------------|
| **Lean** | `chemfiles` (no `metatensor`) | `-cpp` only | no `libmetatensor` | status **`RKR_STATUS_FEATURE_DISABLED` (-11)**, null block |
| **Fat** | `chemfiles,metatensor` | `-cpp -DREADCON_HAS_METATENSOR` | `libmetatensor` + paths from env | real blocks / `SECTION_ABSENT` (-8) |

After `cargo build --release --features metatensor`, source **`target/release/readcon-metatensor.env`** (`READCON_METATENSOR_INCLUDE`, `READCON_METATENSOR_LIB_DIR`). `scripts/run_fortran_tests.sh` does this automatically for fat runs.

| Helper | C symbol | Shape / status |
|--------|----------|----------------|
| `frame_metatensor_positions_block` | `rkr_frame_metatensor_positions_block` | `[N,3]` owned `mts_block_t*` |
| `frame_metatensor_velocities_block` | `…_velocities_block` | or `SECTION_ABSENT` (-8) |
| `frame_metatensor_forces_block` | `…_forces_block` | or -8 |
| `frame_metatensor_atom_energies_block` | `…_atom_energies_block` | `[N,1]` or -8 |
| `mts_block_free_rkr` | `rkr_mts_block_free` | calls `mts_block_free` once |

C consumers: prefer `include/readcon-metatensor.h` (`metatensor.h` **first**). Inspect with `mts_block_data` / `mts_block_labels`. Example: `examples/c_metatensor_sample.c`. Full matrix and ownership rules: Sphinx **Language bindings** page.

## Chemfiles (feature-enabled lib)

Build with `cargo build --release --features chemfiles`, then:

```fortran
fr = read_chemfiles_first("water.xyz")
st = fr%select("name O", nmatch)
st = fr%select_primary("name H", indices, nwritten)
```

C API: `rkr_read_chemfiles_first`, `rkr_read_chemfiles_memory`, `rkr_has_chemfiles_support`.  
Note: the Fortran **test suite** does not call into chemfiles C++ on CI (SIGFPE traps under gfortran on some runners); chemfiles is covered by Rust CI and the API above remains available for applications.
