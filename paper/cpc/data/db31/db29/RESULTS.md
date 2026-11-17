# db29 realistic arms

Commit `a584a28816c2f603c8c94759fdf45d86fc20f069`, tree `c1c761697b9aa9e57f3f1943868811285c5d8d03`. Host label `host`, Intel(R) Xeon(R) Processor, 8 CPUs. OMP_NUM_THREADS=1, OPENBLAS_NUM_THREADS=1, MKL_NUM_THREADS=1, NUMEXPR_NUM_THREADS=1. cpuinfo 2700.0 MHz. Kernel 6.12.113+. CPU Intel(R) Xeon(R) Processor. serial=true. quantile type-7. n=12, serial. Warm reads are full, range, and selected. Cold bulk is the full read. Threads are the process default and `RAYON_NUM_THREADS=1`. The paired CI is a 10000-draw percentile bootstrap, type-7 median, numpy Generator seed 0. The ratio is the right-hand layout over the left. Faster counts the right-hand layout.

raw and shuffle-zstd are `READCON_DB_COOKED_CODEC`. warm-point and cold-bulk are `set_cooked_access` with that variable unset. The lattice arm is the best case. Quote md and thermal.

## Bytes and peak RSS

| arm | layout | codec stored | atoms/frame | corpus bytes | frames_soa bytes | hit shuffle | peak RSS |
| --- | --- | --- | --- | --- | --- | --- | --- |
| md | raw | raw | 60702 | 614641664 | 409898306 | False | 2937233408 |
| md | shuffle | shuffle-zstd | 60702 | 416727040 | 212073873 | True | 2576334848 |
| md | warm-point | raw | 60702 | 614641664 | 409898306 | False | 2937249792 |
| md | cold-bulk | shuffle-zstd | 60702 | 416727040 | 212073873 | True | 2589184000 |
| thermal | raw | raw | 60702 | 779874304 | 409898306 | False | 1760907264 |
| thermal | shuffle | shuffle-zstd | 60702 | 722833408 | 353274932 | True | 1667948544 |
| thermal | warm-point | raw | 60702 | 779874304 | 409898306 | False | 1786368000 |
| thermal | cold-bulk | shuffle-zstd | 60702 | 722833408 | 353274932 | True | 1732227072 |
| lattice | raw | raw | 100000 | 341966848 | 307208960 | False | 1349799936 |
| lattice | shuffle | shuffle-zstd | 100000 | 36569088 | 1583727 | True | 944427008 |
| lattice | warm-point | raw | 100000 | 341966848 | 307208960 | False | 1349902336 |
| lattice | cold-bulk | shuffle-zstd | 100000 | 36569088 | 1583727 | True | 910475264 |

## Float32 XTC widened to float64

The NhaA XTC stores coordinates as float32 nanometres. The arm widens them to float64 and multiplies by 10. A widened float32 keeps zeros in the low bytes. Thermal noise fills those bytes, so the same atoms compress less. Lane 0 is the least-significant byte.

- md stored angstrom: n=38424366 low32=0.027212706645569636 low29=0.21440957542409417 low24=1.0 lanes=[1.000, 1.000, 1.000, 0.027, 0.040, 0.008, 0.001, 0.000]
- thermal stored angstrom: n=38424366 low32=0.0 low29=0.0 low24=1.0410061157547791e-07 lanes=[0.004, 0.004, 0.004, 0.004, 0.004, 0.004, 0.001, 0.000]
- lattice stored angstrom: n=19200000 low32=0.9999933333333333 low29=0.9999933333333333 low24=0.9999933333333333 lanes=[1.000, 1.000, 1.000, 1.000, 0.742, 0.585, 0.005, 0.000]
- md widened nm, before times 10: n=38424366 low32=0.12535514574267798 low29=1.0 low24=1.0 lanes=[1.000, 1.000, 1.000, 0.125, 0.008, 0.005, 0.007, 0.000]
- md times 10 angstrom, from the XTC: n=38424366 low32=0.027212706645569636 low29=0.21440957542409417 low24=1.0 lanes=[1.000, 1.000, 1.000, 0.027, 0.040, 0.008, 0.001, 0.000]

