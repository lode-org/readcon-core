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
    static SMALL_POS: RefCell<Option<FloatArray2>> = const { RefCell::new(None) };
    static SMALL_MASS: RefCell<Option<FloatArray1>> = const { RefCell::new(None) };
    static SMALL_IDS: RefCell<Option<ndarray::ArcArray1<u64>>> = const { RefCell::new(None) };
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

/// Short-frame position matrix. The `Arc` is reused whole; peeling it back
/// to a `Vec` cost more than the allocation it saved.
#[inline]
pub(crate) fn take_small_positions(n_atoms: usize) -> FloatArray2 {
    SMALL_POS.with(|slot| {
        let cached = slot.borrow_mut().take();
        if let Some(arr) = cached
            && arr.nrows() == n_atoms
            && arr.ncols() == 3
            && arr.kind() == ElementKind::Float64
        {
            return arr;
        }
        FloatArray2::zeros(ElementKind::Float64, n_atoms, 3)
    })
}

#[inline]
pub(crate) fn take_small_ids(n_atoms: usize) -> ndarray::ArcArray1<u64> {
    SMALL_IDS.with(|slot| {
        let cached = slot.borrow_mut().take();
        if let Some(arr) = cached
            && arr.len() == n_atoms
        {
            return arr;
        }
        ndarray::Array1::zeros(n_atoms).into_shared()
    })
}

#[inline]
pub(crate) fn take_small_masses(header: &FrameHeader, n: usize) -> FloatArray1 {
    let mut mass = SMALL_MASS.with(|slot| {
        let cached = slot.borrow_mut().take();
        if let Some(arr) = cached
            && arr.len() == n
            && arr.kind() == ElementKind::Float64
        {
            return arr;
        }
        FloatArray1::zeros(ElementKind::Float64, n)
    });
    if let Some(slice) = mass.f64_slice_mut() {
        let mut off = 0usize;
        for (ti, &count) in header.natms_per_type.iter().enumerate() {
            let m = header.masses_per_type.get(ti).copied().unwrap_or(0.0);
            let end = (off + count).min(n);
            slice[off..end].fill(m);
            off = end;
        }
        if off < n {
            slice[off..].fill(0.0);
        }
    }
    mass
}

/// Drop the short-frame arrays. The large-frame pool stays for the thread.
#[inline(never)]
pub(crate) fn release_small() {
    SMALL_POS.with(|slot| {
        slot.borrow_mut().take();
    });
    SMALL_MASS.with(|slot| {
        slot.borrow_mut().take();
    });
    SMALL_IDS.with(|slot| {
        slot.borrow_mut().take();
    });
}

/// Return a short frame's arrays to the thread. Out of line so a writer that
/// drops a frame does not inline this.
#[inline(never)]
pub(crate) fn recycle_small(frame: &mut ConFrame) {
    let n = frame.atom_data.len();
    if n == 0 || n >= crate::types::ATOM_REUSE_MIN {
        return;
    }
    let positions = std::mem::replace(
        &mut frame.positions,
        FloatArray2::zeros(ElementKind::Float64, 0, 3),
    );
    if positions.kind() == ElementKind::Float64 && positions.ncols() == 3 && positions.nrows() == n
    {
        SMALL_POS.with(|slot| {
            let mut slot = slot.borrow_mut();
            if slot.is_none() {
                *slot = Some(positions);
            }
        });
    }
    let masses = std::mem::replace(
        &mut frame.masses,
        FloatArray1::zeros(ElementKind::Float64, 0),
    );
    if masses.kind() == ElementKind::Float64 && masses.len() == n {
        SMALL_MASS.with(|slot| {
            let mut slot = slot.borrow_mut();
            if slot.is_none() {
                *slot = Some(masses);
            }
        });
    }
    let ids = std::mem::replace(&mut frame.atom_ids, empty_ids());
    if ids.len() == n {
        SMALL_IDS.with(|slot| {
            let mut slot = slot.borrow_mut();
            if slot.is_none() {
                *slot = Some(ids);
            }
        });
    }
}

fn empty_ids() -> ndarray::ArcArray1<u64> {
    static EMPTY: std::sync::OnceLock<ndarray::ArcArray1<u64>> = std::sync::OnceLock::new();
    EMPTY
        .get_or_init(|| ndarray::Array1::from(Vec::<u64>::new()).into_shared())
        .clone()
}
