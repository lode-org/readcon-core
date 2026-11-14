//! Lazy coordinate columns.
//!
//! simdjson splits a structural index from value materialization
//! (Langdale and Lemire, VLDB Journal 2019, <https://doi.org/10.1007/s00778-019-00578-5>).
//! CON already finds newlines with `memchr` and AVX2. The cost that remains
//! on a homogeneous trajectory is the per-frame object: JSON metadata,
//! owned header strings, and an atom table. This walker reads the counts
//! the frame-skip path reads, writes `x y z` into one buffer, and skips
//! vector sections by line count.

use std::sync::Arc;

use crate::error::ParseError;
use crate::parser::{
    line_has_component_label, parse_coord_row_at, parse_count_line, parse_line_of_n_f64,
};

/// The two metadata lines this walker certifies without a second parse.
/// Anything else, including extra JSON keys, is left to the frame parser.
const STOCK_V2: &[u8] = b"{\"con_spec_version\":2}";
const STOCK_V3: &[u8] = b"{\"con_spec_version\":3,\"con_spec_minor\":1,\"units\":{\"length\":\"angstrom\",\"energy\":\"eV\"}}";

/// Coordinates in file order, plus the byte span of each frame.
///
/// `stock` is true when every metadata line is spec 1 or one of the two
/// stock JSON lines, and every section label is a known CON section. The
/// read path uses that certificate. A false certificate means the frame
/// parser must produce the result.
#[derive(Debug, Clone, PartialEq)]
pub struct ConPositions {
    pub n_frames: usize,
    pub counts: Vec<usize>,
    pub positions: Vec<f64>,
    /// Six numbers per frame: box lengths, then angles.
    pub cells: Vec<f64>,
    /// One mass per atom, repeated from the per-type mass line.
    pub masses: Vec<f64>,
    pub spans: Vec<std::ops::Range<usize>>,
    pub stock: bool,
    /// True when any frame had a vector section after the coordinates.
    pub has_section: bool,
    pub ids: Vec<u64>,
    /// Column-4 bitmask, one per atom.
    pub flags: Vec<u8>,
    /// `(symbol, atom count)` in file order, across every frame.
    pub components: Vec<(Arc<str>, usize)>,
    /// Byte offset where the first coordinate row of each frame starts.
    pub head_ends: Vec<usize>,
    /// Absolute newline positions of the coordinate rows, one vector per
    /// frame. Empty when the rows were not indexed.
    pub(crate) wide_breaks: Vec<Vec<usize>>,
    /// `(byte start, row count)` per worker for a wide frame.
    /// Empty when that frame was not split this way.
    pub(crate) wide_chunks: Vec<Vec<(usize, usize)>>,
}

impl ConPositions {
    /// Atom count when every frame has the same count.
    pub fn rectangular_atoms(&self) -> Option<usize> {
        let first = *self.counts.first()?;
        self.counts
            .iter()
            .all(|count| *count == first)
            .then_some(first)
    }
}

/// Positions from a CON or convel buffer, in file order.
/// Three stores into a buffer that already has room. `extend_from_slice`
/// of a 3-float row did not inline into the column walk, so a million-atom
/// frame paid a `memcpy` per atom.
#[inline(always)]
fn push_xyz(dst: &mut Vec<f64>, row: [f64; 3]) {
    let len = dst.len();
    // The caller reserved the frame. A short reserve still grows once.
    if dst.capacity().saturating_sub(len) < 3 {
        dst.reserve(3);
    }
    // SAFETY: `reserve` left three free slots, and `len` is the initialized prefix.
    unsafe {
        let ptr = dst.as_mut_ptr().add(len);
        ptr.write(row[0]);
        ptr.add(1).write(row[1]);
        ptr.add(2).write(row[2]);
        dst.set_len(len + 3);
    }
}

pub fn positions_from_con_bytes(bytes: &[u8]) -> Result<ConPositions, ParseError> {
    parse_con(bytes, false, false, true, 1, None)
}

/// Coordinates plus column 5, the fixed mask, and the per-type symbol runs.
///
/// The position walker still skips vector sections by line count. `ids`,
/// `flags`, and `components` are filled so a later frame can keep an element
/// order that is not the first frame's.
pub fn positions_with_identity(bytes: &[u8]) -> Result<ConPositions, ParseError> {
    parse_con(bytes, true, false, true, 1, None)
}

/// Like [`positions_from_con_bytes`], also keeping ids, flags, and symbols
/// so a frame can be rebuilt without a second numeric scan.
#[allow(dead_code)]
pub fn positions_for_frames(bytes: &[u8]) -> Result<ConPositions, ParseError> {
    // A vector section means the frame objects cannot be rebuilt from the
    // coordinate column. Stop at the first one so the caller can fall back
    // to the frame parser without a second full walk.
    parse_con(bytes, true, true, true, 1, None)
}

