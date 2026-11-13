//! Frames parsed from a byte stream with about one frame in memory.

use crate::error::ParseError;
use crate::iterators::ConFrameIterator;
use crate::types::ConFrame;
use std::io::{self, Read};
use std::path::Path;

/// Error type of [`ConFrameReader`]: a [`ParseError`], or an input or
/// output error from the source.
pub type StreamError = Box<dyn std::error::Error + Send + Sync>;

/// Bytes requested from the source when the buffer has no whole frame.
pub const DEFAULT_READ_SIZE: usize = 1 << 20;

/// Parses frames from any [`Read`], such as a gzip or Zstandard decoder.
///
/// A plain CON stream on standard input is the same kind of reader.
/// Lock stdin and pass it here. The example uses a cursor so the
/// doctest does not wait on a terminal.
///
/// ```
/// use readcon_core::stream::ConFrameReader;
/// use std::io::Cursor;
/// let text = include_str!("../resources/test/tiny_cuh2.con");
/// let count = ConFrameReader::new(Cursor::new(text.as_bytes()))
///     .map(|frame| frame.expect("frame"))
///     .count();
/// assert!(count >= 1);
/// ```
///
/// The buffer keeps the bytes not yet returned and room for one read.
/// Before each read it moves those bytes to its front, and it grows only
/// to fit them plus that read.
/// Each read asks for `read_size` bytes.
/// The request grows to an eighth of the unread bytes when that exceeds
/// `read_size`, so a large frame needs few reads.
/// The capacity therefore stays near the largest frame, with the lines
/// the parser looks at after it, plus one read.
/// For a frame longer than eight reads, the read term is up to an eighth
/// of that frame.
///
/// Frames and errors are those of [`ConFrameIterator::from_bytes`] over
/// the whole stream, up to and including the first error.
/// When the source fails, the reader returns the frames that `from_bytes`
/// returns over the bytes read before the failure, up to its first error,
/// and then the source error.
/// After an error the reader returns `None`.
pub struct ConFrameReader<R> {
    src: R,
    /// Initialized storage, with the unread bytes in `buf[start..end]`.
    buf: Vec<u8>,
    start: usize,
    end: usize,
    read_size: usize,
    eof: bool,
    failed: Option<io::Error>,
    done: bool,
}

impl ConFrameReader<Box<dyn Read + Send>> {
    /// A reader over `path`, decompressed by
    /// [`crate::compression::open_decoded`].
    pub fn open(path: &Path) -> Result<Self, Box<dyn std::error::Error>> {
        Ok(Self::new(crate::compression::open_decoded(path)?))
    }
}

impl<R: Read> ConFrameReader<R> {
    /// A reader that asks `src` for [`DEFAULT_READ_SIZE`] bytes at a time.
    pub fn new(src: R) -> Self {
        Self::with_read_size(src, DEFAULT_READ_SIZE)
    }

    /// Like [`Self::new`], asking the source for `read_size` bytes (at
    /// least 1) whenever the buffer has no whole frame.
    pub fn with_read_size(src: R, read_size: usize) -> Self {
        Self {
            src,
            buf: Vec::new(),
            start: 0,
            end: 0,
            read_size: read_size.max(1),
            eof: false,
            failed: None,
            done: false,
        }
    }

    /// Skip one frame without parsing its atoms, as
    /// [`ConFrameIterator::forward`] does.
    pub fn forward(&mut self) -> Option<Result<(), StreamError>> {
        self.step(|it| it.forward().map(|r| r.map(|()| ((), it.byte_pos()))))
    }

