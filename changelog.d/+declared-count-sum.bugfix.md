A frame skip no longer overflows when the declared atoms, plus two lines per type, pass `usize::MAX`.
A build with overflow checks panicked there.
A release build skipped too few lines and reported success.
`ConFrameIterator::forward` and `skip_frames` now return `IncompleteFrame` for that frame, as a full parse does.
The stream reader, the parallel reader and the frame index find frame ends with this skip.
The full parse no longer panics in a build with overflow checks when the per-type counts sum past `usize::MAX`.
