# db25 warm full and range

Commit `a584a28816c2f603c8c94759fdf45d86fc20f069`, tree `c1c761697b9aa9e57f3f1943868811285c5d8d03`. Pushed base `28dbf15e8ff2cecdff429bcedbd5c9e2e3a60b59`. Host Intel(R) Xeon(R) Processor, 8 CPUs. OMP_NUM_THREADS=1, OPENBLAS_NUM_THREADS=1, MKL_NUM_THREADS=1, NUMEXPR_NUM_THREADS=1. cpuinfo 2700.0 MHz. Kernel 6.12.113+. CPU Intel(R) Xeon(R) Processor. serial=true. quantile type-7. n=12, serial. Arm order is db18, raw, shuffle, ase; reversed on odd sample indexes. These rows are the warm full and range reads. A multi-frame shuffle read unshuffles into the NumPy buffer allocated up front. Selected and the cold rows are unchanged from db24 and are not repeated. The median is type-7. Parentheses are the type-7 IQR. The paired CI is a 10000-draw percentile bootstrap of the shuffle/raw ratio at the same sample index (numpy Generator seed 0).

| op | threads | raw | shuffle-zstd | shuffle/raw | paired median | 95% CI | faster |
| --- | --- | --- | --- | --- | --- | --- | --- |
| full_read | unset | 2.5357e-01 (5.3720e-02) | 7.3485e-02 (9.9416e-03) | 0.2898 | 0.3388 | [0.2864, 0.3664] | 12/12 |
| range | unset | 8.1753e-02 (3.3063e-02) | 2.2405e-02 (8.6346e-03) | 0.2741 | 0.2844 | [0.2742, 0.2983] | 12/12 |
| full_read | 1 | 2.7393e-01 (2.0833e-02) | 1.7534e-01 (2.3418e-02) | 0.6401 | 0.6584 | [0.6220, 0.7668] | 12/12 |
| range | 1 | 7.6848e-02 (3.1458e-02) | 4.6030e-02 (1.5493e-02) | 0.5990 | 0.6173 | [0.4012, 0.8510] | 11/12 |

Single-thread warm full reads are faster: the paired interval is below 1.
