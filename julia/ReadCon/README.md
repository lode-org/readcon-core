# ReadCon.jl

Thin `ccall` bindings over `libreadcon_core` (same ABI as `include/readcon-core.h`).

## Run tests locally

1. Point at a prebuilt prefix from GitHub Releases, or build from the
   **repository root**:

   ```bash
   # Prebuilt C ABI tarball (manylinux_2_28 / macOS)
   tar -xzf readcon-core-*-manylinux_2_28_x86_64.tar.gz
   export READCON_LIB_PATH="$PWD/readcon-core-*/lib/libreadcon_core.so"
   # READCON_CORE_LIB is accepted as an alias (file or directory).

   # Or build from this tree
   cargo build --release --features chemfiles
   # optional fat matrix: chemfiles,zstd,metatensor
   export READCON_CORE_LIB="$PWD/target/release/libreadcon_core.so"
   export JULIA_LOAD_PATH="$PWD/julia/ReadCon:$JULIA_LOAD_PATH"
   ```

2. From `julia/ReadCon` (or with `JULIA_PROJECT` set):

   ```bash
   julia --project=. -e 'using Pkg; Pkg.test()'
   ```

If `libreadcon_core` is not on `LD_LIBRARY_PATH` / `READCON_LIB_PATH` /
`READCON_CORE_LIB`, tests that touch the FFI **fail fast** with a clear load
error (they do not silently skip ABI checks). Pure Julia struct layout tests
in `test/runtests.jl` still run.

## CI

Workflow `.github/workflows/ci_julia.yml` runs when Julia is available on the
runner: builds `libreadcon_core` with `chemfiles`, exports `READCON_CORE_LIB`,
then `Pkg.test()`. Agents without Julia should treat missing `julia` as an
environment limit, not an API gap—the package sources and tests remain in-tree.
