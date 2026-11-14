//! Rectangular trajectories as columns.
//!
//! One streaming pass counts frames and reads the section shape, skipping
//! atom bodies after the first frame. A second pass is the only full parse:
//! it writes coordinates and any per-atom section into caller-owned slabs.
//! Ids, fixed flags, and the symbol index are stored once when every frame
//! has the same atoms, and per frame when they change. The source window
//! stays near one frame, so the file is not retained next to the slabs.

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

/// Which per-atom sections the first frame carried.
///
/// A later frame with a different shape makes the fill fail, and the caller
/// uses the frame parser.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct SectionFlags {
    pub velocities: bool,
    pub forces: bool,
    pub energies: bool,
    pub charges: bool,
    pub spins: bool,
    pub magmoms: bool,
    pub displacements: bool,
    pub spreads: bool,
}

/// Columns for a rectangular trajectory.
///
/// Numeric sections are written into caller-owned buffers. `flags`, `ids`,
/// and `sym_index` hold one frame when `identity_shared` is set, and one
/// entry per frame otherwise.
pub struct Columns {
    pub n_frames: usize,
    pub n_atoms: usize,
    pub flags: Vec<u8>,
    pub ids: Vec<u64>,
    pub sym_index: Vec<u32>,
    pub symbols: Vec<Arc<str>>,
    pub identity_shared: bool,
    /// Distinct headers. Repeated frames share one entry.
    pub headers: Vec<FrameHeader>,
    pub header_index: Vec<u32>,
}

pub struct Layout {
    pub n_frames: usize,
    pub n_atoms: usize,
    pub n_bytes: u64,
    pub sections: SectionFlags,
}

/// Caller-owned section slabs. Absent sections are `None`.
pub struct Slabs<'a> {
    pub positions: &'a mut [f64],
    pub velocities: Option<&'a mut [f64]>,
    pub forces: Option<&'a mut [f64]>,
    pub energies: Option<&'a mut [f64]>,
    pub charges: Option<&'a mut [f64]>,
    pub spins: Option<&'a mut [f64]>,
    pub magmoms: Option<&'a mut [f64]>,
    pub displacements: Option<&'a mut [f64]>,
    pub spreads: Option<&'a mut [f64]>,
}

fn whole_text(buf: &[u8], eof: bool) -> Option<&[u8]> {
    if eof {
        return Some(buf);
    }
    match memchr::memrchr(b'\n', buf) {
        Some(i) => Some(&buf[..=i]),
        None => None,
    }
}

fn take_frame(buf: &[u8], eof: bool) -> Result<Option<(ConFrame, usize)>, ()> {
    let Some(text) = whole_text(buf, eof) else {
        return Ok(None);
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

fn skip_frame(buf: &[u8], eof: bool) -> Result<Option<usize>, ()> {
    let Some(text) = whole_text(buf, eof) else {
        return Ok(None);
    };
    if text.is_empty() {
        return Ok(None);
    }
    let mut it = ConFrameIterator::from_bytes(text);
    match it.forward() {
        Some(Ok(())) => {
            let end = it.byte_pos();
            if eof || settled(text, end) {
                Ok(Some(end))
            } else {
                Ok(None)
            }
        }
        Some(Err(_)) if eof => Err(()),
        Some(Err(_)) => Ok(None),
        None => Ok(None),
    }
}

fn read_more(src: &mut impl Read, buf: &mut Vec<u8>, eof: &mut bool) -> Result<(), ()> {
    let start = buf.len();
    buf.resize(start + READ_CHUNK, 0);
    match src.read(&mut buf[start..]) {
        Ok(0) => {
            buf.truncate(start);
            *eof = true;
            Ok(())
        }
        Ok(n) => {
            buf.truncate(start + n);
            Ok(())
        }
        Err(_) => Err(()),
    }
}

fn shrink(buf: &mut Vec<u8>) {
    if buf.capacity() > WINDOW_CAP {
        buf.shrink_to(READ_CHUNK * 2);
    }
}

fn present(rows: usize, atoms: usize) -> Result<bool, ()> {
    if rows == 0 {
        Ok(false)
    } else if rows == atoms {
        Ok(true)
    } else {
        Err(())
    }
}

fn sections_of(frame: &ConFrame) -> Result<(usize, SectionFlags), ()> {
    let atoms = frame.atom_data.len();
    if atoms == 0 {
        return Err(());
    }
    Ok((
        atoms,
        SectionFlags {
            velocities: present(frame.velocities.nrows(), atoms)?,
            forces: present(frame.forces.nrows(), atoms)?,
            energies: present(frame.atom_energies.len(), atoms)?,
            charges: present(frame.charges.len(), atoms)?,
            spins: present(frame.spins.len(), atoms)?,
            magmoms: present(frame.magmoms.nrows(), atoms)?,
            displacements: present(frame.displacements.nrows(), atoms)?,
            spreads: present(frame.spreads.nrows(), atoms)?,
        },
    ))
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
                shrink(&mut buf);
            }
            None if eof => break,
            None => read_more(&mut src, &mut buf, &mut eof)?,
        }
    }
    Ok(())
}

