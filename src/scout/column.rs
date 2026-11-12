//! Re-export of the always-on column walker. The implementation lives in
//! `crate::columns` so the read path does not depend on the `scout` feature.

pub use crate::columns::{ConPositions, positions_from_con_bytes, positions_from_extxyz_bytes};
