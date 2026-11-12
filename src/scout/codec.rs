//! Lossless corpus codecs.
//!
//! Whole-file zstd already sees a repeated CON header inside its window
//! (Collet, RFC 8878). A trained dictionary pays off when each frame is its
//! own message, which is the readcon-db record, and zstd's own guidance is
//! that dictionaries target similar records under about 100 KiB
//! (<https://github.com/facebook/zstd/blob/release/lib/zdict.h>).
//!
//! The shuffle codec is the HDF5 shuffle filter
//! (<https://docs.hdfgroup.org/documentation/hdf5/latest/group___d_c_p_l.html>,
//! `H5Pset_shuffle`): group byte lane `b` of every little-endian `f64`, then
//! compress. The decoded values are the parsed `f64` bits.

use std::io;

const SHUFFLE_MAGIC: &[u8; 8] = b"RCSHUF01";
const DICT_MAGIC: &[u8; 8] = b"RCDICT01";
const WHOLE_MAGIC: &[u8; 8] = b"RCZDCT01";
const VERSION: u32 = 1;

/// Byte-shuffle `src` into `dst`. Both lengths are multiples of `elem`.
pub fn shuffle(src: &[u8], dst: &mut [u8], elem: usize) {
    let n = src.len() / elem;
    for lane in 0..elem {
        let out = &mut dst[lane * n..(lane + 1) * n];
        for (i, slot) in out.iter_mut().enumerate() {
            *slot = src[i * elem + lane];
        }
    }
}

/// Inverse of [`shuffle`].
pub fn unshuffle(src: &[u8], dst: &mut [u8], elem: usize) {
    let n = src.len() / elem;
    for lane in 0..elem {
        let input = &src[lane * n..(lane + 1) * n];
        for (i, byte) in input.iter().enumerate() {
            dst[i * elem + lane] = *byte;
        }
    }
}

/// Shuffled little-endian `f64` positions, then zstd level `level`.
///
/// `cell` is six header numbers stored uncompressed so a consumer can keep
/// the box without a second file. It is not compressed with the coordinates.
pub fn encode_shuffled(
    positions: &[f64],
    n_frames: u64,
    n_atoms: u64,
    cell: [f64; 6],
    level: i32,
) -> io::Result<Vec<u8>> {
    if positions.len() as u64 != n_frames.saturating_mul(n_atoms).saturating_mul(3) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "position length does not match the frame shape",
        ));
    }
    let raw = f64_bytes(positions);
    let mut shuffled = vec![0u8; raw.len()];
    shuffle(&raw, &mut shuffled, 8);
    let compressed = zstd::bulk::compress(&shuffled, level)?;
    let mut out = Vec::with_capacity(64 + compressed.len());
    out.extend_from_slice(SHUFFLE_MAGIC);
    out.extend_from_slice(&VERSION.to_le_bytes());
    out.extend_from_slice(&n_frames.to_le_bytes());
    out.extend_from_slice(&n_atoms.to_le_bytes());
    out.extend_from_slice(&8u32.to_le_bytes());
    out.extend_from_slice(&level.to_le_bytes());
    out.extend_from_slice(&(raw.len() as u64).to_le_bytes());
    for value in cell {
        out.extend_from_slice(&value.to_le_bytes());
    }
    out.extend_from_slice(&(compressed.len() as u64).to_le_bytes());
    out.extend_from_slice(&compressed);
    Ok(out)
}

/// Decoded shuffled positions. The cell is the six stored header numbers.
pub fn decode_shuffled(bytes: &[u8]) -> io::Result<(Vec<f64>, u64, u64, [f64; 6])> {
    if bytes.len() < 8 + 4 + 8 + 8 + 4 + 4 + 8 + 48 + 8 {
        return Err(truncated());
    }
    if &bytes[0..8] != SHUFFLE_MAGIC {
        return Err(bad("shuffle magic"));
    }
    let version = u32::from_le_bytes(bytes[8..12].try_into().unwrap());
    if version != VERSION {
        return Err(bad("shuffle version"));
    }
    let n_frames = u64::from_le_bytes(bytes[12..20].try_into().unwrap());
    let n_atoms = u64::from_le_bytes(bytes[20..28].try_into().unwrap());
    let elem = u32::from_le_bytes(bytes[28..32].try_into().unwrap());
    if elem != 8 {
        return Err(bad("shuffle element"));
    }
    let raw_len = u64::from_le_bytes(bytes[36..44].try_into().unwrap()) as usize;
    let mut cell = [0.0; 6];
    for (i, slot) in cell.iter_mut().enumerate() {
        let at = 44 + i * 8;
        *slot = f64::from_le_bytes(bytes[at..at + 8].try_into().unwrap());
    }
    let comp_len = u64::from_le_bytes(bytes[92..100].try_into().unwrap()) as usize;
    let comp_at = 100;
    if bytes.len() < comp_at + comp_len {
        return Err(truncated());
    }
    let shuffled = zstd::bulk::decompress(&bytes[comp_at..comp_at + comp_len], raw_len)?;
    if shuffled.len() != raw_len {
        return Err(bad("shuffle length"));
    }
    let mut raw = vec![0u8; raw_len];
    unshuffle(&shuffled, &mut raw, 8);
    Ok((f64_from_bytes(&raw)?, n_frames, n_atoms, cell))
}

