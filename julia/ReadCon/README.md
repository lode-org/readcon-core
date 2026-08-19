# ReadCon.jl

Thin `ccall` bindings over `libreadcon_core` (same ABI as `include/readcon-core.h`).

## Library search order

1. `READCON_CORE_LIB` (CI and this README)
2. `READCON_LIB_PATH` (alias used in older docs)
3. A filled `Artifacts.toml` `readcon_core` artifact (from the
   `readcon-core-clib-$VER-$target.tar.gz` GitHub Release asset)
4. In-tree `target/{release,debug}/libreadcon_core.{so,dylib}`

## Prebuilt C ABI (no local cargo)

Dispatch `.github/workflows/c_lib_tarball.yml` with `tag=vX.Y.Z` (or wait
for the `release` hook) and unpack the matching asset:

```bash
VER=0.14.7
TARGET=x86_64-unknown-linux-gnu   # or aarch64-unknown-linux-gnu, *-apple-darwin
curl -fsSL -O "https://github.com/lode-org/readcon-core/releases/download/v${VER}/readcon-core-clib-${VER}-${TARGET}.tar.gz"
tar -xzf "readcon-core-clib-${VER}-${TARGET}.tar.gz"
export READCON_CORE_LIB="$PWD/readcon-core-clib-${VER}-${TARGET}/lib/libreadcon_core.so"
export JULIA_LOAD_PATH="$PWD/julia/ReadCon:${JULIA_LOAD_PATH:-}"
```

Windows + chemfiles is **not** a clib asset. Use the `readcon-chemfiles`
wheel, or a Linux/macOS tarball.

`Artifacts.toml.in` is the template; `scripts/package-clib.sh` writes
`Artifacts-$target.toml` next to the tarball.

## Run tests locally

1. Build the shared library from the **repository root**, or point at a
   prebuilt clib tarball:

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

If `libreadcon_core` is not on `LD_LIBRARY_PATH` / `READCON_CORE_LIB`, tests that
touch the FFI **fail fast** with a clear load error (they do not silently skip
ABI checks). Pure Julia struct layout tests in `test/runtests.jl` still run.

## CI

Workflow `.github/workflows/ci_julia.yml` runs when Julia is available on the
runner: builds `libreadcon_core` with `chemfiles`, exports `READCON_CORE_LIB`,
then `Pkg.test()`. Agents without Julia should treat missing `julia` as an
environment limit, not an API gap—the package sources and tests remain in-tree.
