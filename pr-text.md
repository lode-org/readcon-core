The Fortran writer passed parsed frames straight through, so a rewrite omitted con_spec_minor whenever the source file had left that key out.
Python, Julia, and C rebuild each read frame with ConFrameBuilder, which stamps con_spec_minor 1 when the caller did not set it.
Fortran now rebuilds each frame on that same path before it extends the writer.
A cross-binding test rewrites every accepted conformance file through C, Python, Julia, and Fortran and requires the four outputs to be byte-identical.
