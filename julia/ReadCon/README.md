# ReadCon.jl

Thin `ccall` bindings over `libreadcon_core` (same ABI as `include/readcon-core.h`).

## Prebuilt library (GitHub Release)

Tag CI attaches `readcon-core-clib-$VERSION-$target-$variant.tar.gz` (cargo-c
prefix: `include/`, `lib/libreadcon_core.*`, `lib/pkgconfig/readcon-core.pc`).
Prefer the `chemfiles` variant when you need XYZ/PDB import or selection.

```bash
# Example: manylinux x86_64 chemfiles prefix from the vX.Y.Z release
curl -fsSL -O \
  https://github.com/lode-org/readcon-core/releases/download/v0.14.7/readcon-core-clib-0.14.7-x86_64-unknown-linux-gnu-chemfiles.tar.gz
tar -xzf readcon-core-clib-0.14.7-x86_64-unknown-linux-gnu-chemfiles.tar.gz
export READCON_CORE_PREFIX="$PWD/readcon-core-clib-0.14.7-x86_64-unknown-linux-gnu-chemfiles"
# or pin the file:
# export READCON_LIB_PATH="$READCON_CORE_PREFIX/lib/libreadcon_core.so"
# export READCON_CORE_LIB="$READCON_LIB_PATH"
```

`wrapper.jl` accepts any of `READCON_LIB_PATH`, `READCON_CORE_LIB`, or
`READCON_CORE_PREFIX`. A Yggdrasil / JuliaBinaryWrappers recipe can publish
the same tarball as an Artifact; until that product exists, point the env
vars at the unpacked prefix (or at `artifact"readcon_core"` after you add
an `Artifacts.toml` with the release SHA-256).

Windows: the DLL is `bin/readcon_core.dll`. The `chemfiles` Windows tarball
links the official prebuilt libchemfiles (not `chemfiles-from-sources`).

## Run tests locally

1. Build the shared library from the **repository root**, or unpack a clib
   tarball and set `READCON_CORE_PREFIX` as above:

   ```bash
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
`READCON_CORE_LIB` / `READCON_CORE_PREFIX`, tests that touch the FFI **fail
fast** with a clear load error (they do not silently skip ABI checks). Pure
Julia struct layout tests in `test/runtests.jl` still run.

## CI

Workflow `.github/workflows/ci_julia.yml` runs when Julia is available on the
runner: builds `libreadcon_core` with `chemfiles`, exports `READCON_CORE_LIB`,
then `Pkg.test()`. Prebuilt prefixes are produced by
`.github/workflows/c_lib_tarball.yml` (not the wheel job). Agents without
Julia should treat missing `julia` as an environment limit, not an API
gap—the package sources and tests remain in-tree.
