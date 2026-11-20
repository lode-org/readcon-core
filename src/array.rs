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

use std::sync::{Arc, RwLock, RwLockReadGuard, TryLockError};

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

/// Manager context of a DLPack tensor over an `Arc<RwLock<ArrayD<T>>>`:
/// the buffer stays read-locked, so no writer can change or move it, until
/// the tensor is deleted.
struct ReadLockedArray<T: 'static> {
    // Declared before `_array` so it unlocks before the Arc that owns the
    // lock is released.
    _guard: RwLockReadGuard<'static, ArrayD<T>>,
    _array: Arc<RwLock<ArrayD<T>>>,
    shape: Vec<i64>,
    strides: Vec<i64>,
}

unsafe extern "C" fn read_locked_deleter<T: 'static>(
    managed: *mut dlpk::sys::DLManagedTensorVersioned,
) {
    if managed.is_null() {
        return;
    }
    // `DLPackTensor::from_raw` frees `managed` itself; only the context is ours.
    unsafe {
        let ctx = (*managed).manager_ctx;
        if !ctx.is_null() {
            drop(Box::from_raw(ctx.cast::<ReadLockedArray<T>>()));
            (*managed).manager_ctx = std::ptr::null_mut();
        }
    }
}

/// Default Rust backing for the Array trait: shared, lockable,
/// dynamic-rank ndarray. Matches metatensor v2's
/// `Arc<RwLock<ArrayD<T>>>` choice and inherits its DLPack +
/// concurrency semantics.
///
/// `as_dlpack` shares the buffer and holds a read lock until the tensor is
/// deleted: other exports and reads proceed, `try_write` fails and `write`
/// blocks meanwhile. A `write` on a thread that still holds a live tensor
/// therefore never returns. Once a writer is waiting, std's `RwLock` lets no
/// new reader in, so `as_dlpack` returns an error until that writer is done.
/// Delete each tensor exactly once: the deleter frees the tensor, so a second
/// call is a use-after-free. Like dlpk's own lock-holding tensors, a tensor
/// handed through C must be deleted on a thread where releasing a std
/// `RwLock` read lock is allowed; std's futex and queue locks allow any
/// thread.
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
        let array = Arc::clone(self);
        let guard = match array.try_read() {
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
        // SAFETY: the guard borrows the RwLock inside the Arc allocation,
        // which `_array` keeps alive and in place; `ReadLockedArray` drops
        // the guard before `_array`.
        let guard: RwLockReadGuard<'static, ArrayD<T>> = unsafe { std::mem::transmute(guard) };
        let data = guard.as_ptr() as *mut std::ffi::c_void;
        let mut ctx = Box::new(ReadLockedArray {
            shape: guard.shape().iter().map(|&d| d as i64).collect(),
            strides: guard.strides().iter().map(|&s| s as i64).collect(),
            _guard: guard,
            _array: array,
        });
        let dl_tensor = dlpk::sys::DLTensor {
            data,
            device: DLDevice::cpu(),
            ndim: ctx.shape.len() as i32,
            dtype: T::get_dlpack_data_type(),
            shape: ctx.shape.as_mut_ptr(),
            strides: ctx.strides.as_mut_ptr(),
            byte_offset: 0,
        };
        let managed = dlpk::sys::DLManagedTensorVersioned {
            version: DLPackVersion::current(),
            manager_ctx: Box::into_raw(ctx).cast(),
            deleter: Some(read_locked_deleter::<T>),
            flags: dlpk::sys::DLPACK_FLAG_BITMASK_READ_ONLY,
            dl_tensor,
        };
        // SAFETY: `managed` points at a live buffer and shape/stride arrays
        // owned by its context, which the deleter frees.
        Ok(unsafe { DLPackTensor::from_raw(managed) })
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

/// Allocate a new zeroed array **on** `device`.
///
/// Default builds only allocate on CPU. Non-CPU allocation fails with a clear
/// error (not silent reinterpret as CPU). Callers that already own device
/// memory should use [`array_from_host_f64_on_device`] / [`from_dlpack_f64`] to
/// **preserve** device identity without allocating on the GPU in this process.
pub fn allocate_array_on_device(
    shape: &[usize],
    device: DLDevice,
) -> Result<Box<dyn Array>, ParseError> {
    if device == DLDevice::cpu() {
        return Ok(array_from_shape::<f64>(shape));
    }
    #[cfg(feature = "cuda")]
    {
        use dlpk::sys::DLDeviceType;
        if device.device_type == DLDeviceType::kDLCUDA {
            return crate::cuda_array::allocate_cuda_f64(shape, device.device_id);
        }
    }
    Err(ParseError::ValidationError(format!(
        "no device allocator in this build for {device:?}; use caller-supplied device buffers via from_dlpack / array_from_host_f64_on_device, or build with `--features cuda` for CUDA devices"
    )))
}

/// Host-resident `f64` buffer tagged with a DLPack `device` (CPU or non-CPU).
///
/// Used for **device-preserving interchange**: callers (or tests) supply
/// buffers that logically live on CUDA/ROCm/etc. without requiring a CUDA
/// driver in the default build. [`Array::device`] and matching
/// [`Array::as_dlpack`] requests preserve the tag; mismatched device requests
/// fail without `--features cuda`; with that feature, CUDA allocate uses real
/// device memory (see [`crate::cuda_array`]).
pub struct DeviceTaggedF64Array {
    shape: Vec<usize>,
    device: DLDevice,
    /// Row-major elements (host-visible for contract tests / zero-copy tag).
    data: Arc<Vec<f64>>,
}

impl DeviceTaggedF64Array {
    /// Build from host `f64` values with an explicit DLPack device tag.
    pub fn new(shape: &[usize], data: Vec<f64>, device: DLDevice) -> Result<Self, ParseError> {
        let n: usize = shape.iter().product();
        if data.len() != n {
            return Err(ParseError::ValidationError(format!(
                "device-tagged array: expected {n} f64 values for shape {shape:?}, got {}",
                data.len()
            )));
        }
        Ok(Self {
            shape: shape.to_vec(),
            device,
            data: Arc::new(data),
        })
    }
}

/// Install a device-tagged f64 array (caller-supplied buffer / logical device).
pub fn array_from_host_f64_on_device(
    shape: &[usize],
    data: Vec<f64>,
    device: DLDevice,
) -> Result<Box<dyn Array>, ParseError> {
    Ok(Box::new(DeviceTaggedF64Array::new(shape, data, device)?))
}

/// Ingest from a DLPack tensor: preserve `tensor.device()` and copy f64 host
/// elements when the tensor is CPU-addressable; for non-CPU tensors in this
/// build we still preserve the **device tag** using host staging only when the
/// tensor reports f64 data that is readable (host tests tag CUDA with host
/// bytes). Pure allocate-on-GPU without a backend is [`allocate_array_on_device`].
pub fn from_dlpack_f64(tensor: &DLPackTensor) -> Result<Box<dyn Array>, ParseError> {
    let device = tensor.device();
    let shape: Vec<usize> = tensor.shape().iter().map(|&d| d as usize).collect();
    let n: usize = shape.iter().product();
    let dtype = tensor.dtype();
    if dtype.code != dlpk::sys::DLDataTypeCode::kDLFloat || dtype.bits != 64 {
        return Err(ParseError::ValidationError(format!(
            "from_dlpack_f64: expected f64, got dtype code={:?} bits={}",
            dtype.code, dtype.bits
        )));
    }
    // Read elements via data pointer (host-backed tensors and host-staged
    // device-tagged tests). Non-readable device memory would fail here.
    let ptr = tensor
        .data_ptr::<f64>()
        .map_err(|e| ParseError::ValidationError(format!("from_dlpack_f64 data_ptr: {e}")))?;
    let mut data = vec![0.0f64; n];
    if n > 0 {
        unsafe {
            std::ptr::copy_nonoverlapping(ptr, data.as_mut_ptr(), n);
        }
    }
    array_from_host_f64_on_device(&shape, data, device)
}

struct DeviceTaggedManager {
    data: Arc<Vec<f64>>,
    shape: Vec<i64>,
}

unsafe extern "C" fn device_tagged_deleter(managed: *mut dlpk::sys::DLManagedTensorVersioned) {
    if managed.is_null() {
        return;
    }
    // Only free our manager_ctx. When constructed via `DLPackTensor::from_raw`,
    // the outer dlpk deleter restores `manager_ctx`/`deleter` then calls us and
    // finally frees the managed tensor allocation — we must not free `managed`.
    unsafe {
        let ctx = (*managed).manager_ctx;
        if !ctx.is_null() {
            let _ = Box::from_raw(ctx as *mut DeviceTaggedManager);
            (*managed).manager_ctx = std::ptr::null_mut();
        }
    }
}

impl Array for DeviceTaggedF64Array {
    fn as_any(&self) -> &dyn std::any::Any {
        self
    }

    fn as_any_mut(&mut self) -> &mut dyn std::any::Any {
        self
    }

    fn shape(&self) -> Vec<usize> {
        self.shape.clone()
    }

    fn dtype(&self) -> DLDataType {
        f64::get_dlpack_data_type()
    }

    fn device(&self) -> DLDevice {
        self.device
    }

    fn as_dlpack(
        &self,
        device: DLDevice,
        _stream: Option<i64>,
        _max_version: DLPackVersion,
    ) -> Result<DLPackTensor, ParseError> {
        if device != self.device {
            return Err(ParseError::ValidationError(format!(
                "device mismatch: array is on {:?}, requested {:?}",
                self.device, device
            )));
        }
        // Build a managed tensor that reports `self.device` while holding an
        // Arc to host-resident f64 storage (device-tag preserving interchange
        // without a CUDA allocator in the default build).
        let manager = Box::new(DeviceTaggedManager {
            data: Arc::clone(&self.data),
            shape: self.shape.iter().map(|&d| d as i64).collect(),
        });
        let data_ptr = manager.data.as_ptr() as *mut std::ffi::c_void;
        let shape_ptr = manager.shape.as_ptr() as *mut i64;
        let mut managed = dlpk::sys::DLManagedTensorVersioned {
            version: dlpk::sys::DLPackVersion {
                major: dlpk::sys::DLPACK_MAJOR_VERSION,
                minor: dlpk::sys::DLPACK_MINOR_VERSION,
            },
            manager_ctx: std::ptr::null_mut(),
            deleter: Some(device_tagged_deleter),
            dl_tensor: dlpk::sys::DLTensor {
                data: data_ptr,
                device: self.device,
                ndim: self.shape.len() as i32,
                dtype: f64::get_dlpack_data_type(),
                shape: shape_ptr,
                strides: std::ptr::null_mut(),
                byte_offset: 0,
            },
            flags: dlpk::sys::DLPACK_FLAG_BITMASK_READ_ONLY,
        };
        managed.manager_ctx = Box::into_raw(manager) as *mut std::ffi::c_void;
        // Safety: valid DLManagedTensorVersioned; deleter frees DeviceTaggedManager
        // (Arc + shape storage). from_raw re-wraps with a Rust manager that
        // still invokes our deleter.
        Ok(unsafe { DLPackTensor::from_raw(managed) })
    }

    fn copy(&self) -> Box<dyn Array> {
        Box::new(Self {
            shape: self.shape.clone(),
            device: self.device,
            data: Arc::clone(&self.data),
        })
    }
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

    fn shared_f64(values: Vec<f64>, shape: &[usize]) -> Arc<RwLock<ArrayD<f64>>> {
        Arc::new(RwLock::new(
            ArrayD::from_shape_vec(ndarray::IxDyn(shape), values).unwrap(),
        ))
    }

    #[test]
    fn locked_array_exports_point_at_its_buffer() {
        let array = shared_f64((0..6).map(f64::from).collect(), &[2, 3]);
        let buffer = array.read().unwrap().as_ptr();
        let first = array
            .as_dlpack(DLDevice::cpu(), None, DLPackVersion::current())
            .unwrap();
        let second = array
            .as_dlpack(DLDevice::cpu(), None, DLPackVersion::current())
            .unwrap();
        for tensor in [&first, &second] {
            assert_eq!(tensor.data_ptr::<f64>().unwrap(), buffer);
            assert_eq!(tensor.shape(), &[2, 3]);
            assert_eq!(tensor.strides(), Some(&[3, 1][..]));
            assert_ne!(tensor.flags() & dlpk::sys::DLPACK_FLAG_BITMASK_READ_ONLY, 0);
        }
        assert_eq!(array.shape(), vec![2, 3]);
    }

    #[test]
    fn a_live_export_keeps_writers_out_until_it_is_deleted() {
        let array = shared_f64(vec![1.0, 2.0, 3.0], &[3]);
        let tensor = array
            .as_dlpack(DLDevice::cpu(), None, DLPackVersion::current())
            .unwrap();
        assert!(matches!(array.try_write(), Err(TryLockError::WouldBlock)));
        drop(array.try_read().expect("readers still get in"));
        drop(tensor);
        array
            .try_write()
            .expect("writers get in after the export is deleted")[0] = 9.0;
        let again = array
            .as_dlpack(DLDevice::cpu(), None, DLPackVersion::current())
            .unwrap();
        assert_eq!(unsafe { *again.data_ptr::<f64>().unwrap() }, 9.0);
    }

    #[test]
    fn an_export_outlives_the_last_array_handle() {
        let array = shared_f64(vec![4.0, 5.0], &[2]);
        let tensor = array
            .as_dlpack(DLDevice::cpu(), None, DLPackVersion::current())
            .unwrap();
        drop(array);
        let values = unsafe { std::slice::from_raw_parts(tensor.data_ptr::<f64>().unwrap(), 2) };
        assert_eq!(values, &[4.0, 5.0]);
    }

    #[test]
    fn exporting_a_write_locked_array_is_an_error() {
        let array = shared_f64(vec![1.0], &[1]);
        let _writer = array.write().unwrap();
        assert!(
            array
                .as_dlpack(DLDevice::cpu(), None, DLPackVersion::current())
                .is_err()
        );
    }

    // std's futex RwLock turns new readers away once a writer is waiting.
    #[cfg(target_os = "linux")]
    #[test]
    fn exports_fail_while_a_writer_waits_on_a_live_export() {
        let array = shared_f64(vec![1.0], &[1]);
        let held = array
            .as_dlpack(DLDevice::cpu(), None, DLPackVersion::current())
            .unwrap();
        std::thread::scope(|scope| {
            let writer = scope.spawn(|| array.write().unwrap()[0] = 2.0);
            let deadline = std::time::Instant::now() + std::time::Duration::from_secs(30);
            while array
                .as_dlpack(DLDevice::cpu(), None, DLPackVersion::current())
                .is_ok()
            {
                assert!(
                    std::time::Instant::now() < deadline,
                    "exports kept succeeding while a writer waited"
                );
                std::thread::yield_now();
            }
            assert!(!writer.is_finished());
            drop(held);
            writer.join().unwrap();
        });
        assert_eq!(array.read().unwrap()[0], 2.0);
    }

    // The deleter frees the tensor it is given, so calling it again reads
    // freed memory. The double call runs in a child process, which
    // AddressSanitizer must stop with a use-after-free report.
    #[cfg(asan_run)]
    #[test]
    fn a_second_deleter_call_is_a_use_after_free() {
        const CHILD: &str = "READCON_DOUBLE_DELETE_CHILD";
        if std::env::var_os(CHILD).is_some() {
            let array = shared_f64(vec![1.0], &[1]);
            let tensor = array
                .as_dlpack(DLDevice::cpu(), None, DLPackVersion::current())
                .unwrap()
                .into_raw()
                .as_ptr();
            unsafe {
                let deleter = (*tensor).deleter.unwrap();
                deleter(tensor);
                deleter(tensor);
            }
            return;
        }
        let output = std::process::Command::new(std::env::current_exe().unwrap())
            .args([
                "--exact",
                "array::tests::a_second_deleter_call_is_a_use_after_free",
                "--nocapture",
                "--test-threads=1",
            ])
            .env(CHILD, "1")
            .output()
            .unwrap();
        let stderr = String::from_utf8_lossy(&output.stderr);
        assert!(!output.status.success(), "{stderr}");
        assert!(stderr.contains("heap-use-after-free"), "{stderr}");
    }

    /// Without `--features cuda`, non-CPU allocate must fail with a clear error
    /// (never panic inside a missing driver loader).
    #[cfg(not(feature = "cuda"))]
    #[test]
    fn allocate_non_cpu_fails_clearly() {
        match allocate_array_on_device(&[2, 3], DLDevice::cuda(0)) {
            Ok(_) => panic!("non-CPU allocate must fail without --features cuda"),
            Err(err) => {
                let msg = format!("{err:?}");
                assert!(
                    msg.contains("no device allocator") || msg.contains("allocator"),
                    "{msg}"
                );
            }
        }
        let cpu = allocate_array_on_device(&[2, 3], DLDevice::cpu()).unwrap();
        assert_eq!(cpu.device(), DLDevice::cpu());
    }

    /// With `--features cuda` and a working driver, allocate on CUDA must succeed
    /// and report `kDLCUDA` (real device memory path).
    #[cfg(feature = "cuda")]
    #[test]
    fn allocate_cuda_succeeds_with_feature() {
        if crate::cuda_array::cuda_device_count().is_err() {
            return;
        }
        let a = allocate_array_on_device(&[2, 3], DLDevice::cuda(0))
            .expect("CUDA allocate must succeed with --features cuda and a driver");
        assert_eq!(a.device(), DLDevice::cuda(0));
        assert_eq!(a.device().device_type, dlpk::sys::DLDeviceType::kDLCUDA);
        let t = a
            .as_dlpack(DLDevice::cuda(0), None, DLPackVersion::current())
            .expect("matching as_dlpack");
        assert_eq!(t.device().device_type, dlpk::sys::DLDeviceType::kDLCUDA);
        let cpu = allocate_array_on_device(&[2, 3], DLDevice::cpu()).unwrap();
        assert_eq!(cpu.device(), DLDevice::cpu());
    }

    #[test]
    fn cuda_tagged_preserves_device_and_matching_as_dlpack() {
        let data: Vec<f64> = (0..6).map(|i| i as f64).collect();
        let a = array_from_host_f64_on_device(&[2, 3], data.clone(), DLDevice::cuda(0)).unwrap();
        assert_eq!(a.device(), DLDevice::cuda(0));
        assert_eq!(a.shape(), vec![2, 3]);

        let mismatch = a
            .as_dlpack(DLDevice::cpu(), None, DLPackVersion::current())
            .unwrap_err();
        assert!(
            format!("{mismatch:?}").contains("device mismatch"),
            "{mismatch:?}"
        );

        let tensor = a
            .as_dlpack(DLDevice::cuda(0), None, DLPackVersion::current())
            .expect("matching CUDA device export");
        assert_eq!(tensor.device(), DLDevice::cuda(0));
        assert_eq!(tensor.shape(), &[2, 3]);

        // from_dlpack preserves device tag
        let back = from_dlpack_f64(&tensor).unwrap();
        assert_eq!(back.device(), DLDevice::cuda(0));
        assert_eq!(back.shape(), vec![2, 3]);
        let again = back
            .as_dlpack(DLDevice::cuda(0), None, DLPackVersion::current())
            .unwrap();
        assert_eq!(again.device(), DLDevice::cuda(0));
    }

    #[test]
    fn cpu_tagged_path_unchanged() {
        let a =
            array_from_host_f64_on_device(&[1, 3], vec![1.0, 2.0, 3.0], DLDevice::cpu()).unwrap();
        assert_eq!(a.device(), DLDevice::cpu());
        let t = a
            .as_dlpack(DLDevice::cpu(), None, DLPackVersion::current())
            .unwrap();
        assert_eq!(t.device(), DLDevice::cpu());
        let back = from_dlpack_f64(&t).unwrap();
        assert_eq!(back.device(), DLDevice::cpu());
    }
}
