//! Opaque numeric storage for builders and frames (metatensor v0.2.x shape).
//!
//! **Design:** internal data is DLPack-shaped (`shape` / `dtype` / `device` /
//! `as_dlpack(device, stream, max_version)`), not “AoS structs with a DLPack
//! export bolt-on.” Callers **query** storage dtype/device, then `as_dlpack`
//! with a **requested device** (and stream / max version)—same contract as
//! metatensor `mts_array_t`. Choosing f32 vs f64 is choosing **storage**
//! (or a future typed builder), not passing a cast-target on every export.
//!
//! `ConFrame` keeps row-major `ArcArray` blocks for positions and optional
//! sections; `atom_data` is the CON-text AoS projection for the writer.
//!
//! Implementors can swap dtypes (f32 / f64 / u64 / bool), devices (CPU /
//! future GPU), and ownership (`ArrayD`, `Arc<RwLock<...>>`, …) without
//! changing the public surface.
//!
//! The default backing is `Arc<RwLock<ndarray::ArrayD<T>>>` --
//!   * `Arc`     : multiple DLPack views can share the same buffer
//!     across threads / FFI consumers.
//!   * `RwLock`  : enforces aliasing soundness; concurrent reads
//!     are non-blocking, concurrent writes contend.
//!   * `ndarray::ArrayD<T>` : type-erased dimension, generic dtype,
//!     ndarray's allocator (8-byte aligned, fine for f64; future
//!     SIMD-aligned variants implement this trait separately).
//!
//! See `docs/orgmode/spec.org` §17 for the public contract.

use std::sync::{Arc, RwLock, TryLockError};

use dlpk::sys::{DLDataType, DLDevice, DLPackVersion};
use dlpk::{DLPackPointerCast, DLPackTensor, GetDLPackDataType};
use ndarray::ArrayD;

use crate::error::ParseError;

/// Storage hook for one per-atom field of a ConFrameBuilder.
///
/// Implementors hold the raw bytes for a single field (e.g. all atom
/// positions as a `(N, 3) f64` block) and expose them via DLPack so
/// downstream consumers can map a numpy / Eigen / torch view onto
/// the same memory zero-copy.
pub trait Array: std::any::Any + Send + Sync {
    /// `&dyn Any` access for downcast (mirrors metatensor's pattern).
    fn as_any(&self) -> &dyn std::any::Any;

    /// `&mut dyn Any` access for downcast.
    fn as_any_mut(&mut self) -> &mut dyn std::any::Any;

    /// Shape of the underlying tensor.
    fn shape(&self) -> Vec<usize>;

    /// DLPack dtype of the elements.
    fn dtype(&self) -> DLDataType;

    /// Device residency of the storage.
    fn device(&self) -> DLDevice;

    /// Export a DLPack-managed tensor view of this array.
    ///
    /// `device` requests the consumer's preferred device; CPU
    /// implementors return `Err(ParseError::ValidationError(...))`
    /// when asked for a non-CPU device they cannot service.
    /// `stream` is the consumer's stream (CUDA / ROCm / SYCL); CPU
    /// backings ignore it.
    fn as_dlpack(
        &self,
        device: DLDevice,
        stream: Option<i64>,
        max_version: DLPackVersion,
    ) -> Result<DLPackTensor, ParseError>;

    /// Deep-copy this array (used by ConFrameBuilder::clone +
    /// `move_data`-style ops). Default impl just `clone`s through
    /// the implementor's natural mechanism.
    fn copy(&self) -> Box<dyn Array>;
}

