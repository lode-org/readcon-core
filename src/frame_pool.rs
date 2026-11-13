//! Recycled position, id, and mass buffers for large coordinate frames.
//!
//! Only the reader calls these. They stay out of line so the writer does not
//! share the code.

use crate::storage_dtype::{Array1Storage, Array2Storage, ElementKind, FloatArray1, FloatArray2};
use crate::types::{ConFrame, FrameHeader};
use std::cell::RefCell;

/// Positions for this many atoms are big enough to be a fresh mapping.
pub(crate) const SOA_MIN: usize = 4096;

thread_local! {
    static POS: RefCell<Option<Vec<f64>>> = const { RefCell::new(None) };
    static MASS: RefCell<Option<Vec<f64>>> = const { RefCell::new(None) };
    static IDS: RefCell<Option<Vec<u64>>> = const { RefCell::new(None) };
}

#[inline(never)]
pub(crate) fn take_pos(n_atoms: usize) -> Vec<f64> {
    let n = n_atoms.saturating_mul(3);
    POS.with(|slot| take(slot, n))
}

#[inline(never)]
pub(crate) fn take_ids(n_atoms: usize) -> Vec<u64> {
    IDS.with(|slot| take(slot, n_atoms))
}

#[inline(never)]
pub(crate) fn fill_masses(header: &FrameHeader, n: usize) -> Vec<f64> {
    let mut mass = MASS.with(|slot| take(slot, n));
    mass.clear();
    let mut off = 0usize;
    for (ti, &count) in header.natms_per_type.iter().enumerate() {
        let m = header.masses_per_type.get(ti).copied().unwrap_or(0.0);
        let end = (off + count).min(n);
        if end > mass.len() {
            mass.resize(end, m);
        }
        off = end;
    }
    if mass.len() < n {
        mass.resize(n, 0.0);
    }
    mass
}

#[cold]
#[inline(never)]
pub(crate) fn recycle_large(frame: &mut ConFrame) {
    recycle_positions(std::mem::replace(
        &mut frame.positions,
        FloatArray2::zeros(ElementKind::Float64, 0, 3),
    ));
    recycle_masses(std::mem::replace(
        &mut frame.masses,
        FloatArray1::zeros(ElementKind::Float64, 0),
    ));
    recycle_ids(std::mem::replace(&mut frame.atom_ids, empty_ids()));
}

fn take<T>(slot: &RefCell<Option<Vec<T>>>, n: usize) -> Vec<T> {
    let mut slot = slot.borrow_mut();
    if let Some(mut buf) = slot.take() {
        if buf.capacity() >= n {
            buf.clear();
            return buf;
        }
    }
    Vec::with_capacity(n)
}

fn stash<T>(slot: &RefCell<Option<Vec<T>>>, buf: Vec<T>, min_cap: usize) {
    if buf.capacity() < min_cap {
        return;
    }
    let mut slot = slot.borrow_mut();
    if slot.is_none() {
        *slot = Some(buf);
    }
}

fn recycle_positions(arr: FloatArray2) {
    let Array2Storage::F64(arr) = arr else {
        return;
    };
    if !arr.is_unique() {
        return;
    }
    let (buf, _) = arr.into_owned().into_raw_vec_and_offset();
    POS.with(|slot| stash(slot, buf, SOA_MIN * 3));
}

fn recycle_masses(arr: FloatArray1) {
    let Array1Storage::F64(arr) = arr else {
        return;
    };
    if !arr.is_unique() {
        return;
    }
    let (buf, _) = arr.into_owned().into_raw_vec_and_offset();
    MASS.with(|slot| stash(slot, buf, SOA_MIN));
}

fn recycle_ids(arr: ndarray::ArcArray1<u64>) {
    if !arr.is_unique() {
        return;
    }
    let (buf, _) = arr.into_owned().into_raw_vec_and_offset();
    IDS.with(|slot| stash(slot, buf, SOA_MIN));
}

fn empty_ids() -> ndarray::ArcArray1<u64> {
    static EMPTY: std::sync::OnceLock<ndarray::ArcArray1<u64>> = std::sync::OnceLock::new();
    EMPTY
        .get_or_init(|| ndarray::Array1::from(Vec::<u64>::new()).into_shared())
        .clone()
}
