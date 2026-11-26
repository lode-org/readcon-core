# Ecosystem exchange benchmarks

These results measure readcon-core commit
`4eaa5f0d9b0e61f07b277a50815704a8795babd8`. The run completed on
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
PyTorch, and JAX. JAX uses `copy=False` and x64 mode. Each explicit-copy
arm performs one copy (`torch.tensor`, `jnp.array(..., copy=True)`, or
`np.array(..., copy=True)`). CuPy was not run. Its rows use the same device
probe status as item 1.
For item 3, a file requesting `storage_dtypes.positions=float32` is read
through the C API. Direct float32 DLPack export is compared with float64
DLPack export followed by `astype(float32)`. For item 4, both arms read the
same file, build one TensorBlock, and free that block before returning.
`elapsed` stops the clock before it deletes the return value. The readcon
arm calls `rkr_mts_block_free` and `free_rkr_frame` before returning. The
ASE arm deletes the Python TensorBlock before returning. Both frees are
inside the measured interval. Before timing, the native and ASE shapes and
all position values are asserted equal.

Item 1 does not simulate a device. It probes with `torch.cuda.is_available()`
and the JAX device list. The status is `NO_CUDA` when at least one of those
libraries imports and neither reports a CUDA or GPU device. It is
`NOT_TIMED` when a CUDA or GPU device is visible, because this harness does
not time a CUDA export. It is `NOT_PROBED` when neither library imports.
The checked-in item 1 and CuPy rows say `NO_CUDA`. They were written before
this probe, on a host with no NVIDIA device.

Status by item:

- 1: probe via `torch.cuda.is_available()` and `jax.devices()`; checked-in
  rows predate the probe
- 2: `MEASURED` on CPU for NumPy, PyTorch, and JAX; CuPy rows use the item 1
  probe status
- 3: `MEASURED`
- 4: both arms free the TensorBlock inside the timer; published medians are in the table below

## Summary

Medians are milliseconds. Ratio is the first arm divided by its comparator.

| Item | Arm / comparator | Atoms | Median A (ms) | Median B (ms) | Ratio |
|---|---|---:|---:|---:|---:|
| 2 | torch DLPack / torch copy | 1,000 | 0.001785 | 0.003479 | 0.5129 |
| 2 | torch DLPack / torch copy | 10,000 | 0.001856 | 0.007525 | 0.2466 |
| 2 | torch DLPack / torch copy | 100,000 | 0.001884 | 0.020309 | 0.0928 |
| 2 | torch DLPack / torch copy | 1,000,000 | 0.010170 | 0.228943 | 0.0444 |
| 2 | JAX DLPack / explicit copy | 1,000 | 0.056466 | 0.031340 | 1.8017 |
| 2 | JAX DLPack / explicit copy | 10,000 | 0.054678 | 0.038123 | 1.4342 |
| 2 | JAX DLPack / explicit copy | 100,000 | 0.091373 | 0.124921 | 0.7314 |
| 2 | JAX DLPack / explicit copy | 1,000,000 | 0.101639 | 0.481759 | 0.2110 |
| 2 | NumPy DLPack / NumPy copy | 1,000 | 0.000448 | 0.001124 | 0.3988 |
| 2 | NumPy DLPack / NumPy copy | 10,000 | 0.000466 | 0.004891 | 0.0954 |
| 2 | NumPy DLPack / NumPy copy | 100,000 | 0.002268 | 0.148133 | 0.0153 |
| 2 | NumPy DLPack / NumPy copy | 1,000,000 | 0.002628 | 1.428977 | 0.0018 |
| 3 | float32 export / float64 then cast | 1,000 | 0.019713 | 0.021064 | 0.9359 |
| 3 | float32 export / float64 then cast | 10,000 | 0.098427 | 0.103367 | 0.9522 |
| 3 | float32 export / float64 then cast | 100,000 | 1.008279 | 1.169183 | 0.8624 |
| 3 | float32 export / float64 then cast | 1,000,000 | 9.579188 | 11.738770 | 0.8160 |
| 4 | readcon TensorBlock / ASE TensorBlock | 1,000 | 0.136762 | 1.015618 | 0.1347 |
| 4 | readcon TensorBlock / ASE TensorBlock | 10,000 | 1.412858 | 15.483655 | 0.0912 |
| 4 | readcon TensorBlock / ASE TensorBlock | 100,000 | 8.405926 | 83.040211 | 0.1012 |
| 4 | readcon TensorBlock / ASE TensorBlock | 1,000,000 | 122.366317 | 947.800469 | 0.1291 |

The JAX explicit-copy arm previously copied with NumPy and then with JAX.
That double copy produced the withdrawn speedup (roughly 55x at one
million atoms). The rows in `summary.csv` and `results.csv` are the
single-copy rerun, and the table above has its medians. Item 4 samples
previously freed only the readcon TensorBlock inside the timer.
`elapsed` stops the clock before `del result`. This rerun frees both
blocks before returning, and the table above has those medians. Other
medians, quartiles, IQRs, statuses, and comparator ratios are in
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
