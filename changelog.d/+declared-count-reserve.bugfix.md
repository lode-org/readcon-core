A header that declares more types or atoms than the input has room for no longer panics or aborts the reader.
The reader used to reserve memory for the declared counts before it read a line.
It now reserves no more than the rest of the input can hold.
The error is the one a short frame always gave: `IncompleteFrame` when atom lines are missing, and `InvalidVectorLength` when line 8 has fewer counts than line 7 declares.
`parser::parse_line_of_n_f64` reserves no more values than its line can hold.
`parser::parse_single_frame` reserves no more atoms than the upper bound of its iterator's `size_hint`.
`str::lines` gives no bound, so over it the vectors grow as rows arrive.
