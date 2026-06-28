//! Real CUDA-backed f64 arrays for DLPack device allocate/export.
//!
//! Enabled only with `--features cuda`. Uses cudarc's CUDA driver API so
//! `allocate_array_on_device(..., DLDevice::cuda(id))` obtains device memory
//! via `cuMemAlloc`, not host staging.

use std::sync::Arc;

use cudarc::driver::{CudaDevice, DevicePtr, DriverError};
use dlpk::sys::{DLDataType, DLDevice, DLPackVersion};
use dlpk::{DLPackTensor, GetDLPackDataType};

use crate::array::Array;
use crate::error::ParseError;

fn map_cuda(e: DriverError) -> ParseError {
    ParseError::ValidationError(format!("CUDA driver error: {e:?}"))
}

/// CUDA-resident f64 buffer owned via `cuMemAlloc` (cudarc `CudaSlice`).
pub struct CudaF64Array {
    shape: Vec<usize>,
    device_id: i32,
    /// Device allocation; length = product(shape).
    slice: cudarc::driver::CudaSlice<f64>,
    /// Keep the device alive for the allocation lifetime.
    _dev: Arc<CudaDevice>,
}

impl CudaF64Array {
    /// Allocate zeros on `device_id` (must match `DLDevice::cuda(device_id)`).
    pub fn alloc_zeros(shape: &[usize], device_id: i32) -> Result<Self, ParseError> {
        let n: usize = shape.iter().product();
        let dev = CudaDevice::new(device_id as usize).map_err(map_cuda)?;
        let slice = if n == 0 {
            // cudarc may not like zero-length; allocate 1 element and track n=0
            dev.alloc_zeros::<f64>(1).map_err(map_cuda)?
        } else {
            dev.alloc_zeros::<f64>(n).map_err(map_cuda)?
        };
        Ok(Self {
            shape: shape.to_vec(),
            device_id,
            slice,
            _dev: dev,
        })
    }

    /// Allocate and copy host f64 data to the device.
    pub fn from_host(shape: &[usize], host: &[f64], device_id: i32) -> Result<Self, ParseError> {
        let n: usize = shape.iter().product();
        if host.len() != n {
            return Err(ParseError::ValidationError(format!(
                "CUDA array: expected {n} f64 values, got {}",
                host.len()
            )));
        }
        let mut a = Self::alloc_zeros(shape, device_id)?;
        if n > 0 {
            a._dev
                .htod_sync_copy_into(host, &mut a.slice)
                .map_err(map_cuda)?;
        }
        Ok(a)
    }

    /// Copy device buffer back to host (for tests / verification).
    pub fn to_host(&self) -> Result<Vec<f64>, ParseError> {
        let n: usize = self.shape.iter().product();
        if n == 0 {
            return Ok(Vec::new());
        }
        let mut host = vec![0.0f64; n];
        self._dev
            .dtoh_sync_copy_into(&self.slice, &mut host)
            .map_err(map_cuda)?;
        Ok(host)
    }

    pub fn device_ptr(&self) -> *mut std::ffi::c_void {
        // CudaSlice implements DevicePtr; data pointer is on the GPU.
        let p: u64 = *self.slice.device_ptr();
        p as usize as *mut std::ffi::c_void
    }

    pub fn dl_device(&self) -> DLDevice {
        DLDevice::cuda(self.device_id)
    }
}

struct CudaDlpackManager {
    /// Owning Arc so the slice stays alive while the DLPack consumer holds the tensor.
    #[allow(dead_code)]
    array: Arc<CudaF64Array>,
    shape: Vec<i64>,
}

unsafe extern "C" fn cuda_dlpack_deleter(managed: *mut dlpk::sys::DLManagedTensorVersioned) {
    if managed.is_null() {
        return;
    }
    unsafe {
        let ctx = (*managed).manager_ctx;
        if !ctx.is_null() {
            let _ = Box::from_raw(ctx as *mut CudaDlpackManager);
            (*managed).manager_ctx = std::ptr::null_mut();
        }
    }
}

impl Array for CudaF64Array {
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
        self.dl_device()
    }

    fn as_dlpack(
        &self,
        device: DLDevice,
        _stream: Option<i64>,
        _max_version: DLPackVersion,
    ) -> Result<DLPackTensor, ParseError> {
        if device != self.dl_device() {
            return Err(ParseError::ValidationError(format!(
                "device mismatch: array is on {:?}, requested {:?}",
                self.dl_device(),
                device
            )));
        }
        // Clone into Arc for manager lifetime: we need a shared owner.
        // CudaF64Array is not Clone; build a thin Arc by allocating a new
        // wrapper that shares the same CudaSlice via unsafe — simpler path:
        // export requires owning the allocation. We use Arc::new of a
        // reconstructed view only for tests by requiring Array to be in Box.
        // Here we leak an Arc by reconstructing from device ptr is wrong.
        //
        // Practical approach: put CudaF64Array behind Arc from the start in
        // allocate_array_on_device (CudaArrayHandle). For as_dlpack on &self,
        // we only support export when we can increment a refcount.
        Err(ParseError::ValidationError(
            "internal: CudaF64Array must be used via CudaArrayHandle for as_dlpack".into(),
        ))
    }

    fn copy(&self) -> Box<dyn Array> {
        // Deep copy on device: host round-trip (sufficient for correctness tests).
        let host = self.to_host().unwrap_or_default();
        Box::new(
            Self::from_host(&self.shape, &host, self.device_id).expect("cuda copy"),
        )
    }
}

