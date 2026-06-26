//! Export `ConFrame` data as metatensor `TensorBlock` instances.
//!
//! Available behind the `metatensor` Cargo feature. The block layout
//! mirrors the metatensor convention: rows are samples (one per atom),
//! and columns are properties (`x`, `y`, `z` for vector quantities or
//! a single column for scalars).
//!
//! Users that want a `TensorMap` keyed by species can build one on top
//! of these blocks; the choice of "per-species block" vs "single block
//! with `species` as a sample column" is user-specific, so we expose
//! the building blocks rather than baking in one convention.
//!
//! ## C ABI ownership (option A)
//!
//! High-level construction stays here. The **FFI boundary** uses only
//! metatensor-sys C types (`metatensor::c_api::mts_block_t`, i.e. the
//! same ABI as `metatensor.h`). Transfer is centralized in
//! [`tensor_block_into_raw_mts`] / [`mts_block_free_sys`] so callers never
//! ad-hoc transmute and never double-free with Rust `Drop`.

use crate::types::ConFrame;
use metatensor::c_api::{self as mts_sys, mts_block_t};
use metatensor::{Labels, LabelsBuilder, TensorBlock};
use ndarray::Array2;
use std::mem::ManuallyDrop;

/// Pin: `metatensor` 0.3.0-rc2 `TensorBlock` is `#[repr(transparent)]` over
/// `*mut mts_block_t` (see upstream `block/owned.rs`). No public `into_raw`
/// exists; this is the single supported ownership transfer for our C ABI.
///
/// After this returns, the pointer must be freed **only** with
/// [`mts_block_free_sys`] / `mts_block_free` (not by dropping a second
/// `TensorBlock` on the same pointer).
pub fn tensor_block_into_raw_mts(block: TensorBlock) -> *mut mts_block_t {
    // Layout mirror of metatensor::TensorBlock { ptr: *mut mts_block_t }
    #[repr(transparent)]
    struct TensorBlockLayout {
        ptr: *mut mts_block_t,
    }
    let block = ManuallyDrop::new(block);
    let layout = unsafe { std::ptr::read(&*block as *const TensorBlock as *const TensorBlockLayout) };
    debug_assert!(!layout.ptr.is_null());
    layout.ptr
}

/// Free an owned `mts_block_t*` transferred via [`tensor_block_into_raw_mts`].
/// Null-safe. Invokes metatensor-sys `mts_block_free` (C ABI destructor).
pub unsafe fn mts_block_free_sys(block: *mut mts_block_t) {
    if !block.is_null() {
        // Ignore status: best-effort free on the C boundary.
        let _ = unsafe { mts_sys::mts_block_free(block) };
    }
}

/// Builds a `TensorBlock` with shape `[N, 3]` carrying the per-atom
/// xyz coordinates from `frame`. Samples are labelled `atom_id` (the
/// post-grouping index from the file's column 5), properties are
/// labelled `xyz` with values `0`, `1`, `2`.
///
/// Returns the underlying metatensor error if the C library rejects
/// the labels or array shape.
pub fn frame_positions_block(frame: &ConFrame) -> Result<TensorBlock, metatensor::Error> {
    let n = frame.atom_data.len();
    let mut data = Vec::with_capacity(n * 3);
    for atom in &frame.atom_data {
        data.extend_from_slice(&[atom.x, atom.y, atom.z]);
    }
    let values = Array2::from_shape_vec((n, 3), data)
        .expect("array shape mismatch when building positions block")
        .into_dyn();

    let samples = build_atom_id_samples(frame)?;
    let properties = build_xyz_properties()?;
    TensorBlock::new(values, &samples, &[], &properties)
}

/// Builds a `TensorBlock` with shape `[N, 3]` carrying the per-atom
/// velocity vectors. Returns `Ok(None)` when the frame has no velocity
/// data; users should not assume the block exists for every frame.
pub fn frame_velocities_block(
    frame: &ConFrame,
) -> Result<Option<TensorBlock>, metatensor::Error> {
    if !frame.has_velocities() {
        return Ok(None);
    }
    let n = frame.atom_data.len();
    let mut data = Vec::with_capacity(n * 3);
    for atom in &frame.atom_data {
        let [vx, vy, vz] = atom.velocity.unwrap_or([0.0; 3]);
        data.extend_from_slice(&[vx, vy, vz]);
    }
    let values = Array2::from_shape_vec((n, 3), data)
        .expect("array shape mismatch when building velocities block")
        .into_dyn();

    let samples = build_atom_id_samples(frame)?;
    let properties = build_xyz_properties()?;
    Ok(Some(TensorBlock::new(
        values,
        &samples,
        &[],
        &properties,
    )?))
}

/// Builds a `TensorBlock` with shape `[N, 3]` carrying the per-atom
/// forces. Returns `Ok(None)` if the frame did not carry a forces
/// section.
pub fn frame_forces_block(
    frame: &ConFrame,
) -> Result<Option<TensorBlock>, metatensor::Error> {
    if !frame.has_forces() {
        return Ok(None);
    }
    let n = frame.atom_data.len();
    let mut data = Vec::with_capacity(n * 3);
    for atom in &frame.atom_data {
        let [fx, fy, fz] = atom.force.unwrap_or([0.0; 3]);
        data.extend_from_slice(&[fx, fy, fz]);
    }
    let values = Array2::from_shape_vec((n, 3), data)
        .expect("array shape mismatch when building forces block")
        .into_dyn();

    let samples = build_atom_id_samples(frame)?;
    let properties = build_xyz_properties()?;
    Ok(Some(TensorBlock::new(
        values,
        &samples,
        &[],
        &properties,
    )?))
}

