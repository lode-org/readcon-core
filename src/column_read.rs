//! Coordinate-only trajectories as columns, one frame at a time.
//!
//! A parallel read keeps every `ConFrame`. That holds the file, a per-atom
//! record, and a second copy of the coordinates at once. A serial read of a
//! file with no velocity or force section streams instead: the source buffer
//! stays near one frame, and the retained bytes are the coordinate slab plus
//! the id, flag, and symbol columns.

use crate::iterators::ConFrameIterator;
use crate::stream::settled;
use crate::types::{AtomDatum, ConFrame, FrameHeader};
use std::collections::HashMap;
use std::io::Read;
use std::path::Path;
use std::sync::Arc;

/// Bytes pulled from the source when the window has no whole frame.
const READ_CHUNK: usize = 8 * 1024;
/// Keep the window from retaining the rest of the file.
const WINDOW_CAP: usize = 48 * 1024;

/// Columns for a rectangular, coordinate-only trajectory.
///
/// Positions are written into a caller-owned buffer so they are not also
/// kept in a `Vec` that is later copied.
pub struct Columns {
    pub n_frames: usize,
    pub n_atoms: usize,
    pub flags: Vec<u8>,
    pub ids: Vec<u64>,
    pub sym_index: Vec<u32>,
    pub symbols: Vec<Arc<str>>,
    /// Distinct headers. Repeated frames share one entry.
    pub headers: Vec<FrameHeader>,
    pub header_index: Vec<u32>,
}

pub struct Layout {
    pub n_frames: usize,
    pub n_atoms: usize,
    pub n_bytes: u64,
}

fn coords_only(frame: &ConFrame) -> bool {
    !frame.atom_data.is_empty()
        && frame.velocities.nrows() == 0
        && frame.forces.nrows() == 0
        && frame.atom_energies.len() == 0
        && frame.charges.len() == 0
        && frame.spins.len() == 0
        && frame.magmoms.nrows() == 0
        && frame.displacements.nrows() == 0
        && frame.spreads.nrows() == 0
}

fn take_frame(buf: &[u8], eof: bool) -> Result<Option<(ConFrame, usize)>, ()> {
    let text = if eof {
        buf
    } else {
        match memchr::memrchr(b'\n', buf) {
            Some(i) => &buf[..=i],
            None => return Ok(None),
        }
    };
    if text.is_empty() {
        return Ok(None);
    }
    let mut it = ConFrameIterator::from_bytes(text);
    match it.next_with_end() {
        Some(Ok((frame, end))) if eof || settled(text, end) => Ok(Some((frame, end))),
        Some(Ok(_)) => Ok(None),
        Some(Err(_)) if eof => Err(()),
        Some(Err(_)) => Ok(None),
        None => Ok(None),
    }
}

fn for_each_frame<R: Read>(
    mut src: R,
    mut on_frame: impl FnMut(ConFrame) -> Result<(), ()>,
) -> Result<(), ()> {
    let mut buf = Vec::with_capacity(READ_CHUNK * 2);
    let mut eof = false;
    loop {
        match take_frame(&buf, eof)? {
            Some((frame, end)) => {
                on_frame(frame)?;
                buf.drain(..end);
                if buf.capacity() > WINDOW_CAP {
                    buf.shrink_to(READ_CHUNK * 2);
                }
            }
            None if eof => break,
            None => {
                let start = buf.len();
                buf.resize(start + READ_CHUNK, 0);
                match src.read(&mut buf[start..]) {
                    Ok(0) => {
                        buf.truncate(start);
                        eof = true;
                    }
                    Ok(n) => buf.truncate(start + n),
                    Err(_) => return Err(()),
                }
            }
        }
    }
    Ok(())
}

fn layout_reader<R: Read>(src: R, n_bytes: u64) -> Result<Layout, ()> {
    let mut n_frames = 0usize;
    let mut n_atoms = None;
    for_each_frame(src, |frame| {
        if !coords_only(&frame) {
            return Err(());
        }
        let atoms = frame.atom_data.len();
        if let Some(expected) = n_atoms {
            if atoms != expected {
                return Err(());
            }
        } else {
            n_atoms = Some(atoms);
        }
        n_frames += 1;
        Ok(())
    })?;
    Ok(Layout {
        n_frames,
        n_atoms: n_atoms.unwrap_or(0),
        n_bytes,
    })
}

