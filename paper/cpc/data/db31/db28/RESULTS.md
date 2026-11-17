# db28 realistic arms at lattice scale

Commit `a584a28816c2f603c8c94759fdf45d86fc20f069`, tree `c1c761697b9aa9e57f3f1943868811285c5d8d03`. Host Intel(R) Xeon(R) Processor, 8 CPUs. OMP_NUM_THREADS=1, OPENBLAS_NUM_THREADS=1, MKL_NUM_THREADS=1, NUMEXPR_NUM_THREADS=1. cpuinfo 2700.0 MHz. Kernel 6.12.113+. CPU Intel(R) Xeon(R) Processor. serial=true. quantile type-7. n=12, serial. The same reads run on every arm. Arm order within a sample is raw, shuffle, reversed on odd indexes. Warm selected seconds are the mean per frame. The median is type-7. Parentheses are the type-7 IQR. The paired CI is a 10000-draw percentile bootstrap, type-7 median, numpy Generator seed 0. The lattice arm is the best case. Quote md and thermal.

md is the CC-BY 4.0 NhaA membrane trajectory (Ian Kenney and Shujie Fan, figshare 7185203): 60702 protein, lipid, and ion atoms, water removed by the authors, 211 strided frames. thermal is seeded 0.08 angstrom noise on that structure, 211 frames.

## Bytes and codec

| arm | role | codec stored | atoms/frame | coord bytes/frame | corpus bytes | frames_soa bytes | stored frame bytes | hit shuffle | peak RSS |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| md | realistic | raw | 60702 | 1456848 | 614641664 | 409898306 | 1942646 | False | 2937352192 |
| md | realistic | shuffle-zstd | 60702 | 1456848 | 416727040 | 212073873 | 1005089 | True | 2582908928 |
| thermal | realistic | raw | 60702 | 1456848 | 779874304 | 409898306 | 1942646 | False | 1786380288 |
| thermal | realistic | shuffle-zstd | 60702 | 1456848 | 722833408 | 353274932 | 1674289 | True | 1705254912 |
| lattice | best case | raw | 100000 | 4800000 | 341966848 | 307208960 | 4800140 | False | 1349898240 |
| lattice | best case | shuffle-zstd | 100000 | 4800000 | 36569088 | 1583727 | 24746 | True | 902901760 |

## Headline ratios

shuffle/raw. File ratio is corpus bytes. Time ratio is the paired median.

| arm | role | file | full cold unset | full warm unset | full cold 1 | full warm 1 |
| --- | --- | --- | --- | --- | --- | --- |
| md | realistic | 0.6780 | 0.3951 [0.3501, 0.4384] 12/12 | 0.6214 [0.5202, 0.6531] 12/12 | 0.8166 [0.7191, 0.9058] 10/12 | 1.3546 [1.0841, 1.9042] 1/12 |
| thermal | realistic | 0.9269 | 0.5180 [0.4516, 0.6436] 12/12 | 0.6571 [0.5851, 1.0290] 8/12 | 0.7764 [0.6841, 0.9392] 10/12 | 1.0788 [0.9376, 1.4444] 6/12 |
| lattice | best case | 0.1069 | 0.1947 [0.1549, 0.2157] 12/12 | 0.3404 [0.2348, 0.3966] 12/12 | 0.4010 [0.3002, 0.4219] 12/12 | 0.6696 [0.5755, 0.7597] 12/12 |

## All reads

