//! RCSO cooked SoA bytes for a caller-side `MPI_Bcast`.
//!
//! Layout matches readcon-db `cooked_soa` v1 (little-endian):
//! magic `RCSO`, version, natoms, flags, dtype, pad, reserved,
//! then positions, optional forces, optional velocities.
//!
//! This crate never calls `MPI_Init` or names WORLD. Rank 0 encodes;
//! the caller broadcasts; workers decode.

use crate::error::ParseError;
use crate::types::ConFrame;

/// Four-byte magic. Identical to readcon-db.
pub const RCSO_MAGIC: &[u8; 4] = b"RCSO";
/// Layout version 1.
pub const RCSO_VERSION: u32 = 1;
/// Positions/forces/velocities stored as f64.
pub const RCSO_DTYPE_F64: u8 = 0;
/// Bit 0: forces block present.
pub const RCSO_FLAG_FORCES: u32 = 1 << 0;
/// Bit 1: velocities block present.
pub const RCSO_FLAG_VELOCITIES: u32 = 1 << 1;

const HEADER_LEN: usize = 24;

/// Length-prefixed RCSO blobs for one collective (ADIOS BP5 grain: many frames).
pub const RCSB_MAGIC: &[u8; 4] = b"RCSB";
/// Batch envelope version 1.
pub const RCSB_VERSION: u32 = 1;

/// Decoded cooked numerics.
#[derive(Clone, Debug, PartialEq)]
pub struct Rcso {
    pub natoms: u32,
    pub positions: Vec<[f64; 3]>,
    pub forces: Option<Vec<[f64; 3]>>,
    pub velocities: Option<Vec<[f64; 3]>>,
}

fn err(msg: impl Into<String>) -> ParseError {
    ParseError::ValidationError(msg.into())
}

impl Rcso {
    /// Pack one parsed frame. CON text stays the authority.
    pub fn encode_frame(frame: &ConFrame) -> Result<Vec<u8>, ParseError> {
        let n = frame.atom_data.len();
        if n > u32::MAX as usize {
            return Err(err("too many atoms for RCSO"));
        }
        let natoms = n as u32;
        let has_f = frame.atom_data.iter().any(|a| a.force.is_some());
        let has_v = frame.atom_data.iter().any(|a| a.velocity.is_some());
        let mut flags = 0u32;
        if has_f {
            flags |= RCSO_FLAG_FORCES;
        }
        if has_v {
            flags |= RCSO_FLAG_VELOCITIES;
        }

        let mut out =
            Vec::with_capacity(HEADER_LEN + n * 3 * 8 * (1 + has_f as usize + has_v as usize));
        out.extend_from_slice(RCSO_MAGIC);
        out.extend_from_slice(&RCSO_VERSION.to_le_bytes());
        out.extend_from_slice(&natoms.to_le_bytes());
        out.extend_from_slice(&flags.to_le_bytes());
        out.push(RCSO_DTYPE_F64);
        out.extend_from_slice(&[0u8; 3]);
        out.extend_from_slice(&0u32.to_le_bytes());

        for a in &frame.atom_data {
            for c in [a.x, a.y, a.z] {
                out.extend_from_slice(&c.to_le_bytes());
            }
        }
        if has_f {
            for a in &frame.atom_data {
                let f = a.force.unwrap_or([0.0; 3]);
                for c in f {
                    out.extend_from_slice(&c.to_le_bytes());
                }
            }
        }
        if has_v {
            for a in &frame.atom_data {
                let v = a.velocity.unwrap_or([0.0; 3]);
                for c in v {
                    out.extend_from_slice(&c.to_le_bytes());
                }
            }
        }
        Ok(out)
    }