pub fn layout_path(path: &Path) -> Result<Layout, ()> {
    let n_bytes = std::fs::metadata(path).map_err(|_| ())?.len();
    let src = crate::compression::open_decoded(path).map_err(|_| ())?;
    layout_reader(src, n_bytes)
}

pub fn layout_bytes(bytes: &[u8]) -> Result<Layout, ()> {
    layout_reader(std::io::Cursor::new(bytes), bytes.len() as u64)
}

fn flag_mask(frame_atom: &AtomDatum) -> u8 {
    let flags = frame_atom.fixed();
    u8::from(flags[0]) | (u8::from(flags[1]) << 1) | (u8::from(flags[2]) << 2)
}

fn intern(table: &mut Vec<Arc<str>>, map: &mut HashMap<Arc<str>, u32>, symbol: &Arc<str>) -> u32 {
    if let Some(&index) = map.get(symbol) {
        return index;
    }
    let index = table.len() as u32;
    table.push(Arc::clone(symbol));
    map.insert(Arc::clone(symbol), index);
    index
}

fn push_frame(
    frame: &ConFrame,
    frame_index: usize,
    n_atoms: usize,
    positions: &mut [f64],
    columns: &mut Columns,
    symbols: &mut HashMap<Arc<str>, u32>,
) -> Result<(), ()> {
    if frame.atom_data.len() != n_atoms || !coords_only(frame) {
        return Err(());
    }
    let stride = n_atoms.saturating_mul(3);
    let start = frame_index.saturating_mul(stride);
    let dest = positions.get_mut(start..start + stride).ok_or(())?;
    for (atom_index, atom) in frame.atom_data.iter().enumerate() {
        let at = atom_index.saturating_mul(3);
        dest[at] = atom.x();
        dest[at + 1] = atom.y();
        dest[at + 2] = atom.z();
        columns.flags.push(flag_mask(atom));
        columns.ids.push(atom.atom_id);
        let index = intern(&mut columns.symbols, symbols, &atom.symbol);
        columns.sym_index.push(index);
    }
    let header_at = if columns
        .headers
        .last()
        .is_some_and(|header| header == &frame.header)
    {
        (columns.headers.len() - 1) as u32
    } else {
        columns.headers.push(frame.header.clone());
        (columns.headers.len() - 1) as u32
    };
    columns.header_index.push(header_at);
    Ok(())
}

fn fill_reader<R: Read>(
    src: R,
    n_frames: usize,
    n_atoms: usize,
    positions: &mut [f64],
) -> Result<Columns, ()> {
    let atoms = n_frames.saturating_mul(n_atoms);
    let mut columns = Columns {
        n_frames,
        n_atoms,
        flags: Vec::with_capacity(atoms),
        ids: Vec::with_capacity(atoms),
        sym_index: Vec::with_capacity(atoms),
        symbols: Vec::new(),
        headers: Vec::new(),
        header_index: Vec::with_capacity(n_frames),
    };
    let mut symbols = HashMap::new();
    let mut frame_index = 0usize;
    for_each_frame(src, |frame| {
        push_frame(
            &frame,
            frame_index,
            n_atoms,
            positions,
            &mut columns,
            &mut symbols,
        )?;
        frame_index += 1;
        Ok(())
    })?;
    if frame_index != n_frames || columns.header_index.len() != n_frames {
        return Err(());
    }
    Ok(columns)
}

pub fn fill_path(
    path: &Path,
    n_frames: usize,
    n_atoms: usize,
    positions: &mut [f64],
) -> Result<Columns, ()> {
    let src = crate::compression::open_decoded(path).map_err(|_| ())?;
    fill_reader(src, n_frames, n_atoms, positions)
}

pub fn fill_bytes(
    bytes: &[u8],
    n_frames: usize,
    n_atoms: usize,
    positions: &mut [f64],
) -> Result<Columns, ()> {
    fill_reader(std::io::Cursor::new(bytes), n_frames, n_atoms, positions)
}

impl Columns {
    pub fn symbol_at(&self, frame: usize, atom: usize) -> &str {
        let index = self.sym_index[frame * self.n_atoms + atom] as usize;
        self.symbols[index].as_ref()
    }

    pub fn flag_at(&self, frame: usize, atom: usize) -> [bool; 3] {
        let mask = self.flags[frame * self.n_atoms + atom];
        [mask & 1 != 0, mask & 2 != 0, mask & 4 != 0]
    }