| arm | op | cache | threads | raw s | shuffle s | shuffle/raw | paired median | 95% CI | faster |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| md | full_read | cold | unset | 7.8495e-01 (9.3447e-02) | 3.1183e-01 (3.4881e-02) | 0.3973 | 0.3951 | [0.3501, 0.4384] | 12/12 |
| md | selected | cold | unset | 3.5441e-03 (4.2788e-04) | 2.9631e-03 (4.0528e-04) | 0.8361 | 0.8108 | [0.7379, 0.8802] | 12/12 |
| md | range | cold | unset | 1.7962e-01 (2.6557e-02) | 8.4607e-02 (9.4075e-03) | 0.4710 | 0.4604 | [0.4439, 0.5391] | 12/12 |
| md | full_read | warm | unset | 2.8609e-01 (6.7640e-02) | 1.7567e-01 (1.6062e-02) | 0.6140 | 0.6214 | [0.5202, 0.6531] | 12/12 |
| md | selected | warm | unset | 1.1614e-03 (2.1706e-05) | 1.5974e-03 (9.3816e-06) | 1.3754 | 1.3726 | [1.3588, 1.3888] | 0/12 |
| md | range | warm | unset | 6.1566e-02 (6.2570e-03) | 3.7233e-02 (5.1481e-03) | 0.6048 | 0.6035 | [0.5150, 0.6605] | 11/12 |
| md | full_read | cold | 1 | 7.2923e-01 (1.7907e-01) | 6.0558e-01 (1.9239e-01) | 0.8304 | 0.8166 | [0.7191, 0.9058] | 10/12 |
| md | selected | cold | 1 | 3.2112e-03 (5.8583e-04) | 2.2039e-03 (2.7619e-04) | 0.6863 | 0.6957 | [0.5769, 0.7791] | 12/12 |
| md | range | cold | 1 | 1.8319e-01 (2.9156e-02) | 1.3775e-01 (1.5043e-02) | 0.7520 | 0.7529 | [0.6874, 0.8684] | 10/12 |
| md | full_read | warm | 1 | 3.4996e-01 (8.6102e-02) | 4.1268e-01 (1.7784e-01) | 1.1792 | 1.3546 | [1.0841, 1.9042] | 1/12 |
| md | selected | warm | 1 | 1.1649e-03 (9.4606e-06) | 1.6244e-03 (2.8685e-05) | 1.3944 | 1.3919 | [1.3696, 1.4111] | 0/12 |
| md | range | warm | 1 | 6.1143e-02 (1.0291e-02) | 8.9193e-02 (1.0379e-02) | 1.4588 | 1.3961 | [1.3013, 1.6574] | 0/12 |
| thermal | full_read | cold | unset | 7.5592e-01 (9.8725e-02) | 3.8883e-01 (1.0494e-01) | 0.5144 | 0.5180 | [0.4516, 0.6436] | 12/12 |
| thermal | selected | cold | unset | 4.0599e-03 (7.2161e-04) | 3.8297e-03 (8.8197e-04) | 0.9433 | 0.8903 | [0.7422, 1.1555] | 7/12 |
| thermal | range | cold | unset | 1.9480e-01 (2.9474e-02) | 1.2169e-01 (1.0510e-02) | 0.6247 | 0.6336 | [0.5712, 0.6476] | 12/12 |
| thermal | full_read | warm | unset | 3.5351e-01 (8.8182e-02) | 2.3546e-01 (4.5683e-02) | 0.6661 | 0.6571 | [0.5851, 1.0290] | 8/12 |
| thermal | selected | warm | unset | 1.1502e-03 (3.5839e-05) | 1.3641e-03 (2.1916e-05) | 1.1859 | 1.1923 | [1.1526, 1.2080] | 1/12 |
| thermal | range | warm | unset | 5.8522e-02 (1.4775e-02) | 4.2011e-02 (4.5023e-03) | 0.7179 | 0.7334 | [0.6278, 0.8052] | 12/12 |
| thermal | full_read | cold | 1 | 7.8766e-01 (1.1995e-01) | 5.7654e-01 (1.1362e-01) | 0.7320 | 0.7764 | [0.6841, 0.9392] | 10/12 |
| thermal | selected | cold | 1 | 3.3088e-03 (4.1442e-04) | 3.5123e-03 (3.7332e-04) | 1.0615 | 1.0157 | [0.9131, 1.1510] | 6/12 |
| thermal | range | cold | 1 | 1.8262e-01 (2.8952e-02) | 1.2644e-01 (2.8188e-02) | 0.6923 | 0.7605 | [0.6335, 0.8623] | 11/12 |
| thermal | full_read | warm | 1 | 3.0524e-01 (8.7042e-02) | 3.3000e-01 (3.2907e-02) | 1.0811 | 1.0788 | [0.9376, 1.4444] | 6/12 |
| thermal | selected | warm | 1 | 1.1447e-03 (2.4721e-05) | 1.3648e-03 (9.9915e-05) | 1.1922 | 1.2011 | [1.1762, 1.3219] | 0/12 |
| thermal | range | warm | 1 | 5.7311e-02 (1.3098e-02) | 7.0184e-02 (1.0912e-02) | 1.2246 | 1.1391 | [1.0674, 1.4855] | 2/12 |
| lattice | full_read | cold | unset | 4.1950e-01 (3.9583e-02) | 8.0402e-02 (8.6799e-03) | 0.1917 | 0.1947 | [0.1549, 0.2157] | 12/12 |
| lattice | selected | cold | unset | 4.7387e-03 (7.7692e-04) | 1.4056e-03 (1.5589e-04) | 0.2966 | 0.2915 | [0.2717, 0.3128] | 12/12 |
| lattice | range | cold | unset | 1.2363e-01 (1.9522e-02) | 2.0271e-02 (3.5105e-03) | 0.1640 | 0.1660 | [0.1443, 0.1962] | 12/12 |
| lattice | full_read | warm | unset | 1.9307e-01 (2.3064e-02) | 6.5687e-02 (2.0169e-02) | 0.3402 | 0.3404 | [0.2348, 0.3966] | 12/12 |
| lattice | selected | warm | unset | 2.3424e-03 (4.2031e-05) | 1.8916e-03 (8.0485e-05) | 0.8076 | 0.8047 | [0.7917, 0.8479] | 12/12 |
| lattice | range | warm | unset | 5.9511e-02 (1.2403e-02) | 1.7129e-02 (3.2440e-03) | 0.2878 | 0.2640 | [0.2411, 0.3324] | 12/12 |
| lattice | full_read | cold | 1 | 5.1289e-01 (6.2044e-02) | 1.7590e-01 (4.5491e-02) | 0.3430 | 0.4010 | [0.3002, 0.4219] | 12/12 |
| lattice | selected | cold | 1 | 5.7027e-03 (4.8100e-04) | 1.4604e-03 (1.6807e-04) | 0.2561 | 0.2521 | [0.2380, 0.2785] | 12/12 |
| lattice | range | cold | 1 | 1.3065e-01 (1.6959e-02) | 3.5940e-02 (9.9093e-03) | 0.2751 | 0.2762 | [0.2209, 0.3482] | 12/12 |
| lattice | full_read | warm | 1 | 2.0739e-01 (4.4869e-02) | 1.4176e-01 (1.7602e-02) | 0.6836 | 0.6696 | [0.5755, 0.7597] | 12/12 |
| lattice | selected | warm | 1 | 2.4082e-03 (7.6617e-05) | 1.9086e-03 (9.3557e-05) | 0.7925 | 0.7864 | [0.7625, 0.8238] | 12/12 |
| lattice | range | warm | 1 | 6.0005e-02 (9.4528e-03) | 3.2591e-02 (8.1369e-03) | 0.5431 | 0.4902 | [0.4490, 0.6629] | 12/12 |
