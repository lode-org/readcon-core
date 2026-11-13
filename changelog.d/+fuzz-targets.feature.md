Nine cargo-fuzz targets in `fuzz/` start from the seed inputs in `fuzz/corpus/<target>/`.
They cover the line parsers, the frame readers, the frame index, the unit parser, the surface grammar and the bond metadata.
`frame-parser` checks that the frame iterator ends, and `frame-parallel` that two threads return the frames that one thread returns.
The contributing guide runs each target on a scratch copy of its corpus, so `fuzz/corpus/` stays as committed.
