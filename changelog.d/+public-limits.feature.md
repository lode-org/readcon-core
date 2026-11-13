`parser::NUMERIC_STACK_WIDTH` is the length of the buffer that `parse_line_of_range_f64_stack` fills.
It counts the columns of an atom line with its id.
`compression::MMAP_THRESHOLD` is the size in bytes from which `read_file_contents` maps an uncompressed file.
Neither constant is part of the C header.