/// Header walk plus a parallel fill of the coordinate rows.
///
/// The serial walker parses every float on the calling thread and the
/// old parallel path parsed them again. This walk only counts lines,
/// then the rows are parsed into one buffer. `workers < 2` is the
/// serial walker.
#[cfg(feature = "parallel")]
pub(crate) fn positions_parallel(
    bytes: &[u8],
    workers: usize,
    rich: bool,
) -> Result<ConPositions, ParseError> {
    if workers < 2 {
        return parse_con(bytes, rich, false, true, 1, None);
    }
    // N copies of one wide frame. Planning the first copy on every core
    // and then parsing it again made N threads slower than one thread.
    if let Some(repeated) = parse_repeated_copies(bytes, workers, rich)? {
        return Ok(repeated);
    }
    // Equal frames of one component are filled below, straight into the
    // slab. Re-parsing each frame into its own vector and then copying
    // it made 100 000 frames of 32 atoms slower at eight threads than
    // the serial walk was at four.
    let mut direct: Option<(usize, usize, u32, usize)> = None;
    let mut out = parse_con(bytes, rich, false, false, workers, Some(1))?;
    if let Some(first) = out.spans.first() {
        let frame_start = first.start;
        let first_end = first.end;
        let head0 = out.head_ends.first().copied().unwrap_or(0);
        if first_end > 0 && first_end < bytes.len() {
            if let Some(nframes) = tiled_frame_count(bytes, first_end, head0) {
                let count0 = out.counts[0];
                let spec = frame_spec(bytes, frame_start)?;
                let block_lines = header_block_lines(bytes, frame_start)?;
                if count0 > 0 && block_lines == count0 + 2 {
                    direct = Some((first_end, head0, spec, block_lines));
                }
                let cells0 = out.cells.clone();
                let masses0 = out.masses.clone();
                out.counts.reserve(nframes);
                out.spans.reserve(nframes);
                out.head_ends.reserve(nframes);
                out.cells.reserve(nframes.saturating_mul(6));
                out.masses.reserve(nframes.saturating_mul(masses0.len()));
                out.wide_breaks.reserve(nframes);
                out.wide_chunks.reserve(nframes);
                for frame in 1..nframes {
                    let base = frame * first_end;
                    out.counts.push(count0);
                    out.spans.push(base..base + first_end);
                    out.head_ends.push(head0 + base);
                    out.cells.extend_from_slice(&cells0);
                    out.masses.extend_from_slice(&masses0);
                    out.wide_breaks.push(Vec::new());
                    // Planned on the worker. Shifted chunk offsets are only
                    // valid when every line has the same width.
                    out.wide_chunks.push(Vec::new());
                    out.n_frames += 1;
                }
            } else {
                out = parse_con(bytes, rich, false, false, workers, None)?;
            }
        }
    }
    let n_atoms: usize = out.counts.iter().sum();
    let mut positions = Vec::<f64>::with_capacity(n_atoms.saturating_mul(3));
    let mut ids = Vec::<u64>::new();
    let mut flags = Vec::<u8>::new();
    if rich && n_atoms > 0 {
        ids = Vec::with_capacity(n_atoms);
        flags = Vec::with_capacity(n_atoms);
    }
    let positions_ptr = positions.as_mut_ptr() as usize;
    let ids_ptr = ids.as_mut_ptr() as usize;
    let flags_ptr = flags.as_mut_ptr() as usize;
    if let Some((span, head0, spec, block_lines)) = direct {
        let count0 = out.counts[0];
        let nframes = out.n_frames;
        let (certified, saw) = fill_tiled_frames(
            bytes,
            span,
            head0,
            count0,
            nframes,
            workers,
            rich,
            spec,
            block_lines,
            positions_ptr,
            ids_ptr,
            flags_ptr,
        )?;
        if !certified {
            out.stock = false;
        }
        if saw {
            out.has_section = true;
        }
        if n_atoms > 0 {
            // SAFETY: every tiled frame wrote its rows before this, or the
            // fill returned an error and this length stays 0.
            unsafe {
                positions.set_len(n_atoms * 3);
                if rich {
                    ids.set_len(n_atoms);
                    flags.set_len(n_atoms);
                }
            }
        }
        out.positions = positions;
        if rich {
            out.ids = ids;
            out.flags = flags;
        }
        return Ok(out);
    }
    let mut jobs = Vec::with_capacity(out.n_frames);
    let mut dest_at = 0usize;
    for frame in 0..out.n_frames {
        jobs.push((frame, dest_at));
        dest_at += out.counts[frame];
    }
    // One wide frame must start the row split on this thread. An outer
    // parallel iterator of a single job would run the split inside a
    // worker that already holds the pool.
    if jobs.len() == 1 {
        let (frame, dest) = jobs[0];
        fill_frame_rows(
            bytes,
            &out,
            frame,
            dest,
            workers,
            rich,
            crate::parser::CoordPtrs {
                xyz: positions_ptr as *mut f64,
                ids: ids_ptr as *mut u64,
                flags: flags_ptr as *mut u8,
            },
        )?;
    } else if !jobs.is_empty() {
        // One worker per frame once there is a frame for every worker.
        // Passing `workers` into each frame nested another pool inside
        // the frame iterator, so two million-atom frames on two threads
        // were slower than one frame on one thread.
        let frame_workers = if jobs.len() >= workers {
            1
        } else {
            (workers / jobs.len()).max(1)
        };
        if frame_workers < 2 {
            let pool_threads = workers.min(jobs.len());
            crate::parser::on_pool(pool_threads, || {
                use rayon::prelude::*;
                let failed = jobs.par_iter().find_map_any(|&(frame, dest)| {
                    let span = out.spans[frame].clone();
                    let parsed = match parse_con(
                        &bytes[span.start..span.end],
                        rich,
                        false,
                        true,
                        1,
                        Some(1),
                    ) {
                        Ok(parsed) => parsed,
                        Err(err) => return Some(err),
                    };
                    if parsed.positions.len() != out.counts[frame] * 3 {
                        return Some(ParseError::InvalidCount(
                            "frame atom count does not match the first frame".into(),
                        ));
                    }
                    unsafe {
                        std::ptr::copy_nonoverlapping(
                            parsed.positions.as_ptr(),
                            (positions_ptr as *mut f64).add(dest * 3),
                            parsed.positions.len(),
                        );
                        if rich {
                            std::ptr::copy_nonoverlapping(
                                parsed.ids.as_ptr(),
                                (ids_ptr as *mut u64).add(dest),
                                parsed.ids.len(),
                            );
                            std::ptr::copy_nonoverlapping(
                                parsed.flags.as_ptr(),
                                (flags_ptr as *mut u8).add(dest),
                                parsed.flags.len(),
                            );
                        }
                    }
                    None
                });
                if let Some(err) = failed {
                    return Err(err);
                }
                Ok(())
            })?;
        } else {
            for &(frame, dest) in &jobs {
                fill_frame_rows(
                    bytes,
                    &out,
                    frame,
                    dest,
                    frame_workers,
                    rich,
                    crate::parser::CoordPtrs {
                        xyz: positions_ptr as *mut f64,
                        ids: ids_ptr as *mut u64,
                        flags: flags_ptr as *mut u8,
                    },
                )?;
            }
        }
    }
    if n_atoms > 0 {
        // SAFETY: fill_frame_rows wrote every coordinate before this.
        // The length stays 0 if a fill returns an error, so the drop
        // does not read an uninitialised lane.
        unsafe {
            positions.set_len(n_atoms * 3);
            if rich {
                ids.set_len(n_atoms);
                flags.set_len(n_atoms);
            }
        }
    }
    out.positions = positions;
    if rich {
        out.ids = ids;
        out.flags = flags;
    }
    Ok(out)
}

#[cfg(feature = "parallel")]
fn fill_frame_rows(
    bytes: &[u8],
    out: &ConPositions,
    frame: usize,
    dest: usize,
    workers: usize,
    rich: bool,
    ptrs: crate::parser::CoordPtrs,
) -> Result<(), ParseError> {
    let crate::parser::CoordPtrs {
        xyz: positions,
        ids,
        flags,
    } = ptrs;
    let count = out.counts[frame];
    if count == 0 {
        return Ok(());
    }
    let head = out.head_ends[frame];
    let spec = frame_spec(bytes, out.spans[frame].start)?;
    if out
        .wide_chunks
        .get(frame)
        .is_some_and(|chunks| chunks.iter().map(|(_, nrows)| *nrows).sum::<usize>() == count)
    {
        let chunks = &out.wide_chunks[frame];
        let ids_ptr = if rich {
            unsafe { ids.add(dest) }
        } else {
            std::ptr::null_mut()
        };
        let flags_ptr = if rich {
            unsafe { flags.add(dest) }
        } else {
            std::ptr::null_mut()
        };
        return crate::parser::fill_rows_from_chunks(
            bytes,
            chunks,
            spec,
            0,
            workers,
            crate::parser::CoordPtrs {
                xyz: unsafe { positions.add(dest * 3) },
                ids: ids_ptr,
                flags: flags_ptr,
            },
        );
    }
    if out.wide_breaks.get(frame).map(|item| item.len()) == Some(count) {
        let breaks = &out.wide_breaks[frame];
        let ids_ptr = if rich {
            unsafe { ids.add(dest) }
        } else {
            std::ptr::null_mut()
        };
        let flags_ptr = if rich {
            unsafe { flags.add(dest) }
        } else {
            std::ptr::null_mut()
        };
        return crate::parser::fill_rows_from_breaks(
            bytes,
            breaks,
            head,
            spec,
            0,
            workers,
            crate::parser::CoordPtrs {
                xyz: unsafe { positions.add(dest * 3) },
                ids: ids_ptr,
                flags: flags_ptr,
            },
        );
    }
    let rows = if count >= 4096 {
        crate::parser::parallel_coord_rows(&bytes[head..], count, spec, 0, workers, None)?
    } else {
        serial_coord_rows(&bytes[head..], count, spec)?
    };
    if rows.xyz.len() != count * 3 {
        return Err(ParseError::InvalidCount(
            "frame atom count does not match the first frame".into(),
        ));
    }
    unsafe {
        std::ptr::copy_nonoverlapping(rows.xyz.as_ptr(), positions.add(dest * 3), count * 3);
        if rich {
            std::ptr::copy_nonoverlapping(rows.ids.as_ptr(), ids.add(dest), count);
            for (index, flag) in rows.flags.iter().enumerate() {
                *flags.add(dest + index) = flag_bits(*flag);
            }
        }
    }
    Ok(())
}

