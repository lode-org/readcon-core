# Ecosystem exchange benchmarks

These results measure readcon-core commit
`8bba6f59ced996784ba713250603dbbdd8220a75`. The run completed on
2026-11-25 UTC. Lower wall time and lower ratios are better.

## Hardware and software

- CPU: Intel Xeon Processor, 8 physical cores, one socket
- Memory: 47 GiB, no swap
- GPU: none exposed; `nvidia-smi` was not installed and no NVIDIA driver was
  available
- Rust: rustc 1.88.0, cargo 1.88.0
- Python: 3.12.3
- NumPy: 2.5.5
- PyTorch: 2.15.0+cu132 (CPU used)
- JAX/jaxlib: 0.12.1 (CPU used, x64 enabled)
- CuPy: not installed because no CUDA device was available
- metatensor-core: 0.2.0
- ASE: 3.29.0
- readcon: 0.24.0, built from the commit above

The `cuda` Cargo feature compiled successfully with:

```console
cargo +1.88.0 check --features cuda
```

This is a compile result only. It is not evidence of a working CUDA device.

## Method

Each measured arm has two untimed warmups followed by six timed samples.
Comparative arms run serially. Their lead order rotates `AB`, `BA`, `BA`,
`AB` across repeats and then repeats the cycle. Quartiles use NumPy's linear
percentile method; IQR is Q3 minus Q1.

The harness first creates deterministic seed coordinates, reads them with
readcon, and writes the benchmark CON files with `readcon.write_con`.
Generated frames live under `bench/ecosystem/work/` and are ignored by Git.
Sizes are 1,000, 10,000, 100,000, and 1,000,000 atoms.

For item 2, pointer equality was asserted for every size for NumPy,
PyTorch, and JAX. JAX uses `copy=False` and x64 mode. CuPy was not run.
For item 3, a file requesting `storage_dtypes.positions=float32` is read
through the C API. Direct float32 DLPack export is compared with float64
DLPack export followed by `astype(float32)`. For item 4, each timed arm
includes reading the same file and constructing/freeing the TensorBlock.
Before timing, the native and ASE shapes and all position values are asserted
equal.

Item 1 is `NO_CUDA` rather than simulated. `results.csv` contains explicit
`NO_CUDA` rows for all requested sizes, fields, and arms.

Status by item:

- 1: `NO_CUDA`; feature compile passed, but no NVIDIA device or driver existed
- 2: `MEASURED` on CPU for NumPy, PyTorch, and JAX; CuPy rows are `NO_CUDA`
- 3: `MEASURED`
- 4: `MEASURED`

## Summary

Medians are milliseconds. Ratio is the first arm divided by its comparator.

| Item | Arm / comparator | Atoms | Median A (ms) | Median B (ms) | Ratio |
|---|---|---:|---:|---:|---:|
| 2 | torch DLPack / torch copy | 1,000 | 0.001288 | 0.002500 | 0.5152 |
| 2 | torch DLPack / torch copy | 10,000 | 0.001124 | 0.006592 | 0.1704 |
| 2 | torch DLPack / torch copy | 100,000 | 0.001732 | 0.027771 | 0.0624 |
| 2 | torch DLPack / torch copy | 1,000,000 | 0.006492 | 0.204037 | 0.0318 |
| 2 | JAX DLPack / explicit copy | 1,000 | 0.045468 | 0.031766 | 1.4313 |
| 2 | JAX DLPack / explicit copy | 10,000 | 0.055626 | 0.055088 | 1.0098 |
| 2 | JAX DLPack / explicit copy | 100,000 | 0.096821 | 0.977080 | 0.0991 |
| 2 | JAX DLPack / explicit copy | 1,000,000 | 0.121788 | 6.809362 | 0.0179 |
| 2 | NumPy DLPack / NumPy copy | 1,000 | 0.000372 | 0.000945 | 0.3934 |
| 2 | NumPy DLPack / NumPy copy | 10,000 | 0.000376 | 0.004918 | 0.0764 |
| 2 | NumPy DLPack / NumPy copy | 100,000 | 0.001043 | 0.163884 | 0.0064 |
| 2 | NumPy DLPack / NumPy copy | 1,000,000 | 0.002376 | 1.387827 | 0.0017 |
| 3 | float32 export / float64 then cast | 1,000 | 0.019275 | 0.021406 | 0.9005 |
| 3 | float32 export / float64 then cast | 10,000 | 0.096822 | 0.101636 | 0.9526 |
| 3 | float32 export / float64 then cast | 100,000 | 1.005458 | 1.146253 | 0.8772 |
| 3 | float32 export / float64 then cast | 1,000,000 | 9.506717 | 11.059092 | 0.8596 |
| 4 | readcon TensorBlock / ASE TensorBlock | 1,000 | 0.199492 | 1.050601 | 0.1899 |
| 4 | readcon TensorBlock / ASE TensorBlock | 10,000 | 1.392714 | 8.116269 | 0.1716 |
| 4 | readcon TensorBlock / ASE TensorBlock | 100,000 | 12.917369 | 82.507692 | 0.1566 |
| 4 | readcon TensorBlock / ASE TensorBlock | 1,000,000 | 162.013881 | 955.342921 | 0.1696 |

The complete medians, quartiles, IQRs, statuses, and comparator ratios are in
`summary.csv`. Every individual sample is in `results.csv`.

## Reproduction

Install the matching Rust toolchain and Python dependencies, then run:

```console
rustup toolchain install 1.88.0
python3 -m venv .bench-venv
.bench-venv/bin/pip install -r bench/ecosystem/requirements.txt
./bench/ecosystem/run.sh
```

The metatensor-core pin matches the C ABI used by the repository's
`metatensor-sys` dependency. GNU 13 C/C++ compilers and CMake are required.
Set `CC` and `CXX` if those compiler executable names differ.
