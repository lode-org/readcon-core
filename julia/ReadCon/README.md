# ReadCon.jl

Thin `ccall` bindings over `libreadcon_core` (same ABI as `include/readcon-core.h`).

## Shared library

`wrapper.jl` loads `libreadcon_core` from, in order:

1. `READCON_LIB_PATH` or `READCON_CORE_LIB` (exact file)
2. `READCON_CORE_PREFIX` (unpacked GitHub Release
   `readcon-core-clib-$VERSION-$target.tar.gz` cargo-c prefix)
3. in-tree `target/release` / `target/debug`

```bash
VER=0.14.7
TRIPLE=x86_64-unknown-linux-gnu   # or aarch64-apple-darwin
curl -fsSL -O \
  "https://github.com/lode-org/readcon-core/releases/download/v${VER}/readcon-core-clib-${VER}-${TRIPLE}.tar.gz"
mkdir -p "$HOME/.local/readcon-core"
tar -C "$HOME/.local/readcon-core" --strip-components=1 \
  -xzf "readcon-core-clib-${VER}-${TRIPLE}.tar.gz"
export READCON_CORE_PREFIX="$HOME/.local/readcon-core"
```

Windows Release tarball is lean (chemfiles OFF). JuliaBinaryWrappers can
wrap the same prefix tarball as a binary artifact.

## Run tests locally

1. Build the shared library from the **repository root**:

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
`READCON_LIB_PATH` / `READCON_CORE_PREFIX`, tests that touch the FFI
**fail fast** with a clear load error (they do not silently skip ABI
checks). Pure Julia struct layout tests in `test/runtests.jl` still run.

## CI

Workflow `.github/workflows/ci_julia.yml` runs when Julia is available on the
runner: builds `libreadcon_core` with `chemfiles`, exports `READCON_CORE_LIB`,
then `Pkg.test()`. Agents without Julia should treat missing `julia` as an
environment limit, not an API gap—the package sources and tests remain in-tree.