#[cfg(feature = "parallel")]
fn frame_spec(bytes: &[u8], frame_start: usize) -> Result<u32, ParseError> {
    let mut pos = frame_start;
    skip_line(bytes, &mut pos)?;
    let meta = read_line(bytes, &mut pos)?;
    spec_version(meta)
}

#[cfg(feature = "parallel")]
fn serial_coord_rows(
    bytes: &[u8],
    n: usize,
    spec: u32,
) -> Result<crate::parser::CoordRows, ParseError> {
    let mut xyz = Vec::with_capacity(n * 3);
    let mut ids = Vec::with_capacity(n);
    let mut flags = Vec::with_capacity(n);
    let mut pos = 0usize;
    let mut default_id = 0u64;
    for _ in 0..n {
        let ((row, fixed, atom_id), next) = parse_coord_row_at(bytes, pos, spec, default_id)?;
        push_xyz(&mut xyz, row);
        ids.push(atom_id);
        flags.push(fixed);
        pos = next;
        default_id = default_id.saturating_add(1);
    }
    Ok(crate::parser::CoordRows {
        xyz,
        ids,
        flags,
        atoms: Vec::new(),
        consumed: pos,
    })
}

fn parse_con(
    bytes: &[u8],
    rich: bool,
    stop_on_section: bool,
    store_rows: bool,
    workers: usize,
    frame_limit: Option<usize>,
) -> Result<ConPositions, ParseError> {
    let mut pos = 0usize;
    let mut out = ConPositions {
        n_frames: 0,
        counts: Vec::new(),
        positions: Vec::new(),
        cells: Vec::new(),
        masses: Vec::new(),
        spans: Vec::new(),
        stock: true,
        has_section: false,
        ids: Vec::new(),
        flags: Vec::new(),
        components: Vec::new(),
        head_ends: Vec::new(),
        wide_breaks: Vec::new(),
        wide_chunks: Vec::new(),
    };
    loop {
        if pos >= bytes.len() || bytes[pos..].iter().all(u8::is_ascii_whitespace) {
            break;
        }
        let start = pos;
        let (n, stock) = parse_one_frame(bytes, &mut pos, &mut out, rich, store_rows, workers)?;
        out.stock &= stock;
        out.counts.push(n);
        out.spans.push(start..pos);
        out.n_frames += 1;
        if stop_on_section && out.has_section {
            break;
        }
        if frame_limit.is_some_and(|limit| out.n_frames >= limit) {
            break;
        }
    }
    Ok(out)
}

/// Identical copies of one wide frame, one copy per worker.
///
/// The size check is a single header. A file that is only one frame never
/// walks its coordinate lines here, so the single-frame split below is
/// unchanged. Each copy is then the serial column walk on its own core.
#[cfg(feature = "parallel")]
fn parse_repeated_copies(
    bytes: &[u8],
    workers: usize,
    rich: bool,
) -> Result<Option<ConPositions>, ParseError> {
    let Some(header) = peek_first_coord_line(bytes) else {
        return Ok(None);
    };
    if header.count < 4096 || header.line_len == 0 {
        return Ok(None);
    }
    // The first coordinate line is the short one on this file. A single
    // frame stays under 1.5x that estimate and keeps the chunked fill.
    // Walking those lines to learn the span took 15 ms, which was the
    // whole weak-scaling gap, so the second copy is found with memmem.
    let est = header
        .head_end
        .saturating_add(header.count.saturating_mul(header.line_len));
    if est == 0 || bytes.len() <= est.saturating_add(est / 2) {
        return Ok(None);
    }
    let Some((span, nframes)) = repeated_span(bytes, header.head_end, est) else {
        return Ok(None);
    };
    let count0 = header.count;
    let mut out = ConPositions {
        n_frames: 0,
        counts: Vec::with_capacity(nframes),
        positions: Vec::new(),
        cells: Vec::with_capacity(nframes * 6),
        masses: Vec::new(),
        spans: Vec::with_capacity(nframes),
        stock: header.stock,
        has_section: false,
        ids: Vec::new(),
        flags: Vec::new(),
        components: Vec::new(),
        head_ends: Vec::with_capacity(nframes),
        wide_breaks: Vec::new(),
        wide_chunks: Vec::new(),
    };
    for frame in 0..nframes {
        let base = frame * span;
        out.counts.push(count0);
        out.spans.push(base..base + span);
        out.head_ends.push(header.head_end + base);
        out.cells.extend_from_slice(&header.cells);
        if rich {
            out.components.push((Arc::clone(&header.symbol), count0));
        }
        out.wide_breaks.push(Vec::new());
        out.wide_chunks.push(Vec::new());
        out.n_frames += 1;
    }
    let n_atoms = count0.saturating_mul(nframes);
    let mut positions = Vec::<f64>::with_capacity(n_atoms.saturating_mul(3));
    let mut masses = Vec::<f64>::new();
    if rich && n_atoms > 0 {
        masses.reserve(n_atoms);
    }
    let mut ids = Vec::<u64>::new();
    let mut flags = Vec::<u8>::new();
    if rich && n_atoms > 0 {
        ids = Vec::with_capacity(n_atoms);
        flags = Vec::with_capacity(n_atoms);
    }
    let positions_ptr = positions.as_mut_ptr() as usize;
    let masses_ptr = if rich {
        masses.as_mut_ptr() as usize
    } else {
        0
    };
    let ids_ptr = ids.as_mut_ptr() as usize;
    let flags_ptr = flags.as_mut_ptr() as usize;
    let saw_section = std::sync::atomic::AtomicBool::new(false);
    let lost_stock = std::sync::atomic::AtomicBool::new(false);
    let saw_section = &saw_section;
    let lost_stock = &lost_stock;
    // One core per copy. A two-item rayon iterator stayed on the caller,
    // so the second copy never overlapped the first.
    let pool_threads = workers.min(nframes);
    let share = nframes.div_ceil(pool_threads);
    let mass = header.mass;
    let head0 = header.head_end;
    let mut failed: Option<ParseError> = None;
    std::thread::scope(|scope| {
        let mut guards = Vec::with_capacity(pool_threads);
        for worker in 0..pool_threads {
            let start_frame = worker * share;
            let end_frame = (start_frame + share).min(nframes);
            guards.push(scope.spawn(move || -> Result<(), ParseError> {
                crate::parser::pin_worker(worker);
                for frame in start_frame..end_frame {
                    let start = frame * span;
                    let (certified, saw) = fill_copied_frame(
                        bytes,
                        CopiedSpan {
                            start,
                            end: start + span,
                            head: head0 + start,
                        },
                        count0,
                        mass,
                        frame * count0,
                        rich,
                        CopiedCols {
                            positions: positions_ptr,
                            masses: masses_ptr,
                            ids: ids_ptr,
                            flags: flags_ptr,
                        },
                    )?;
                    if saw {
                        saw_section.store(true, std::sync::atomic::Ordering::Relaxed);
                    }
                    if !certified {
                        lost_stock.store(true, std::sync::atomic::Ordering::Relaxed);
                    }
                }
                Ok(())
            }));
        }
        for guard in guards {
            if failed.is_some() {
                break;
            }
            if let Err(err) = guard.join().expect("frame parser panicked") {
                failed = Some(err);
            }
        }
    });
    if let Some(err) = failed {
        return Err(err);
    }
    if lost_stock.load(std::sync::atomic::Ordering::Relaxed) {
        out.stock = false;
    }
    if saw_section.load(std::sync::atomic::Ordering::Relaxed) {
        out.has_section = true;
    }
    if n_atoms > 0 {
        unsafe {
            positions.set_len(n_atoms * 3);
            if rich {
                masses.set_len(n_atoms);
            }
            if rich {
                ids.set_len(n_atoms);
                flags.set_len(n_atoms);
            }
        }
    }
    out.positions = positions;
    out.masses = masses;
    if rich {
        out.ids = ids;
        out.flags = flags;
    }
    Ok(Some(out))
}

