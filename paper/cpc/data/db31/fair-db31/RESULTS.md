# readcon-db vs ASE sqlite

Type-7 median and IQR. One discarded warmup and twelve serial samples
for every fair row. The published log has no discarded warmup.
A mismatch of any stored field aborts the run, so every sample below
passed an element-wise check (fidelity exact).
Cold medians use samples whose mincore resident fraction is 0.
Full read and the selected frame share each sample index.

## Published ingest (`paper/cpc/logs/db.log`)

40 frames, 8 Cu atoms. ASE commits every row. No warmup.

| tool | median s | IQR s | q1 s | q3 s | min s | max s |
| --- | --- | --- | --- | --- | --- | --- |
| readcon-db | 4.6724e-03 | 2.0083e-03 | 3.6932e-03 | 5.7016e-03 | 3.3584e-03 | 6.2406e-03 |
| ase.db | 7.2318e-02 | 3.7693e-02 | 6.0244e-02 | 9.7937e-02 | 5.4239e-02 | 1.0352e-01 |

## This machine, published harness

| tool | median s | IQR s | q1 s | q3 s | min s | max s |
| --- | --- | --- | --- | --- | --- | --- |
| readcon-db | 2.8223e-03 | 1.5053e-03 | 2.3476e-03 | 3.8529e-03 | 1.7859e-03 | 4.6338e-03 |
| ase.db | 4.3732e-02 | 1.8376e-02 | 3.8141e-02 | 5.6517e-02 | 3.3933e-02 | 6.6886e-02 |

## This machine, fair harness

Insert creates the database outside the clock and times the commit.
A full read and the selected-row query (`frame_index` of the middle
frame) copy positions, cell, masses, atomic numbers, constraints,
and velocities into NumPy arrays. ASE does the same via toatoms().
db5 timed only the sqlite fetch, which is why its 1M-atom warm
full read was 0.0166 s against db4's 0.226 s. Open, directory
fsync, fadvise, mincore, and the field check stay outside the
clock. cold-open times the open and the query together, for
both tools, so neither keeps readahead from an open outside
the clock. The cold row still opens outside the clock. Each
row is its own process. A short read repeats to 50 ms and a
short commit to 2 s. Both inserts are one transaction and one
commit fsync. A long readcon-db trajectory puts one 64-frame
group at a time and drops that scratch after the put; the
transaction still commits once. n is 12 serial samples
(READCON_DB_N_SAMPLES, never below 12). p90 is
the type-7 90th percentile of those means. A range read
materializes an inclusive frame-index span. A metadata read
returns the frame indexes whose energy is in the last tenth.
Ingest rows report frames/s and MB/s of the CON text. disk B
is the database file after that ingest.

