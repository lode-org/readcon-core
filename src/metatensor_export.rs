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

use crate::types::ConFrame;
use metatensor::{Labels, LabelsBuilder, TensorBlock};
use ndarray::Array2;

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
        .expect("array shape mismatch when building positions block");

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
        .expect("array shape mismatch when building velocities block");

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
        .expect("array shape mismatch when building forces block");

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
        .expect("array shape mismatch when building energies block");

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
    for atom in &frame.atom_data {
        builder.add(&[atom.atom_id as i32]);
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
