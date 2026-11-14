# readcon-db vs ASE sqlite

Type-7 median and IQR. One discarded warmup and six serial samples
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
| readcon-db | 2.9056e-03 | 1.1606e-03 | 2.5203e-03 | 3.6809e-03 | 1.6138e-03 | 3.9865e-03 |
| ase.db | 4.8304e-02 | 5.1410e-03 | 4.6371e-02 | 5.1512e-02 | 4.5235e-02 | 5.2593e-02 |

## This machine, fair harness

Insert unlinks and creates the database file, then times one
transaction and one commit fsync. Full read and the selected-row
query (`frame_index` of the middle frame) are cold and warm.

| workload | frames | atoms | op | cache | tool | n | median s | IQR s | fidelity |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| paper40x8 | 40 | 8 | insert | cold-file | readcon-db | 6 | 1.9885e-03 | 2.0879e-04 | exact |
| paper40x8 | 40 | 8 | insert | cold-file | ase.db | 6 | 5.1624e-03 | 1.2995e-04 | exact |
| atoms-1000 | 1 | 1000 | insert | cold-file | readcon-db | 6 | 7.7016e-04 | 6.5469e-04 | exact |
| atoms-1000 | 1 | 1000 | insert | cold-file | ase.db | 6 | 1.2346e-03 | 3.6328e-04 | exact |
| atoms-1000 | 1 | 1000 | full_read | cold | readcon-db | 6 | 4.1172e-04 | 2.9597e-04 | exact |
| atoms-1000 | 1 | 1000 | full_read | cold | ase.db | 6 | 1.4036e-03 | 6.8785e-04 | exact |
| atoms-1000 | 1 | 1000 | selected | cold | readcon-db | 6 | 9.6442e-04 | 6.2120e-04 | exact |
| atoms-1000 | 1 | 1000 | selected | cold | ase.db | 6 | 1.2152e-03 | 8.8730e-04 | exact |
| atoms-1000 | 1 | 1000 | full_read | warm | readcon-db | 6 | 1.4380e-04 | 2.9451e-05 | exact |
| atoms-1000 | 1 | 1000 | full_read | warm | ase.db | 6 | 3.7053e-04 | 6.8857e-05 | exact |
| atoms-1000 | 1 | 1000 | selected | warm | readcon-db | 6 | 1.6905e-04 | 3.4259e-05 | exact |
| atoms-1000 | 1 | 1000 | selected | warm | ase.db | 6 | 3.7303e-04 | 1.5690e-05 | exact |
| atoms-10000 | 1 | 10000 | insert | cold-file | readcon-db | 6 | 3.0391e-03 | 2.1877e-04 | exact |
| atoms-10000 | 1 | 10000 | insert | cold-file | ase.db | 6 | 4.0714e-03 | 8.5115e-04 | exact |
| atoms-10000 | 1 | 10000 | full_read | cold | readcon-db | 6 | 1.9359e-03 | 5.2096e-04 | exact |
| atoms-10000 | 1 | 10000 | full_read | cold | ase.db | 6 | 4.0638e-03 | 8.3548e-04 | exact |
| atoms-10000 | 1 | 10000 | selected | cold | readcon-db | 6 | 1.5112e-03 | 2.8316e-04 | exact |
| atoms-10000 | 1 | 10000 | selected | cold | ase.db | 6 | 4.2053e-03 | 7.8786e-04 | exact |
| atoms-10000 | 1 | 10000 | full_read | warm | readcon-db | 6 | 1.1241e-03 | 1.7960e-05 | exact |
| atoms-10000 | 1 | 10000 | full_read | warm | ase.db | 6 | 2.1725e-03 | 4.7425e-05 | exact |
| atoms-10000 | 1 | 10000 | selected | warm | readcon-db | 6 | 1.1314e-03 | 4.5751e-05 | exact |
| atoms-10000 | 1 | 10000 | selected | warm | ase.db | 6 | 2.1766e-03 | 2.2096e-05 | exact |
| atoms-100000 | 1 | 100000 | insert | cold-file | readcon-db | 6 | 1.6198e-02 | 1.1244e-04 | exact |
| atoms-100000 | 1 | 100000 | insert | cold-file | ase.db | 6 | 2.8463e-02 | 1.6711e-03 | exact |
| atoms-100000 | 1 | 100000 | full_read | cold | readcon-db | 6 | 1.4204e-02 | 4.2107e-04 | exact |
| atoms-100000 | 1 | 100000 | full_read | cold | ase.db | 6 | 2.7399e-02 | 1.4569e-03 | exact |
| atoms-100000 | 1 | 100000 | selected | cold | readcon-db | 6 | 1.4274e-02 | 9.5348e-04 | exact |
| atoms-100000 | 1 | 100000 | selected | cold | ase.db | 6 | 2.8570e-02 | 1.4364e-03 | exact |
| atoms-100000 | 1 | 100000 | full_read | warm | readcon-db | 6 | 1.2485e-02 | 2.3778e-05 | exact |
| atoms-100000 | 1 | 100000 | full_read | warm | ase.db | 6 | 2.0769e-02 | 1.2723e-03 | exact |
| atoms-100000 | 1 | 100000 | selected | warm | readcon-db | 6 | 1.2698e-02 | 7.4356e-04 | exact |
| atoms-100000 | 1 | 100000 | selected | warm | ase.db | 6 | 2.1042e-02 | 2.0162e-03 | exact |
| atoms-1000000 | 1 | 1000000 | insert | cold-file | readcon-db | 6 | 1.5510e-01 | 5.9221e-03 | exact |
| atoms-1000000 | 1 | 1000000 | insert | cold-file | ase.db | 6 | 2.4116e-01 | 9.1247e-03 | exact |
| atoms-1000000 | 1 | 1000000 | full_read | cold | readcon-db | 6 | 1.6388e-01 | 1.8236e-03 | exact |
| atoms-1000000 | 1 | 1000000 | full_read | cold | ase.db | 6 | 3.0509e-01 | 1.5535e-02 | exact |
| atoms-1000000 | 1 | 1000000 | selected | cold | readcon-db | 6 | 1.8359e-01 | 4.0343e-02 | exact |
| atoms-1000000 | 1 | 1000000 | selected | cold | ase.db | 6 | 3.1041e-01 | 1.7259e-03 | exact |
| atoms-1000000 | 1 | 1000000 | full_read | warm | readcon-db | 6 | 1.6366e-01 | 1.7798e-02 | exact |
| atoms-1000000 | 1 | 1000000 | full_read | warm | ase.db | 6 | 2.2573e-01 | 2.9103e-02 | exact |
| atoms-1000000 | 1 | 1000000 | selected | warm | readcon-db | 6 | 1.6918e-01 | 5.1237e-02 | exact |
| atoms-1000000 | 1 | 1000000 | selected | warm | ase.db | 6 | 2.2074e-01 | 4.7235e-02 | exact |
| frames-1 | 1 | 8 | insert | cold-file | readcon-db | 6 | 2.8531e-04 | 1.1869e-04 | exact |
| frames-1 | 1 | 8 | insert | cold-file | ase.db | 6 | 8.8701e-04 | 1.5810e-04 | exact |
| frames-1 | 1 | 8 | full_read | cold | readcon-db | 6 | 4.5754e-04 | 5.7364e-04 | exact |
| frames-1 | 1 | 8 | full_read | cold | ase.db | 6 | 7.1832e-04 | 2.6318e-04 | exact |
| frames-1 | 1 | 8 | selected | cold | readcon-db | 6 | 4.8884e-04 | 3.0775e-04 | exact |
| frames-1 | 1 | 8 | selected | cold | ase.db | 6 | 1.0620e-03 | 5.2866e-04 | exact |
| frames-1 | 1 | 8 | full_read | warm | readcon-db | 6 | 4.0213e-05 | 4.2485e-06 | exact |
| frames-1 | 1 | 8 | full_read | warm | ase.db | 6 | 1.5699e-04 | 2.6990e-05 | exact |
| frames-1 | 1 | 8 | selected | warm | readcon-db | 6 | 4.6933e-05 | 2.0829e-05 | exact |
| frames-1 | 1 | 8 | selected | warm | ase.db | 6 | 1.6038e-04 | 8.6378e-06 | exact |
| frames-100 | 100 | 8 | insert | cold-file | readcon-db | 6 | 3.9267e-03 | 4.5741e-04 | exact |
| frames-100 | 100 | 8 | insert | cold-file | ase.db | 6 | 2.8139e-02 | 5.3444e-04 | exact |
| frames-100 | 100 | 8 | full_read | cold | readcon-db | 6 | 1.3717e-03 | 3.6884e-04 | exact |
| frames-100 | 100 | 8 | full_read | cold | ase.db | 6 | 8.4436e-03 | 4.4229e-04 | exact |
| frames-100 | 100 | 8 | selected | cold | readcon-db | 6 | 7.0124e-04 | 5.1896e-04 | exact |
| frames-100 | 100 | 8 | selected | cold | ase.db | 6 | 1.1992e-03 | 7.1470e-05 | exact |
| frames-100 | 100 | 8 | full_read | warm | readcon-db | 6 | 7.4358e-04 | 2.4575e-05 | exact |
| frames-100 | 100 | 8 | full_read | warm | ase.db | 6 | 7.3091e-03 | 1.4030e-04 | exact |
| frames-100 | 100 | 8 | selected | warm | readcon-db | 6 | 9.0092e-05 | 5.0458e-05 | exact |
| frames-100 | 100 | 8 | selected | warm | ase.db | 6 | 2.2240e-04 | 3.7329e-05 | exact |
| frames-10000 | 10000 | 8 | insert | cold-file | readcon-db | 6 | 2.5039e-01 | 9.2066e-03 | exact |
| frames-10000 | 10000 | 8 | insert | cold-file | ase.db | 6 | 2.6756e+00 | 2.3133e-02 | exact |
| frames-10000 | 10000 | 8 | full_read | cold | readcon-db | 6 | 1.0309e-01 | 3.1923e-03 | exact |
| frames-10000 | 10000 | 8 | full_read | cold | ase.db | 6 | 7.6695e-01 | 1.7480e-02 | exact |
| frames-10000 | 10000 | 8 | selected | cold | readcon-db | 6 | 1.6208e-03 | 3.8625e-04 | exact |
| frames-10000 | 10000 | 8 | selected | cold | ase.db | 6 | 8.2983e-03 | 4.2769e-04 | exact |
| frames-10000 | 10000 | 8 | full_read | warm | readcon-db | 6 | 8.4286e-02 | 6.2152e-03 | exact |
| frames-10000 | 10000 | 8 | full_read | warm | ase.db | 6 | 7.4958e-01 | 3.6290e-03 | exact |
| frames-10000 | 10000 | 8 | selected | warm | readcon-db | 6 | 1.6720e-04 | 7.4509e-05 | exact |
| frames-10000 | 10000 | 8 | selected | warm | ase.db | 6 | 1.3706e-03 | 2.2260e-04 | exact |