/// Train a dictionary on `samples` and compress each sample as its own frame.
///
/// `samples` are the CON frame spans. The dictionary is stored in the blob.
/// An empty sample list is an error.
pub fn encode_dict_frames(
    samples: &[&[u8]],
    level: i32,
    dict_size: usize,
    train_n: usize,
) -> io::Result<Vec<u8>> {
    if samples.is_empty() {
        return Err(bad("dictionary needs a sample"));
    }
    let n = train_n.clamp(1, samples.len());
    let dict = train_dict(&samples[..n], dict_size)?;
    let mut compressor = zstd::bulk::Compressor::with_dictionary(level, &dict)?;
    let mut payload = Vec::new();
    for sample in samples {
        let compressed = compressor.compress(sample)?;
        if sample.len() > u32::MAX as usize || compressed.len() > u32::MAX as usize {
            return Err(bad("frame does not fit in a u32 length"));
        }
        payload.extend_from_slice(&(sample.len() as u32).to_le_bytes());
        payload.extend_from_slice(&(compressed.len() as u32).to_le_bytes());
        payload.extend_from_slice(&compressed);
    }
    let mut out = Vec::with_capacity(24 + dict.len() + payload.len());
    out.extend_from_slice(DICT_MAGIC);
    out.extend_from_slice(&VERSION.to_le_bytes());
    out.extend_from_slice(&level.to_le_bytes());
    out.extend_from_slice(&(samples.len() as u64).to_le_bytes());
    out.extend_from_slice(&(dict.len() as u32).to_le_bytes());
    out.extend_from_slice(&dict);
    out.extend_from_slice(&payload);
    Ok(out)
}

/// Decompress per-frame dictionary records and concatenate them.
pub fn decode_dict_frames(bytes: &[u8]) -> io::Result<Vec<u8>> {
    let (dict, mut rest, n_frames) = split_dict_header(bytes, DICT_MAGIC)?;
    let mut decompressor = zstd::bulk::Decompressor::with_dictionary(&dict)?;
    let mut out = Vec::new();
    for _ in 0..n_frames {
        if rest.len() < 8 {
            return Err(truncated());
        }
        let raw_len = u32::from_le_bytes(rest[..4].try_into().unwrap()) as usize;
        let len = u32::from_le_bytes(rest[4..8].try_into().unwrap()) as usize;
        rest = &rest[8..];
        if rest.len() < len {
            return Err(truncated());
        }
        let piece = decompressor.decompress(&rest[..len], raw_len.max(1))?;
        if piece.len() != raw_len {
            return Err(bad("dict frame length"));
        }
        out.extend_from_slice(&piece);
        rest = &rest[len..];
    }
    Ok(out)
}

/// One zstd frame of `text`, using a dictionary trained on `samples`.
pub fn encode_dict_whole(
    text: &[u8],
    samples: &[&[u8]],
    level: i32,
    dict_size: usize,
    train_n: usize,
) -> io::Result<Vec<u8>> {
    if samples.is_empty() {
        return Err(bad("dictionary needs a sample"));
    }
    let n = train_n.clamp(1, samples.len());
    let dict = train_dict(&samples[..n], dict_size)?;
    let mut compressor = zstd::bulk::Compressor::with_dictionary(level, &dict)?;
    let compressed = compressor.compress(text)?;
    let mut out = Vec::with_capacity(28 + dict.len() + compressed.len());
    out.extend_from_slice(WHOLE_MAGIC);
    out.extend_from_slice(&VERSION.to_le_bytes());
    out.extend_from_slice(&level.to_le_bytes());
    out.extend_from_slice(&(dict.len() as u32).to_le_bytes());
    out.extend_from_slice(&dict);
    out.extend_from_slice(&(text.len() as u64).to_le_bytes());
    out.extend_from_slice(&(compressed.len() as u64).to_le_bytes());
    out.extend_from_slice(&compressed);
    Ok(out)
}

/// Inverse of [`encode_dict_whole`].
pub fn decode_dict_whole(bytes: &[u8]) -> io::Result<Vec<u8>> {
    if bytes.len() < 8 + 4 + 4 + 4 {
        return Err(truncated());
    }
    if &bytes[0..8] != WHOLE_MAGIC {
        return Err(bad("whole-dict magic"));
    }
    let dict_len = u32::from_le_bytes(bytes[16..20].try_into().unwrap()) as usize;
    let dict_at = 20;
    if bytes.len() < dict_at + dict_len + 8 {
        return Err(truncated());
    }
    let dict = &bytes[dict_at..dict_at + dict_len];
    let len_at = dict_at + dict_len;
    if bytes.len() < len_at + 16 {
        return Err(truncated());
    }
    let raw_len = u64::from_le_bytes(bytes[len_at..len_at + 8].try_into().unwrap()) as usize;
    let comp_len = u64::from_le_bytes(bytes[len_at + 8..len_at + 16].try_into().unwrap()) as usize;
    let comp_at = len_at + 16;
    if bytes.len() < comp_at + comp_len {
        return Err(truncated());
    }
    let mut decompressor = zstd::bulk::Decompressor::with_dictionary(dict)?;
    let text = decompressor.decompress(&bytes[comp_at..comp_at + comp_len], raw_len.max(1))?;
    if text.len() != raw_len {
        return Err(bad("dict whole length"));
    }
    Ok(text)
}

