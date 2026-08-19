# ReadCon.jl

Thin `ccall` bindings over `libreadcon_core` (same ABI as `include/readcon-core.h`).

## Run tests locally

Point at a prebuilt prefix from the GitHub Release
(`readcon-core-$VERSION-$triple[-chemfiles].tar.gz`) **or** build from
this checkout. `READCON_CORE_LIB` and `READCON_LIB_PATH` are aliases;
each may be the shared library file or the unpacked prefix directory.

1. Build the shared library from the **repository root** (or unpack a
   Release tarball):

   ```bash
   cargo build --release --features chemfiles
   # optional fat matrix: chemfiles,zstd,metatensor
   export READCON_CORE_LIB="$PWD/target/release/libreadcon_core.so"
   # alias: READCON_LIB_PATH (file or prefix directory)
   export JULIA_LOAD_PATH="$PWD/julia/ReadCon:$JULIA_LOAD_PATH"
   ```

2. From `julia/ReadCon` (or with `JULIA_PROJECT` set):

   ```bash
   julia --project=. -e 'using Pkg; Pkg.test()'
   ```

If `libreadcon_core` is not on `LD_LIBRARY_PATH` / `READCON_CORE_LIB` /
`READCON_LIB_PATH`, tests that touch the FFI **fail fast** with a clear
load error (they do not silently skip ABI checks). Pure Julia struct
layout tests in `test/runtests.jl` still run.

A Yggdrasil / JuliaBinaryWrappers artifact is the registry path once
the prefix tarball URL and SHA256 are pinned in `Artifacts.toml`. Until
then the Release tarball plus `READCON_CORE_LIB` is the artifact path.

## CI

Workflow `.github/workflows/ci_julia.yml` runs when Julia is available on the
runner: builds `libreadcon_core` with `chemfiles`, exports `READCON_CORE_LIB`,
then `Pkg.test()`. Agents without Julia should treat missing `julia` as an
environment limit, not an API gap—the package sources and tests remain in-tree.