## raw vs shuffle-zstd

| arm | op | cache | threads | raw s | shuffle s | paired | 95% CI | faster |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| md | full_read | cold | unset | 7.7079e-01 | 3.6178e-01 | 0.4114 | [0.3722, 0.6428] | 11/12 |
| md | full_read | warm | unset | 2.9467e-01 | 1.7831e-01 | 0.6247 | [0.5292, 0.6852] | 12/12 |
| md | range | warm | unset | 5.7934e-02 | 3.1643e-02 | 0.5512 | [0.4752, 0.6971] | 12/12 |
| md | selected | warm | unset | 1.1623e-03 | 1.6007e-03 | 1.3840 | [1.3431, 1.4195] | 0/12 |
| md | full_read | cold | 1 | 9.1533e-01 | 6.4729e-01 | 0.7234 | [0.6243, 0.9093] | 9/12 |
| md | full_read | warm | 1 | 3.6664e-01 | 4.7127e-01 | 1.2537 | [1.0457, 1.5977] | 2/12 |
| md | range | warm | 1 | 6.4626e-02 | 8.8324e-02 | 1.4265 | [1.1735, 1.6113] | 1/12 |
| md | selected | warm | 1 | 1.2679e-03 | 1.6551e-03 | 1.3177 | [1.2853, 1.3325] | 0/12 |
| thermal | full_read | cold | unset | 8.0128e-01 | 4.7156e-01 | 0.5885 | [0.5296, 0.6497] | 12/12 |
| thermal | full_read | warm | unset | 3.6130e-01 | 1.9504e-01 | 0.5305 | [0.4715, 0.6795] | 12/12 |
| thermal | range | warm | unset | 5.9325e-02 | 3.5829e-02 | 0.6064 | [0.5123, 0.7792] | 10/12 |
| thermal | selected | warm | unset | 1.1904e-03 | 1.5140e-03 | 1.3015 | [1.2106, 1.3290] | 0/12 |
| thermal | full_read | cold | 1 | 7.6036e-01 | 6.5732e-01 | 0.7780 | [0.6602, 1.0444] | 8/12 |
| thermal | full_read | warm | 1 | 3.5890e-01 | 3.3660e-01 | 0.9377 | [0.9173, 1.3898] | 7/12 |
| thermal | range | warm | 1 | 6.3519e-02 | 7.3402e-02 | 1.1770 | [1.0679, 1.3972] | 1/12 |
| thermal | selected | warm | 1 | 1.1716e-03 | 1.3877e-03 | 1.1904 | [1.1757, 1.1956] | 0/12 |
| lattice | full_read | cold | unset | 5.1301e-01 | 1.0579e-01 | 0.1961 | [0.1593, 0.2720] | 12/12 |
| lattice | full_read | warm | unset | 2.2257e-01 | 6.4541e-02 | 0.2880 | [0.2682, 0.4182] | 12/12 |
| lattice | range | warm | unset | 6.4649e-02 | 1.9268e-02 | 0.2931 | [0.2765, 0.3281] | 12/12 |
| lattice | selected | warm | unset | 2.6245e-03 | 2.0266e-03 | 0.7725 | [0.7070, 0.8192] | 12/12 |
| lattice | full_read | cold | 1 | 4.9797e-01 | 2.1891e-01 | 0.4498 | [0.3553, 0.5522] | 12/12 |
| lattice | full_read | warm | 1 | 2.2315e-01 | 1.7516e-01 | 0.7903 | [0.7310, 0.8859] | 10/12 |
| lattice | range | warm | 1 | 6.5126e-02 | 3.8410e-02 | 0.5596 | [0.4431, 0.7337] | 12/12 |
| lattice | selected | warm | 1 | 2.4512e-03 | 2.0359e-03 | 0.8121 | [0.7986, 0.8466] | 12/12 |

