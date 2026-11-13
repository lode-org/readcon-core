A frame that stores positions in a dtype other than float64 no longer allocates them for the declared atom count before it reads a row.
A count beyond the input used to abort the reader there, for example with 48 GiB of float32 positions for 2^32 - 1 atoms.
The positions are now converted from the rows read once the coordinate block is complete, with the same values as before.