    /// Decode a v1 RCSO blob.
    pub fn decode(bytes: &[u8]) -> Result<Self, ParseError> {
        if bytes.len() < HEADER_LEN {
            return Err(err("RCSO truncated header"));
        }
        if &bytes[0..4] != RCSO_MAGIC {
            return Err(err("RCSO bad magic"));
        }
        let version = u32::from_le_bytes(bytes[4..8].try_into().unwrap());
        if version != RCSO_VERSION {
            return Err(err(format!("RCSO unsupported version {version}")));
        }
        let natoms = u32::from_le_bytes(bytes[8..12].try_into().unwrap());
        let flags = u32::from_le_bytes(bytes[12..16].try_into().unwrap());
        let dtype = bytes[16];
        if dtype != RCSO_DTYPE_F64 {
            return Err(err(format!("RCSO unsupported dtype {dtype}")));
        }
        let n = natoms as usize;
        let block = n.checked_mul(3).ok_or_else(|| err("RCSO overflow"))?;
        let block_bytes = block.checked_mul(8).ok_or_else(|| err("RCSO overflow"))?;
        let mut need = HEADER_LEN + block_bytes;
        let has_f = flags & RCSO_FLAG_FORCES != 0;
        let has_v = flags & RCSO_FLAG_VELOCITIES != 0;
        if has_f {
            need = need
                .checked_add(block_bytes)
                .ok_or_else(|| err("RCSO overflow"))?;
        }
        if has_v {
            need = need
                .checked_add(block_bytes)
                .ok_or_else(|| err("RCSO overflow"))?;
        }
        if bytes.len() < need {
            return Err(err("RCSO truncated body"));
        }

        let mut off = HEADER_LEN;
        let positions = read_vec3_block(&bytes[off..off + block_bytes], n)?;
        off += block_bytes;
        let forces = if has_f {
            let f = read_vec3_block(&bytes[off..off + block_bytes], n)?;
            off += block_bytes;
            Some(f)
        } else {
            None
        };
        let velocities = if has_v {
            Some(read_vec3_block(&bytes[off..off + block_bytes], n)?)
        } else {
            None
        };
        Ok(Self {
            natoms,
            positions,
            forces,
            velocities,
        })
    }
}

fn read_vec3_block(bytes: &[u8], n: usize) -> Result<Vec<[f64; 3]>, ParseError> {
    let mut out = Vec::with_capacity(n);
    for i in 0..n {
        let base = i * 24;
        let x = f64::from_le_bytes(bytes[base..base + 8].try_into().unwrap());
        let y = f64::from_le_bytes(bytes[base + 8..base + 16].try_into().unwrap());
        let z = f64::from_le_bytes(bytes[base + 16..base + 24].try_into().unwrap());
        out.push([x, y, z]);
    }
    Ok(out)
}

/// Pack many RCSO blobs into one RCSB envelope (one Bcast).
pub fn encode_batch(blobs: &[Vec<u8>]) -> Result<Vec<u8>, ParseError> {
    if blobs.len() > u32::MAX as usize {
        return Err(err("too many frames in RCSB batch"));
    }
    let mut out = Vec::new();
    out.extend_from_slice(RCSB_MAGIC);
    out.extend_from_slice(&RCSB_VERSION.to_le_bytes());
    out.extend_from_slice(&(blobs.len() as u32).to_le_bytes());
    for b in blobs {
        if b.len() > u32::MAX as usize {
            return Err(err("RCSO blob exceeds u32 length"));
        }
        out.extend_from_slice(&(b.len() as u32).to_le_bytes());
        out.extend_from_slice(b);
    }
    Ok(out)
}