struct PeekedHeader {
    count: usize,
    head_end: usize,
    line_len: usize,
    cells: [f64; 6],
    mass: f64,
    stock: bool,
    symbol: Arc<str>,
}

struct CopiedSpan {
    start: usize,
    end: usize,
    head: usize,
}

struct CopiedCols {
    positions: usize,
    masses: usize,
    ids: usize,
    flags: usize,
}

/// Parse one copied frame straight into the shared column buffers.
///
/// A temporary `Vec` per copy allocated, copied, and freed on the same
/// core as the parse. Eight of those on eight cores were slower than the
/// parse itself.
#[cfg(feature = "parallel")]
fn fill_copied_frame(
    bytes: &[u8],
    span: CopiedSpan,
    count: usize,
    mass: f64,
    dest: usize,
    rich: bool,
    cols: CopiedCols,
) -> Result<(bool, bool), ParseError> {
    let CopiedSpan {
        start: frame_start,
        end: frame_end,
        head,
    } = span;
    let CopiedCols {
        positions,
        masses,
        ids,
        flags,
    } = cols;
    let spec = frame_spec(bytes, frame_start)?;
    let mut pos = head;
    for row in 0..count {
        let ((row_xyz, fixed, atom_id), next) = parse_coord_row_at(bytes, pos, spec, row as u64)?;
        unsafe {
            std::ptr::copy_nonoverlapping(
                row_xyz.as_ptr(),
                (positions as *mut f64).add((dest + row) * 3),
                3,
            );
            if masses != 0 {
                *((masses as *mut f64).add(dest + row)) = mass;
            }
            if rich {
                *((ids as *mut u64).add(dest + row)) = atom_id;
                *((flags as *mut u8).add(dest + row)) = flag_bits(fixed);
            }
        }
        pos = next;
    }
    if pos < frame_start || pos > frame_end {
        return Err(ParseError::InvalidCount(
            "frame atom count does not match the first frame".into(),
        ));
    }
    let mut rel = pos - frame_start;
    let (certified, saw) = skip_sections(&bytes[frame_start..frame_end], &mut rel, count + 2)?;
    Ok((certified, saw))
}

/// Header fields of a one-component frame, without walking its atom lines.
/// `None` when the header is not the shape this fast path owns.
#[cfg(feature = "parallel")]
fn peek_first_coord_line(bytes: &[u8]) -> Option<PeekedHeader> {
    let mut pos = 0usize;
    skip_line(bytes, &mut pos).ok()?;
    let meta = read_line(bytes, &mut pos).ok()?;
    spec_version(meta).ok()?;
    let stock = stock_meta_line(meta);
    let box_line = utf8_line(read_line(bytes, &mut pos).ok()?).ok()?;
    let boxl = parse_line_of_n_f64(box_line, 3).ok()?;
    let ang_line = utf8_line(read_line(bytes, &mut pos).ok()?).ok()?;
    let angles = parse_line_of_n_f64(ang_line, 3).ok()?;
    skip_line(bytes, &mut pos).ok()?;
    skip_line(bytes, &mut pos).ok()?;
    let types_line = utf8_line(read_line(bytes, &mut pos).ok()?).ok()?;
    let natm_types = parse_count_line(types_line, 1).ok()?[0];
    if natm_types != 1 {
        return None;
    }
    let count_line = utf8_line(read_line(bytes, &mut pos).ok()?).ok()?;
    let counts = parse_count_line(count_line, 1).ok()?;
    let count = counts[0];
    if count == 0 {
        return None;
    }
    let mass_line = utf8_line(read_line(bytes, &mut pos).ok()?).ok()?;
    let mass = parse_line_of_n_f64(mass_line, 1).ok()?[0];
    let symbol_line = utf8_line(read_line(bytes, &mut pos).ok()?).ok()?;
    let symbol: Arc<str> = Arc::from(symbol_line.trim());
    skip_line(bytes, &mut pos).ok()?;
    let head_end = pos;
    let start = pos;
    skip_line(bytes, &mut pos).ok()?;
    let line_len = pos - start;
    let mut cells = [0.0; 6];
    cells[..3].copy_from_slice(&boxl);
    cells[3..].copy_from_slice(&angles);
    Some(PeekedHeader {
        count,
        head_end,
        line_len,
        cells,
        mass,
        stock,
        symbol,
    })
}

/// Byte length of one copy, and how many copies tile `bytes`.
///
/// The second header is a memmem hit. Counting every newline of the first
/// copy to learn the same number was a serial 15 ms on a million-atom frame.
#[cfg(feature = "parallel")]
fn repeated_span(bytes: &[u8], head_end: usize, est: usize) -> Option<(usize, usize)> {
    if head_end < 16 || head_end >= bytes.len() {
        return None;
    }
    let eol = memchr::memchr(b'\n', bytes)?;
    if eol + 1 >= head_end {
        return None;
    }
    let first_line = &bytes[..=eol];
    // Lines are at least as long as the first coordinate line, so the next
    // copy starts at or after `est`. Scanning from byte 0 read the whole
    // first frame and cost 5 ms before any worker could parse.
    let hinted = find_line_at(bytes, first_line, est.max(eol + 1));
    let span = match hinted {
        Some(span) => span,
        None => find_line_at(bytes, first_line, eol + 1)?,
    };
    let nframes = tiled_frame_count(bytes, span, head_end)?;
    Some((span, nframes))
}

#[cfg(feature = "parallel")]
fn find_line_at(bytes: &[u8], line: &[u8], from: usize) -> Option<usize> {
    if line.is_empty() || from >= bytes.len() {
        return None;
    }
    let rare = line[0];
    let mut cursor = from;
    while let Some(hit) = memchr::memchr(rare, &bytes[cursor..]) {
        let at = cursor + hit;
        if bytes[at..].starts_with(line) {
            return Some(at);
        }
        cursor = at + 1;
    }
    None
}

/// `bytes` is `n` copies of a frame of `span` bytes, each starting with
/// the same header. Later frames can then be planned on their own core.
/// Lines in one coordinate block: the atom rows plus a symbol line and a
/// label line per component. One component is `count + 2`.
#[cfg(feature = "parallel")]
fn header_block_lines(bytes: &[u8], frame_start: usize) -> Result<usize, ParseError> {
    let mut pos = frame_start;
    skip_line(bytes, &mut pos)?;
    let _meta = read_line(bytes, &mut pos)?;
    let _box = read_line(bytes, &mut pos)?;
    let _angles = read_line(bytes, &mut pos)?;
    skip_line(bytes, &mut pos)?;
    skip_line(bytes, &mut pos)?;
    let types_line = utf8_line(read_line(bytes, &mut pos)?)?;
    let natm_types = parse_count_line(types_line, 1)?[0];
    if natm_types == 0 {
        return Ok(0);
    }
    let count_line = utf8_line(read_line(bytes, &mut pos)?)?;
    let counts = parse_count_line(count_line, natm_types)?;
    let n: usize = counts.iter().sum();
    Ok(n + natm_types.saturating_mul(2))
}