## set_cooked_access

warm-point against cold-bulk. The ratio is cold-bulk / warm-point.

| arm | op | cache | threads | warm-point s | cold-bulk s | paired | 95% CI | faster |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| md | full_read | cold | unset | 8.2610e-01 | 3.5080e-01 | 0.4164 | [0.3898, 0.4909] | 12/12 |
| md | full_read | warm | unset | 3.8945e-01 | 2.2131e-01 | 0.5763 | [0.4316, 0.7069] | 12/12 |
| md | range | warm | unset | 7.0522e-02 | 3.6680e-02 | 0.5590 | [0.4235, 0.6325] | 12/12 |
| md | selected | warm | unset | 1.2721e-03 | 1.6579e-03 | 1.2820 | [1.2441, 1.3382] | 0/12 |
| md | full_read | cold | 1 | 8.7452e-01 | 5.7709e-01 | 0.6638 | [0.6086, 0.7923] | 11/12 |
| md | full_read | warm | 1 | 3.8162e-01 | 4.1585e-01 | 1.0767 | [0.8521, 1.1891] | 5/12 |
| md | range | warm | 1 | 6.2016e-02 | 7.9859e-02 | 1.3338 | [1.2170, 1.4126] | 1/12 |
| md | selected | warm | 1 | 1.1961e-03 | 1.5946e-03 | 1.3231 | [1.2700, 1.3581] | 0/12 |
| thermal | full_read | cold | unset | 9.4083e-01 | 4.8206e-01 | 0.5416 | [0.4107, 0.6711] | 12/12 |
| thermal | full_read | warm | unset | 3.2857e-01 | 1.7237e-01 | 0.5408 | [0.4111, 0.6711] | 12/12 |
| thermal | range | warm | unset | 6.3612e-02 | 3.1786e-02 | 0.5381 | [0.4444, 0.6221] | 12/12 |
| thermal | selected | warm | unset | 1.2451e-03 | 1.4096e-03 | 1.1479 | [1.0572, 1.1754] | 1/12 |
| thermal | full_read | cold | 1 | 8.5940e-01 | 7.1833e-01 | 0.8044 | [0.7223, 1.1288] | 8/12 |
| thermal | full_read | warm | 1 | 3.7906e-01 | 3.4664e-01 | 0.8731 | [0.7963, 1.2831] | 8/12 |
| thermal | range | warm | 1 | 6.2741e-02 | 7.5537e-02 | 1.2361 | [1.0412, 1.4368] | 2/12 |
| thermal | selected | warm | 1 | 1.2028e-03 | 1.4109e-03 | 1.1759 | [1.1605, 1.1915] | 0/12 |
| lattice | full_read | cold | unset | 4.9529e-01 | 1.0091e-01 | 0.2070 | [0.1514, 0.2773] | 12/12 |
| lattice | full_read | warm | unset | 2.1374e-01 | 6.7518e-02 | 0.3141 | [0.2851, 0.3977] | 12/12 |
| lattice | range | warm | unset | 6.3613e-02 | 1.9853e-02 | 0.2810 | [0.2423, 0.3986] | 12/12 |
| lattice | selected | warm | unset | 2.4208e-03 | 1.9726e-03 | 0.7937 | [0.7846, 0.8554] | 11/12 |
| lattice | full_read | cold | 1 | 4.8450e-01 | 1.8164e-01 | 0.3766 | [0.3592, 0.4153] | 12/12 |
| lattice | full_read | warm | 1 | 2.1575e-01 | 1.5059e-01 | 0.6903 | [0.6282, 0.7576] | 10/12 |
| lattice | range | warm | 1 | 6.1063e-02 | 3.2510e-02 | 0.5596 | [0.3946, 0.6844] | 12/12 |
| lattice | selected | warm | 1 | 2.4573e-03 | 1.9138e-03 | 0.7804 | [0.7687, 0.7911] | 12/12 |
