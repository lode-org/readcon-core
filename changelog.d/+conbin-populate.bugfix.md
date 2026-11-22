A failed `MADV_POPULATE_READ` on the default span prefetch no longer fails `map_file`.
The mapping stays in place, and one byte of each page is read before the function returns.
When `mmap` itself fails, the file is read into a private mapping and the accessors return the same values.