/// One worker owns a contiguous run of equal frames and writes each row
/// into the shared slab. A rayon job per frame allocated a fresh vector
/// for 32 atoms, and that allocation was the whole 8-thread plateau.
#[cfg(feature = "parallel")]
fn fill_tiled_frames(
    bytes: &[u8],
    span: usize,
    head: usize,
    count: usize,
    nframes: usize,
    workers: usize,
    rich: bool,
    spec: u32,
    block_lines: usize,
    positions: usize,
    ids: usize,
    flags: usize,
) -> Result<(bool, bool), ParseError> {
    let saw_section = std::sync::atomic::AtomicBool::new(false);
    let lost_stock = std::sync::atomic::AtomicBool::new(false);
    let saw_section = &saw_section;
    let lost_stock = &lost_stock;
    let pool_threads = workers.min(nframes).max(1);
    let share = nframes.div_ceil(pool_threads);
    let mut failed: Option<ParseError> = None;
    std::thread::scope(|scope| {
        let mut guards = Vec::with_capacity(pool_threads);
        for worker in 0..pool_threads {
            let start_frame = worker * share;
            let end_frame = (start_frame + share).min(nframes);
            guards.push(scope.spawn(move || -> Result<(), ParseError> {
                crate::parser::pin_worker(worker);
                for frame in start_frame..end_frame {
                    let start = frame * span;
                    let (certified, saw) = fill_one_tiled_frame(
                        bytes,
                        start,
                        start + span,
                        head + start,
                        count,
                        frame * count,
                        spec,
                        block_lines,
                        rich,
                        positions,
                        ids,
                        flags,
                    )?;
                    if saw {
                        saw_section.store(true, std::sync::atomic::Ordering::Relaxed);
                    }
                    if !certified {
                        lost_stock.store(true, std::sync::atomic::Ordering::Relaxed);
                    }
                }
                Ok(())
            }));
        }
        for guard in guards {
            if let Err(err) = guard.join().expect("tiled frame parser panicked") {
                if failed.is_none() {
                    failed = Some(err);
                }
            }
        }
    });
    if let Some(err) = failed {
        return Err(err);
    }
    Ok((
        !lost_stock.load(std::sync::atomic::Ordering::Relaxed),
        saw_section.load(std::sync::atomic::Ordering::Relaxed),
    ))
}

#[cfg(feature = "parallel")]
fn fill_one_tiled_frame(
    bytes: &[u8],
    frame_start: usize,
    frame_end: usize,
    head: usize,
    count: usize,
    dest: usize,
    spec: u32,
    block_lines: usize,
    rich: bool,
    positions: usize,
    ids: usize,
    flags: usize,
) -> Result<(bool, bool), ParseError> {
    let mut pos = head;
    for row in 0..count {
        let ((row_xyz, fixed, atom_id), next) = parse_coord_row_at(bytes, pos, spec, row as u64)?;
        unsafe {
            std::ptr::copy_nonoverlapping(
                row_xyz.as_ptr(),
                (positions as *mut f64).add((dest + row) * 3),
                3,
            );
            if rich {
                *((ids as *mut u64).add(dest + row)) = atom_id;
                *((flags as *mut u8).add(dest + row)) = flag_bits(fixed);
            }
        }
        pos = next;
    }
    if pos < frame_start || pos > frame_end {
        return Err(ParseError::InvalidCount(
            "frame atom count does not match the first frame".into(),
        ));
    }
    let mut rel = pos - frame_start;
    skip_sections(&bytes[frame_start..frame_end], &mut rel, block_lines)
}

fn tiled_frame_count(bytes: &[u8], span: usize, head_end: usize) -> Option<usize> {
    if span < 16 || head_end == 0 || head_end > span {
        return None;
    }
    let n = bytes.len() / span;
    if n < 2 {
        return None;
    }
    // A trailing newline is not another frame. Requiring an exact multiple
    // sent every 32-atom trajectory through a second parse.
    let tail = &bytes[n * span..];
    if !tail.iter().all(u8::is_ascii_whitespace) {
        return None;
    }
    let header = &bytes[..head_end];
    for frame in 1..n {
        let start = frame * span;
        if bytes.get(start - 1) != Some(&b'\n') {
            return None;
        }
        if bytes.get(start..start + head_end) != Some(header) {
            return None;
        }
    }
    Some(n)
}

fn parse_one_frame(
    bytes: &[u8],
    pos: &mut usize,
    out: &mut ConPositions,
    rich: bool,
    store_rows: bool,
    workers: usize,
) -> Result<(usize, bool), ParseError> {
    out.wide_breaks.push(Vec::new());
    out.wide_chunks.push(Vec::new());
    skip_line(bytes, pos)?;
    let meta = read_line(bytes, pos)?;
    let spec = spec_version(meta)?;
    let mut stock = stock_meta_line(meta);
    let box_line = utf8_line(read_line(bytes, pos)?)?;
    let boxl = parse_line_of_n_f64(box_line, 3)?;
    let ang_line = utf8_line(read_line(bytes, pos)?)?;
    let angles = parse_line_of_n_f64(ang_line, 3)?;
    out.cells.extend_from_slice(&boxl);
    out.cells.extend_from_slice(&angles);
    skip_line(bytes, pos)?;
    skip_line(bytes, pos)?;
    let types_line = utf8_line(read_line(bytes, pos)?)?;
    let natm_types = parse_count_line(types_line, 1)?[0];
    if natm_types == 0 {
        zero_atom_tail(bytes, pos)?;
        // Every frame records where its rows would start, including a
        // frame with no atoms. The parallel fill indexes this by frame.
        out.head_ends.push(*pos);
        return Ok((0, stock));
    }
    let count_line = utf8_line(read_line(bytes, pos)?)?;
    let counts = parse_count_line(count_line, natm_types)?;
    if counts.contains(&0) {
        return Err(ParseError::InvalidCount(
            "each per-type count must be >= 1".into(),
        ));
    }
    let mass_line = utf8_line(read_line(bytes, pos)?)?;
    let masses = parse_line_of_n_f64(mass_line, natm_types)?;
    let mut n = 0usize;
    let mut head_end = *pos;
    if store_rows {
        let total: usize = counts.iter().sum();
        // One allocation for the whole frame. Growing by three floats at a
        // time copied the slab on every power of two, which is what made a
        // one-thread million-atom read slower than the plain walker.
        // The declared count is not a size: the unread bytes hold at most
        // one atom per `MIN_COORD_ROW_BYTES`, and the symbol and label
        // lines only make that bound smaller.
        let rest = bytes.len().saturating_sub(*pos);
        let fit = rest / crate::parser::MIN_COORD_ROW_BYTES;
        let reserve_atoms = total.min(fit);
        out.positions.reserve(reserve_atoms.saturating_mul(3));
        out.masses.reserve(reserve_atoms);
        if rich {
            out.ids.reserve(reserve_atoms);
            out.flags.reserve(reserve_atoms);
        }
    }
    for (count, mass) in counts.iter().zip(&masses) {
        let symbol_line = utf8_line(read_line(bytes, pos)?)?;
        let symbol: Arc<str> = Arc::from(symbol_line.trim());
        if rich {
            out.components.push((symbol, *count));
        }
        skip_line(bytes, pos)?;
        if n == 0 {
            head_end = *pos;
        }
        if store_rows {
            for atom in 0..*count {
                let (row, next) = parse_coord_row_at(bytes, *pos, spec, atom as u64)?;
                push_xyz(&mut out.positions, row.0);
                if rich {
                    out.ids.push(row.2);
                    out.flags.push(flag_bits(row.1));
                }
                out.masses.push(*mass);
                *pos = next;
                n += 1;
            }
        } else if counts.len() == 1 && *count >= 4096 && workers >= 2 {
            #[cfg(feature = "parallel")]
            {
                let (chunks, end) = crate::parser::plan_coord_chunks(
                    bytes,
                    *pos,
                    *count,
                    workers.saturating_mul(4),
                )?;
                // Positions-only reads drop this column. Filling it was a
                // second pass over a million atoms on the timed path.
                if rich {
                    let origin = out.masses.len();
                    let mut row_at = Vec::with_capacity(chunks.len());
                    let mut acc = origin;
                    for (_, nrows) in &chunks {
                        row_at.push(acc);
                        acc += *nrows;
                    }
                    out.masses.reserve(acc - origin);
                    let ptr = out.masses.as_mut_ptr() as usize;
                    let mass_value = *mass;
                    let nchunks = chunks.len();
                    if nchunks >= 2 {
                        crate::parser::on_pool(workers, || {
                            use rayon::prelude::*;
                            (0..nchunks).into_par_iter().for_each(|index| {
                                let start = row_at[index];
                                let rows = chunks[index].1;
                                for step in 0..rows {
                                    unsafe {
                                        *((ptr as *mut f64).add(start + step)) = mass_value;
                                    }
                                }
                            });
                        });
                        unsafe { out.masses.set_len(acc) };
                    } else {
                        out.masses.extend(std::iter::repeat_n(mass_value, *count));
                    }
                }
                *out.wide_chunks.last_mut().expect("frame chunks") = chunks;
                *pos = end;
                n += *count;
            }
            #[cfg(not(feature = "parallel"))]
            {
                skip_count_lines(bytes, pos, *count)?;
                out.masses.extend(std::iter::repeat_n(*mass, *count));
                n += *count;
            }
        } else {
            skip_count_lines(bytes, pos, *count)?;
            out.masses.extend(std::iter::repeat_n(*mass, *count));
            n += *count;
        }
    }
    let block_lines = n + natm_types * 2;
    let (certified, saw_section) = skip_sections(bytes, pos, block_lines)?;
    if !certified {
        stock = false;
    }
    out.has_section |= saw_section;
    out.head_ends.push(head_end);
    Ok((n, stock))
}

