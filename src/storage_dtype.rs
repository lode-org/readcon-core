//! In-memory storage dtypes for SoA numeric fields (CON v3 `storage_dtypes` metadata).
//!
//! On-disk CON coordinate and section text remains IEEE binary64. `storage_dtypes`
//! declares how the **library** holds those quantities after load/build so that
//! `as_dlpack` exports the real backing type (metatensor-style), not a silent
//! always-f64 fiction.

use crate::error::ParseError;
use crate::types::meta;
use serde_json::{json, Value};

/// Element type for a float SoA field in memory.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Default)]
pub enum FloatStorageKind {
    #[default]
    Float64,
    Float32,
}

impl FloatStorageKind {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Float64 => "float64",
            Self::Float32 => "float32",
        }
    }

    pub fn parse(s: &str) -> Result<Self, ParseError> {
        match s.trim().to_ascii_lowercase().as_str() {
            "float64" | "f64" | "double" => Ok(Self::Float64),
            "float32" | "f32" | "single" => Ok(Self::Float32),
            other => Err(ParseError::ValidationError(format!(
                "unknown float storage dtype '{other}' (use float32 or float64)"
            ))),
        }
    }

    pub fn dlpack_bits(self) -> u8 {
        match self {
            Self::Float64 => 64,
            Self::Float32 => 32,
        }
    }
}

/// Per-field in-memory dtypes (v3 optional metadata; defaults all float64 / uint64).
#[derive(Clone, Debug, PartialEq, Eq, Default)]
pub struct StorageDtypes {
    pub positions: FloatStorageKind,
    pub velocities: FloatStorageKind,
    pub forces: FloatStorageKind,
    pub energies: FloatStorageKind,
    pub masses: FloatStorageKind,
    /// Atom ids are always uint64 in this implementation.
    pub atom_ids_uint64: bool,
}

impl StorageDtypes {
    pub fn all_f64() -> Self {
        Self::default()
    }

    pub fn to_json(&self) -> Value {
        json!({
            "positions": self.positions.as_str(),
            "velocities": self.velocities.as_str(),
            "forces": self.forces.as_str(),
            "energies": self.energies.as_str(),
            "masses": self.masses.as_str(),
            "atom_ids": "uint64",
        })
    }

    pub fn from_metadata(meta_map: &std::collections::BTreeMap<String, Value>) -> Result<Self, ParseError> {
        let Some(v) = meta_map.get(meta::STORAGE_DTYPES) else {
            return Ok(Self::all_f64());
        };
        Self::from_json(v)
    }

    pub fn from_json(v: &Value) -> Result<Self, ParseError> {
        let obj = v.as_object().ok_or_else(|| {
            ParseError::ValidationError("storage_dtypes must be a JSON object".into())
        })?;
        let get = |k: &str| -> Result<FloatStorageKind, ParseError> {
            match obj.get(k) {
                None => Ok(FloatStorageKind::Float64),
                Some(Value::String(s)) => FloatStorageKind::parse(s),
                Some(_) => Err(ParseError::ValidationError(format!(
                    "storage_dtypes.{k} must be a string"
                ))),
            }
        };
        if let Some(id) = obj.get("atom_ids") {
            let s = id.as_str().ok_or_else(|| {
                ParseError::ValidationError("storage_dtypes.atom_ids must be a string".into())
            })?;
            if s != "uint64" && s != "u64" {
                return Err(ParseError::ValidationError(
                    "storage_dtypes.atom_ids must be \"uint64\" in this implementation".into(),
                ));
            }
        }
        Ok(Self {
            positions: get("positions")?,
            velocities: get("velocities")?,
            forces: get("forces")?,
            energies: get("energies")?,
            masses: get("masses")?,
            atom_ids_uint64: true,
        })
    }

    /// Merge into a metadata map (overwrites `storage_dtypes` key).
    pub fn insert_into(&self, metadata: &mut std::collections::BTreeMap<String, Value>) {
        metadata.insert(meta::STORAGE_DTYPES.into(), self.to_json());
    }
}

