An extended XYZ atom count that does not fit in the file no longer panics or reserves that count.
`f64 as usize` used to saturate at `usize::MAX`, and adding the header lines to that count overflowed.
A count larger than the remaining bytes is rejected, and the numeric columns are not reserved when their lanes would outnumber the bytes in the file.