fn stock_meta_line(line: &[u8]) -> bool {
    let line = trim_ascii(line);
    if !line.starts_with(b"{") {
        return true;
    }
    line == STOCK_V2 || line == STOCK_V3
}

fn zero_atom_tail(bytes: &[u8], pos: &mut usize) -> Result<(), ParseError> {
    let bad = || {
        ParseError::InvalidCount("a zero-atom frame requires whitespace-only lines 8 and 9".into())
    };
    if *pos >= bytes.len() {
        return Ok(());
    }
    if !is_blank(read_line(bytes, pos)?) {
        return Err(bad());
    }
    if *pos >= bytes.len() {
        return Ok(());
    }
    if !is_blank(read_line(bytes, pos)?) {
        return Err(bad());
    }
    Ok(())
}

fn flag_bits(flags: [bool; 3]) -> u8 {
    u8::from(flags[0]) | (u8::from(flags[1]) << 1) | (u8::from(flags[2]) << 2)
}

/// `(certified, saw a section)`.
fn skip_sections(
    bytes: &[u8],
    pos: &mut usize,
    block_lines: usize,
) -> Result<(bool, bool), ParseError> {
    let mut saw = false;
    loop {
        if *pos >= bytes.len() {
            return Ok((true, saw));
        }
        let rest = &bytes[*pos..];
        let eol = memchr::memchr(b'\n', rest);
        let line = strip_cr(match eol {
            Some(i) => &rest[..i],
            None => rest,
        });
        if !is_blank(line) {
            return Ok((true, saw));
        }
        let after = eol.map(|i| *pos + i + 1).unwrap_or(bytes.len());
        if bytes[after..].iter().all(u8::is_ascii_whitespace) {
            *pos = bytes.len();
            return Ok((true, saw));
        }
        if !blank_opens_section(bytes, after)? {
            return Ok((true, saw));
        }
        let known = section_word_known(bytes, after)?;
        *pos = after;
        for _ in 0..block_lines {
            skip_line(bytes, pos)?;
        }
        saw = true;
        if !known {
            return Ok((false, saw));
        }
    }
}

fn section_word_known(bytes: &[u8], blank_end: usize) -> Result<bool, ParseError> {
    let after_symbol = next_line_pos(bytes, blank_end);
    let Some(label) = line_at(bytes, after_symbol) else {
        return Ok(false);
    };
    let text = utf8_line(label)?;
    let word = text.split_ascii_whitespace().next().unwrap_or("");
    Ok(matches!(
        word,
        "Velocities"
            | "Forces"
            | "Energies"
            | "Charges"
            | "Spins"
            | "Magmoms"
            | "Displacements"
            | "Spreads"
    ))
}

fn blank_opens_section(bytes: &[u8], blank_end: usize) -> Result<bool, ParseError> {
    let Some(line1) = line_at(bytes, blank_end) else {
        return Ok(false);
    };
    if is_blank(line1) {
        return Ok(false);
    }
    let text1 = utf8_line(line1)?;
    if text1.trim_start().starts_with('{') {
        return Ok(false);
    }
    let after1 = next_line_pos(bytes, blank_end);
    let Some(line2) = line_at(bytes, after1) else {
        return Ok(false);
    };
    Ok(line_has_component_label(utf8_line(line2)?))
}

fn spec_version(line: &[u8]) -> Result<u32, ParseError> {
    let line = trim_ascii(line);
    if !line.starts_with(b"{") {
        return Ok(1);
    }
    let key = b"\"con_spec_version\"";
    let Some(at) = find_slice(line, key) else {
        return Err(ParseError::MissingSpecVersion);
    };
    let mut i = at + key.len();
    while i < line.len() && matches!(line[i], b' ' | b'\t' | b':') {
        i += 1;
    }
    if i >= line.len() || !line[i].is_ascii_digit() {
        return Err(ParseError::InvalidMetadataJson(
            "con_spec_version must be an integer".into(),
        ));
    }
    let mut val: u32 = 0;
    while i < line.len() && line[i].is_ascii_digit() {
        let digit = u32::from(line[i] - b'0');
        val = val
            .checked_mul(10)
            .and_then(|v| v.checked_add(digit))
            .ok_or(ParseError::UnsupportedVersion(u32::MAX))?;
        i += 1;
    }
    if val == 0 || val > crate::CON_SPEC_VERSION {
        return Err(ParseError::UnsupportedVersion(val));
    }
    Ok(val)
}

fn utf8_line(line: &[u8]) -> Result<&str, ParseError> {
    std::str::from_utf8(line).map_err(|_| ParseError::ValidationError("invalid UTF-8".into()))
}

fn is_blank(line: &[u8]) -> bool {
    line.iter().all(|b| matches!(b, b' ' | b'\t'))
}

fn strip_cr(line: &[u8]) -> &[u8] {
    if line.last() == Some(&b'\r') {
        &line[..line.len() - 1]
    } else {
        line
    }
}

fn trim_ascii(line: &[u8]) -> &[u8] {
    let start = line
        .iter()
        .position(|b| !b.is_ascii_whitespace())
        .unwrap_or(line.len());
    let end = line
        .iter()
        .rposition(|b| !b.is_ascii_whitespace())
        .map(|i| i + 1)
        .unwrap_or(start);
    &line[start..end]
}

fn read_line<'a>(bytes: &'a [u8], pos: &mut usize) -> Result<&'a [u8], ParseError> {
    if *pos >= bytes.len() {
        return Err(ParseError::IncompleteFrame);
    }
    let rest = &bytes[*pos..];
    let (raw, advance) = match memchr::memchr(b'\n', rest) {
        Some(i) => (&rest[..i], i + 1),
        None => (rest, rest.len()),
    };
    *pos += advance;
    Ok(strip_cr(raw))
}

