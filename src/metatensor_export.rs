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
    let layout =
        unsafe { std::ptr::read(&*block as *const TensorBlock as *const TensorBlockLayout) };
    debug_assert!(!layout.ptr.is_null());
    layout.ptr
}

/// Free an owned `mts_block_t*` transferred via [`tensor_block_into_raw_mts`].
/// Null-safe. Invokes metatensor-sys `mts_block_free` (C ABI destructor).
///
/// # Safety
///
/// `block` is null or a pointer produced by [`tensor_block_into_raw_mts`]
/// that has not been freed. `mts_block_free` frees that allocation. A
/// pointer from any other source, or a second free of the same pointer,
/// is undefined behavior.
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
        data.extend_from_slice(&[atom.x(), atom.y(), atom.z()]);
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
pub fn frame_velocities_block(frame: &ConFrame) -> Result<Option<TensorBlock>, metatensor::Error> {
    if !frame.has_velocities() {
        return Ok(None);
    }
    let n = frame.atom_data.len();
    let mut data = Vec::with_capacity(n * 3);
    for atom in &frame.atom_data {
        let [vx, vy, vz] = atom.velocity().unwrap_or([0.0; 3]);
        data.extend_from_slice(&[vx, vy, vz]);
    }
    let values = Array2::from_shape_vec((n, 3), data)
        .expect("array shape mismatch when building velocities block")
        .into_dyn();

    let samples = build_atom_id_samples(frame)?;
    let properties = build_xyz_properties()?;
    Ok(Some(TensorBlock::new(values, &samples, &[], &properties)?))
}

/// Builds a `TensorBlock` with shape `[N, 3]` carrying the per-atom
/// forces. Returns `Ok(None)` if the frame did not carry a forces
/// section.
pub fn frame_forces_block(frame: &ConFrame) -> Result<Option<TensorBlock>, metatensor::Error> {
    if !frame.has_forces() {
        return Ok(None);
    }
    let n = frame.atom_data.len();
    let mut data = Vec::with_capacity(n * 3);
    for atom in &frame.atom_data {
        let [fx, fy, fz] = atom.force().unwrap_or([0.0; 3]);
        data.extend_from_slice(&[fx, fy, fz]);
    }
    let values = Array2::from_shape_vec((n, 3), data)
        .expect("array shape mismatch when building forces block")
        .into_dyn();

    let samples = build_atom_id_samples(frame)?;
    let properties = build_xyz_properties()?;
    Ok(Some(TensorBlock::new(values, &samples, &[], &properties)?))
}

/// Builds a `TensorBlock` with shape `[N, 1]` carrying the per-atom
/// energy contributions. Returns `Ok(None)` if the frame did not carry
/// an energies section.
pub fn frame_energies_block(frame: &ConFrame) -> Result<Option<TensorBlock>, metatensor::Error> {
    if !frame.has_energies() {
        return Ok(None);
    }
    let n = frame.atom_data.len();
    let data: Vec<f64> = frame
        .atom_data
        .iter()
        .map(|a| a.energy().unwrap_or(0.0))
        .collect();
    let values = Array2::from_shape_vec((n, 1), data)
        .expect("array shape mismatch when building energies block")
        .into_dyn();

    let samples = build_atom_id_samples(frame)?;
    let mut props = LabelsBuilder::new(vec!["energy"]);
    props.add(&[0]);
    let properties = props.finish();
    Ok(Some(TensorBlock::new(values, &samples, &[], &properties)?))
}

