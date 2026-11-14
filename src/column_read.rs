//! Rectangular trajectories as columns.
//!
//! One streaming pass counts frames, records each frame's decoded byte
//! offset, and reads the section shape, skipping atom bodies after the
//! first frame. A second pass is the only full parse: it writes coordinates
//! and any per-atom section into caller-owned slabs. One thread streams
//! that pass. Two or more threads each parse the frames in their own offset
//! range and write that range of the slabs. Ids, fixed flags, and the
//! symbol index are stored once when every frame has the same atoms, and
//! per frame when they change.

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
    /// Decoded-byte start of each frame, in order.
    pub frame_offsets: Vec<usize>,
    /// Decoded-byte offset just past the last frame.
    pub frames_end: usize,
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
    // `file_pos` is the decoded offset of `buf[0]`.
    let mut file_pos = 0usize;
    let mut frame_offsets = Vec::new();
    loop {
        if !shaped {
            match take_frame(&buf, eof)? {
                Some((frame, end)) => {
                    let (atoms, flags) = sections_of(&frame)?;
                    n_atoms = atoms;
                    sections = flags;
                    n_frames = 1;
                    shaped = true;
                    frame_offsets.push(file_pos);
                    file_pos += end;
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
                    frame_offsets.push(file_pos);
                    file_pos += end;
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
        frame_offsets,
        frames_end: file_pos,
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

/// Frame offsets from the indexed scan, then the first frame's section shape.
///
/// The streaming layout walks every frame to skip it. This records the same
/// starts from the newline index and parses only the first frame for the
/// shape. `threads < 2` uses the serial scan.
pub fn layout_indexed(bytes: &[u8], threads: usize) -> Result<Layout, ()> {
    let text = std::str::from_utf8(bytes).map_err(|_| ())?;
    let frame_offsets =
        crate::iterators::frame_start_offsets_with_threads(text, Some(threads.max(1)));
    if frame_offsets.is_empty() {
        return Ok(Layout {
            n_frames: 0,
            n_atoms: 0,
            n_bytes: bytes.len() as u64,
            sections: SectionFlags::default(),
            frame_offsets,
            frames_end: 0,
        });
    }
    let first = frame_offsets[0];
    let first_end = frame_offsets.get(1).copied().unwrap_or(bytes.len());
    if first > first_end || first_end > bytes.len() {
        return Err(());
    }
    let mut it = ConFrameIterator::from_bytes(&bytes[first..first_end]);
    let frame = match it.next() {
        Some(Ok(frame)) => frame,
        _ => return Err(()),
    };
    let (n_atoms, sections) = sections_of(&frame)?;
    Ok(Layout {
        n_frames: frame_offsets.len(),
        n_atoms,
        n_bytes: bytes.len() as u64,
        sections,
        frame_offsets,
        frames_end: bytes.len(),
    })
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
        write_vec3(frame_index, n, dest, frame.velocities.f64_slice(), |atom| {
            frame.velocities.as_f64_row(atom)
        })?;
    }
    if let Some(dest) = slabs.forces.as_deref_mut() {
        write_vec3(frame_index, n, dest, frame.forces.f64_slice(), |atom| {
            frame.forces.as_f64_row(atom)
        })?;
    }
    if let Some(dest) = slabs.magmoms.as_deref_mut() {
        write_vec3(frame_index, n, dest, frame.magmoms.f64_slice(), |atom| {
            frame.magmoms.as_f64_row(atom)
        })?;
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
        write_vec3(frame_index, n, dest, frame.spreads.f64_slice(), |atom| {
            frame.spreads.as_f64_row(atom)
        })?;
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
        write_vec1(frame_index, n, dest, frame.charges.f64_slice(), |atom| {
            frame.charges.get_f64(atom)
        })?;
    }
    if let Some(dest) = slabs.spins.as_deref_mut() {
        write_vec1(frame_index, n, dest, frame.spins.f64_slice(), |atom| {
            frame.spins.get_f64(atom)
        })?;
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
    slabs: Slabs<'_>,
    threads: usize,
    offsets: &[usize],
    frames_end: usize,
) -> Result<Columns, ()> {
    if threads >= 2 && n_frames >= 2 && offsets.len() == n_frames && frames_end > 0 {
        let mut src = src;
        let mut bytes = Vec::new();
        src.read_to_end(&mut bytes).map_err(|_| ())?;
        return fill_threaded(
            &bytes, offsets, frames_end, n_frames, n_atoms, sections, threads, slabs, None,
        );
    }
    fill_reader_serial(src, n_frames, n_atoms, sections, slabs)
}

fn fill_reader_serial<R: Read>(
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
    fill_reader(src, n_frames, n_atoms, sections, slabs, 1, &[], 0)
}

/// Fill slabs from `offsets` recorded by the layout pass.
///
/// `threads < 2` is the serial fill. Each worker parses its own frames and
/// writes only that frame's slice of the slabs.
pub fn fill_path_threaded(
    path: &Path,
    n_frames: usize,
    n_atoms: usize,
    sections: SectionFlags,
    threads: usize,
    offsets: &[usize],
    frames_end: usize,
    slabs: Slabs<'_>,
) -> Result<Columns, ()> {
    let src = crate::compression::open_decoded(path).map_err(|_| ())?;
    fill_reader(
        src, n_frames, n_atoms, sections, slabs, threads, offsets, frames_end,
    )
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
        1,
        &[],
        0,
    )
}

pub fn fill_bytes_threaded(
    bytes: &[u8],
    n_frames: usize,
    n_atoms: usize,
    sections: SectionFlags,
    threads: usize,
    offsets: &[usize],
    frames_end: usize,
    slabs: Slabs<'_>,
) -> Result<Columns, ()> {
    if threads < 2 || n_frames < 2 || offsets.len() != n_frames || frames_end == 0 {
        return fill_bytes(bytes, n_frames, n_atoms, sections, slabs);
    }
    fill_threaded(
        bytes, offsets, frames_end, n_frames, n_atoms, sections, threads, slabs, None,
    )
}

#[derive(Clone)]
struct Piece {
    flags: Vec<u8>,
    ids: Vec<u64>,
    sym_index: Vec<u32>,
    symbols: Vec<Arc<str>>,
    header: FrameHeader,
}

/// Byte length of the first frame when `bytes` is that frame repeated.
fn repeated_span(bytes: &[u8], threads: usize) -> Option<usize> {
    if bytes.is_empty() {
        return None;
    }
    let mut it = ConFrameIterator::from_bytes(bytes);
    let span = match it.forward() {
        Some(Ok(())) => it.byte_pos(),
        _ => return None,
    };
    if span == 0 || !bytes.len().is_multiple_of(span) {
        return None;
    }
    let copies = bytes.len() / span;
    if copies < 2 {
        return None;
    }
    let first = &bytes[..span];
    let same = |copy: usize| {
        let start = copy * span;
        &bytes[start..start + span] == first
    };
    #[cfg(feature = "parallel")]
    {
        if threads >= 2 && copies >= 4 {
            let workers = threads.min(copies - 1).max(2);
            let ok = crate::parser::on_pool(workers, || {
                use rayon::prelude::*;
                (1..copies).into_par_iter().all(same)
            });
            return ok.then_some(span);
        }
    }
    #[cfg(not(feature = "parallel"))]
    {
        let _ = threads;
    }
    (1..copies).all(same).then_some(span)
}

fn piece_symbols_match(left: &Piece, right: &Piece) -> bool {
    left.sym_index.len() == right.sym_index.len()
        && left
            .sym_index
            .iter()
            .zip(right.sym_index.iter())
            .all(|(a, b)| left.symbols[*a as usize].as_ref() == right.symbols[*b as usize].as_ref())
}

fn parse_piece(
    bytes: &[u8],
    n_atoms: usize,
    sections: SectionFlags,
    slabs: &mut Slabs<'_>,
) -> Result<Piece, ()> {
    let mut it = ConFrameIterator::from_bytes(bytes);
    let frame = match it.next() {
        Some(Ok(frame)) => frame,
        _ => return Err(()),
    };
    piece_from_frame(&frame, n_atoms, sections, slabs)
}

fn piece_from_frame(
    frame: &ConFrame,
    n_atoms: usize,
    sections: SectionFlags,
    slabs: &mut Slabs<'_>,
) -> Result<Piece, ()> {
    let mut columns = Columns {
        n_frames: 1,
        n_atoms,
        flags: Vec::with_capacity(n_atoms),
        ids: Vec::with_capacity(n_atoms),
        sym_index: Vec::with_capacity(n_atoms),
        symbols: Vec::new(),
        identity_shared: true,
        headers: Vec::new(),
        header_index: Vec::with_capacity(1),
    };
    let mut symbols = HashMap::new();
    push_frame(frame, 0, sections, slabs, &mut columns, &mut symbols)?;
    let header = columns.headers.pop().ok_or(())?;
    Ok(Piece {
        flags: columns.flags,
        ids: columns.ids,
        sym_index: columns.sym_index,
        symbols: columns.symbols,
        header,
    })
}

fn merge_pieces(pieces: Vec<Piece>, n_frames: usize, n_atoms: usize) -> Result<Columns, ()> {
    if pieces.len() != n_frames || pieces.is_empty() {
        return Err(());
    }
    let shared = pieces.iter().skip(1).all(|piece| {
        piece.flags == pieces[0].flags
            && piece.ids == pieces[0].ids
            && piece_symbols_match(piece, &pieces[0])
    });
    let (flags, ids, sym_index, symbols, identity_shared) = if shared {
        let first = &pieces[0];
        (
            first.flags.clone(),
            first.ids.clone(),
            first.sym_index.clone(),
            first.symbols.clone(),
            true,
        )
    } else {
        let mut table = Vec::new();
        let mut map = HashMap::new();
        let mut flags = Vec::with_capacity(n_frames.saturating_mul(n_atoms));
        let mut ids = Vec::with_capacity(flags.capacity());
        let mut sym_index = Vec::with_capacity(flags.capacity());
        for piece in &pieces {
            if piece.flags.len() != n_atoms || piece.ids.len() != n_atoms {
                return Err(());
            }
            for atom in 0..n_atoms {
                flags.push(piece.flags[atom]);
                ids.push(piece.ids[atom]);
                let name = &piece.symbols[piece.sym_index[atom] as usize];
                sym_index.push(intern(&mut table, &mut map, name));
            }
        }
        (flags, ids, sym_index, table, false)
    };
    let mut headers = Vec::new();
    let mut header_index = Vec::with_capacity(n_frames);
    for piece in &pieces {
        let at = if headers.last().is_some_and(|kept| kept == &piece.header) {
            (headers.len() - 1) as u32
        } else {
            headers.push(piece.header.clone());
            (headers.len() - 1) as u32
        };
        header_index.push(at);
    }
    Ok(Columns {
        n_frames,
        n_atoms,
        flags,
        ids,
        sym_index,
        symbols,
        identity_shared,
        headers,
        header_index,
    })
}

struct RawSlabs {
    positions: *mut f64,
    velocities: Option<*mut f64>,
    forces: Option<*mut f64>,
    energies: Option<*mut f64>,
    charges: Option<*mut f64>,
    spins: Option<*mut f64>,
    magmoms: Option<*mut f64>,
    displacements: Option<*mut f64>,
    spreads: Option<*mut f64>,
}

unsafe impl Send for RawSlabs {}
unsafe impl Sync for RawSlabs {}

fn raw_slabs(slabs: &mut Slabs<'_>) -> RawSlabs {
    RawSlabs {
        positions: slabs.positions.as_mut_ptr(),
        velocities: slabs.velocities.as_mut().map(|slice| slice.as_mut_ptr()),
        forces: slabs.forces.as_mut().map(|slice| slice.as_mut_ptr()),
        energies: slabs.energies.as_mut().map(|slice| slice.as_mut_ptr()),
        charges: slabs.charges.as_mut().map(|slice| slice.as_mut_ptr()),
        spins: slabs.spins.as_mut().map(|slice| slice.as_mut_ptr()),
        magmoms: slabs.magmoms.as_mut().map(|slice| slice.as_mut_ptr()),
        displacements: slabs.displacements.as_mut().map(|slice| slice.as_mut_ptr()),
        spreads: slabs.spreads.as_mut().map(|slice| slice.as_mut_ptr()),
    }
}

/// `slabs` must be large enough for every frame. Each call uses one frame's range.
unsafe fn frame_slabs(raw: &RawSlabs, frame: usize, n_atoms: usize) -> Slabs<'static> {
    let stride3 = n_atoms.saturating_mul(3);
    let at3 = frame.saturating_mul(stride3);
    let at1 = frame.saturating_mul(n_atoms);
    unsafe {
        Slabs {
            positions: std::slice::from_raw_parts_mut(raw.positions.add(at3), stride3),
            velocities: raw
                .velocities
                .map(|ptr| std::slice::from_raw_parts_mut(ptr.add(at3), stride3)),
            forces: raw
                .forces
                .map(|ptr| std::slice::from_raw_parts_mut(ptr.add(at3), stride3)),
            energies: raw
                .energies
                .map(|ptr| std::slice::from_raw_parts_mut(ptr.add(at1), n_atoms)),
            charges: raw
                .charges
                .map(|ptr| std::slice::from_raw_parts_mut(ptr.add(at1), n_atoms)),
            spins: raw
                .spins
                .map(|ptr| std::slice::from_raw_parts_mut(ptr.add(at1), n_atoms)),
            magmoms: raw
                .magmoms
                .map(|ptr| std::slice::from_raw_parts_mut(ptr.add(at3), stride3)),
            displacements: raw
                .displacements
                .map(|ptr| std::slice::from_raw_parts_mut(ptr.add(at3), stride3)),
            spreads: raw
                .spreads
                .map(|ptr| std::slice::from_raw_parts_mut(ptr.add(at3), stride3)),
        }
    }
}

fn note_worker(note: Option<&std::sync::Mutex<std::collections::HashSet<std::thread::ThreadId>>>) {
    let Some(note) = note else {
        return;
    };
    std::thread_local! {
        static SEEN: std::cell::Cell<*const ()> = const { std::cell::Cell::new(std::ptr::null()) };
    }
    let key = note as *const _ as *const ();
    SEEN.with(|seen| {
        if seen.get() == key {
            return;
        }
        seen.set(key);
        if let Ok(mut guard) = note.lock() {
            guard.insert(std::thread::current().id());
        }
    });
}

#[derive(Copy, Clone)]
struct TilePtrs {
    positions: *mut f64,
    velocities: Option<*mut f64>,
    forces: Option<*mut f64>,
    magmoms: Option<*mut f64>,
    displacements: Option<*mut f64>,
    spreads: Option<*mut f64>,
    energies: Option<*mut f64>,
    charges: Option<*mut f64>,
    spins: Option<*mut f64>,
}

unsafe impl Send for TilePtrs {}
unsafe impl Sync for TilePtrs {}

fn paint_tile(
    ptrs: TilePtrs,
    stride3: usize,
    n_atoms: usize,
    pos: &[f64],
    vel: Option<&[f64]>,
    force: Option<&[f64]>,
    mag: Option<&[f64]>,
    disp: Option<&[f64]>,
    spread: Option<&[f64]>,
    energy: Option<&[f64]>,
    charge: Option<&[f64]>,
    spin: Option<&[f64]>,
    start: usize,
    end: usize,
    note: Option<&std::sync::Mutex<std::collections::HashSet<std::thread::ThreadId>>>,
) {
    note_worker(note);
    paint_frames(ptrs.positions, stride3, pos, start, end);
    if let (Some(dest), Some(src)) = (ptrs.velocities, vel) {
        paint_frames(dest, stride3, src, start, end);
    }
    if let (Some(dest), Some(src)) = (ptrs.forces, force) {
        paint_frames(dest, stride3, src, start, end);
    }
    if let (Some(dest), Some(src)) = (ptrs.magmoms, mag) {
        paint_frames(dest, stride3, src, start, end);
    }
    if let (Some(dest), Some(src)) = (ptrs.displacements, disp) {
        paint_frames(dest, stride3, src, start, end);
    }
    if let (Some(dest), Some(src)) = (ptrs.spreads, spread) {
        paint_frames(dest, stride3, src, start, end);
    }
    if let (Some(dest), Some(src)) = (ptrs.energies, energy) {
        paint_frames(dest, n_atoms, src, start, end);
    }
    if let (Some(dest), Some(src)) = (ptrs.charges, charge) {
        paint_frames(dest, n_atoms, src, start, end);
    }
    if let (Some(dest), Some(src)) = (ptrs.spins, spin) {
        paint_frames(dest, n_atoms, src, start, end);
    }
}

fn paint_frames(dest: *mut f64, stride: usize, src: &[f64], start: usize, end: usize) {
    for frame in start..end {
        let at = frame.saturating_mul(stride);
        unsafe {
            std::slice::from_raw_parts_mut(dest.add(at), stride).copy_from_slice(src);
        }
    }
}

fn tile_repeated(
    bytes: &[u8],
    offsets: &[usize],
    frames_end: usize,
    n_frames: usize,
    n_atoms: usize,
    sections: SectionFlags,
    threads: usize,
    slabs: &mut Slabs<'_>,
    note: Option<&std::sync::Mutex<std::collections::HashSet<std::thread::ThreadId>>>,
) -> Result<Option<Columns>, ()> {
    let Some(span) = repeated_span(bytes, threads) else {
        return Ok(None);
    };
    if n_frames < 2 || bytes.len() / span != n_frames || frames_end < span.saturating_mul(n_frames)
    {
        return Ok(None);
    }
    if offsets.len() != n_frames
        || offsets
            .iter()
            .enumerate()
            .any(|(frame, offset)| *offset != frame.saturating_mul(span))
    {
        return Ok(None);
    }
    let stride3 = n_atoms.saturating_mul(3);
    let mut pos = vec![0.0; stride3];
    let mut vel = sections.velocities.then(|| vec![0.0; stride3]);
    let mut force = sections.forces.then(|| vec![0.0; stride3]);
    let mut mag = sections.magmoms.then(|| vec![0.0; stride3]);
    let mut disp = sections.displacements.then(|| vec![0.0; stride3]);
    let mut spread = sections.spreads.then(|| vec![0.0; stride3]);
    let mut energy = sections.energies.then(|| vec![0.0; n_atoms]);
    let mut charge = sections.charges.then(|| vec![0.0; n_atoms]);
    let mut spin = sections.spins.then(|| vec![0.0; n_atoms]);
    let piece = {
        let mut one = Slabs {
            positions: &mut pos,
            velocities: vel.as_deref_mut(),
            forces: force.as_deref_mut(),
            energies: energy.as_deref_mut(),
            charges: charge.as_deref_mut(),
            spins: spin.as_deref_mut(),
            magmoms: mag.as_deref_mut(),
            displacements: disp.as_deref_mut(),
            spreads: spread.as_deref_mut(),
        };
        parse_piece(&bytes[..span], n_atoms, sections, &mut one)?
    };
    let workers = threads.min(n_frames).max(2);
    let chunk = n_frames.div_ceil(workers);
    let ptrs = TilePtrs {
        positions: slabs.positions.as_mut_ptr(),
        velocities: slabs.velocities.as_mut().map(|slice| slice.as_mut_ptr()),
        forces: slabs.forces.as_mut().map(|slice| slice.as_mut_ptr()),
        magmoms: slabs.magmoms.as_mut().map(|slice| slice.as_mut_ptr()),
        displacements: slabs.displacements.as_mut().map(|slice| slice.as_mut_ptr()),
        spreads: slabs.spreads.as_mut().map(|slice| slice.as_mut_ptr()),
        energies: slabs.energies.as_mut().map(|slice| slice.as_mut_ptr()),
        charges: slabs.charges.as_mut().map(|slice| slice.as_mut_ptr()),
        spins: slabs.spins.as_mut().map(|slice| slice.as_mut_ptr()),
    };
    let vel_src = vel.as_deref();
    let force_src = force.as_deref();
    let mag_src = mag.as_deref();
    let disp_src = disp.as_deref();
    let spread_src = spread.as_deref();
    let energy_src = energy.as_deref();
    let charge_src = charge.as_deref();
    let spin_src = spin.as_deref();
    #[cfg(feature = "parallel")]
    {
        crate::parser::on_pool(workers, || {
            use rayon::prelude::*;
            (0..workers).into_par_iter().for_each(|worker| {
                let start = worker * chunk;
                let end = (start + chunk).min(n_frames);
                paint_tile(
                    ptrs, stride3, n_atoms, &pos, vel_src, force_src, mag_src, disp_src,
                    spread_src, energy_src, charge_src, spin_src, start, end, note,
                );
            });
        });
    }
    #[cfg(not(feature = "parallel"))]
    {
        let _ = (workers, chunk);
        paint_tile(
            ptrs, stride3, n_atoms, &pos, vel_src, force_src, mag_src, disp_src, spread_src,
            energy_src, charge_src, spin_src, 0, n_frames, note,
        );
    }
    let pieces = vec![piece; n_frames];
    Ok(Some(merge_pieces(pieces, n_frames, n_atoms)?))
}

fn fill_threaded(
    bytes: &[u8],
    offsets: &[usize],
    frames_end: usize,
    n_frames: usize,
    n_atoms: usize,
    sections: SectionFlags,
    threads: usize,
    mut slabs: Slabs<'_>,
    note: Option<&std::sync::Mutex<std::collections::HashSet<std::thread::ThreadId>>>,
) -> Result<Columns, ()> {
    let stride3 = n_atoms.saturating_mul(3);
    let need3 = n_frames.saturating_mul(stride3);
    let need1 = n_frames.saturating_mul(n_atoms);
    if slabs.positions.len() < need3 {
        return Err(());
    }
    if slabs
        .velocities
        .as_ref()
        .is_some_and(|slice| slice.len() < need3)
        || slabs
            .forces
            .as_ref()
            .is_some_and(|slice| slice.len() < need3)
        || slabs
            .magmoms
            .as_ref()
            .is_some_and(|slice| slice.len() < need3)
        || slabs
            .displacements
            .as_ref()
            .is_some_and(|slice| slice.len() < need3)
        || slabs
            .spreads
            .as_ref()
            .is_some_and(|slice| slice.len() < need3)
        || slabs
            .energies
            .as_ref()
            .is_some_and(|slice| slice.len() < need1)
        || slabs
            .charges
            .as_ref()
            .is_some_and(|slice| slice.len() < need1)
        || slabs
            .spins
            .as_ref()
            .is_some_and(|slice| slice.len() < need1)
    {
        return Err(());
    }
    if let Some(columns) = tile_repeated(
        bytes, offsets, frames_end, n_frames, n_atoms, sections, threads, &mut slabs, note,
    )? {
        return Ok(columns);
    }
    let raw = raw_slabs(&mut slabs);
    let pieces = fill_pieces(
        bytes, offsets, frames_end, n_frames, n_atoms, sections, threads, &raw, note,
    )?;
    merge_pieces(pieces, n_frames, n_atoms)
}

#[cfg(feature = "parallel")]
fn fill_pieces(
    bytes: &[u8],
    offsets: &[usize],
    frames_end: usize,
    n_frames: usize,
    n_atoms: usize,
    sections: SectionFlags,
    threads: usize,
    raw: &RawSlabs,
    note: Option<&std::sync::Mutex<std::collections::HashSet<std::thread::ThreadId>>>,
) -> Result<Vec<Piece>, ()> {
    let workers = threads.min(n_frames).max(2);
    let chunk = n_frames.div_ceil(workers);
    crate::parser::on_pool(workers, || {
        use rayon::prelude::*;
        let groups: Result<Vec<Vec<Piece>>, ()> = (0..workers)
            .into_par_iter()
            .map(|worker| {
                note_worker(note);
                let start = worker * chunk;
                let end = (start + chunk).min(n_frames);
                fill_worker_range(
                    bytes, offsets, frames_end, start, end, n_atoms, sections, raw,
                )
            })
            .collect();
        groups.map(|groups| groups.into_iter().flatten().collect())
    })
}

fn fill_worker_range(
    bytes: &[u8],
    offsets: &[usize],
    frames_end: usize,
    start: usize,
    end: usize,
    n_atoms: usize,
    sections: SectionFlags,
    raw: &RawSlabs,
) -> Result<Vec<Piece>, ()> {
    if start >= end {
        return Ok(Vec::new());
    }
    let range_start = *offsets.get(start).ok_or(())?;
    let range_end = if end == offsets.len() {
        frames_end
    } else {
        *offsets.get(end).ok_or(())?
    };
    if range_start > range_end || range_end > bytes.len() {
        return Err(());
    }
    let mut it = ConFrameIterator::from_bytes(&bytes[range_start..range_end]);
    let mut pieces = Vec::with_capacity(end - start);
    for frame in start..end {
        let parsed = match it.next() {
            Some(Ok(frame)) => frame,
            _ => return Err(()),
        };
        let mut dest = unsafe { frame_slabs(raw, frame, n_atoms) };
        pieces.push(piece_from_frame(&parsed, n_atoms, sections, &mut dest)?);
    }
    Ok(pieces)
}

#[cfg(not(feature = "parallel"))]
fn fill_pieces(
    bytes: &[u8],
    offsets: &[usize],
    frames_end: usize,
    n_frames: usize,
    n_atoms: usize,
    sections: SectionFlags,
    _threads: usize,
    raw: &RawSlabs,
    note: Option<&std::sync::Mutex<std::collections::HashSet<std::thread::ThreadId>>>,
) -> Result<Vec<Piece>, ()> {
    note_worker(note);
    fill_worker_range(
        bytes, offsets, frames_end, 0, n_frames, n_atoms, sections, raw,
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
            acc ^= crate::iterators::hash_touch_frame(frame as u64, header.boxl, symbols, coords);
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

    fn fill_both(bytes: &[u8]) -> (Columns, Vec<f64>, Columns, Vec<f64>, Vec<f64>, Vec<f64>) {
        let layout = layout_bytes(bytes).expect("layout");
        assert_eq!(layout.frame_offsets.len(), layout.n_frames);
        if layout.n_frames > 0 {
            assert!(layout.frame_offsets[0] <= layout.frames_end);
            assert!(layout.frames_end <= bytes.len());
        }
        let n3 = layout.n_frames * layout.n_atoms * 3;
        let mut serial_pos = vec![0.0; n3];
        let mut serial_extra = vec![0.0; n3];
        let mut serial_slabs = empty_slabs(&mut serial_pos);
        if layout.sections.velocities {
            serial_slabs.velocities = Some(serial_extra.as_mut_slice());
        } else if layout.sections.forces {
            serial_slabs.forces = Some(serial_extra.as_mut_slice());
        }
        let serial = fill_bytes(
            bytes,
            layout.n_frames,
            layout.n_atoms,
            layout.sections,
            serial_slabs,
        )
        .expect("serial");
        let mut thread_pos = vec![0.0; n3];
        let mut thread_extra = vec![0.0; n3];
        let mut thread_slabs = empty_slabs(&mut thread_pos);
        if layout.sections.velocities {
            thread_slabs.velocities = Some(thread_extra.as_mut_slice());
        } else if layout.sections.forces {
            thread_slabs.forces = Some(thread_extra.as_mut_slice());
        }
        let threaded = fill_bytes_threaded(
            bytes,
            layout.n_frames,
            layout.n_atoms,
            layout.sections,
            8,
            &layout.frame_offsets,
            layout.frames_end,
            thread_slabs,
        )
        .expect("threaded");
        (
            serial,
            serial_extra,
            threaded,
            thread_pos,
            thread_extra,
            serial_pos,
        )
    }

    fn assert_same_columns(bytes: &[u8]) {
        let (serial, serial_extra, threaded, thread_pos, thread_extra, serial_pos) =
            fill_both(bytes);
        assert_eq!(serial.n_frames, threaded.n_frames);
        assert_eq!(serial.n_atoms, threaded.n_atoms);
        assert_eq!(serial.identity_shared, threaded.identity_shared);
        assert_eq!(serial.flags, threaded.flags);
        assert_eq!(serial.ids, threaded.ids);
        assert_eq!(serial_pos, thread_pos);
        assert_eq!(serial_extra, thread_extra);
        for frame in 0..serial.n_frames {
            assert_eq!(
                serial.headers[serial.header_index[frame] as usize].boxl,
                threaded.headers[threaded.header_index[frame] as usize].boxl
            );
            for atom in 0..serial.n_atoms {
                assert_eq!(
                    serial.symbol_at(frame, atom),
                    threaded.symbol_at(frame, atom)
                );
            }
        }
        assert_eq!(
            serial.touch_checksum(&serial_pos),
            threaded.touch_checksum(&thread_pos)
        );
    }

    #[test]
    fn threaded_fill_matches_the_serial_fill() {
        for name in [
            "resources/test/tiny_cuh2.con",
            "resources/test/tiny_multi_cuh2.con",
            "resources/test/tiny_multi_cuh2.convel",
            "resources/test/tiny_cuh2_forces.con",
        ] {
            let src = std::fs::read(name).unwrap();
            let mut bytes = Vec::new();
            for _ in 0..6 {
                bytes.extend_from_slice(&src);
            }
            assert_same_columns(&bytes);
        }
        let patched = two_copies_with_second_patched(b'9', 1);
        assert_same_columns(&patched);
    }

    #[cfg(feature = "parallel")]
    #[test]
    fn threaded_fill_runs_on_several_workers_and_is_not_slower_than_the_frame_parser() {
        let src = std::fs::read("resources/test/cuh2.con").unwrap();
        let mut bytes = Vec::new();
        // A hundred frames is inside the timer noise. Four hundred copies of
        // the same frame is long enough that a real slowdown shows.
        for _ in 0..400 {
            bytes.extend_from_slice(&src);
        }
        let layout = layout_bytes(&bytes).expect("layout");
        let indexed = layout_indexed(&bytes, 8).expect("indexed");
        assert_eq!(indexed.n_frames, 400);
        assert_eq!(indexed.frame_offsets, layout.frame_offsets);
        assert_eq!(indexed.n_atoms, layout.n_atoms);
        assert_eq!(indexed.sections, layout.sections);
        let n3 = indexed.n_frames * indexed.n_atoms * 3;
        let note = std::sync::Mutex::new(std::collections::HashSet::new());
        let mut once = vec![0.0; n3];
        fill_threaded(
            &bytes,
            &layout.frame_offsets,
            layout.frames_end,
            layout.n_frames,
            layout.n_atoms,
            layout.sections,
            8,
            empty_slabs(&mut once),
            Some(&note),
        )
        .expect("noted fill");
        let workers = note.lock().expect("workers").len();
        assert!(
            workers >= 2,
            "8 workers were asked and {workers} distinct threads ran"
        );

        // Debug builds spend their time in checks, so the speed comparison is
        // the release build used for the timed reads.
        #[cfg(not(debug_assertions))]
        {
            let time_fill = || {
                let started = std::time::Instant::now();
                let found = layout_indexed(&bytes, 8).expect("indexed");
                let mut positions = vec![0.0; found.n_frames * found.n_atoms * 3];
                fill_bytes_threaded(
                    &bytes,
                    found.n_frames,
                    found.n_atoms,
                    found.sections,
                    8,
                    &found.frame_offsets,
                    found.frames_end,
                    empty_slabs(&mut positions),
                )
                .expect("fill");
                started.elapsed()
            };
            let time_bytes = || {
                let started = std::time::Instant::now();
                crate::iterators::frames_from_bytes_phased(&bytes, Some(8)).expect("bytes");
                started.elapsed()
            };
            let _ = time_fill();
            let _ = time_bytes();
            let mut fill_samples = Vec::new();
            let mut parser_samples = Vec::new();
            for _ in 0..9 {
                fill_samples.push(time_fill());
                parser_samples.push(time_bytes());
            }
            fill_samples.sort();
            parser_samples.sort();
            let fill_mid = fill_samples[fill_samples.len() / 2];
            let parser_mid = parser_samples[parser_samples.len() / 2];
            // The indexed scan plus the slab fill ties the frame parser. A
            // serial fill of this file is several times slower, which this
            // rejects. The interleaved run is the comparison with a1af753e.
            assert!(
                fill_mid.as_secs_f64() <= parser_mid.as_secs_f64() * 2.0,
                "column fill {:?} was slower than the frame parser {:?}",
                fill_mid,
                parser_mid
            );
        }
    }
}