fn layout_reader<R: Read>(src: R, n_bytes: u64) -> Result<Layout, ()> {
    let mut src = src;
    let mut buf = Vec::with_capacity(READ_CHUNK * 2);
    let mut eof = false;
    let mut n_frames = 0usize;
    let mut n_atoms = 0usize;
    let mut sections = SectionFlags::default();
    let mut shaped = false;
    loop {
        if !shaped {
            match take_frame(&buf, eof)? {
                Some((frame, end)) => {
                    let (atoms, flags) = sections_of(&frame)?;
                    n_atoms = atoms;
                    sections = flags;
                    n_frames = 1;
                    shaped = true;
                    buf.drain(..end);
                    shrink(&mut buf);
                }
                None if eof => break,
                None => read_more(&mut src, &mut buf, &mut eof)?,
            }
        } else {
            match skip_frame(&buf, eof)? {
                Some(end) => {
                    n_frames += 1;
                    buf.drain(..end);
                    shrink(&mut buf);
                }
                None if eof => break,
                None => read_more(&mut src, &mut buf, &mut eof)?,
            }
        }
    }
    Ok(Layout {
        n_frames,
        n_atoms,
        n_bytes,
        sections,
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

fn write_values(
    dest: &mut [f64],
    src: Option<&[f64]>,
    n: usize,
    mut one: impl FnMut(usize) -> f64,
) -> Result<(), ()> {
    let dest = dest.get_mut(..n).ok_or(())?;
    if let Some(src) = src {
        if src.len() < n {
            return Err(());
        }
        dest.copy_from_slice(&src[..n]);
        return Ok(());
    }
    for (slot, value) in dest.iter_mut().enumerate() {
        *value = one(slot);
    }
    Ok(())
}

fn write_vec3(
    frame_index: usize,
    n_atoms: usize,
    dest: &mut [f64],
    src: Option<&[f64]>,
    mut row: impl FnMut(usize) -> [f64; 3],
) -> Result<(), ()> {
    let stride = n_atoms.saturating_mul(3);
    let start = frame_index.saturating_mul(stride);
    let dest = dest.get_mut(start..start + stride).ok_or(())?;
    write_values(dest, src, stride, |slot| {
        let atom = slot / 3;
        let axis = slot % 3;
        row(atom)[axis]
    })
}

fn write_vec1(
    frame_index: usize,
    n_atoms: usize,
    dest: &mut [f64],
    src: Option<&[f64]>,
    mut one: impl FnMut(usize) -> f64,
) -> Result<(), ()> {
    let start = frame_index.saturating_mul(n_atoms);
    let dest = dest.get_mut(start..start + n_atoms).ok_or(())?;
    write_values(dest, src, n_atoms, |slot| one(slot))
}

fn same_identity(frame: &ConFrame, columns: &Columns) -> bool {
    frame.atom_data.len() == columns.n_atoms
        && frame.atom_data.iter().enumerate().all(|(atom, item)| {
            item.atom_id == columns.ids[atom]
                && flag_mask(item) == columns.flags[atom]
                && item.symbol.as_ref() == columns.symbol_at(0, atom)
        })
}

fn expand_identity(columns: &mut Columns, already: usize) {
    let mut flags = Vec::with_capacity(already.saturating_add(1).saturating_mul(columns.n_atoms));
    let mut ids = Vec::with_capacity(flags.capacity());
    let mut symbols = Vec::with_capacity(flags.capacity());
    for _ in 0..already {
        flags.extend_from_slice(&columns.flags);
        ids.extend_from_slice(&columns.ids);
        symbols.extend_from_slice(&columns.sym_index);
    }
    columns.flags = flags;
    columns.ids = ids;
    columns.sym_index = symbols;
    columns.identity_shared = false;
}

fn push_identity(
    frame: &ConFrame,
    frame_index: usize,
    columns: &mut Columns,
    symbols: &mut HashMap<Arc<str>, u32>,
) -> Result<(), ()> {
    if frame.atom_data.len() != columns.n_atoms {
        return Err(());
    }
    if frame_index > 0 && columns.identity_shared && same_identity(frame, columns) {
        return Ok(());
    }
    if frame_index > 0 && columns.identity_shared {
        expand_identity(columns, frame_index);
    }
    for atom in &frame.atom_data {
        columns.flags.push(flag_mask(atom));
        columns.ids.push(atom.atom_id);
        let index = intern(&mut columns.symbols, symbols, &atom.symbol);
        columns.sym_index.push(index);
    }
    Ok(())
}

fn push_frame(
    frame: &ConFrame,
    frame_index: usize,
    sections: SectionFlags,
    slabs: &mut Slabs<'_>,
    columns: &mut Columns,
    symbols: &mut HashMap<Arc<str>, u32>,
) -> Result<(), ()> {
    let (atoms, got) = sections_of(frame)?;
    if atoms != columns.n_atoms || got != sections {
        return Err(());
    }
    let n = columns.n_atoms;
    write_vec3(frame_index, n, slabs.positions, None, |atom| {
        let item = &frame.atom_data[atom];
        [item.x(), item.y(), item.z()]
    })?;
    if let Some(dest) = slabs.velocities.as_deref_mut() {
        write_vec3(
            frame_index,
            n,
            dest,
            frame.velocities.f64_slice(),
            |atom| frame.velocities.as_f64_row(atom),
        )?;
    }
    if let Some(dest) = slabs.forces.as_deref_mut() {
        write_vec3(
            frame_index,
            n,
            dest,
            frame.forces.f64_slice(),
            |atom| frame.forces.as_f64_row(atom),
        )?;
    }
    if let Some(dest) = slabs.magmoms.as_deref_mut() {
        write_vec3(
            frame_index,
            n,
            dest,
            frame.magmoms.f64_slice(),
            |atom| frame.magmoms.as_f64_row(atom),
        )?;
    }
    if let Some(dest) = slabs.displacements.as_deref_mut() {
        write_vec3(
            frame_index,
            n,
            dest,
            frame.displacements.f64_slice(),
            |atom| frame.displacements.as_f64_row(atom),
        )?;
    }
    if let Some(dest) = slabs.spreads.as_deref_mut() {
        write_vec3(
            frame_index,
            n,
            dest,
            frame.spreads.f64_slice(),
            |atom| frame.spreads.as_f64_row(atom),
        )?;
    }
    if let Some(dest) = slabs.energies.as_deref_mut() {
        write_vec1(
            frame_index,
            n,
            dest,
            frame.atom_energies.f64_slice(),
            |atom| frame.atom_energies.get_f64(atom),
        )?;
    }
    if let Some(dest) = slabs.charges.as_deref_mut() {
        write_vec1(
            frame_index,
            n,
            dest,
            frame.charges.f64_slice(),
            |atom| frame.charges.get_f64(atom),
        )?;
    }
    if let Some(dest) = slabs.spins.as_deref_mut() {
        write_vec1(
            frame_index,
            n,
            dest,
            frame.spins.f64_slice(),
            |atom| frame.spins.get_f64(atom),
        )?;
    }
    push_identity(frame, frame_index, columns, symbols)?;
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
    sections: SectionFlags,
    mut slabs: Slabs<'_>,
) -> Result<Columns, ()> {
    let mut columns = Columns {
        n_frames,
        n_atoms,
        flags: Vec::with_capacity(n_atoms),
        ids: Vec::with_capacity(n_atoms),
        sym_index: Vec::with_capacity(n_atoms),
        symbols: Vec::new(),
        identity_shared: true,
        headers: Vec::new(),
        header_index: Vec::with_capacity(n_frames),
    };
    let mut symbols = HashMap::new();
    let mut frame_index = 0usize;
    for_each_frame(src, |frame| {
        push_frame(
            &frame,
            frame_index,
            sections,
            &mut slabs,
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
    sections: SectionFlags,
    slabs: Slabs<'_>,
) -> Result<Columns, ()> {
    let src = crate::compression::open_decoded(path).map_err(|_| ())?;
    fill_reader(src, n_frames, n_atoms, sections, slabs)
}

pub fn fill_bytes(
    bytes: &[u8],
    n_frames: usize,
    n_atoms: usize,
    sections: SectionFlags,
    slabs: Slabs<'_>,
) -> Result<Columns, ()> {
    fill_reader(
        std::io::Cursor::new(bytes),
        n_frames,
        n_atoms,
        sections,
        slabs,
    )
}

impl Columns {
    fn slot(&self, frame: usize, atom: usize) -> usize {
        if self.identity_shared {
            atom
        } else {
            frame * self.n_atoms + atom
        }
    }

    pub fn symbol_at(&self, frame: usize, atom: usize) -> &str {
        let index = self.sym_index[self.slot(frame, atom)] as usize;
        self.symbols[index].as_ref()
    }

    pub fn flag_at(&self, frame: usize, atom: usize) -> [bool; 3] {
        let mask = self.flags[self.slot(frame, atom)];
        [mask & 1 != 0, mask & 2 != 0, mask & 4 != 0]
    }

    pub fn id_at(&self, frame: usize, atom: usize) -> u64 {
        self.ids[self.slot(frame, atom)]
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

    fn empty_slabs(positions: &mut [f64]) -> Slabs<'_> {
        Slabs {
            positions,
            velocities: None,
            forces: None,
            energies: None,
            charges: None,
            spins: None,
            magmoms: None,
            displacements: None,
            spreads: None,
        }
    }

    #[test]
    fn plain_con_columns_match_the_frame_reader() {
        let path = Path::new("resources/test/tiny_multi_cuh2.con");
        let layout = layout_path(path).expect("layout");
        assert_eq!(layout.n_frames, 2);
        assert_eq!(layout.n_atoms, 4);
        assert!(!layout.sections.velocities);
        let mut positions = vec![0.0; layout.n_frames * layout.n_atoms * 3];
        let columns = fill_path(
            path,
            layout.n_frames,
            layout.n_atoms,
            layout.sections,
            empty_slabs(&mut positions),
        )
        .unwrap();
        assert!(columns.identity_shared);
        assert_eq!(columns.ids.len(), layout.n_atoms);
        let frames = read_all_frames(path).unwrap();
        assert_eq!(frames.len(), columns.n_frames);
        for (index, frame) in frames.iter().enumerate() {
            let header = &columns.headers[columns.header_index[index] as usize];
            assert_eq!(frame.header.boxl, header.boxl);
            for (atom_index, atom) in frame.atom_data.iter().enumerate() {
                assert_eq!(atom.symbol.as_ref(), columns.symbol_at(index, atom_index));
                assert_eq!(atom.fixed(), columns.flag_at(index, atom_index));
                assert_eq!(atom.atom_id, columns.id_at(index, atom_index));
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
        let columns = fill_bytes(
            &bytes,
            layout.n_frames,
            layout.n_atoms,
            layout.sections,
            empty_slabs(&mut positions),
        )
        .unwrap();
        assert_eq!(columns.headers.len(), 1, "distinct headers");
        assert!(columns.identity_shared);
        assert_eq!(columns.flags.len(), 4);
    }

    #[test]
    fn a_velocity_file_fills_the_velocity_slab() {
        let path = Path::new("resources/test/tiny_multi_cuh2.convel");
        let layout = layout_path(path).expect("layout");
        assert!(layout.sections.velocities);
        assert!(!layout.sections.forces);
        let n = layout.n_frames * layout.n_atoms * 3;
        let mut positions = vec![0.0; n];
        let mut velocities = vec![0.0; n];
        let mut slabs = empty_slabs(&mut positions);
        slabs.velocities = Some(&mut velocities);
        let columns = fill_path(
            path,
            layout.n_frames,
            layout.n_atoms,
            layout.sections,
            slabs,
        )
        .unwrap();
        let frames = read_all_frames(path).unwrap();
        for (index, frame) in frames.iter().enumerate() {
            for (atom_index, atom) in frame.atom_data.iter().enumerate() {
                let at = (index * columns.n_atoms + atom_index) * 3;
                let vel = atom.velocity().expect("velocity");
                assert_eq!(velocities[at], vel[0]);
                assert_eq!(velocities[at + 1], vel[1]);
                assert_eq!(velocities[at + 2], vel[2]);
            }
        }
    }

    #[test]
    fn a_force_file_fills_the_force_slab() {
        let path = Path::new("resources/test/tiny_cuh2_forces.con");
        let layout = layout_path(path).expect("layout");
        assert!(layout.sections.forces);
        assert!(!layout.sections.velocities);
        let n = layout.n_frames * layout.n_atoms * 3;
        let mut positions = vec![0.0; n];
        let mut forces = vec![0.0; n];
        let mut slabs = empty_slabs(&mut positions);
        slabs.forces = Some(&mut forces);
        fill_path(
            path,
            layout.n_frames,
            layout.n_atoms,
            layout.sections,
            slabs,
        )
        .unwrap();
        let frames = read_all_frames(path).unwrap();
        let atom = &frames[0].atom_data[0];
        let force = atom.force().expect("force");
        assert_eq!(forces[0], force[0]);
        assert_eq!(forces[1], force[1]);
        assert_eq!(forces[2], force[2]);
    }

    fn two_copies_with_second_patched(patch: u8, from_end: usize) -> Vec<u8> {
        let src = std::fs::read("resources/test/tiny_cuh2.con").unwrap();
        let mut bytes = Vec::new();
        bytes.extend_from_slice(&src);
        bytes.extend_from_slice(&src);
        let marker = b"6.97529999999999539 7    0";
        let mut hits = Vec::new();
        let mut start = 0usize;
        while let Some(pos) = bytes[start..]
            .windows(marker.len())
            .position(|window| window == marker)
        {
            hits.push(start + pos);
            start += pos + marker.len();
        }
        assert!(hits.len() >= 2, "marker hits {}", hits.len());
        let at = hits[1] + marker.len() - from_end;
        bytes[at] = patch;
        bytes
    }

    fn fill_copies(bytes: &[u8]) -> Columns {
        let layout = layout_bytes(bytes).expect("layout");
        let mut positions = vec![0.0; layout.n_frames * layout.n_atoms * 3];
        fill_bytes(
            bytes,
            layout.n_frames,
            layout.n_atoms,
            layout.sections,
            empty_slabs(&mut positions),
        )
        .expect("fill")
    }

    #[test]
    fn a_later_frame_with_a_new_id_expands_identity() {
        // The id is the last byte of `7    0`.
        let bytes = two_copies_with_second_patched(b'9', 1);
        let columns = fill_copies(&bytes);
        assert!(!columns.identity_shared);
        assert_eq!(columns.ids.len(), columns.n_frames * columns.n_atoms);
        assert_eq!(columns.flags.len(), columns.ids.len());
        assert_eq!(columns.ids[0], 0);
        assert_eq!(columns.ids[columns.n_atoms], 9);
    }

    #[test]
    fn a_later_frame_with_a_new_flag_expands_identity() {
        // The fixed mask is the `7` six bytes before the end of `7    0`.
        let bytes = two_copies_with_second_patched(b'0', 6);
        let columns = fill_copies(&bytes);
        assert!(!columns.identity_shared);
        assert_eq!(columns.flags.len(), columns.n_frames * columns.n_atoms);
        assert_eq!(columns.flags[0], 7);
        assert_eq!(columns.flags[columns.n_atoms], 0);
    }

    #[test]
    fn a_changed_atom_count_refuses_the_column_fill() {
        let text = "\
Frame
one
8.0 8.0 4.0
90.0 90.0 90.0
0 0
0 0
1
2
63.546
Cu
Coordinates of Component 1
0.0 0.0 0.0 0 0
1.0 0.0 0.0 0 1
Frame
two
8.0 8.0 4.0
90.0 90.0 90.0
0 0
0 0
1
1
63.546
Cu
Coordinates of Component 1
2.0 0.0 0.0 0 0
";
        let bytes = text.as_bytes();
        let layout = layout_bytes(bytes).expect("first frame still sets the shape");
        assert_eq!(layout.n_frames, 2);
        assert_eq!(layout.n_atoms, 2);
        let mut positions = vec![0.0; layout.n_frames * layout.n_atoms * 3];
        let filled = fill_bytes(
            bytes,
            layout.n_frames,
            layout.n_atoms,
            layout.sections,
            empty_slabs(&mut positions),
        );
        assert!(filled.is_err());
    }
}
