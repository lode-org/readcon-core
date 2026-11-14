The `conbin-reader` fuzz target reads each input with the mapped reader, the `pread` copy, `read_owned_f64` and `sum_mapped`.
Where a mapped read and a copied read both succeed, they return the same bits.
A column the file cannot hold still fails before `read_owned_f64` reserves it.
