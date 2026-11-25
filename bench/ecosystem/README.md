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
- 4: both arms free the TensorBlock inside the timer; published medians are pending a rerun

## Summary

Medians are milliseconds. Ratio is the first arm divided by its comparator.

| Item | Arm / comparator | Atoms | Median A (ms) | Median B (ms) | Ratio |
|---|---|---:|---:|---:|---:|
| 2 | torch DLPack / torch copy | 1,000 | 0.001288 | 0.002500 | 0.5152 |
| 2 | torch DLPack / torch copy | 10,000 | 0.001124 | 0.006592 | 0.1704 |
| 2 | torch DLPack / torch copy | 100,000 | 0.001732 | 0.027771 | 0.0624 |
| 2 | torch DLPack / torch copy | 1,000,000 | 0.006492 | 0.204037 | 0.0318 |
| 2 | JAX DLPack / explicit copy | 1,000 | pending rerun | pending rerun | pending rerun |
| 2 | JAX DLPack / explicit copy | 10,000 | pending rerun | pending rerun | pending rerun |
| 2 | JAX DLPack / explicit copy | 100,000 | pending rerun | pending rerun | pending rerun |
| 2 | JAX DLPack / explicit copy | 1,000,000 | pending rerun | pending rerun | pending rerun |
| 2 | NumPy DLPack / NumPy copy | 1,000 | 0.000372 | 0.000945 | 0.3934 |
| 2 | NumPy DLPack / NumPy copy | 10,000 | 0.000376 | 0.004918 | 0.0764 |
| 2 | NumPy DLPack / NumPy copy | 100,000 | 0.001043 | 0.163884 | 0.0064 |
| 2 | NumPy DLPack / NumPy copy | 1,000,000 | 0.002376 | 1.387827 | 0.0017 |
| 3 | float32 export / float64 then cast | 1,000 | 0.019275 | 0.021406 | 0.9005 |
| 3 | float32 export / float64 then cast | 10,000 | 0.096822 | 0.101636 | 0.9526 |
| 3 | float32 export / float64 then cast | 100,000 | 1.005458 | 1.146253 | 0.8772 |
| 3 | float32 export / float64 then cast | 1,000,000 | 9.506717 | 11.059092 | 0.8596 |
| 4 | readcon TensorBlock / ASE TensorBlock | 1,000 | pending rerun | pending rerun | pending rerun |
| 4 | readcon TensorBlock / ASE TensorBlock | 10,000 | pending rerun | pending rerun | pending rerun |
| 4 | readcon TensorBlock / ASE TensorBlock | 100,000 | pending rerun | pending rerun | pending rerun |
| 4 | readcon TensorBlock / ASE TensorBlock | 1,000,000 | pending rerun | pending rerun | pending rerun |

The JAX explicit-copy arm previously copied with NumPy and then with JAX.
That double copy produced the withdrawn speedup (roughly 55x at one
million atoms). Those figures are pending a rerun. The JAX rows in
`summary.csv` and `results.csv` are that double-copy run and are not a
current result. Item 4 samples in those files were recorded when only the
readcon arm freed inside the timer. `elapsed` stopped the clock before
`del result`, so the ASE TensorBlock was freed afterwards. Those medians
are pending a rerun. Other medians, quartiles, IQRs, statuses, and
comparator ratios are in `summary.csv`. Every individual sample is in
`results.csv`.

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