fn train_dict(samples: &[&[u8]], dict_size: usize) -> io::Result<Vec<u8>> {
    let mut data = Vec::new();
    let mut sizes = Vec::with_capacity(samples.len());
    for sample in samples {
        if sample.is_empty() {
            return Err(bad("empty dictionary sample"));
        }
        data.extend_from_slice(sample);
        sizes.push(sample.len());
    }
    zstd::dict::from_continuous(&data, &sizes, dict_size)
}

fn split_dict_header<'a>(bytes: &'a [u8], magic: &[u8; 8]) -> io::Result<(Vec<u8>, &'a [u8], u64)> {
    if bytes.len() < 8 + 4 + 4 + 8 + 4 {
        return Err(truncated());
    }
    if &bytes[0..8] != magic {
        return Err(bad("dict magic"));
    }
    let n_frames = u64::from_le_bytes(bytes[16..24].try_into().unwrap());
    let dict_len = u32::from_le_bytes(bytes[24..28].try_into().unwrap()) as usize;
    if bytes.len() < 28 + dict_len {
        return Err(truncated());
    }
    let dict = bytes[28..28 + dict_len].to_vec();
    Ok((dict, &bytes[28 + dict_len..], n_frames))
}

/// Whole-buffer zstd at `level`, the same level the CON writer uses by default.
pub fn compress_zstd(bytes: &[u8], level: i32) -> io::Result<Vec<u8>> {
    zstd::bulk::compress(bytes, level)
}

fn f64_bytes(values: &[f64]) -> Vec<u8> {
    let mut raw = Vec::with_capacity(values.len() * 8);
    for value in values {
        raw.extend_from_slice(&value.to_le_bytes());
    }
    raw
}

fn f64_from_bytes(raw: &[u8]) -> io::Result<Vec<f64>> {
    if raw.len() % 8 != 0 {
        return Err(bad("f64 width"));
    }
    let mut out = Vec::with_capacity(raw.len() / 8);
    for chunk in raw.chunks_exact(8) {
        out.push(f64::from_le_bytes(chunk.try_into().unwrap()));
    }
    Ok(out)
}

fn truncated() -> io::Error {
    io::Error::new(io::ErrorKind::UnexpectedEof, "truncated scout codec")
}

fn bad(message: &str) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, message)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn shuffle_roundtrip_keeps_bits() {
        let values = vec![
            0.0,
            -0.0,
            1.0,
            -2.5,
            1.0e-8,
            f64::from_bits(0x3ff0_0000_0000_0001),
        ];
        let raw = f64_bytes(&values);
        let mut shuffled = vec![0u8; raw.len()];
        shuffle(&raw, &mut shuffled, 8);
        let mut back = vec![0u8; raw.len()];
        unshuffle(&shuffled, &mut back, 8);
        assert_eq!(raw, back);
        let blob = encode_shuffled(&values, 1, 2, [4.0, 5.0, 6.0, 90.0, 90.0, 90.0], 3).unwrap();
        let (decoded, frames, atoms, cell) = decode_shuffled(&blob).unwrap();
        assert_eq!((frames, atoms), (1, 2));
        assert_eq!(cell[0].to_bits(), 4.0f64.to_bits());
        for (got, expect) in decoded.iter().zip(&values) {
            assert_eq!(got.to_bits(), expect.to_bits());
        }
    }

    #[test]
    fn dictionary_frames_and_whole_file_roundtrip() {
        let pattern = [
            &b"grid\n{\"con_spec_version\":2}\n1.0 0.0 0.0 0 0\n"[..],
            &b"grid\n{\"con_spec_version\":2}\n2.0 0.0 0.0 0 1\n"[..],
            &b"grid\n{\"con_spec_version\":2}\n3.0 0.0 0.0 0 2\n"[..],
            &b"grid\n{\"con_spec_version\":2}\n4.0 0.0 0.0 0 3\n"[..],
        ];
        let mut samples = Vec::new();
        for _ in 0..32 {
            samples.extend_from_slice(&pattern);
        }
        let blob = encode_dict_frames(&samples, 3, 256, samples.len()).unwrap();
        let text = decode_dict_frames(&blob).unwrap();
        let mut expect = Vec::new();
        for sample in &samples {
            expect.extend_from_slice(sample);
        }
        assert_eq!(text, expect);
        let whole = encode_dict_whole(&expect, &samples, 3, 256, samples.len()).unwrap();
        assert_eq!(decode_dict_whole(&whole).unwrap(), expect);
    }
}