| workload | op | cache | tool | RAYON_NUM_THREADS | threads | n | median s | p90 s | IQR s | IQR/median | frames/s | MB/s | disk B | peak RSS B | fidelity |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| paper40x8 | insert | cold-file | readcon-db | 1 | 1 | 12 | 2.2606e-03 | 2.3325e-03 | 3.4993e-05 | 0.015 | 1.7694e+04 | 5.5206e+00 | 49152 | 117788672 | exact |
| paper40x8 | insert | cold-file | ase.db | 1 | 1 | 12 | 5.5270e-03 | 5.8677e-03 | 2.9134e-04 | 0.053 | 7.2372e+03 | 2.2580e+00 | 90112 | 104882176 | exact |
| paper40x8 | insert | cold-file | readcon-db | unset | 8 | 12 | 2.2525e-03 | 2.3023e-03 | 8.8849e-05 | 0.039 | 1.7758e+04 | 5.5406e+00 | 49152 | 117813248 | exact |
| atoms-1000 | insert | cold-file | readcon-db | 1 | 1 | 12 | 1.3483e-03 | 1.4791e-03 | 1.6841e-04 | 0.125 | 7.4168e+02 | 3.1560e+01 | 98304 | 104386560 | exact |
| atoms-1000 | insert | cold-file | ase.db | 1 | 1 | 12 | 1.5520e-03 | 1.6173e-03 | 5.7700e-05 | 0.037 | 6.4434e+02 | 2.7418e+01 | 126976 | 102690816 | exact |
| atoms-1000 | insert | cold-file | readcon-db | unset | 8 | 12 | 1.2377e-03 | 1.4385e-03 | 1.8024e-04 | 0.146 | 8.0797e+02 | 3.4381e+01 | 98304 | 104542208 | exact |
| atoms-1000 | full_read | cold | readcon-db | 1 | 1 | 12 | 3.1071e-05 | 3.1869e-05 | 5.5773e-07 | 0.018 |  |  | 98304 | 100728832 | exact |
| atoms-1000 | full_read | cold | ase.db | 1 | 1 | 12 | 2.5292e-03 | 2.8897e-03 | 4.0854e-04 | 0.162 |  |  | 126976 | 117956608 | exact |
| atoms-1000 | full_read | cold | readcon-db | unset | 8 | 12 | 3.2399e-05 | 3.3588e-05 | 1.1548e-06 | 0.036 |  |  | 98304 | 100597760 | exact |
| atoms-1000 | selected | cold | readcon-db | 1 | 1 | 12 | 3.0146e-05 | 3.0375e-05 | 5.0589e-07 | 0.017 |  |  | 98304 | 100597760 | exact |
| atoms-1000 | selected | cold | ase.db | 1 | 1 | 12 | 2.2604e-03 | 2.4061e-03 | 2.4431e-04 | 0.108 |  |  | 126976 | 119599104 | exact |
| atoms-1000 | selected | cold | readcon-db | unset | 8 | 12 | 3.1183e-05 | 3.2230e-05 | 7.7045e-07 | 0.025 |  |  | 98304 | 100638720 | exact |
| atoms-1000 | full_read | warm | readcon-db | 1 | 1 | 12 | 1.6289e-05 | 1.6503e-05 | 2.0560e-07 | 0.013 |  |  | 98304 | 100626432 | exact |
| atoms-1000 | full_read | warm | ase.db | 1 | 1 | 12 | 5.2822e-04 | 5.9683e-04 | 7.8732e-05 | 0.149 |  |  | 126976 | 185679872 | exact |
| atoms-1000 | full_read | warm | readcon-db | unset | 8 | 12 | 1.6148e-05 | 1.6224e-05 | 8.1405e-08 | 0.005 |  |  | 98304 | 100569088 | exact |
| atoms-1000 | selected | warm | readcon-db | 1 | 1 | 12 | 1.6055e-05 | 1.6263e-05 | 1.7329e-07 | 0.011 |  |  | 98304 | 100364288 | exact |
| atoms-1000 | selected | warm | ase.db | 1 | 1 | 12 | 4.7984e-04 | 5.6213e-04 | 3.4183e-05 | 0.071 |  |  | 126976 | 188715008 | exact |
| atoms-1000 | selected | warm | readcon-db | unset | 8 | 12 | 1.6105e-05 | 1.6369e-05 | 1.0260e-07 | 0.006 |  |  | 98304 | 100667392 | exact |
| atoms-10000 | insert | cold-file | readcon-db | 1 | 1 | 12 | 3.6841e-03 | 3.8274e-03 | 1.1295e-04 | 0.031 | 2.7144e+02 | 1.2522e+02 | 589824 | 118878208 | exact |
| atoms-10000 | insert | cold-file | ase.db | 1 | 1 | 12 | 3.7112e-03 | 3.9603e-03 | 2.6231e-04 | 0.071 | 2.6945e+02 | 1.2431e+02 | 667648 | 111525888 | exact |
| atoms-10000 | insert | cold-file | readcon-db | unset | 8 | 12 | 3.6967e-03 | 3.7826e-03 | 7.9570e-05 | 0.022 | 2.7051e+02 | 1.2480e+02 | 589824 | 118685696 | exact |
| atoms-10000 | full_read | cold | readcon-db | 1 | 1 | 12 | 2.9262e-04 | 3.0129e-04 | 8.9008e-06 | 0.030 |  |  | 589824 | 104771584 | exact |
| atoms-10000 | full_read | cold | ase.db | 1 | 1 | 12 | 5.0335e-03 | 5.4418e-03 | 5.3503e-04 | 0.106 |  |  | 667648 | 193077248 | exact |
| atoms-10000 | full_read | cold | readcon-db | unset | 8 | 12 | 2.9915e-04 | 3.0351e-04 | 5.2025e-06 | 0.017 |  |  | 589824 | 104865792 | exact |
| atoms-10000 | selected | cold | readcon-db | 1 | 1 | 12 | 2.8709e-04 | 2.9374e-04 | 3.4965e-06 | 0.012 |  |  | 589824 | 104734720 | exact |
| atoms-10000 | selected | cold | ase.db | 1 | 1 | 12 | 5.2154e-03 | 5.5012e-03 | 2.9050e-04 | 0.056 |  |  | 667648 | 189767680 | exact |
| atoms-10000 | selected | cold | readcon-db | unset | 8 | 12 | 2.9732e-04 | 2.9927e-04 | 3.6390e-06 | 0.012 |  |  | 589824 | 104697856 | exact |
| atoms-10000 | full_read | warm | readcon-db | 1 | 1 | 12 | 2.6799e-04 | 2.7067e-04 | 2.5281e-06 | 0.009 |  |  | 589824 | 103976960 | exact |
| atoms-10000 | full_read | warm | ase.db | 1 | 1 | 12 | 3.5971e-03 | 3.7031e-03 | 9.6192e-05 | 0.027 |  |  | 667648 | 225787904 | exact |
| atoms-10000 | full_read | warm | readcon-db | unset | 8 | 12 | 2.4852e-04 | 2.5315e-04 | 1.2145e-06 | 0.005 |  |  | 589824 | 103940096 | exact |
| atoms-10000 | selected | warm | readcon-db | 1 | 1 | 12 | 2.5789e-04 | 2.5901e-04 | 1.1558e-06 | 0.004 |  |  | 589824 | 103833600 | exact |
| atoms-10000 | selected | warm | ase.db | 1 | 1 | 12 | 3.2082e-03 | 3.3043e-03 | 9.2489e-05 | 0.029 |  |  | 667648 | 241971200 | exact |
| atoms-10000 | selected | warm | readcon-db | unset | 8 | 12 | 2.5917e-04 | 2.5990e-04 | 6.1699e-07 | 0.002 |  |  | 589824 | 103862272 | exact |
| atoms-100000 | insert | cold-file | readcon-db | 1 | 1 | 12 | 2.5725e-02 | 2.6295e-02 | 7.3101e-04 | 0.028 | 3.8873e+01 | 1.9472e+02 | 5390336 | 197238784 | exact |
| atoms-100000 | insert | cold-file | ase.db | 1 | 1 | 12 | 2.4346e-02 | 2.5430e-02 | 1.1074e-03 | 0.045 | 4.1074e+01 | 2.0574e+02 | 6074368 | 206053376 | exact |
| atoms-100000 | insert | cold-file | readcon-db | unset | 8 | 12 | 2.5603e-02 | 2.6048e-02 | 5.0497e-04 | 0.020 | 3.9058e+01 | 1.9564e+02 | 5390336 | 197636096 | exact |
| atoms-100000 | full_read | cold | readcon-db | 1 | 1 | 12 | 5.2342e-03 | 5.9531e-03 | 7.1177e-04 | 0.136 |  |  | 5390336 | 135249920 | exact |
| atoms-100000 | full_read | cold | ase.db | 1 | 1 | 12 | 3.4039e-02 | 3.6355e-02 | 1.6057e-03 | 0.047 |  |  | 6074368 | 300965888 | exact |
| atoms-100000 | full_read | cold | readcon-db | unset | 8 | 12 | 5.0995e-03 | 5.4065e-03 | 4.3834e-04 | 0.086 |  |  | 5390336 | 135114752 | exact |
| atoms-100000 | selected | cold | readcon-db | 1 | 1 | 12 | 5.2760e-03 | 6.1515e-03 | 6.9354e-04 | 0.131 |  |  | 5390336 | 134938624 | exact |
| atoms-100000 | selected | cold | ase.db | 1 | 1 | 12 | 3.3105e-02 | 3.3783e-02 | 9.2038e-04 | 0.028 |  |  | 6074368 | 298041344 | exact |
| atoms-100000 | selected | cold | readcon-db | unset | 8 | 12 | 5.8148e-03 | 6.3039e-03 | 4.4585e-04 | 0.077 |  |  | 5390336 | 135098368 | exact |
| atoms-100000 | full_read | warm | readcon-db | 1 | 1 | 12 | 2.5425e-03 | 2.6161e-03 | 6.5370e-05 | 0.026 |  |  | 5390336 | 128856064 | exact |
| atoms-100000 | full_read | warm | ase.db | 1 | 1 | 12 | 2.9110e-02 | 2.9425e-02 | 5.9353e-04 | 0.020 |  |  | 6074368 | 307011584 | exact |
| atoms-100000 | full_read | warm | readcon-db | unset | 8 | 12 | 2.5597e-03 | 2.6517e-03 | 3.1850e-05 | 0.012 |  |  | 5390336 | 129028096 | exact |
| atoms-100000 | selected | warm | readcon-db | 1 | 1 | 12 | 2.5028e-03 | 2.5640e-03 | 5.7157e-05 | 0.023 |  |  | 5390336 | 128847872 | exact |
| atoms-100000 | selected | warm | ase.db | 1 | 1 | 12 | 3.0952e-02 | 3.3099e-02 | 2.2938e-03 | 0.074 |  |  | 6074368 | 301453312 | exact |
| atoms-100000 | selected | warm | readcon-db | unset | 8 | 12 | 2.4801e-03 | 2.6111e-03 | 7.4531e-05 | 0.030 |  |  | 5390336 | 128839680 | exact |
| atoms-1000000 | insert | cold-file | readcon-db | 1 | 1 | 12 | 2.8672e-01 | 2.9074e-01 | 3.8113e-03 | 0.013 | 3.4877e+00 | 1.8864e+02 | 52592640 | 683089920 | exact |
| atoms-1000000 | insert | cold-file | ase.db | 1 | 1 | 12 | 2.4002e-01 | 2.5204e-01 | 6.2174e-03 | 0.026 | 4.1663e+00 | 2.2534e+02 | 60125184 | 1119891456 | exact |
| atoms-1000000 | insert | cold-file | readcon-db | unset | 8 | 12 | 3.0400e-01 | 3.1394e-01 | 1.1045e-02 | 0.036 | 3.2895e+00 | 1.7792e+02 | 52592640 | 683077632 | exact |
| atoms-1000000 | full_read | cold | readcon-db | 1 | 1 | 12 | 6.4952e-02 | 7.4176e-02 | 7.5588e-03 | 0.116 |  |  | 52592640 | 427593728 | exact |
| atoms-1000000 | full_read | cold | ase.db | 1 | 1 | 12 | 3.6831e-01 | 3.9523e-01 | 3.1972e-02 | 0.087 |  |  | 60125184 | 1353707520 | exact |
| atoms-1000000 | full_read | cold | readcon-db | unset | 8 | 12 | 5.9874e-02 | 7.0124e-02 | 1.4704e-02 | 0.246 |  |  | 52592640 | 427728896 | exact |
| atoms-1000000 | selected | cold | readcon-db | 1 | 1 | 12 | 5.5127e-02 | 6.2114e-02 | 3.7247e-03 | 0.068 |  |  | 52592640 | 427565056 | exact |
| atoms-1000000 | selected | cold | ase.db | 1 | 1 | 12 | 3.3654e-01 | 3.8793e-01 | 2.1308e-02 | 0.063 |  |  | 60125184 | 1320587264 | exact |
| atoms-1000000 | selected | cold | readcon-db | unset | 8 | 12 | 5.8254e-02 | 6.4147e-02 | 5.1813e-03 | 0.089 |  |  | 52592640 | 427384832 | exact |
| atoms-1000000 | full_read | warm | readcon-db | 1 | 1 | 12 | 1.9523e-02 | 2.1238e-02 | 3.0079e-03 | 0.154 |  |  | 52592640 | 364515328 | exact |
| atoms-1000000 | full_read | warm | ase.db | 1 | 1 | 12 | 3.0455e-01 | 3.2944e-01 | 2.0187e-02 | 0.066 |  |  | 60125184 | 1330720768 | exact |
| atoms-1000000 | full_read | warm | readcon-db | unset | 8 | 12 | 2.2791e-02 | 2.5009e-02 | 1.7826e-03 | 0.078 |  |  | 52592640 | 364507136 | exact |
| atoms-1000000 | selected | warm | readcon-db | 1 | 1 | 12 | 2.0628e-02 | 2.1751e-02 | 1.2009e-03 | 0.058 |  |  | 52592640 | 364380160 | exact |
| atoms-1000000 | selected | warm | ase.db | 1 | 1 | 12 | 2.9787e-01 | 3.1964e-01 | 1.5303e-02 | 0.051 |  |  | 60125184 | 1338724352 | exact |
| atoms-1000000 | selected | warm | readcon-db | unset | 8 | 12 | 2.6620e-02 | 3.8538e-02 | 1.0403e-02 | 0.391 |  |  | 52592640 | 364646400 | exact |
| frames-1 | insert | cold-file | readcon-db | 1 | 1 | 12 | 9.4435e-04 | 1.0059e-03 | 1.7707e-04 | 0.188 | 1.0589e+03 | 7.6773e-01 | 40960 | 101908480 | exact |
| frames-1 | insert | cold-file | ase.db | 1 | 1 | 12 | 1.1152e-03 | 1.2051e-03 | 8.7670e-05 | 0.079 | 8.9668e+02 | 6.5010e-01 | 69632 | 105234432 | exact |
| frames-1 | insert | cold-file | readcon-db | unset | 8 | 12 | 7.3380e-04 | 9.2425e-04 | 1.1462e-04 | 0.156 | 1.3628e+03 | 9.8801e-01 | 40960 | 102039552 | exact |
| frames-1 | full_read | cold | readcon-db | 1 | 1 | 12 | 2.2461e-05 | 2.2777e-05 | 5.7441e-07 | 0.026 |  |  | 40960 | 98385920 | exact |
| frames-1 | full_read | cold | ase.db | 1 | 1 | 12 | 5.6110e-04 | 5.8220e-04 | 3.4943e-05 | 0.062 |  |  | 69632 | 103600128 | exact |
| frames-1 | full_read | cold | readcon-db | unset | 8 | 12 | 2.2424e-05 | 2.3624e-05 | 8.5599e-07 | 0.038 |  |  | 40960 | 98656256 | exact |
| frames-1 | selected | cold | readcon-db | 1 | 1 | 12 | 2.1296e-05 | 2.2114e-05 | 8.1619e-07 | 0.038 |  |  | 40960 | 98050048 | exact |
| frames-1 | selected | cold | ase.db | 1 | 1 | 12 | 7.2995e-04 | 7.9777e-04 | 6.5754e-05 | 0.090 |  |  | 69632 | 102383616 | exact |
| frames-1 | selected | cold | readcon-db | unset | 8 | 12 | 2.1199e-05 | 2.4839e-05 | 1.1677e-06 | 0.055 |  |  | 40960 | 98340864 | exact |
| frames-1 | full_read | warm | readcon-db | 1 | 1 | 12 | 1.1577e-05 | 1.1921e-05 | 1.8762e-07 | 0.016 |  |  | 40960 | 98287616 | exact |
| frames-1 | full_read | warm | ase.db | 1 | 1 | 12 | 1.5962e-04 | 1.6167e-04 | 3.2613e-06 | 0.020 |  |  | 69632 | 108957696 | exact |
| frames-1 | full_read | warm | readcon-db | unset | 8 | 12 | 1.1320e-05 | 1.1701e-05 | 1.9945e-07 | 0.018 |  |  | 40960 | 98467840 | exact |
| frames-1 | selected | warm | readcon-db | 1 | 1 | 12 | 1.1264e-05 | 1.1440e-05 | 1.5223e-07 | 0.014 |  |  | 40960 | 98111488 | exact |
| frames-1 | selected | warm | ase.db | 1 | 1 | 12 | 1.6237e-04 | 1.6547e-04 | 1.6166e-06 | 0.010 |  |  | 69632 | 108732416 | exact |
| frames-1 | selected | warm | readcon-db | unset | 8 | 12 | 1.1251e-05 | 1.1646e-05 | 5.7430e-08 | 0.005 |  |  | 40960 | 98226176 | exact |
| frames-100 | insert | cold-file | readcon-db | 1 | 1 | 12 | 4.5084e-03 | 4.5733e-03 | 1.7605e-04 | 0.039 | 2.2181e+04 | 1.6331e+01 | 65536 | 114462720 | exact |
| frames-100 | insert | cold-file | ase.db | 1 | 1 | 12 | 3.1948e-02 | 3.2381e-02 | 2.7029e-04 | 0.008 | 3.1301e+03 | 2.3045e+00 | 151552 | 100802560 | exact |
| frames-100 | insert | cold-file | readcon-db | unset | 8 | 12 | 4.6017e-03 | 4.6819e-03 | 1.3435e-04 | 0.029 | 2.1731e+04 | 1.5999e+01 | 65536 | 115609600 | exact |
| frames-100 | full_read | cold | readcon-db | 1 | 1 | 12 | 6.9793e-05 | 7.2984e-05 | 3.5463e-06 | 0.051 |  |  | 65536 | 105365504 | exact |
| frames-100 | full_read | cold | ase.db | 1 | 1 | 12 | 1.0073e-02 | 1.0428e-02 | 4.0134e-04 | 0.040 |  |  | 151552 | 117723136 | exact |
| frames-100 | full_read | cold | readcon-db | unset | 8 | 12 | 6.7728e-05 | 7.1677e-05 | 4.2985e-06 | 0.063 |  |  | 65536 | 105222144 | exact |
| frames-100 | selected | cold | readcon-db | 1 | 1 | 12 | 2.0235e-05 | 2.0531e-05 | 4.7301e-07 | 0.023 |  |  | 65536 | 103170048 | exact |
| frames-100 | selected | cold | ase.db | 1 | 1 | 12 | 1.0385e-03 | 1.1464e-03 | 5.7204e-05 | 0.055 |  |  | 151552 | 101179392 | exact |
| frames-100 | selected | cold | readcon-db | unset | 8 | 12 | 2.0905e-05 | 2.1439e-05 | 7.5981e-07 | 0.036 |  |  | 65536 | 102940672 | exact |
| frames-100 | full_read | warm-after-open | readcon-db | 1 | 1 | 12 | 6.9148e-05 | 7.0040e-05 | 1.3734e-06 | 0.020 |  |  | 65536 | 105144320 | exact |
| frames-100 | full_read | warm-after-open | ase.db | 1 | 1 | 12 | 1.0071e-02 | 1.0172e-02 | 3.8752e-04 | 0.038 |  |  | 151552 | 117661696 | exact |
| frames-100 | full_read | warm-after-open | readcon-db | unset | 8 | 12 | 6.6315e-05 | 6.7385e-05 | 1.5493e-06 | 0.023 |  |  | 65536 | 105267200 | exact |
| frames-100 | selected | warm-after-open | readcon-db | 1 | 1 | 12 | 2.0707e-05 | 2.0916e-05 | 2.5392e-07 | 0.012 |  |  | 65536 | 102871040 | exact |
| frames-100 | selected | warm-after-open | ase.db | 1 | 1 | 12 | 1.0452e-03 | 1.1504e-03 | 2.0771e-04 | 0.199 |  |  | 151552 | 101351424 | exact |
| frames-100 | selected | warm-after-open | readcon-db | unset | 8 | 12 | 2.0521e-05 | 2.0947e-05 | 4.5520e-07 | 0.022 |  |  | 65536 | 103006208 | exact |
| frames-100 | full_read | cold-open | readcon-db | 1 | 1 | 12 | 4.0415e-04 | 4.3455e-04 | 4.3676e-05 | 0.108 |  |  | 65536 | 105119744 | exact |
| frames-100 | full_read | cold-open | ase.db | 1 | 1 | 12 | 1.0349e-02 | 1.0498e-02 | 2.2779e-04 | 0.022 |  |  | 151552 | 116625408 | exact |
| frames-100 | full_read | cold-open | readcon-db | unset | 8 | 12 | 3.8734e-04 | 4.4248e-04 | 7.5414e-05 | 0.195 |  |  | 65536 | 105385984 | exact |
| frames-100 | selected | cold-open | readcon-db | 1 | 1 | 12 | 2.5348e-04 | 2.8617e-04 | 3.8027e-05 | 0.150 |  |  | 65536 | 102551552 | exact |
| frames-100 | selected | cold-open | ase.db | 1 | 1 | 12 | 1.1549e-03 | 1.2878e-03 | 2.3935e-04 | 0.207 |  |  | 151552 | 100954112 | exact |
| frames-100 | selected | cold-open | readcon-db | unset | 8 | 12 | 2.2326e-04 | 2.8743e-04 | 3.8960e-05 | 0.175 |  |  | 65536 | 102895616 | exact |
| frames-100 | full_read | warm | readcon-db | 1 | 1 | 12 | 4.3565e-05 | 5.4449e-05 | 3.7538e-06 | 0.086 |  |  | 65536 | 105029632 | exact |
| frames-100 | full_read | warm | ase.db | 1 | 1 | 12 | 8.5145e-03 | 8.6257e-03 | 6.8468e-05 | 0.008 |  |  | 151552 | 119808000 | exact |
| frames-100 | full_read | warm | readcon-db | unset | 8 | 12 | 4.3719e-05 | 4.4080e-05 | 1.2872e-07 | 0.003 |  |  | 65536 | 105070592 | exact |
| frames-100 | selected | warm | readcon-db | 1 | 1 | 12 | 9.8706e-06 | 1.0006e-05 | 7.2268e-08 | 0.007 |  |  | 65536 | 102641664 | exact |
| frames-100 | selected | warm | ase.db | 1 | 1 | 12 | 1.6737e-04 | 1.6959e-04 | 1.1039e-06 | 0.007 |  |  | 151552 | 108503040 | exact |
| frames-100 | selected | warm | readcon-db | unset | 8 | 12 | 9.3902e-06 | 9.6876e-06 | 2.1255e-07 | 0.023 |  |  | 65536 | 102760448 | exact |
| frames-10000 | insert | cold-file | readcon-db | 1 | 1 | 12 | 3.2152e-01 | 3.2567e-01 | 3.8625e-03 | 0.012 | 3.1102e+04 | 2.3869e+01 | 3362816 | 196276224 | exact |
| frames-10000 | insert | cold-file | ase.db | 1 | 1 | 12 | 3.0469e+00 | 3.0907e+00 | 3.9406e-02 | 0.013 | 3.2820e+03 | 2.5188e+00 | 10792960 | 200929280 | exact |
| frames-10000 | insert | cold-file | readcon-db | unset | 8 | 12 | 3.2521e-01 | 3.2692e-01 | 2.8567e-03 | 0.009 | 3.0749e+04 | 2.3598e+01 | 3362816 | 200204288 | exact |
| frames-10000 | full_read | cold | readcon-db | 1 | 1 | 12 | 6.0743e-03 | 6.4868e-03 | 1.3463e-04 | 0.022 |  |  | 3362816 | 160985088 | exact |
| frames-10000 | full_read | cold | ase.db | 1 | 1 | 12 | 9.0206e-01 | 9.1095e-01 | 1.3047e-02 | 0.014 |  |  | 10817536 | 534056960 | exact |
| frames-10000 | full_read | cold | readcon-db | unset | 8 | 12 | 6.1198e-03 | 6.5915e-03 | 1.0667e-04 | 0.017 |  |  | 3362816 | 160841728 | exact |
| frames-10000 | selected | cold | readcon-db | 1 | 1 | 12 | 4.4252e-05 | 4.4669e-05 | 1.3349e-06 | 0.030 |  |  | 3362816 | 117338112 | exact |
| frames-10000 | selected | cold | ase.db | 1 | 1 | 12 | 3.8061e-03 | 4.0783e-03 | 2.6646e-04 | 0.070 |  |  | 10817536 | 99561472 | exact |
| frames-10000 | selected | cold | readcon-db | unset | 8 | 12 | 4.4596e-05 | 4.5502e-05 | 1.0493e-06 | 0.024 |  |  | 3362816 | 117493760 | exact |
| frames-10000 | full_read | warm | readcon-db | 1 | 1 | 12 | 6.1211e-03 | 6.8676e-03 | 4.3108e-04 | 0.070 |  |  | 3362816 | 179617792 | exact |
| frames-10000 | full_read | warm | ase.db | 1 | 1 | 12 | 9.0138e-01 | 9.4045e-01 | 3.3025e-02 | 0.037 |  |  | 10817536 | 552607744 | exact |
| frames-10000 | full_read | warm | readcon-db | unset | 8 | 12 | 6.0319e-03 | 6.5630e-03 | 2.7847e-04 | 0.046 |  |  | 3362816 | 179597312 | exact |
| frames-10000 | selected | warm | readcon-db | 1 | 1 | 12 | 9.3503e-06 | 9.4167e-06 | 1.0788e-07 | 0.012 |  |  | 3362816 | 113197056 | exact |
| frames-10000 | selected | warm | ase.db | 1 | 1 | 12 | 7.3826e-04 | 7.4695e-04 | 1.0693e-05 | 0.014 |  |  | 10817536 | 101081088 | exact |
| frames-10000 | selected | warm | readcon-db | unset | 8 | 12 | 9.3094e-06 | 9.3813e-06 | 8.5766e-08 | 0.009 |  |  | 3362816 | 113004544 | exact |