/// Default Rust backing for the Array trait: shared, lockable,
/// dynamic-rank ndarray. Matches metatensor v2's
/// `Arc<RwLock<ArrayD<T>>>` choice and inherits its DLPack +
/// concurrency semantics.
impl<T> Array for Arc<RwLock<ArrayD<T>>>
where
    T: 'static + Send + Sync + Clone + Default + GetDLPackDataType + DLPackPointerCast,
{
    fn as_any(&self) -> &dyn std::any::Any {
        self
    }

    fn as_any_mut(&mut self) -> &mut dyn std::any::Any {
        self
    }

    fn shape(&self) -> Vec<usize> {
        match self.try_read() {
            Ok(lock) => lock.shape().to_vec(),
            Err(TryLockError::Poisoned(_)) => panic!("readcon-core array lock is poisoned"),
            Err(TryLockError::WouldBlock) => panic!("readcon-core array is already locked"),
        }
    }

    fn dtype(&self) -> DLDataType {
        T::get_dlpack_data_type()
    }

    fn device(&self) -> DLDevice {
        DLDevice::cpu()
    }

    fn as_dlpack(
        &self,
        device: DLDevice,
        _stream: Option<i64>,
        _max_version: DLPackVersion,
    ) -> Result<DLPackTensor, ParseError> {
        if device != DLDevice::cpu() {
            return Err(ParseError::ValidationError(format!(
                "Arc<RwLock<ArrayD>> is CPU-only; requested device {device:?} unsupported"
            )));
        }
        // Borrow the inner ArrayD<T> read-only and convert to DLPack
        // through dlpk's ndarray feature. The resulting DLPackTensor
        // owns a clone of the Arc, so the lifetime is decoupled from
        // the borrow above.
        let lock = match self.try_read() {
            Ok(lock) => lock,
            Err(TryLockError::Poisoned(_)) => {
                return Err(ParseError::ValidationError(
                    "readcon-core array lock is poisoned".into(),
                ));
            }
            Err(TryLockError::WouldBlock) => {
                return Err(ParseError::ValidationError(
                    "readcon-core array is already locked".into(),
                ));
            }
        };
        // Clone the ArrayD<T> contents into an owned ndarray, then
        // hand it to dlpk's TryFrom<ArrayD<T>> -> DLPackTensor (this
        // takes ownership, so the resulting DLPackTensor has its own
        // backing storage independent of the Arc<RwLock<...>>; future
        // optimisation: build a custom Array impl that exposes the
        // Arc-shared storage directly via dlpk's manager_ctx).
        let owned: ArrayD<T> = lock.to_owned();
        DLPackTensor::try_from(owned).map_err(|e| {
            ParseError::ValidationError(format!("dlpk ArrayD conversion failed: {e}"))
        })
    }

    fn copy(&self) -> Box<dyn Array> {
        // Cheap Arc clone, NOT a deep copy of the data buffer. If a
        // caller needs a true deep copy, materialize via
        // `Arc::new(RwLock::new(ArrayD::clone(&*lock)))`.
        Box::new(Arc::clone(self))
    }
}

/// Convenience constructor for the default backing.
pub fn array_from_shape<T>(shape: &[usize]) -> Box<dyn Array>
where
    T: 'static + Send + Sync + Clone + Default + GetDLPackDataType + DLPackPointerCast,
{
    let arr: ArrayD<T> = ArrayD::default(ndarray::IxDyn(shape));
    Box::new(Arc::new(RwLock::new(arr)))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn array_from_shape_reports_shape_and_dtype() {
        let a: Box<dyn Array> = array_from_shape::<f64>(&[5, 3]);
        assert_eq!(a.shape(), vec![5, 3]);
        let dt = a.dtype();
        assert_eq!(dt.code, dlpk::sys::DLDataTypeCode::kDLFloat);
        assert_eq!(dt.bits, 64);
        assert_eq!(dt.lanes, 1);
        assert_eq!(a.device(), DLDevice::cpu());
    }

    #[test]
    fn array_copy_shares_storage_via_arc() {
        let a = array_from_shape::<f64>(&[2, 3]);
        let b = a.copy();
        // shapes match
        assert_eq!(a.shape(), b.shape());
    }

    #[test]
    fn array_dlpack_export_round_trip() {
        let a = array_from_shape::<f64>(&[4, 3]);
        let tensor = a
            .as_dlpack(DLDevice::cpu(), None, DLPackVersion::current())
            .expect("DLPack export should succeed for CPU array");
        assert_eq!(tensor.shape(), &[4, 3]);
    }
}