    /// Run `op` on a fresh iterator over the buffered whole lines.
    /// Its result is final once the stream has ended, or once the lines
    /// after its cursor fix every look-ahead decision.
    /// Otherwise read more.
    ///
    /// After a source error no more bytes arrive, so the buffer is parsed
    /// as a whole input.
    /// A frame from it is returned, and an error or the end of the buffer
    /// gives way to the source error.
    fn step<T>(
        &mut self,
        mut op: impl FnMut(&mut ConFrameIterator<'_>) -> Option<Result<(T, usize), ParseError>>,
    ) -> Option<Result<T, StreamError>> {
        let mut cut = false;
        while !self.done {
            let ended = self.eof || self.failed.is_some();
            let rest = &self.buf[self.start..self.end];
            let text = if ended {
                rest
            } else {
                memchr::memrchr(b'\n', rest).map_or(&rest[..0], |i| &rest[..=i])
            };
            // Once a frame was cut by the buffer end, a skip walk checks
            // each longer buffer first, so a frame larger than one read is
            // not parsed in full once per read.
            if ended || !cut || {
                let mut probe = ConFrameIterator::from_bytes(text);
                probe.forward();
                settled(text, probe.byte_pos())
            } {
                let mut it = ConFrameIterator::from_bytes(text);
                let result = op(&mut it);
                if ended || settled(text, it.byte_pos()) {
                    match result {
                        Some(Ok((value, used))) => {
                            self.start += used;
                            return Some(Ok(value));
                        }
                        other if self.failed.is_none() => {
                            self.done = true;
                            return other.map(|r| r.map(|(value, _)| value).map_err(Into::into));
                        }
                        _ => {}
                    }
                }
            }
            cut = true;
            if let Some(e) = self.failed.take() {
                self.done = true;
                return Some(Err(e.into()));
            }
            self.fill();
        }
        None
    }

    /// Move the unread bytes to the front, and grow the buffer to fit them
    /// plus one read.
    /// Then read until that read is full, the source ends, or it fails.
    /// The bytes read before a failure are kept.
    fn fill(&mut self) {
        self.buf.copy_within(self.start..self.end, 0);
        self.end -= self.start;
        self.start = 0;
        let target = self.end + self.read_size.max(self.end / 8);
        if target > self.buf.len() {
            self.buf.reserve_exact(target - self.buf.len());
            self.buf.resize(target, 0);
        }
        while self.end < target {
            match self.src.read(&mut self.buf[self.end..target]) {
                Ok(0) => {
                    self.eof = true;
                    return;
                }
                Ok(n) => self.end += n,
                Err(e) if e.kind() == io::ErrorKind::Interrupted => {}
                Err(e) => {
                    self.failed = Some(e);
                    return;
                }
            }
        }
    }
}

/// Whether `text` has, after `pos`, any whitespace-only lines, then a
/// line with text and one more line.
/// The parser reads no further past its cursor.
/// A scan for trailing whitespace stops at the line with text.
/// A section probe after a peeked blank reads two lines.
/// It stops early when the first of them is whitespace.
/// `text` ends in a newline, so every piece is a whole line.
fn settled(text: &[u8], pos: usize) -> bool {
    let mut lines = text[pos.min(text.len())..].split_inclusive(|&b| b == b'\n');
    lines.any(|line| !line.iter().all(u8::is_ascii_whitespace)) && lines.next().is_some()
}

impl<R: Read> Iterator for ConFrameReader<R> {
    type Item = Result<ConFrame, StreamError>;

    fn next(&mut self) -> Option<Self::Item> {
        self.step(|it| it.next_with_end())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A zero-atom frame of `len` bytes, padded by its user line.
    fn zero_atom_frame(len: usize) -> Vec<u8> {
        let tail = "\n{\"con_spec_version\":2}\n10.000000 10.000000 10.000000\n\
                    90.000000 90.000000 90.000000\n\n\n0\n\n\n";
        let mut frame = vec![b'U'; len - tail.len()];
        frame.extend_from_slice(tail.as_bytes());
        frame
    }

    /// The buffer after the first frame of `frame` then `after`.
    fn after_first(frame: &[u8], after: &[u8]) -> (usize, usize) {
        let text = [frame, after].concat();
        let mut reader = ConFrameReader::new(&text[..]);
        let want = ConFrameIterator::from_bytes(frame).next().unwrap().unwrap();
        assert_eq!(reader.next().unwrap().unwrap(), want);
        assert_eq!(reader.start, frame.len());
        (reader.buf.len(), reader.buf.capacity())
    }

    #[test]
    fn a_frame_over_one_read_grows_the_buffer_to_about_one_frame_and_one_read() {
        let small = zero_atom_frame(100).repeat(2);
        for len in [(1 << 20) + 57, (1 << 21) + 57] {
            let frame = zero_atom_frame(len);
            for after in [&small[..], &[][..]] {
                let (filled, capacity) = after_first(&frame, after);
                assert!(filled <= capacity);
                assert!(
                    capacity <= len + DEFAULT_READ_SIZE,
                    "frame {len}, {} bytes after it: capacity {capacity}",
                    after.len()
                );
            }
        }
    }

    #[test]
    fn a_frame_of_many_reads_grows_the_buffer_by_an_eighth_at_most() {
        let read_size = 4096;
        let len = 64 * read_size + 57;
        let text = [zero_atom_frame(len), zero_atom_frame(100)]
            .concat()
            .repeat(2);
        let mut reader = ConFrameReader::with_read_size(&text[..], read_size);
        for _ in 0..4 {
            assert!(reader.next().unwrap().is_ok());
            assert!(reader.buf.capacity() <= len + len / 8 + read_size);
        }
        assert!(reader.next().is_none());
    }
}