/// Row-major 2-D float storage that can project between f32 and f64.
#[derive(Clone, Debug, PartialEq)]
pub enum FloatArray2 {
    F64(ndarray::ArcArray2<f64>),
    F32(ndarray::ArcArray2<f32>),
}

impl FloatArray2 {
    pub fn zeros_f64(n: usize, c: usize) -> Self {
        Self::F64(ndarray::ArcArray2::zeros((n, c)))
    }

    /// Allocate empty storage in the requested element type (no later project needed).
    pub fn zeros(kind: FloatStorageKind, n: usize, c: usize) -> Self {
        match kind {
            FloatStorageKind::Float64 => Self::F64(ndarray::ArcArray2::zeros((n, c))),
            FloatStorageKind::Float32 => Self::F32(ndarray::ArcArray2::zeros((n, c))),
        }
    }

    pub fn kind(&self) -> FloatStorageKind {
        match self {
            Self::F64(_) => FloatStorageKind::Float64,
            Self::F32(_) => FloatStorageKind::Float32,
        }
    }

    pub fn nrows(&self) -> usize {
        match self {
            Self::F64(a) => a.nrows(),
            Self::F32(a) => a.nrows(),
        }
    }

    pub fn ncols(&self) -> usize {
        match self {
            Self::F64(a) => a.ncols(),
            Self::F32(a) => a.ncols(),
        }
    }

    /// Project storage to `kind` (no-op if already that kind).
    pub fn project_to(&mut self, kind: FloatStorageKind) {
        match (self, kind) {
            (Self::F64(_), FloatStorageKind::Float64) => {}
            (Self::F32(_), FloatStorageKind::Float32) => {}
            (this @ Self::F64(_), FloatStorageKind::Float32) => {
                if let Self::F64(a) = this {
                    let b: ndarray::ArcArray2<f32> = a.mapv(|x| x as f32).into();
                    *this = Self::F32(b);
                }
            }
            (this @ Self::F32(_), FloatStorageKind::Float64) => {
                if let Self::F32(a) = this {
                    let b: ndarray::ArcArray2<f64> = a.mapv(|x| x as f64).into();
                    *this = Self::F64(b);
                }
            }
        }
    }

    pub fn as_f64_row(&self, i: usize) -> [f64; 3] {
        match self {
            Self::F64(a) => {
                let r = a.row(i);
                [r[0], r[1], r[2]]
            }
            Self::F32(a) => {
                let r = a.row(i);
                [r[0] as f64, r[1] as f64, r[2] as f64]
            }
        }
    }

    #[inline]
    pub fn set_f64_row(&mut self, i: usize, v: [f64; 3]) {
        match self {
            Self::F64(a) => {
                // Fast path: hot parse/build is overwhelmingly f64 storage.
                let mut row = a.row_mut(i);
                row[0] = v[0];
                row[1] = v[1];
                row[2] = v[2];
            }
            Self::F32(a) => {
                let mut row = a.row_mut(i);
                row[0] = v[0] as f32;
                row[1] = v[1] as f32;
                row[2] = v[2] as f32;
            }
        }
    }

    pub fn as_dlpack(
        &self,
        device: dlpk::sys::DLDevice,
    ) -> Result<dlpk::DLPackTensor, ParseError> {
        if device != dlpk::sys::DLDevice::cpu() {
            return Err(ParseError::ValidationError(
                "FloatArray2 is CPU-resident; non-CPU as_dlpack unsupported".into(),
            ));
        }
        match self {
            Self::F64(a) => dlpk::DLPackTensor::try_from(a.clone()).map_err(|e| {
                ParseError::ValidationError(format!("as_dlpack f64: {e}"))
            }),
            Self::F32(a) => dlpk::DLPackTensor::try_from(a.clone()).map_err(|e| {
                ParseError::ValidationError(format!("as_dlpack f32: {e}"))
            }),
        }
    }