/// Split an RCSB envelope into RCSO blobs.
pub fn decode_batch(bytes: &[u8]) -> Result<Vec<Vec<u8>>, ParseError> {
    if bytes.len() < 12 {
        return Err(err("RCSB truncated header"));
    }
    if &bytes[0..4] != RCSB_MAGIC {
        return Err(err("RCSB bad magic"));
    }
    let version = u32::from_le_bytes(bytes[4..8].try_into().unwrap());
    if version != RCSB_VERSION {
        return Err(err(format!("RCSB unsupported version {version}")));
    }
    let n = u32::from_le_bytes(bytes[8..12].try_into().unwrap()) as usize;
    let mut off = 12usize;
    let mut out = Vec::with_capacity(n);
    for _ in 0..n {
        if off + 4 > bytes.len() {
            return Err(err("RCSB truncated length"));
        }
        let ln = u32::from_le_bytes(bytes[off..off + 4].try_into().unwrap()) as usize;
        off += 4;
        if off + ln > bytes.len() {
            return Err(err("RCSB truncated blob"));
        }
        out.push(bytes[off..off + ln].to_vec());
        off += ln;
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::iterators::ConFrameIterator;

    fn first_frame(text: &str) -> ConFrame {
        ConFrameIterator::new(text)
            .next()
            .expect("frame")
            .expect("parse")
    }

    #[test]
    fn v2_minimal_roundtrip_positions() {
        let text = include_str!("../resources/conformance/valid/v2_minimal.con");
        let frame = first_frame(text);
        let blob = Rcso::encode_frame(&frame).unwrap();
        assert_eq!(&blob[0..4], b"RCSO");
        assert_eq!(u32::from_le_bytes(blob[4..8].try_into().unwrap()), 1);
        let got = Rcso::decode(&blob).unwrap();
        assert_eq!(got.natoms as usize, frame.atom_data.len());
        assert!(got.forces.is_none());
        assert!(got.velocities.is_none());
        for (a, p) in frame.atom_data.iter().zip(&got.positions) {
            assert_eq!([a.x, a.y, a.z], *p);
        }
    }

    #[test]
    fn forces_fixture_keeps_force_block() {
        let text = include_str!("../resources/test/tiny_cuh2_forces.con");
        let frame = first_frame(text);
        assert!(frame.atom_data.iter().any(|a| a.force.is_some()));
        let blob = Rcso::encode_frame(&frame).unwrap();
        let flags = u32::from_le_bytes(blob[12..16].try_into().unwrap());
        assert_ne!(flags & RCSO_FLAG_FORCES, 0);
        let got = Rcso::decode(&blob).unwrap();
        let forces = got.forces.expect("forces");
        for (a, f) in frame.atom_data.iter().zip(&forces) {
            assert_eq!(a.force.unwrap_or([0.0; 3]), *f);
        }
    }

    #[test]
    fn rejects_bad_magic() {
        assert!(Rcso::decode(b"NOPE").is_err());
    }

    #[test]
    fn rejects_truncated_and_bad_fields() {
        assert!(Rcso::decode(&[0u8; 8]).is_err());
        let frame = first_frame(include_str!(
            "../resources/conformance/valid/v2_minimal.con"
        ));
        let good = Rcso::encode_frame(&frame).unwrap();
        let mut ver = good.clone();
        ver[4..8].copy_from_slice(&2u32.to_le_bytes());
        assert!(Rcso::decode(&ver).is_err());
        let mut dt = good.clone();
        dt[16] = 1;
        assert!(Rcso::decode(&dt).is_err());
        assert!(Rcso::decode(&good[..20]).is_err());
        assert!(decode_batch(b"xxxx").is_err());
        assert!(decode_batch(b"RCSB\x02\x00\x00\x00\x00\x00\x00\x00").is_err());
    }

    #[test]
    fn velocities_fixture_keeps_velocity_block() {
        let text = include_str!("../resources/test/tiny_cuh2.convel");
        let frame = first_frame(text);
        assert!(frame.atom_data.iter().any(|a| a.velocity.is_some()));
        let blob = Rcso::encode_frame(&frame).unwrap();
        let flags = u32::from_le_bytes(blob[12..16].try_into().unwrap());
        assert_ne!(flags & RCSO_FLAG_VELOCITIES, 0);
        let got = Rcso::decode(&blob).unwrap();
        let vels = got.velocities.expect("velocities");
        for (a, v) in frame.atom_data.iter().zip(&vels) {
            assert_eq!(a.velocity.unwrap_or([0.0; 3]), *v);
        }
    }

    #[test]
    fn rcsb_batch_holds_two_blobs() {
        let text = include_str!("../resources/conformance/valid/v2_minimal.con");
        let frame = first_frame(text);
        let a = Rcso::encode_frame(&frame).unwrap();
        let b = a.clone();
        let batch = encode_batch(&[a.clone(), b.clone()]).unwrap();
        assert_eq!(&batch[0..4], b"RCSB");
        let parts = decode_batch(&batch).unwrap();
        assert_eq!(parts.len(), 2);
        assert_eq!(parts[0], a);
        assert_eq!(parts[1], b);
    }
}