fn skip_line(bytes: &[u8], pos: &mut usize) -> Result<(), ParseError> {
    let _ = read_line(bytes, pos)?;
    Ok(())
}

fn skip_count_lines(bytes: &[u8], pos: &mut usize, n: usize) -> Result<(), ParseError> {
    let rest = &bytes[*pos..];
    let mut seen = 0usize;
    let mut at = 0usize;
    while seen < n {
        if at >= rest.len() {
            return Err(ParseError::IncompleteFrame);
        }
        match memchr::memchr(b'\n', &rest[at..]) {
            Some(hit) => {
                at += hit + 1;
                seen += 1;
            }
            None => {
                at = rest.len();
                seen += 1;
                if seen < n {
                    return Err(ParseError::IncompleteFrame);
                }
            }
        }
    }
    *pos += at;
    Ok(())
}

fn line_at(bytes: &[u8], pos: usize) -> Option<&[u8]> {
    if pos >= bytes.len() {
        return None;
    }
    let rest = &bytes[pos..];
    let raw = match memchr::memchr(b'\n', rest) {
        Some(i) => &rest[..i],
        None => rest,
    };
    Some(strip_cr(raw))
}

fn next_line_pos(bytes: &[u8], pos: usize) -> usize {
    let rest = &bytes[pos..];
    match memchr::memchr(b'\n', rest) {
        Some(i) => pos + i + 1,
        None => bytes.len(),
    }
}

