# ReadCon.jl

Thin `ccall` bindings over `libreadcon_core` (same ABI as `include/readcon-core.h`).

## Library discovery

`wrapper.jl` searches in this order and **fails fast** if none exist
(FFI tests do not skip ABI checks):

1. Julia artifact `libreadcon_core` from `Artifacts.toml` (lazy GitHub
   Release clib tarball `readcon-core-clib-$VERSION-$target.tar.gz`)
2. `READCON_LIB_PATH` (file or directory)
3. `READCON_CORE_LIB` (file or directory; CI uses this)
4. In-tree `target/{release,debug}` and `target/<triple>/{release,debug}`

`scripts/package-clib.sh` prints the `[[libreadcon_core.download]]`
fragment to paste into `Artifacts.toml` after a Release attaches the
tarball.

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
   julia --project=. -e 'using Pkg; Pkg.instantiate(); Pkg.test()'
   ```

## CI

Workflow `.github/workflows/ci_julia.yml` builds `libreadcon_core` with
`chemfiles`, exports `READCON_CORE_LIB`, then `Pkg.test()`. Agents
without Julia should treat missing `julia` as an environment limit, not
an API gap.
