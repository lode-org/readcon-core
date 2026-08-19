# ReadCon.jl

Thin `ccall` bindings over `libreadcon_core` (same ABI as `include/readcon-core.h`).

The wrapper searches, in order:

1. `READCON_CORE_LIB` (preferred; CI uses this)
2. `READCON_LIB_PATH` (alias)
3. the `readcon_core` Julia artifact (`Artifacts.toml`, filled from `Artifacts.toml.in`)
4. a local cargo `target/{release,debug}` build next to this tree

## Prebuilt C ABI tarball

GitHub Releases attach `readcon-core-clib-$VERSION-$target.tar.gz` (shipped
headers + `libreadcon_core` + `readcon-core.pc`). cbindgen is not required.

`Artifacts.toml.in` is the registry template. `scripts/package-clib.sh` writes
per-target sha256 fragments next to the tarball. Point the wrapper at an
unpacked tarball without an artifact:

```bash
export READCON_CORE_LIB="$PREFIX/lib/libreadcon_core.so"
```

Windows chemfiles tarballs are not published.

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

If `libreadcon_core` is not on `LD_LIBRARY_PATH` / `READCON_CORE_LIB`, tests that
touch the FFI **fail fast** with a clear load error (they do not silently skip
ABI checks). Pure Julia struct layout tests in `test/runtests.jl` still run.

## CI

Workflow `.github/workflows/ci_julia.yml` runs when Julia is available on the
runner: builds `libreadcon_core` with `chemfiles`, exports `READCON_CORE_LIB`,
then `Pkg.test()`. Agents without Julia should treat missing `julia` as an
environment limit, not an API gap—the package sources and tests remain in-tree.