fn find_slice(hay: &[u8], needle: &[u8]) -> Option<usize> {
    hay.windows(needle.len())
        .position(|window| window == needle)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::iterators::ConFrameIterator;
    use std::path::PathBuf;

    fn first_bit_mismatch(left: &[f64], right: &[f64]) -> Option<usize> {
        if left.len() != right.len() {
            return Some(left.len().min(right.len()));
        }
        left.iter()
            .zip(right)
            .position(|(a, b)| a.to_bits() != b.to_bits())
    }

    fn manifest(rel: &str) -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join(rel)
    }

    #[test]
    fn push_xyz_grows_a_short_reserve_and_keeps_the_bits() {
        for spare in [0usize, 1, 2] {
            let mut dst = Vec::with_capacity(spare);
            push_xyz(&mut dst, [1.0, -0.0, 0.5]);
            assert_eq!(dst.len(), 3);
            assert!(dst.capacity() >= 3);
            assert_eq!(dst[0].to_bits(), 1.0f64.to_bits());
            assert_eq!(dst[1].to_bits(), (-0.0f64).to_bits());
            assert_eq!(dst[2].to_bits(), 0.5f64.to_bits());
        }
        let mut exact = Vec::with_capacity(3);
        push_xyz(&mut exact, [1.0, 2.0, 3.0]);
        assert_eq!(exact, [1.0, 2.0, 3.0]);
    }

    fn coord_file(declared: usize, rows: &str) -> Vec<u8> {
        format!(
            "\n{{\"con_spec_version\":2}}\n10.0 10.0 10.0\n90.0 90.0 90.0\n0 0\n0 0\n1\n{declared}\n63.546\nCu\nCoordinates of Component 1\n{rows}"
        )
        .into_bytes()
    }

    #[test]
    fn a_lying_or_truncated_row_is_not_a_full_column() {
        let one = coord_file(1, "0.0 0.0 1.0 0 0\n");
        let got = positions_from_con_bytes(&one).unwrap();
        assert_eq!(got.positions, [0.0, 0.0, 1.0]);
        assert!(positions_from_con_bytes(&coord_file(100_000, "0.0 0.0 1.0 0 0\n")).is_err());
        assert!(positions_from_con_bytes(&coord_file(1, "0.0 0.")).is_err());
        assert!(positions_from_con_bytes(&coord_file(3, "")).is_err());
        let mut mismatch = coord_file(1, "0.0 0.0 1.0 0 0\n");
        mismatch.extend(coord_file(4, "1.0 2.0 3.0 0 1\n"));
        assert!(positions_from_con_bytes(&mismatch).is_err());
    }

    fn bits_match_iterator(rel: &str) {
        let bytes = std::fs::read(manifest(rel)).unwrap();
        let got = positions_from_con_bytes(&bytes).unwrap();
        let mut expected = Vec::new();
        let mut counts = Vec::new();
        for frame in ConFrameIterator::from_bytes(&bytes) {
            let frame = frame.unwrap();
            counts.push(frame.atom_data.len());
            for atom in &frame.atom_data {
                expected.extend_from_slice(&[atom.x(), atom.y(), atom.z()]);
            }
        }
        assert_eq!(got.counts, counts, "{rel}");
        assert_eq!(first_bit_mismatch(&got.positions, &expected), None, "{rel}");
        assert_eq!(got.spans.first().map(|span| span.start), Some(0), "{rel}");
        let tail = got.spans.last().map(|span| span.end).unwrap_or(0);
        assert!(
            bytes[tail..].iter().all(u8::is_ascii_whitespace),
            "{rel} left {} non-whitespace bytes",
            bytes.len() - tail
        );
    }

    #[cfg(feature = "parallel")]
    #[test]
    fn parallel_rows_match_the_serial_walker_on_a_wide_frame() {
        let n = 5000usize;
        let mut text = String::new();
        text.push_str(
            "grid\n{\"con_spec_version\":2}\n10.0 10.0 10.0\n90.0 90.0 90.0\n0 0\n0 0\n1\n",
        );
        text.push_str(&format!("{n}\n63.546\nCu\nCoordinates of Component 1\n"));
        for i in 0..n {
            text.push_str(&format!(" {i}.000000 0.250000 0.500000 0 {i}\n"));
        }
        let bytes = text.as_bytes();
        let serial = positions_with_identity(bytes).unwrap();
        let parallel = positions_parallel(bytes, 4, true).unwrap();
        assert_eq!(parallel.counts, serial.counts);
        assert_eq!(
            first_bit_mismatch(&parallel.positions, &serial.positions),
            None
        );
        assert_eq!(parallel.ids, serial.ids);
        assert_eq!(parallel.flags, serial.flags);
        assert_eq!(parallel.masses, serial.masses);
    }

    #[cfg(feature = "parallel")]
    #[test]
    fn tiled_small_frames_match_the_serial_walker() {
        let one = "\n{\"con_spec_version\":3,\"con_spec_minor\":1,\"units\":{\"length\":\"angstrom\",\"energy\":\"eV\"}}\n20.0 20.0 20.0\n90.0 90.0 90.0\n\n\n1\n4\n63.546\nCu\nCoordinates of Component 1\n00.0 0.25 0.5 0 0\n01.0 1.25 1.5 0 1\n02.0 2.25 2.5 0 2\n03.0 3.25 3.5 7 3\n";
        let mut text = String::new();
        for frame in 0..64u32 {
            text.push_str(&one.replace("00.0 0.25 0.5", &format!("{frame:02}.0 0.25 0.5")));
        }
        text.push('\n');
        let bytes = text.as_bytes();
        let serial = positions_from_con_bytes(bytes).unwrap();
        let parallel = positions_parallel(bytes, 8, false).unwrap();
        assert_eq!(parallel.n_frames, serial.n_frames);
        assert_eq!(parallel.counts, serial.counts);
        assert_eq!(
            first_bit_mismatch(&parallel.positions, &serial.positions),
            None
        );
        assert_eq!(parallel.masses, serial.masses);
        assert_eq!(parallel.cells, serial.cells);
        assert_eq!(parallel.stock, serial.stock);
        assert!(!parallel.has_section);
        let rich_serial = positions_with_identity(bytes).unwrap();
        let rich = positions_parallel(bytes, 4, true).unwrap();
        assert_eq!(rich.ids, rich_serial.ids);
        assert_eq!(rich.flags, rich_serial.flags);
        assert_eq!(first_bit_mismatch(&rich.positions, &rich_serial.positions), None);

        let mut typed = String::new();
        let two = "seed\n{\"con_spec_version\":2}\n10 10 10\n90 90 90\n0 0\n0 0 0\n2\n2 1\n63.546 1.0\nCu\nCoordinates of Component 1\n0.1 0.2 0.3 0 0\n0.4 0.5 0.6 0 1\nH\nCoordinates of Component 2\n0.7 0.8 0.9 7 2\n";
        for _ in 0..8 {
            typed.push_str(two);
        }
        let bytes = typed.as_bytes();
        let serial = positions_with_identity(bytes).unwrap();
        let parallel = positions_parallel(bytes, 4, true).unwrap();
        assert_eq!(parallel.counts, serial.counts);
        assert_eq!(
            first_bit_mismatch(&parallel.positions, &serial.positions),
            None
        );
        assert_eq!(parallel.ids, serial.ids);
        assert_eq!(parallel.flags, serial.flags);

        let real_path = manifest("bench/h2h/work/parallel-frames/frames-32x100000.con");
        if let Ok(real) = std::fs::read(&real_path) {
            let marker = b"\n{\"con_spec_version\":3";
            let second = real[1..]
                .windows(marker.len())
                .position(|window| window == marker)
                .map(|at| at + 1)
                .expect("second frame");
            let first = positions_from_con_bytes(&real[..second]).unwrap();
            assert_eq!(first.n_frames, 1);
            assert_eq!(
                tiled_frame_count(&real, first.spans[0].end, first.head_ends[0]),
                Some(100_000)
            );
            let parallel = positions_parallel(&real, 8, false).unwrap();
            let serial = positions_from_con_bytes(&real).unwrap();
            assert_eq!(parallel.n_frames, 100_000);
            assert_eq!(
                first_bit_mismatch(&parallel.positions, &serial.positions),
                None
            );
            assert_eq!(parallel.masses, serial.masses);
            assert_eq!(parallel.stock, serial.stock);
        }
    }

    #[cfg(feature = "parallel")]
    #[test]
    fn parallel_newlines_match_serial_rows_past_one_mib() {
        let n = 80_000usize;
        let mut text = String::new();
        text.push_str(
            "grid\n{\"con_spec_version\":2}\n100.0 100.0 100.0\n90.0 90.0 90.0\n0 0\n0 0\n1\n",
        );
        text.push_str(&format!("{n}\n63.546\nCu\nCoordinates of Component 1\n"));
        for i in 0..n {
            text.push_str(&format!("{i}.125000 1.250000 2.500000 0 {i}\n"));
        }
        assert!(text.len() > (1 << 20));
        let bytes = text.as_bytes();
        let serial = positions_with_identity(bytes).unwrap();
        let parallel = positions_parallel(bytes, 4, true).unwrap();
        assert_eq!(
            first_bit_mismatch(&parallel.positions, &serial.positions),
            None
        );
        assert_eq!(parallel.ids, serial.ids);
    }

    #[test]
    fn golden_con_and_convel_match_the_frame_parser() {
        for rel in [
            "resources/conformance/valid/v2_minimal.con",
            "resources/conformance/valid/v3_units.con",
            "resources/conformance/valid/empty_user_line.con",
            "resources/conformance/valid/empty_user_line_two.con",
            "resources/conformance/valid/zero_atom.con",
            "resources/conformance/valid/zero_atom_eof.con",
            "resources/conformance/valid/zero_atom_then_frame.con",
            "resources/conformance/valid/column4_spec1_all_fixed.con",
            "resources/conformance/valid/column4_spec2_xz.con",
            "resources/test/tiny_cuh2.con",
            "resources/test/tiny_cuh2.convel",
            "resources/test/tiny_multi_cuh2.con",
            "resources/test/tiny_multi_cuh2.convel",
            "resources/test/tiny_cuh2_vel_forces.con",
            "resources/test/cuh2.con",
        ] {
            bits_match_iterator(rel);
        }
    }

    #[cfg(feature = "parallel")]
    #[test]
    fn two_wide_frames_on_two_threads_keep_up_with_one_frame() {
        let n = 200_000usize;
        let mut one = String::from(
            "grid\n{\"con_spec_version\":2}\n10.0 10.0 10.0\n90.0 90.0 90.0\n0 0\n0 0\n1\n",
        );
        one.push_str(&format!("{n}\n63.546\nCu\nCoordinates of Component 1\n"));
        for i in 0..n {
            one.push_str(&format!("{i}.125000 0.250000 0.500000 0 {i}\n"));
        }
        let two = format!("{one}{one}");
        let serial = positions_parallel(one.as_bytes(), 1, false).unwrap();
        let parallel = positions_parallel(two.as_bytes(), 2, false).unwrap();
        assert_eq!(parallel.n_frames, 2);
        assert_eq!(parallel.counts, vec![n, n]);
        assert_eq!(
            first_bit_mismatch(&parallel.positions[..n * 3], &serial.positions),
            None
        );
        // llvm-cov and an unoptimized build stretch the parallel walk past
        // this ratio: the serial column walk is a few thread spawns shorter.
        // The samples still run so those lines stay in the coverage build.
        // The equality checks above still run. Release builds keep the ratio.
        let time = |bytes: &[u8], workers: usize| {
            let _ = positions_parallel(bytes, workers, false).unwrap();
            let mut samples = Vec::with_capacity(5);
            for _ in 0..5 {
                let started = std::time::Instant::now();
                let got = positions_parallel(bytes, workers, false).unwrap();
                std::hint::black_box(got.positions.len());
                samples.push(started.elapsed().as_secs_f64());
            }
            samples.sort_by(|left, right| left.partial_cmp(right).unwrap());
            samples[samples.len() / 2]
        };
        let one_s = time(one.as_bytes(), 1);
        let two_s = time(two.as_bytes(), 2);
        #[cfg(all(not(coverage), not(debug_assertions)))]
        assert!(
            two_s < one_s * 1.7,
            "two frames on two threads took {two_s:.4}s against one frame {one_s:.4}s"
        );
        #[cfg(any(coverage, debug_assertions))]
        let _ = (one_s, two_s);
    }

    #[cfg(feature = "parallel")]
    #[test]
    fn a_wide_parallel_fill_matches_the_serial_column_walk() {
        let n = 5000usize;
        let mut text = String::from(
            "grid\n{\"con_spec_version\":2}\n10.0 10.0 10.0\n90.0 90.0 90.0\n0 0\n0 0\n1\n",
        );
        text.push_str(&format!("{n}\n63.546\nCu\nCoordinates of Component 1\n"));
        for i in 0..n {
            text.push_str(&format!("{i}.125 0.25 0.5 0 {i}\n"));
        }
        let bytes = text.as_bytes();
        let serial = positions_from_con_bytes(bytes).unwrap();
        let parallel = positions_parallel(bytes, 8, false).unwrap();
        assert_eq!(parallel.counts, serial.counts);
        assert_eq!(
            first_bit_mismatch(&parallel.positions, &serial.positions),
            None
        );
        let covered: usize = parallel.wide_chunks[0]
            .iter()
            .map(|(_, nrows)| *nrows)
            .sum();
        assert_eq!(covered, n);
    }
}
