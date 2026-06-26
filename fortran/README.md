# Fortran bindings (`ReadCon` via fpm)

First-class **ISO_C_BINDING** module over `include/readcon-core.h`, managed with
[fpm](https://fpm.fortran-lang.org/).

## Layout

```
fortran/ReadCon/
  fpm.toml
  src/readcon.f90      # catom_t, cframe_t, frame_t + metadata helpers
  test/test_read_con.f90
  example/read_first.f90
```

## Build & test

```bash
# 1) C ABI library
cargo build --release

# 2) fpm (link against target/release)
cd fortran/ReadCon
export LD_LIBRARY_PATH="$(pwd)/../../target/release:${LD_LIBRARY_PATH}"
fpm test --flag "-L../../target/release" \
  --link-flag "-L../../target/release -lreadcon_core -ldl -lpthread -lm"
fpm run --example read_first --flag "-L../../target/release" \
  --link-flag "-L../../target/release -lreadcon_core -ldl -lpthread -lm"
```

## Ergonomics

- `frame_t` — owns opaque `RKRConFrame*`, lazy `CFrame` view for atoms/cell
- `catom_t` — bind(C) layout with **per-axis** `fixed_x/y/z` (spec bitmask)
- `metadata_json()`, `energy()`, `potential_type()`, `frame_index()`, `sim_time()`, `timestep()`
- Always call `call fr%free()` when done (no FINAL, avoids double-free)

See docs **Language bindings** (Fortran + multi-language panels).
