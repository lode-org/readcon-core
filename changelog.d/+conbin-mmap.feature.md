`read_conbin` maps a binary coordinate file and returns the position run.
It also returns the velocity run when the header flag is set.
The mapped readers follow the header flags.
The wrong width returns an error.
`write_from_con` writes a velocity run only when every frame has velocities.
A mix of frames is an error.
When the velocity flag is clear, the Python readers return no velocity array.
The header block is 64 KiB, and a payload offset need not be a multiple of the host page.
`read_conbin_copy` allocates the position array, fills it with `pread`, and checks that the host is little-endian.
When the file has no velocity run, that copy returns no velocity array.
A Rust caller that passes a velocity slice for that file gets an error.
The copy path uses the same payload-offset check as the mapped reader.
