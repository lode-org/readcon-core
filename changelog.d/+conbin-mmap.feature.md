`write_uniform` writes a binary64 CON-bin whose two runs come from a seed.
`conbin_perf` times one warm-cache mapped read against the `pread` copy of that file.
The header block is one host page. The payload offset stored there is that page size, and it has to be an 8-byte aligned address inside the file.
