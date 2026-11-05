read_con maps a large file and builds each Python frame on first use.
The coordinate slab is filled off the GIL.
Phase times cover open, scan, slot allocation, the worker parse, and the return.
