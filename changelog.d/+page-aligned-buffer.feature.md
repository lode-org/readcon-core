`tests/page_aligned_buffer.rs` copies 64 frames into a buffer that starts on a page boundary.
The byte and the string reader each parse it at 1, 2 and 8 threads.
Each read must return the frames of the one-thread string read and leave every byte of the buffer as it was.
The test asks `libc` for the page size, so `libc` becomes a dev-dependency on every Unix target instead of Linux alone.