    /// Same word as [`crate::iterators::hash_touch_frame`] over every frame.
    pub fn touch_checksum(&self, positions: &[f64]) -> u64 {
        let stride = self.n_atoms.saturating_mul(3);
        let mut acc = 0u64;
        for frame in 0..self.n_frames {
            let start = frame * stride;
            let coords = &positions[start..start + stride];
            let symbols = (0..self.n_atoms).map(|atom| self.symbol_at(frame, atom));
            let header = &self.headers[self.header_index[frame] as usize];
            acc ^= crate::iterators::hash_touch_frame(
                frame as u64,
                header.boxl,
                symbols,
                coords,
            );
        }
        acc
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::iterators::read_all_frames;
    use std::path::Path;

    #[test]
    fn plain_con_columns_match_the_frame_reader() {
        let path = Path::new("resources/test/tiny_multi_cuh2.con");
        let layout = layout_path(path).expect("layout");
        assert_eq!(layout.n_frames, 2);
        assert_eq!(layout.n_atoms, 4);
        let mut positions = vec![0.0; layout.n_frames * layout.n_atoms * 3];
        let columns = fill_path(path, layout.n_frames, layout.n_atoms, &mut positions).unwrap();
        let frames = read_all_frames(path).unwrap();
        assert_eq!(frames.len(), columns.n_frames);
        for (index, frame) in frames.iter().enumerate() {
            let header = &columns.headers[columns.header_index[index] as usize];
            assert_eq!(frame.header.boxl, header.boxl);
            for (atom_index, atom) in frame.atom_data.iter().enumerate() {
                assert_eq!(atom.symbol.as_ref(), columns.symbol_at(index, atom_index));
                assert_eq!(atom.fixed(), columns.flag_at(index, atom_index));
                assert_eq!(atom.atom_id, columns.ids[index * columns.n_atoms + atom_index]);
                let at = (index * columns.n_atoms + atom_index) * 3;
                assert_eq!(positions[at], atom.x());
                assert_eq!(positions[at + 1], atom.y());
                assert_eq!(positions[at + 2], atom.z());
            }
        }
    }

    #[test]
    fn the_first_frame_is_emitted_before_the_rest_of_the_file() {
        let one = std::fs::read("resources/test/tiny_cuh2.con").unwrap();
        let mut bytes = Vec::new();
        for _ in 0..50 {
            bytes.extend_from_slice(&one);
        }
        let seen = std::rc::Rc::new(std::cell::Cell::new(0usize));
        struct Track<'a> {
            bytes: &'a [u8],
            pos: usize,
            seen: std::rc::Rc<std::cell::Cell<usize>>,
        }
        impl Read for Track<'_> {
            fn read(&mut self, dest: &mut [u8]) -> std::io::Result<usize> {
                let n = (self.bytes.len() - self.pos).min(dest.len());
                dest[..n].copy_from_slice(&self.bytes[self.pos..self.pos + n]);
                self.pos += n;
                if self.pos > self.seen.get() {
                    self.seen.set(self.pos);
                }
                Ok(n)
            }
        }
        let mut first_at = None;
        for_each_frame(
            Track {
                bytes: &bytes,
                pos: 0,
                seen: std::rc::Rc::clone(&seen),
            },
            |_| {
                if first_at.is_none() {
                    first_at = Some(seen.get());
                }
                Ok(())
            },
        )
        .unwrap();
        let at = first_at.expect("frame");
        assert!(
            at <= READ_CHUNK * 2,
            "first frame after reading {at} of {} bytes",
            bytes.len()
        );
    }

    #[test]
    fn repeated_tiny_frames_fill() {
        let src = std::fs::read("resources/test/tiny_cuh2.con").unwrap();
        let mut bytes = Vec::new();
        for _ in 0..50 {
            bytes.extend_from_slice(&src);
        }
        let layout = layout_bytes(&bytes).expect("layout");
        assert_eq!(layout.n_frames, 50, "frames");
        assert_eq!(layout.n_atoms, 4);
        let mut positions = vec![0.0; layout.n_frames * layout.n_atoms * 3];
        let columns = fill_bytes(&bytes, layout.n_frames, layout.n_atoms, &mut positions).unwrap();
        assert_eq!(columns.headers.len(), 1, "distinct headers");
    }

    #[test]
    fn a_velocity_file_is_not_columnar() {
        let path = Path::new("resources/test/tiny_cuh2.convel");
        assert!(layout_path(path).is_err());
    }
}