/// Sample labels from the atoms' `atom_id`. metatensor labels are `i32`, so
/// an id above `i32::MAX` is an error rather than a wrapped label.
fn build_atom_id_samples(frame: &ConFrame) -> Result<Labels, metatensor::Error> {
    let mut builder = LabelsBuilder::new(vec!["atom_id"]);
    // Prefer atom_id; fall back to row index if ids are non-unique (metatensor
    // rejects duplicate sample rows).
    let mut seen = std::collections::HashSet::new();
    for (i, atom) in frame.atom_data.iter().enumerate() {
        let mut key = i32::try_from(atom.atom_id).map_err(|_| metatensor::Error {
            code: Some(mts_sys::MTS_INVALID_PARAMETER_ERROR),
            message: format!(
                "atom {i} has atom_id {}, which does not fit a metatensor i32 label",
                atom.atom_id
            ),
        })?;
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
    use metatensor::data::{DLDevice, DLPackVersion};

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
        builder.build().unwrap()
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
        let frame = builder.build().unwrap();
        assert!(frame_velocities_block(&frame).unwrap().is_none());
        assert!(frame_forces_block(&frame).unwrap().is_none());
        assert!(frame_energies_block(&frame).unwrap().is_none());
    }

    fn frame_with_ids(ids: [u64; 2]) -> crate::types::ConFrame {
        let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
        builder.add_atom("Cu", 0.1, 0.2, 0.3, [false, false, false], ids[0], 63.546);
        builder.add_atom("H", 1.1, 1.2, 1.3, [false, false, false], ids[1], 1.008);
        builder.build().unwrap()
    }

    fn sample_ids(block: &TensorBlock) -> Vec<i32> {
        block.samples().iter().map(|row| row[0].i32()).collect()
    }

    #[test]
    fn atom_id_above_i32_max_is_an_error_not_a_wrapped_label() {
        let frame = frame_with_ids([0, 1 << 32]);
        assert_eq!(frame.atom_data[1].atom_id, 1 << 32);
        let err = frame_positions_block(&frame).unwrap_err();
        assert_eq!(err.code, Some(mts_sys::MTS_INVALID_PARAMETER_ERROR));
        assert!(err.message.contains("4294967296"), "{}", err.message);
        let wide = frame_with_ids([0, i32::MAX as u64 + 1]);
        assert!(frame_positions_block(&wide).is_err());
    }

    #[test]
    fn atom_ids_up_to_i32_max_are_the_sample_labels() {
        let frame = frame_with_ids([7, i32::MAX as u64]);
        let block = frame_positions_block(&frame).unwrap();
        assert_eq!(sample_ids(&block), vec![7, i32::MAX]);
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

    fn parsed_frame() -> crate::types::ConFrame {
        let text = "\
PRE
{\"con_spec_version\":2,\"sections\":[\"velocities\",\"forces\",\"energies\"]}
10 10 10
90 90 90
0 0
0 0 0
1
2
1.0
H
Coordinates of Component 1
0.1 0.2 0.3 0 0
1.1 1.2 1.3 0 1

H
Velocities of Component 1
1.0 0.0 0.0 0 0
0.0 1.0 0.0 0 1

H
Forces of Component 1
0.5 0.0 0.0 0 0
0.0 0.5 0.0 0 1

H
Energies of Component 1
-0.42 0 0
0.13 0 1
";
        crate::iterators::ConFrameIterator::new(text)
            .next()
            .unwrap()
            .unwrap()
    }

    fn block_f64s(block: &TensorBlock) -> Vec<f64> {
        let tensor = block
            .values()
            .as_dlpack(DLDevice::cpu(), None, DLPackVersion::current())
            .unwrap();
        let len = tensor.shape().iter().product::<i64>() as usize;
        let data = tensor.data_ptr::<f64>().unwrap();
        unsafe { std::slice::from_raw_parts(data, len) }.to_vec()
    }

    fn all_blocks(frame: &crate::types::ConFrame) -> [TensorBlock; 4] {
        [
            frame_positions_block(frame).unwrap(),
            frame_velocities_block(frame).unwrap().unwrap(),
            frame_forces_block(frame).unwrap().unwrap(),
            frame_energies_block(frame).unwrap().unwrap(),
        ]
    }

    #[test]
    fn blocks_keep_their_values_when_the_atoms_change() {
        let mut frame = parsed_frame();
        let blocks = all_blocks(&frame);
        let before = blocks.each_ref().map(block_f64s);
        let atom = &mut frame.atom_data[0];
        atom.set_x(42.0);
        atom.set_y(43.0);
        atom.set_z(44.0);
        atom.set_velocity(Some([7.0; 3]));
        atom.set_force(Some([8.0; 3]));
        atom.set_energy(Some(9.0));
        assert_eq!(blocks.each_ref().map(block_f64s), before);
    }

    #[test]
    fn blocks_built_after_atom_writes_hold_the_atom_values() {
        let mut frame = parsed_frame();
        frame.atom_data[0].set_x(42.0);
        frame.atom_data[0].set_velocity(None);
        frame.atom_data[1].set_force(None);
        frame.atom_data[1].set_energy(Some(9.0));
        let [positions, velocities, forces, energies] = all_blocks(&frame).map(|b| block_f64s(&b));
        assert_eq!(positions, [42.0, 0.2, 0.3, 1.1, 1.2, 1.3]);
        assert_eq!(velocities, [0.0, 0.0, 0.0, 0.0, 1.0, 0.0]);
        assert_eq!(forces, [0.5, 0.0, 0.0, 0.0, 0.0, 0.0]);
        assert_eq!(energies, [-0.42, 9.0]);
    }

    // Under ThreadSanitizer this reports a data race if a block's values
    // share memory with the coordinates that `set_x` writes.
    #[test]
    fn reading_a_block_while_another_thread_moves_an_atom() {
        let mut frame = parsed_frame();
        let block = frame_positions_block(&frame).unwrap();
        let before = block_f64s(&block);
        std::thread::scope(|scope| {
            let reader = scope.spawn(|| {
                for _ in 0..1000 {
                    assert_eq!(block_f64s(&block), before);
                }
            });
            for step in 0..1000 {
                frame.atom_data[0].set_x(f64::from(step));
            }
            reader.join().unwrap();
        });
        assert_eq!(frame.atom_data[0].x(), 999.0);
        assert_eq!(block_f64s(&block), before);
    }
}
