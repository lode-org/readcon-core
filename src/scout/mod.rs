//! Opt-in prototypes for trajectory reads and corpus storage.
//!
//! Nothing here replaces the CON reader. Lossless column scans and the
//! byte-shuffle codec keep parsed `f64` bits. The low-rank fit is lossy,
//! takes an explicit absolute bound, and is never called by the reader.

mod codec;
mod column;
mod floats;
mod lowrank;

pub use codec::{
    compress_zstd, decode_dict_frames, decode_dict_whole, decode_shuffled, encode_dict_frames,
    encode_dict_whole, encode_shuffled,
};
pub use column::{ConPositions, positions_from_con_bytes, positions_from_extxyz_bytes};
pub use floats::{FloatReport, bench_float_kernels};
pub use lowrank::{Fit, decode_lowrank, fit_positions};