/// Builds a `TensorBlock` with shape `[N, 1]` carrying the per-atom
/// energy contributions. Returns `Ok(None)` if the frame did not carry
/// an energies section.
pub fn frame_energies_block(
    frame: &ConFrame,
) -> Result<Option<TensorBlock>, metatensor::Error> {
    if !frame.has_energies() {
        return Ok(None);
    }
    let n = frame.atom_data.len();
    let data: Vec<f64> = frame
        .atom_data
        .iter()
        .map(|a| a.energy.unwrap_or(0.0))
        .collect();
    let values = Array2::from_shape_vec((n, 1), data)
        .expect("array shape mismatch when building energies block")
        .into_dyn();

    let samples = build_atom_id_samples(frame)?;
    let mut props = LabelsBuilder::new(vec!["energy"]);
    props.add(&[0]);
    let properties = props.finish();
    Ok(Some(TensorBlock::new(
        values,
        &samples,
        &[],
        &properties,
    )?))
}

fn build_atom_id_samples(frame: &ConFrame) -> Result<Labels, metatensor::Error> {
    let mut builder = LabelsBuilder::new(vec!["atom_id"]);
    // Prefer atom_id; fall back to row index if ids are non-unique (metatensor
    // rejects duplicate sample rows).
    let mut seen = std::collections::HashSet::new();
    for (i, atom) in frame.atom_data.iter().enumerate() {
        let mut key = atom.atom_id as i32;
        if !seen.insert(key) {
            key = i as i32;
            while !seen.insert(key) {
                key = key.wrapping_add(1);
            }
        }
        builder.add(&[key]);
    }
    Ok(builder.finish())
}

fn build_xyz_properties() -> Result<Labels, metatensor::Error> {
    let mut builder = LabelsBuilder::new(vec!["xyz"]);
    for axis in 0..3 {
        builder.add(&[axis]);
    }
    Ok(builder.finish())
}

impl ConFrame {
    /// Convenience: build the positions [`TensorBlock`] for this frame.
    /// See [`frame_positions_block`] for the column / sample
    /// conventions.
    pub fn to_metatensor_positions_block(&self) -> Result<TensorBlock, metatensor::Error> {
        frame_positions_block(self)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::ConFrameBuilder;

    fn small_frame() -> crate::types::ConFrame {
        let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
        builder
            .add_atom("Cu", 0.1, 0.2, 0.3, [false, false, false], 0, 63.546)
            .with_velocity([1.0, 0.0, 0.0])
            .with_force([0.5, 0.0, 0.0])
            .with_energy(-0.42);
        builder
            .add_atom("H", 1.1, 1.2, 1.3, [false, false, false], 1, 1.008)
            .with_velocity([0.0, 1.0, 0.0])
            .with_force([0.0, 0.5, 0.0])
            .with_energy(0.13);
        builder.build()
    }

    #[test]
    fn positions_block_has_expected_shape_and_samples() {
        let frame = small_frame();
        let block = frame.to_metatensor_positions_block().unwrap();
        let values = block.values();
        let array_lock = values.as_ndarray_lock::<f64>();
        let array = array_lock.read().expect("positions array lock");
        assert_eq!(array.shape(), &[2, 3]);
        let samples = block.samples();
        assert_eq!(samples.count(), 2); // 2 atoms
        let properties = block.properties();
        assert_eq!(properties.count(), 3); // x, y, z columns
    }

    #[test]
    fn velocities_forces_energies_present_when_data_present() {
        let frame = small_frame();
        assert!(frame_velocities_block(&frame).unwrap().is_some());
        assert!(frame_forces_block(&frame).unwrap().is_some());
        assert!(frame_energies_block(&frame).unwrap().is_some());
    }

    #[test]
    fn velocities_block_is_none_when_data_absent() {
        let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
        builder.add_atom("Cu", 0.1, 0.2, 0.3, [false, false, false], 0, 63.546);
        let frame = builder.build();
        assert!(frame_velocities_block(&frame).unwrap().is_none());
        assert!(frame_forces_block(&frame).unwrap().is_none());
        assert!(frame_energies_block(&frame).unwrap().is_none());
    }

    #[test]
    fn tensor_block_into_raw_mts_round_trip_free_via_sys() {
        let frame = small_frame();
        let block = frame_positions_block(&frame).unwrap();
        let ptr = tensor_block_into_raw_mts(block);
        assert!(!ptr.is_null());
        // Inspect via sys C API (same as consumers of metatensor.h)
        let mut array = unsafe { std::mem::zeroed::<mts_sys::mts_array_t>() };
        assert_eq!(
            unsafe { mts_sys::mts_block_data(ptr, &mut array) },
            mts_sys::MTS_SUCCESS
        );
        unsafe { mts_block_free_sys(ptr) };
    }
}
