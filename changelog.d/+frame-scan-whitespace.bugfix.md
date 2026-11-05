With two or more threads, `frames_from_text` and `frames_from_bytes` now return the frames that one thread returns when only whitespace follows the last frame.
`frames_from_text` used to fail with `IncompleteFrame` on a lone newline, and both failed on a vertical tab after the last frame.
`iterators::frame_start_offsets` no longer gives a frame start for such a tail, and `frame_index::FrameIndex::scan` no longer fails on it.
The frame skip `ConFrameIterator::forward_fast` now finds blank lines with `str::trim`, like the full parse.
Form feeds, vertical tabs and no-break spaces count as blank there.
So the section after such a line stays in its frame.
