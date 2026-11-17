# raw full-read bisect

Commit `a584a28816c2f603c8c94759fdf45d86fc20f069`. n=30. Each CI is computed from the paired samples in `samples.json`. Host label `host`. OMP_NUM_THREADS=1, OPENBLAS_NUM_THREADS=1, MKL_NUM_THREADS=1, NUMEXPR_NUM_THREADS=1. cpuinfo 2700.0 MHz. Kernel 6.12.113+. CPU Intel(R) Xeon(R) Processor. serial=true. quantile type-7.

| left | right | threads | n | paired | 95% CI | right faster |
| --- | --- | --- | --- | --- | --- | --- |
| `aedcbda468d208278b8699b80c6db743edcdc21e` | `750b1970b2ddc9cc0bb4547d3918024d67d7f6a6` | unset | 30 | 0.8410 | [0.7230, 1.2262] | 16/30 |
| `aedcbda468d208278b8699b80c6db743edcdc21e` | `750b1970b2ddc9cc0bb4547d3918024d67d7f6a6` | 1 | 30 | 1.0744 | [0.9923, 1.3720] | 10/30 |
| `750b1970b2ddc9cc0bb4547d3918024d67d7f6a6` | `d671c327375f588044b6f4953314cd80ddddf356` | unset | 30 | 0.8654 | [0.6483, 1.0415] | 18/30 |
| `750b1970b2ddc9cc0bb4547d3918024d67d7f6a6` | `d671c327375f588044b6f4953314cd80ddddf356` | 1 | 30 | 0.8978 | [0.7520, 1.2712] | 16/30 |
| `d671c327375f588044b6f4953314cd80ddddf356` | `20a5f64e37d9a0892e913289d39bcbe71d7718f8` | unset | 30 | 0.9638 | [0.9033, 1.0244] | 18/30 |
| `d671c327375f588044b6f4953314cd80ddddf356` | `20a5f64e37d9a0892e913289d39bcbe71d7718f8` | 1 | 30 | 0.9745 | [0.7573, 1.1875] | 17/30 |
