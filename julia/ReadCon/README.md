# ReadCon.jl

Thin `ccall` bindings over `libreadcon_core` (same ABI as `include/readcon-core.h`).

## Run tests locally

1. Point the wrapper at `libreadcon_core`. Both `READCON_LIB_PATH` and
   `READCON_CORE_LIB` are accepted (CI uses `READCON_CORE_LIB`). Search
   order: those env vars, then the `libreadcon_core` artifact
   (`Artifacts.toml` filled from `Artifacts.toml.in` after a clib
   tarball is published), then an in-tree `target/` build.

   ```bash
   cargo build --release --features chemfiles
   # optional fat matrix: chemfiles,zstd,metatensor
   export READCON_CORE_LIB="$PWD/target/release/libreadcon_core.so"
   # equivalent: export READCON_LIB_PATH="$READCON_CORE_LIB"
   export JULIA_LOAD_PATH="$PWD/julia/ReadCon:$JULIA_LOAD_PATH"
   ```

   Or unpack a GitHub Release prefix (`readcon-core-clib-$VER-$TARGET.tar.gz`)
   and set the env var to `$prefix/lib/libreadcon_core.so` (`.dylib` /
   `bin/readcon_core.dll` on other hosts). The Windows clib tarball is
   lean: chemfiles is not in that prefix (`FEATURE_DISABLED`).

2. From `julia/ReadCon` (or with `JULIA_PROJECT` set):

   ```bash
   julia --project=. -e 'using Pkg; Pkg.test()'
   ```

If `libreadcon_core` is not on `READCON_LIB_PATH` / `READCON_CORE_LIB`,
the artifact, or `target/`, tests that touch the FFI **fail fast** with
a clear load error (they do not silently skip ABI checks). Pure Julia
struct layout tests in `test/runtests.jl` still run.

## CI

Workflow `.github/workflows/ci_julia.yml` runs when Julia is available on the
runner: builds `libreadcon_core` with `chemfiles`, exports `READCON_CORE_LIB`,
then `Pkg.test()`. Agents without Julia should treat missing `julia` as an
environment limit, not an API gap—the package sources and tests remain in-tree.
