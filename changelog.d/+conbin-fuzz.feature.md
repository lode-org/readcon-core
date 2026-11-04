The `conbin-reader` fuzz target builds a binary coordinate file from each input.
It reads that file with the Rust readers of `readcon_core::conbin`.
Where a mapped read and a copied read both succeed, they return the same bits.
