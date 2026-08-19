# ReadCon.jl

Thin `ccall` bindings over `libreadcon_core` (same ABI as `include/readcon-core.h`).
cbindgen is not required. The wrapper searches `READCON_CORE_LIB`, then
`READCON_LIB_PATH`, then `READCON_CORE_PREFIX` (unpacked clib tarball), then
an in-tree `target/{release,debug}` build.

## Prebuilt C ABI (registry / artifact path)

GitHub Releases ship `readcon-core-clib-$VERSION-$target.tar.gz` (headers +
`libreadcon_core` + `readcon-core.pc`). Unpack and point the wrapper at it:

```bash
tar -xzf readcon-core-clib-0.14.7-x86_64-unknown-linux-gnu.tar.gz
export READCON_CORE_PREFIX="$PWD/readcon-core-clib-0.14.7-x86_64-unknown-linux-gnu"
# or a single file:
export READCON_CORE_LIB="$READCON_CORE_PREFIX/lib/libreadcon_core.so"
# Windows: READCON_CORE_LIB=.../bin/readcon_core.dll
```

`Artifacts.toml.in` is the JuliaBinaryWrappers / ArtifactUtils template for
that URL. A filled `Artifacts.toml` is the General-registry path; until then
the env vars above are the supported install.

Windows chemfiles-enabled libraries use the official prebuilt libchemfiles
and `advapi32`. They are **not** built with `chemfiles-from-sources`.

## Run tests locally

1. Build the shared library from the **repository root**, or unpack a clib
   tarball as above:

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

If `libreadcon_core` is not on `LD_LIBRARY_PATH` / `READCON_CORE_LIB` /
`READCON_CORE_PREFIX`, tests that touch the FFI **fail fast** with a clear
load error (they do not silently skip ABI checks). Pure Julia struct layout
tests in `test/runtests.jl` still run.

## CI

Workflow `.github/workflows/ci_julia.yml` runs when Julia is available on the
runner: builds `libreadcon_core` with `chemfiles`, exports `READCON_CORE_LIB`,
then `Pkg.test()`. Agents without Julia should treat missing `julia` as an
environment limit, not an API gap—the package sources and tests remain in-tree.
