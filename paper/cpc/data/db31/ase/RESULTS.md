# legacy ASE sqlite bench

OMP_NUM_THREADS=1, OPENBLAS_NUM_THREADS=1, MKL_NUM_THREADS=1, NUMEXPR_NUM_THREADS=1. cpuinfo 2700.0 MHz. Kernel 6.12.113+. CPU Intel(R) Xeon(R) Processor. serial=true. quantile type-7.

Cu2 stand-in. The times are the script means.

| n | insert s | extract mean s | select mean s | 8 readers s |
| --- | --- | --- | --- | --- |
| 10 | 1.767817e-02 | 1.779490e-03 | 1.189910e-03 | 2.246536e-02 |
| 50 | 1.888678e-02 | 7.046710e-03 | 5.563764e-03 | 1.206282e-01 |
| 100 | 1.910654e-02 | 1.403469e-02 | 1.119707e-02 | 2.081662e-01 |
| 200 | 3.263465e-02 | 2.830114e-02 | 2.236683e-02 | 4.525824e-01 |
| 500 | 6.613120e-02 | 6.996189e-02 | 5.600132e-02 | 1.103500e+00 |
