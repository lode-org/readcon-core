# ReadCon.jl

Thin `ccall` bindings over `libreadcon_core` (same ABI as `include/readcon-core.h`).

## Prebuilt C ABI tarball (no cargo)

GitHub Releases attach `readcon-core-clib-$VERSION-$TARGET.tar.gz` via
`c_lib_tarball.yml` (not cargo-dist; cargo-dist ships the CLI only). Unpack
and point the wrapper at the shared library:

```bash
curl -fsSL -O https://github.com/lode-org/readcon-core/releases/download/v0.14.7/readcon-core-clib-0.14.7-x86_64-unknown-linux-gnu.tar.gz
tar -xzf readcon-core-clib-0.14.7-x86_64-unknown-linux-gnu.tar.gz
prefix="$PWD/readcon-core-clib-0.14.7-x86_64-unknown-linux-gnu"
export READCON_CORE_PREFIX="$prefix"
# or a file path (either name works):
# export READCON_LIB_PATH="$prefix/lib/libreadcon_core.so"
# export READCON_CORE_LIB="$prefix/lib/libreadcon_core.so"
```

A Julia `Artifacts.toml` entry can pin that same URL (sha256 is the sibling
`.tar.gz.sha256` on the Release). Yggdrasil / JuliaBinaryWrappers is the
registry path; this tarball is the artifact a JLL would wrap.

Windows chemfiles is not in the C ABI tarball matrix. Use a lean Windows
tarball, or build from source with `--features chemfiles`.

## Run tests from a source checkout

1. Build the shared library from the **repository root**:

   ```bash
   cargo build --release --features chemfiles
   # optional fat matrix: chemfiles,zstd,metatensor
   export READCON_CORE_LIB="$PWD/target/release/libreadcon_core.so"
   export READCON_LIB_PATH="$PWD/target/release/libreadcon_core.so"
   export JULIA_LOAD_PATH="$PWD/julia/ReadCon:$JULIA_LOAD_PATH"
   ```

2. From `julia/ReadCon` (or with `JULIA_PROJECT` set):

   ```bash
   julia --project=. -e 'using Pkg; Pkg.test()'
   ```

If `libreadcon_core` is not on `LD_LIBRARY_PATH` / `READCON_CORE_LIB` /
`READCON_LIB_PATH`, tests that touch the FFI **fail fast** with a clear load
error (they do not silently skip ABI checks). Pure Julia struct layout tests
in `test/runtests.jl` still run.

## CI

Workflow `.github/workflows/ci_julia.yml` runs when Julia is available on the
runner: builds `libreadcon_core` with `chemfiles`, exports `READCON_CORE_LIB`,
then `Pkg.test()`. Missing `julia` is an environment limit, not an API gap;
the package sources and tests remain in-tree.