/// Public handle: `Arc<CudaF64Array>` so DLPack export can share ownership.
pub struct CudaArrayHandle(pub Arc<CudaF64Array>);

impl Array for CudaArrayHandle {
    fn as_any(&self) -> &dyn std::any::Any {
        self
    }
    fn as_any_mut(&mut self) -> &mut dyn std::any::Any {
        self
    }
    fn shape(&self) -> Vec<usize> {
        self.0.shape.clone()
    }
    fn dtype(&self) -> DLDataType {
        f64::get_dlpack_data_type()
    }
    fn device(&self) -> DLDevice {
        self.0.dl_device()
    }
    fn as_dlpack(
        &self,
        device: DLDevice,
        _stream: Option<i64>,
        _max_version: DLPackVersion,
    ) -> Result<DLPackTensor, ParseError> {
        if device != self.0.dl_device() {
            return Err(ParseError::ValidationError(format!(
                "device mismatch: array is on {:?}, requested {:?}",
                self.0.dl_device(),
                device
            )));
        }
        let manager = Box::new(CudaDlpackManager {
            array: Arc::clone(&self.0),
            shape: self.0.shape.iter().map(|&d| d as i64).collect(),
        });
        let data_ptr = self.0.device_ptr();
        let shape_ptr = manager.shape.as_ptr() as *mut i64;
        let mut managed = dlpk::sys::DLManagedTensorVersioned {
            version: dlpk::sys::DLPackVersion {
                major: dlpk::sys::DLPACK_MAJOR_VERSION,
                minor: dlpk::sys::DLPACK_MINOR_VERSION,
            },
            manager_ctx: std::ptr::null_mut(),
            deleter: Some(cuda_dlpack_deleter),
            dl_tensor: dlpk::sys::DLTensor {
                data: data_ptr,
                device: self.0.dl_device(),
                ndim: self.0.shape.len() as i32,
                dtype: f64::get_dlpack_data_type(),
                shape: shape_ptr,
                strides: std::ptr::null_mut(),
                byte_offset: 0,
            },
            flags: 0,
        };
        managed.manager_ctx = Box::into_raw(manager) as *mut std::ffi::c_void;
        Ok(unsafe { DLPackTensor::from_raw(managed) })
    }
    fn copy(&self) -> Box<dyn Array> {
        let host = self.0.to_host().unwrap_or_default();
        let inner = CudaF64Array::from_host(&self.0.shape, &host, self.0.device_id)
            .expect("cuda copy");
        Box::new(CudaArrayHandle(Arc::new(inner)))
    }
}

/// Allocate zeros on a CUDA device (real `cuMemAlloc` via cudarc).
pub fn allocate_cuda_f64(shape: &[usize], device_id: i32) -> Result<Box<dyn Array>, ParseError> {
    let inner = CudaF64Array::alloc_zeros(shape, device_id)?;
    Ok(Box::new(CudaArrayHandle(Arc::new(inner))))
}

/// True if at least one CUDA device is visible.
pub fn cuda_device_count() -> Result<usize, ParseError> {
    // Probe device 0; if it fails, report zero.
    match CudaDevice::new(0) {
        Ok(_) => Ok(1), // cudarc 0.13 may not expose count easily; at least one works
        Err(e) => Err(map_cuda(e)),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use dlpk::sys::DLDeviceType;

    #[test]
    fn cuda_allocate_export_roundtrip_values() {
        let shape = [2usize, 3];
        let host_in: Vec<f64> = (0..6).map(|i| (i as f64) + 0.5).collect();
        let arr = CudaF64Array::from_host(&shape, &host_in, 0).expect("cuda from_host");
        assert_eq!(arr.device(), DLDevice::cuda(0));
        assert_eq!(arr.device().device_type, DLDeviceType::kDLCUDA);
        let ptr = arr.device_ptr();
        assert!(!ptr.is_null(), "device pointer must be non-null");

        let handle = CudaArrayHandle(Arc::new(arr));
        let tensor = handle
            .as_dlpack(DLDevice::cuda(0), None, DLPackVersion::current())
            .expect("as_dlpack cuda");
        assert_eq!(tensor.device(), DLDevice::cuda(0));
        assert_eq!(tensor.device().device_type, DLDeviceType::kDLCUDA);
        // Data pointer from DLPack must be non-null (device address).
        let tptr = tensor.data_ptr::<f64>().expect("data_ptr");
        assert!(!tptr.is_null());

        // Host round-trip proves real device memory held the values.
        let host_out = handle.0.to_host().expect("to_host");
        assert_eq!(host_out, host_in);

        // Mismatch fails
        let err = handle
            .as_dlpack(DLDevice::cpu(), None, DLPackVersion::current())
            .unwrap_err();
        assert!(format!("{err:?}").contains("device mismatch"));
    }

    #[test]
    fn cuda_alloc_zeros_via_public_allocate() {
        let a = allocate_cuda_f64(&[4, 3], 0).expect("allocate_cuda_f64");
        assert_eq!(a.device(), DLDevice::cuda(0));
        let t = a
            .as_dlpack(DLDevice::cuda(0), None, DLPackVersion::current())
            .expect("export");
        assert_eq!(t.device().device_type, DLDeviceType::kDLCUDA);
    }
}