    /// Copy from a flat f64 buffer length nrows*ncols (e.g. after CON parse).
    pub fn fill_from_f64_flat(&mut self, data: &[f64]) {
        let n = self.nrows();
        let c = self.ncols();
        debug_assert_eq!(data.len(), n * c);
        for i in 0..n {
            for j in 0..c {
                let v = data[i * c + j];
                match self {
                    Self::F64(a) => a[[i, j]] = v,
                    Self::F32(a) => a[[i, j]] = v as f32,
                }
            }
        }
    }
}

/// 1-D float storage.
#[derive(Clone, Debug, PartialEq)]
pub enum FloatArray1 {
    F64(ndarray::ArcArray1<f64>),
    F32(ndarray::ArcArray1<f32>),
}

impl FloatArray1 {
    pub fn zeros_f64(n: usize) -> Self {
        Self::F64(ndarray::ArcArray1::zeros(n))
    }

    /// Allocate empty 1-D storage in the requested element type.
    pub fn zeros(kind: FloatStorageKind, n: usize) -> Self {
        match kind {
            FloatStorageKind::Float64 => Self::F64(ndarray::ArcArray1::zeros(n)),
            FloatStorageKind::Float32 => Self::F32(ndarray::ArcArray1::zeros(n)),
        }
    }

    pub fn kind(&self) -> FloatStorageKind {
        match self {
            Self::F64(_) => FloatStorageKind::Float64,
            Self::F32(_) => FloatStorageKind::Float32,
        }
    }

    pub fn len(&self) -> usize {
        match self {
            Self::F64(a) => a.len(),
            Self::F32(a) => a.len(),
        }
    }

    pub fn project_to(&mut self, kind: FloatStorageKind) {
        match (self, kind) {
            (Self::F64(_), FloatStorageKind::Float64) => {}
            (Self::F32(_), FloatStorageKind::Float32) => {}
            (this @ Self::F64(_), FloatStorageKind::Float32) => {
                if let Self::F64(a) = this {
                    *this = Self::F32(a.mapv(|x| x as f32).into());
                }
            }
            (this @ Self::F32(_), FloatStorageKind::Float64) => {
                if let Self::F32(a) = this {
                    *this = Self::F64(a.mapv(|x| x as f64).into());
                }
            }
        }
    }

    pub fn get_f64(&self, i: usize) -> f64 {
        match self {
            Self::F64(a) => a[i],
            Self::F32(a) => a[i] as f64,
        }
    }

    pub fn set_f64(&mut self, i: usize, v: f64) {
        match self {
            Self::F64(a) => a[i] = v,
            Self::F32(a) => a[i] = v as f32,
        }
    }

    pub fn as_dlpack(
        &self,
        device: dlpk::sys::DLDevice,
    ) -> Result<dlpk::DLPackTensor, ParseError> {
        if device != dlpk::sys::DLDevice::cpu() {
            return Err(ParseError::ValidationError(
                "FloatArray1 is CPU-resident; non-CPU as_dlpack unsupported".into(),
            ));
        }
        match self {
            Self::F64(a) => dlpk::DLPackTensor::try_from(a.clone())
                .map_err(|e| ParseError::ValidationError(format!("as_dlpack f64: {e}"))),
            Self::F32(a) => dlpk::DLPackTensor::try_from(a.clone())
                .map_err(|e| ParseError::ValidationError(format!("as_dlpack f32: {e}"))),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn project_f64_to_f32_and_dlpack_bits() {
        let mut a = FloatArray2::zeros_f64(2, 3);
        a.set_f64_row(0, [1.0, 2.0, 3.0]);
        a.project_to(FloatStorageKind::Float32);
        assert_eq!(a.kind(), FloatStorageKind::Float32);
        let t = a.as_dlpack(dlpk::sys::DLDevice::cpu()).unwrap();
        assert_eq!(t.shape(), &[2, 3]);
    }

    #[test]
    fn storage_dtypes_json_roundtrip() {
        let mut s = StorageDtypes::all_f64();
        s.positions = FloatStorageKind::Float32;
        let j = s.to_json();
        let s2 = StorageDtypes::from_json(&j).unwrap();
        assert_eq!(s2.positions, FloatStorageKind::Float32);
    }
}
