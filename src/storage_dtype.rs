//! In-memory SoA element types (CON v3 `storage_dtypes`) and DLPack export.
//!
//! On-disk CON text stays IEEE binary64 decimals. In-memory arrays may use any
//! host element type **dlpk can own and export**: signed/unsigned ints 8–64,
//! float16/32/64, bool (kDLBool), complex64/128 (`[f32;2]` / `[f64;2]`).
//! DLPack ABI codes without a Rust host in dlpk (bfloat16, float8_*, opaque)
//! are rejected with a clear error. `as_dlpack` exports the **actual** backing
//! (metatensor-style), not a silent always-f64 fiction.

use crate::error::ParseError;
use crate::types::meta;
use serde_json::{json, Value};

/// Element type for a numeric SoA field in memory (maps to DLPack codes).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Default)]
pub enum ElementKind {
    #[default]
    Float64,
    Float32,
    /// IEEE binary16 (`half::f16`); DLPack `kDLFloat` bits=16.
    Float16,
    Int8,
    Int16,
    Int32,
    Int64,
    UInt8,
    UInt16,
    UInt32,
    UInt64,
    /// Stored as `u8` 0/1; DLPack export uses `bool` / `kDLBool`.
    Bool,
    /// Real+imag `f32` pair; DLPack `kDLComplex` bits=64.
    Complex64,
    /// Real+imag `f64` pair; DLPack `kDLComplex` bits=128.
    Complex128,
}

/// Back-compat alias used by older call sites.
pub type FloatStorageKind = ElementKind;

impl ElementKind {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Float64 => "float64",
            Self::Float32 => "float32",
            Self::Float16 => "float16",
            Self::Int8 => "int8",
            Self::Int16 => "int16",
            Self::Int32 => "int32",
            Self::Int64 => "int64",
            Self::UInt8 => "uint8",
            Self::UInt16 => "uint16",
            Self::UInt32 => "uint32",
            Self::UInt64 => "uint64",
            Self::Bool => "bool",
            Self::Complex64 => "complex64",
            Self::Complex128 => "complex128",
        }
    }

    /// DLPack `DLDataTypeCode` numeric value (matches `dlpk::sys::DLDataTypeCode`).
    pub fn dlpack_code(self) -> u8 {
        match self {
            Self::Int8 | Self::Int16 | Self::Int32 | Self::Int64 => 0,
            Self::UInt8 | Self::UInt16 | Self::UInt32 | Self::UInt64 => 1,
            Self::Float16 | Self::Float32 | Self::Float64 => 2,
            Self::Complex64 | Self::Complex128 => 5,
            Self::Bool => 6,
        }
    }

    /// Element width in bits (complex = full real+imag size, DLPack convention).
    pub fn dlpack_bits(self) -> u8 {
        match self {
            Self::Int8 | Self::UInt8 | Self::Bool => 8,
            Self::Int16 | Self::UInt16 | Self::Float16 => 16,
            Self::Int32 | Self::UInt32 | Self::Float32 => 32,
            Self::Int64 | Self::UInt64 | Self::Float64 | Self::Complex64 => 64,
            Self::Complex128 => 128,
        }
    }

    pub fn parse(s: &str) -> Result<Self, ParseError> {
        match s.trim().to_ascii_lowercase().as_str() {
            "float64" | "f64" | "double" => Ok(Self::Float64),
            "float32" | "f32" | "single" => Ok(Self::Float32),
            "float16" | "f16" | "half" => Ok(Self::Float16),
            "int8" | "i8" => Ok(Self::Int8),
            "int16" | "i16" => Ok(Self::Int16),
            "int32" | "i32" => Ok(Self::Int32),
            "int64" | "i64" => Ok(Self::Int64),
            "uint8" | "u8" => Ok(Self::UInt8),
            "uint16" | "u16" => Ok(Self::UInt16),
            "uint32" | "u32" => Ok(Self::UInt32),
            "uint64" | "u64" => Ok(Self::UInt64),
            "bool" | "boolean" => Ok(Self::Bool),
            "complex64" | "c64" => Ok(Self::Complex64),
            "complex128" | "c128" => Ok(Self::Complex128),
            // DLPack ABI exists; no host type in dlpk (or not yet wired here)
            "bfloat16" | "bf16" | "float8" | "float8_e4m3fn" | "float8_e5m2" | "opaque"
            | "opaque_handle" => Err(ParseError::ValidationError(format!(
                "storage dtype '{s}' is a DLPack code without an in-memory host in this library"
            ))),
            other => Err(ParseError::ValidationError(format!(
                "unknown storage dtype '{other}'"
            ))),
        }
    }

    /// All kinds we can allocate and `as_dlpack` on CPU today (dlpk-hosted).
    pub fn all_hosted() -> &'static [Self] {
        &[
            Self::Float64,
            Self::Float32,
            Self::Float16,
            Self::Int8,
            Self::Int16,
            Self::Int32,
            Self::Int64,
            Self::UInt8,
            Self::UInt16,
            Self::UInt32,
            Self::UInt64,
            Self::Bool,
            Self::Complex64,
            Self::Complex128,
        ]
    }
}

/// Per-field in-memory dtypes (v3 optional `storage_dtypes` metadata).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StorageDtypes {
    pub positions: ElementKind,
    pub velocities: ElementKind,
    pub forces: ElementKind,
    pub energies: ElementKind,
    pub masses: ElementKind,
    pub atom_ids: ElementKind,
}

impl Default for StorageDtypes {
    fn default() -> Self {
        Self {
            positions: ElementKind::Float64,
            velocities: ElementKind::Float64,
            forces: ElementKind::Float64,
            energies: ElementKind::Float64,
            masses: ElementKind::Float64,
            atom_ids: ElementKind::UInt64,
        }
    }
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
            "atom_ids": self.atom_ids.as_str(),
        })
    }

    pub fn from_metadata(
        meta_map: &std::collections::BTreeMap<String, Value>,
    ) -> Result<Self, ParseError> {
        let Some(v) = meta_map.get(meta::STORAGE_DTYPES) else {
            return Ok(Self::all_f64());
        };
        Self::from_json(v)
    }

    pub fn from_json(v: &Value) -> Result<Self, ParseError> {
        let obj = v.as_object().ok_or_else(|| {
            ParseError::ValidationError("storage_dtypes must be a JSON object".into())
        })?;
        let get = |k: &str, default: ElementKind| -> Result<ElementKind, ParseError> {
            match obj.get(k) {
                None => Ok(default),
                Some(Value::String(s)) => ElementKind::parse(s),
                Some(_) => Err(ParseError::ValidationError(format!(
                    "storage_dtypes.{k} must be a string"
                ))),
            }
        };
        Ok(Self {
            positions: get("positions", ElementKind::Float64)?,
            velocities: get("velocities", ElementKind::Float64)?,
            forces: get("forces", ElementKind::Float64)?,
            energies: get("energies", ElementKind::Float64)?,
            masses: get("masses", ElementKind::Float64)?,
            atom_ids: get("atom_ids", ElementKind::UInt64)?,
        })
    }

    pub fn insert_into(&self, metadata: &mut std::collections::BTreeMap<String, Value>) {
        metadata.insert(meta::STORAGE_DTYPES.into(), self.to_json());
    }
}

/// 2-D SoA block (positions / velocities / forces).
#[derive(Clone, Debug)]
pub enum Array2Storage {
    F64(ndarray::ArcArray2<f64>),
    F32(ndarray::ArcArray2<f32>),
    F16(ndarray::ArcArray2<half::f16>),
    I8(ndarray::ArcArray2<i8>),
    I16(ndarray::ArcArray2<i16>),
    I32(ndarray::ArcArray2<i32>),
    I64(ndarray::ArcArray2<i64>),
    U8(ndarray::ArcArray2<u8>),
    U16(ndarray::ArcArray2<u16>),
    U32(ndarray::ArcArray2<u32>),
    U64(ndarray::ArcArray2<u64>),
    /// 0/1 bytes; exported as bool via DLPack `Vec<bool>` path.
    Bool(ndarray::ArcArray2<u8>),
    /// Complex element = `[re, im]` (DLPack complex64 / complex128).
    C64(ndarray::ArcArray2<[f32; 2]>),
    C128(ndarray::ArcArray2<[f64; 2]>),
}

/// Back-compat name.
pub type FloatArray2 = Array2Storage;

impl PartialEq for Array2Storage {
    fn eq(&self, other: &Self) -> bool {
        self.kind() == other.kind()
            && self.nrows() == other.nrows()
            && self.ncols() == other.ncols()
            && (0..self.nrows()).all(|i| self.as_f64_row(i) == other.as_f64_row(i))
    }
}

impl Array2Storage {
    pub fn zeros(kind: ElementKind, n: usize, c: usize) -> Self {
        use ElementKind::*;
        match kind {
            Float64 => Self::F64(ndarray::ArcArray2::zeros((n, c))),
            Float32 => Self::F32(ndarray::ArcArray2::zeros((n, c))),
            Float16 => Self::F16(ndarray::ArcArray2::from_elem((n, c), half::f16::ZERO)),
            Int8 => Self::I8(ndarray::ArcArray2::zeros((n, c))),
            Int16 => Self::I16(ndarray::ArcArray2::zeros((n, c))),
            Int32 => Self::I32(ndarray::ArcArray2::zeros((n, c))),
            Int64 => Self::I64(ndarray::ArcArray2::zeros((n, c))),
            UInt8 => Self::U8(ndarray::ArcArray2::zeros((n, c))),
            UInt16 => Self::U16(ndarray::ArcArray2::zeros((n, c))),
            UInt32 => Self::U32(ndarray::ArcArray2::zeros((n, c))),
            UInt64 => Self::U64(ndarray::ArcArray2::zeros((n, c))),
            Bool => Self::Bool(ndarray::ArcArray2::zeros((n, c))),
            Complex64 => Self::C64(ndarray::ArcArray2::from_elem((n, c), [0.0f32, 0.0])),
            Complex128 => Self::C128(ndarray::ArcArray2::from_elem((n, c), [0.0f64, 0.0])),
        }
    }

    pub fn zeros_f64(n: usize, c: usize) -> Self {
        Self::zeros(ElementKind::Float64, n, c)
    }

    pub fn kind(&self) -> ElementKind {
        match self {
            Self::F64(_) => ElementKind::Float64,
            Self::F32(_) => ElementKind::Float32,
            Self::F16(_) => ElementKind::Float16,
            Self::I8(_) => ElementKind::Int8,
            Self::I16(_) => ElementKind::Int16,
            Self::I32(_) => ElementKind::Int32,
            Self::I64(_) => ElementKind::Int64,
            Self::U8(_) => ElementKind::UInt8,
            Self::U16(_) => ElementKind::UInt16,
            Self::U32(_) => ElementKind::UInt32,
            Self::U64(_) => ElementKind::UInt64,
            Self::Bool(_) => ElementKind::Bool,
            Self::C64(_) => ElementKind::Complex64,
            Self::C128(_) => ElementKind::Complex128,
        }
    }

    pub fn nrows(&self) -> usize {
        match self {
            Self::F64(a) => a.nrows(),
            Self::F32(a) => a.nrows(),
            Self::F16(a) => a.nrows(),
            Self::I8(a) => a.nrows(),
            Self::I16(a) => a.nrows(),
            Self::I32(a) => a.nrows(),
            Self::I64(a) => a.nrows(),
            Self::U8(a) | Self::Bool(a) => a.nrows(),
            Self::U16(a) => a.nrows(),
            Self::U32(a) => a.nrows(),
            Self::U64(a) => a.nrows(),
            Self::C64(a) => a.nrows(),
            Self::C128(a) => a.nrows(),
        }
    }

    pub fn ncols(&self) -> usize {
        match self {
            Self::F64(a) => a.ncols(),
            Self::F32(a) => a.ncols(),
            Self::F16(a) => a.ncols(),
            Self::I8(a) => a.ncols(),
            Self::I16(a) => a.ncols(),
            Self::I32(a) => a.ncols(),
            Self::I64(a) => a.ncols(),
            Self::U8(a) | Self::Bool(a) => a.ncols(),
            Self::U16(a) => a.ncols(),
            Self::U32(a) => a.ncols(),
            Self::U64(a) => a.ncols(),
            Self::C64(a) => a.ncols(),
            Self::C128(a) => a.ncols(),
        }
    }

    /// Reallocate in `kind` and copy values via f64 real part (allocate-as-type).
    pub fn project_to(&mut self, kind: ElementKind) {
        if self.kind() == kind {
            return;
        }
        let n = self.nrows();
        let c = self.ncols();
        let mut next = Self::zeros(kind, n, c);
        for i in 0..n {
            next.set_f64_row(i, self.as_f64_row(i));
        }
        *self = next;
    }

    /// Real part of each column (imag discarded / zero for complex hosts).
    pub fn as_f64_row(&self, i: usize) -> [f64; 3] {
        let g = |a: f64, b: f64, c: f64| [a, b, c];
        match self {
            Self::F64(a) => {
                let r = a.row(i);
                g(r[0], r[1], r[2])
            }
            Self::F32(a) => {
                let r = a.row(i);
                g(r[0] as f64, r[1] as f64, r[2] as f64)
            }
            Self::F16(a) => {
                let r = a.row(i);
                g(r[0].to_f64(), r[1].to_f64(), r[2].to_f64())
            }
            Self::I8(a) => {
                let r = a.row(i);
                g(r[0] as f64, r[1] as f64, r[2] as f64)
            }
            Self::I16(a) => {
                let r = a.row(i);
                g(r[0] as f64, r[1] as f64, r[2] as f64)
            }
            Self::I32(a) => {
                let r = a.row(i);
                g(r[0] as f64, r[1] as f64, r[2] as f64)
            }
            Self::I64(a) => {
                let r = a.row(i);
                g(r[0] as f64, r[1] as f64, r[2] as f64)
            }
            Self::U8(a) | Self::Bool(a) => {
                let r = a.row(i);
                g(r[0] as f64, r[1] as f64, r[2] as f64)
            }
            Self::U16(a) => {
                let r = a.row(i);
                g(r[0] as f64, r[1] as f64, r[2] as f64)
            }
            Self::U32(a) => {
                let r = a.row(i);
                g(r[0] as f64, r[1] as f64, r[2] as f64)
            }
            Self::U64(a) => {
                let r = a.row(i);
                g(r[0] as f64, r[1] as f64, r[2] as f64)
            }
            Self::C64(a) => {
                let r = a.row(i);
                g(r[0][0] as f64, r[1][0] as f64, r[2][0] as f64)
            }
            Self::C128(a) => {
                let r = a.row(i);
                g(r[0][0], r[1][0], r[2][0])
            }
        }
    }

    #[inline]
    pub fn set_f64_row(&mut self, i: usize, v: [f64; 3]) {
        match self {
            Self::F64(a) => {
                // Contiguous (N,3) layout: three stores at i*3 without ndarray
                // row view machinery on the coordinate hot path.
                if let Some(s) = a.as_slice_memory_order_mut() {
                    let o = i * 3;
                    s[o] = v[0];
                    s[o + 1] = v[1];
                    s[o + 2] = v[2];
                } else {
                    let mut row = a.row_mut(i);
                    row[0] = v[0];
                    row[1] = v[1];
                    row[2] = v[2];
                }
            }
            Self::F32(a) => {
                let mut row = a.row_mut(i);
                row[0] = v[0] as f32;
                row[1] = v[1] as f32;
                row[2] = v[2] as f32;
            }
            Self::F16(a) => {
                let mut row = a.row_mut(i);
                row[0] = half::f16::from_f64(v[0]);
                row[1] = half::f16::from_f64(v[1]);
                row[2] = half::f16::from_f64(v[2]);
            }
            Self::I8(a) => {
                let mut row = a.row_mut(i);
                row[0] = v[0] as i8;
                row[1] = v[1] as i8;
                row[2] = v[2] as i8;
            }
            Self::I16(a) => {
                let mut row = a.row_mut(i);
                row[0] = v[0] as i16;
                row[1] = v[1] as i16;
                row[2] = v[2] as i16;
            }
            Self::I32(a) => {
                let mut row = a.row_mut(i);
                row[0] = v[0] as i32;
                row[1] = v[1] as i32;
                row[2] = v[2] as i32;
            }
            Self::I64(a) => {
                let mut row = a.row_mut(i);
                row[0] = v[0] as i64;
                row[1] = v[1] as i64;
                row[2] = v[2] as i64;
            }
            Self::U8(a) => {
                let mut row = a.row_mut(i);
                row[0] = v[0] as u8;
                row[1] = v[1] as u8;
                row[2] = v[2] as u8;
            }
            Self::Bool(a) => {
                let mut row = a.row_mut(i);
                row[0] = (v[0] != 0.0) as u8;
                row[1] = (v[1] != 0.0) as u8;
                row[2] = (v[2] != 0.0) as u8;
            }
            Self::U16(a) => {
                let mut row = a.row_mut(i);
                row[0] = v[0] as u16;
                row[1] = v[1] as u16;
                row[2] = v[2] as u16;
            }
            Self::U32(a) => {
                let mut row = a.row_mut(i);
                row[0] = v[0] as u32;
                row[1] = v[1] as u32;
                row[2] = v[2] as u32;
            }
            Self::U64(a) => {
                let mut row = a.row_mut(i);
                row[0] = v[0] as u64;
                row[1] = v[1] as u64;
                row[2] = v[2] as u64;
            }
            Self::C64(a) => {
                let mut row = a.row_mut(i);
                row[0] = [v[0] as f32, 0.0];
                row[1] = [v[1] as f32, 0.0];
                row[2] = [v[2] as f32, 0.0];
            }
            Self::C128(a) => {
                let mut row = a.row_mut(i);
                row[0] = [v[0], 0.0];
                row[1] = [v[1], 0.0];
                row[2] = [v[2], 0.0];
            }
        }
    }

    pub fn as_dlpack(
        &self,
        device: dlpk::sys::DLDevice,
    ) -> Result<dlpk::DLPackTensor, ParseError> {
        if device != dlpk::sys::DLDevice::cpu() {
            #[cfg(feature = "cuda")]
            {
                use dlpk::sys::DLDeviceType;
                if device.device_type == DLDeviceType::kDLCUDA {
                    // Frame SoA stays on host; H2D into real CUDA memory then export.
                    let nrows = self.nrows();
                    let ncols = self.ncols();
                    let mut host = Vec::with_capacity(nrows.saturating_mul(ncols));
                    for i in 0..nrows {
                        host.extend_from_slice(&self.as_f64_row(i));
                    }
                    return crate::cuda_array::export_host_f64_as_cuda_dlpack(
                        &[nrows, ncols],
                        &host,
                        device.device_id,
                    );
                }
            }
            return Err(ParseError::ValidationError(
                "Array2Storage is CPU-resident; non-CPU as_dlpack unsupported (build with --features cuda for CUDA H2D export)".into(),
            ));
        }
        match self {
            Self::F64(a) => dlpk::DLPackTensor::try_from(a.clone())
                .map_err(|e| ParseError::ValidationError(format!("as_dlpack: {e}"))),
            Self::F32(a) => dlpk::DLPackTensor::try_from(a.clone())
                .map_err(|e| ParseError::ValidationError(format!("as_dlpack: {e}"))),
            Self::F16(_) => Err(ParseError::ValidationError(
                "float16 as_dlpack blocked on half/dlpk version skew; storage still allocates".into(),
            )),
            Self::I8(a) => dlpk::DLPackTensor::try_from(a.clone())
                .map_err(|e| ParseError::ValidationError(format!("as_dlpack: {e}"))),
            Self::I16(a) => dlpk::DLPackTensor::try_from(a.clone())
                .map_err(|e| ParseError::ValidationError(format!("as_dlpack: {e}"))),
            Self::I32(a) => dlpk::DLPackTensor::try_from(a.clone())
                .map_err(|e| ParseError::ValidationError(format!("as_dlpack: {e}"))),
            Self::I64(a) => dlpk::DLPackTensor::try_from(a.clone())
                .map_err(|e| ParseError::ValidationError(format!("as_dlpack: {e}"))),
            Self::U8(a) => dlpk::DLPackTensor::try_from(a.clone())
                .map_err(|e| ParseError::ValidationError(format!("as_dlpack: {e}"))),
            Self::U16(a) => dlpk::DLPackTensor::try_from(a.clone())
                .map_err(|e| ParseError::ValidationError(format!("as_dlpack: {e}"))),
            Self::U32(a) => dlpk::DLPackTensor::try_from(a.clone())
                .map_err(|e| ParseError::ValidationError(format!("as_dlpack: {e}"))),
            Self::U64(a) => dlpk::DLPackTensor::try_from(a.clone())
                .map_err(|e| ParseError::ValidationError(format!("as_dlpack: {e}"))),
            Self::Bool(a) => {
                let v: Vec<bool> = a.iter().map(|&x| x != 0).collect();
                dlpk::DLPackTensor::try_from(v)
                    .map_err(|e| ParseError::ValidationError(format!("as_dlpack bool: {e}")))
            }
            Self::C64(a) => dlpk::DLPackTensor::try_from(a.clone())
                .map_err(|e| ParseError::ValidationError(format!("as_dlpack complex64: {e}"))),
            Self::C128(a) => dlpk::DLPackTensor::try_from(a.clone())
                .map_err(|e| ParseError::ValidationError(format!("as_dlpack complex128: {e}"))),
        }
    }
}

/// 1-D SoA (energies / masses / scalar fields).
#[derive(Clone, Debug)]
pub enum Array1Storage {
    F64(ndarray::ArcArray1<f64>),
    F32(ndarray::ArcArray1<f32>),
    F16(ndarray::ArcArray1<half::f16>),
    I8(ndarray::ArcArray1<i8>),
    I16(ndarray::ArcArray1<i16>),
    I32(ndarray::ArcArray1<i32>),
    I64(ndarray::ArcArray1<i64>),
    U8(ndarray::ArcArray1<u8>),
    U16(ndarray::ArcArray1<u16>),
    U32(ndarray::ArcArray1<u32>),
    U64(ndarray::ArcArray1<u64>),
    Bool(ndarray::ArcArray1<u8>),
    C64(ndarray::ArcArray1<[f32; 2]>),
    C128(ndarray::ArcArray1<[f64; 2]>),
}

pub type FloatArray1 = Array1Storage;

impl PartialEq for Array1Storage {
    fn eq(&self, other: &Self) -> bool {
        self.kind() == other.kind()
            && self.len() == other.len()
            && (0..self.len()).all(|i| (self.get_f64(i) - other.get_f64(i)).abs() < 1e-12)
    }
}

impl Array1Storage {
    pub fn zeros(kind: ElementKind, n: usize) -> Self {
        use ElementKind::*;
        match kind {
            Float64 => Self::F64(ndarray::ArcArray1::zeros(n)),
            Float32 => Self::F32(ndarray::ArcArray1::zeros(n)),
            Float16 => Self::F16(ndarray::ArcArray1::from_elem(n, half::f16::ZERO)),
            Int8 => Self::I8(ndarray::ArcArray1::zeros(n)),
            Int16 => Self::I16(ndarray::ArcArray1::zeros(n)),
            Int32 => Self::I32(ndarray::ArcArray1::zeros(n)),
            Int64 => Self::I64(ndarray::ArcArray1::zeros(n)),
            UInt8 => Self::U8(ndarray::ArcArray1::zeros(n)),
            UInt16 => Self::U16(ndarray::ArcArray1::zeros(n)),
            UInt32 => Self::U32(ndarray::ArcArray1::zeros(n)),
            UInt64 => Self::U64(ndarray::ArcArray1::zeros(n)),
            Bool => Self::Bool(ndarray::ArcArray1::zeros(n)),
            Complex64 => Self::C64(ndarray::ArcArray1::from_elem(n, [0.0f32, 0.0])),
            Complex128 => Self::C128(ndarray::ArcArray1::from_elem(n, [0.0f64, 0.0])),
        }
    }

    pub fn zeros_f64(n: usize) -> Self {
        Self::zeros(ElementKind::Float64, n)
    }

    pub fn kind(&self) -> ElementKind {
        match self {
            Self::F64(_) => ElementKind::Float64,
            Self::F32(_) => ElementKind::Float32,
            Self::F16(_) => ElementKind::Float16,
            Self::I8(_) => ElementKind::Int8,
            Self::I16(_) => ElementKind::Int16,
            Self::I32(_) => ElementKind::Int32,
            Self::I64(_) => ElementKind::Int64,
            Self::U8(_) => ElementKind::UInt8,
            Self::U16(_) => ElementKind::UInt16,
            Self::U32(_) => ElementKind::UInt32,
            Self::U64(_) => ElementKind::UInt64,
            Self::Bool(_) => ElementKind::Bool,
            Self::C64(_) => ElementKind::Complex64,
            Self::C128(_) => ElementKind::Complex128,
        }
    }

    pub fn len(&self) -> usize {
        match self {
            Self::F64(a) => a.len(),
            Self::F32(a) => a.len(),
            Self::F16(a) => a.len(),
            Self::I8(a) => a.len(),
            Self::I16(a) => a.len(),
            Self::I32(a) => a.len(),
            Self::I64(a) => a.len(),
            Self::U8(a) | Self::Bool(a) => a.len(),
            Self::U16(a) => a.len(),
            Self::U32(a) => a.len(),
            Self::U64(a) => a.len(),
            Self::C64(a) => a.len(),
            Self::C128(a) => a.len(),
        }
    }

    pub fn project_to(&mut self, kind: ElementKind) {
        if self.kind() == kind {
            return;
        }
        let n = self.len();
        let mut next = Self::zeros(kind, n);
        for i in 0..n {
            next.set_f64(i, self.get_f64(i));
        }
        *self = next;
    }

    pub fn get_f64(&self, i: usize) -> f64 {
        match self {
            Self::F64(a) => a[i],
            Self::F32(a) => a[i] as f64,
            Self::F16(a) => a[i].to_f64(),
            Self::I8(a) => a[i] as f64,
            Self::I16(a) => a[i] as f64,
            Self::I32(a) => a[i] as f64,
            Self::I64(a) => a[i] as f64,
            Self::U8(a) | Self::Bool(a) => a[i] as f64,
            Self::U16(a) => a[i] as f64,
            Self::U32(a) => a[i] as f64,
            Self::U64(a) => a[i] as f64,
            Self::C64(a) => a[i][0] as f64,
            Self::C128(a) => a[i][0],
        }
    }

    pub fn set_f64(&mut self, i: usize, v: f64) {
        match self {
            Self::F64(a) => a[i] = v,
            Self::F32(a) => a[i] = v as f32,
            Self::F16(a) => a[i] = half::f16::from_f64(v),
            Self::I8(a) => a[i] = v as i8,
            Self::I16(a) => a[i] = v as i16,
            Self::I32(a) => a[i] = v as i32,
            Self::I64(a) => a[i] = v as i64,
            Self::U8(a) => a[i] = v as u8,
            Self::Bool(a) => a[i] = (v != 0.0) as u8,
            Self::U16(a) => a[i] = v as u16,
            Self::U32(a) => a[i] = v as u32,
            Self::U64(a) => a[i] = v as u64,
            Self::C64(a) => a[i] = [v as f32, 0.0],
            Self::C128(a) => a[i] = [v, 0.0],
        }
    }

    pub fn as_dlpack(
        &self,
        device: dlpk::sys::DLDevice,
    ) -> Result<dlpk::DLPackTensor, ParseError> {
        if device != dlpk::sys::DLDevice::cpu() {
            #[cfg(feature = "cuda")]
            {
                use dlpk::sys::DLDeviceType;
                if device.device_type == DLDeviceType::kDLCUDA {
                    let n = self.len();
                    let mut host = Vec::with_capacity(n);
                    for i in 0..n {
                        host.push(self.get_f64(i));
                    }
                    return crate::cuda_array::export_host_f64_as_cuda_dlpack(
                        &[n],
                        &host,
                        device.device_id,
                    );
                }
            }
            return Err(ParseError::ValidationError(
                "Array1Storage is CPU-resident; non-CPU as_dlpack unsupported (build with --features cuda for CUDA H2D export)".into(),
            ));
        }
        match self {
            Self::F64(a) => dlpk::DLPackTensor::try_from(a.clone())
                .map_err(|e| ParseError::ValidationError(format!("as_dlpack: {e}"))),
            Self::F32(a) => dlpk::DLPackTensor::try_from(a.clone())
                .map_err(|e| ParseError::ValidationError(format!("as_dlpack: {e}"))),
            Self::F16(_) => Err(ParseError::ValidationError(
                "float16 as_dlpack blocked on half/dlpk version skew; storage still allocates".into(),
            )),
            Self::I8(a) => dlpk::DLPackTensor::try_from(a.clone())
                .map_err(|e| ParseError::ValidationError(format!("as_dlpack: {e}"))),
            Self::I16(a) => dlpk::DLPackTensor::try_from(a.clone())
                .map_err(|e| ParseError::ValidationError(format!("as_dlpack: {e}"))),
            Self::I32(a) => dlpk::DLPackTensor::try_from(a.clone())
                .map_err(|e| ParseError::ValidationError(format!("as_dlpack: {e}"))),
            Self::I64(a) => dlpk::DLPackTensor::try_from(a.clone())
                .map_err(|e| ParseError::ValidationError(format!("as_dlpack: {e}"))),
            Self::U8(a) => dlpk::DLPackTensor::try_from(a.clone())
                .map_err(|e| ParseError::ValidationError(format!("as_dlpack: {e}"))),
            Self::U16(a) => dlpk::DLPackTensor::try_from(a.clone())
                .map_err(|e| ParseError::ValidationError(format!("as_dlpack: {e}"))),
            Self::U32(a) => dlpk::DLPackTensor::try_from(a.clone())
                .map_err(|e| ParseError::ValidationError(format!("as_dlpack: {e}"))),
            Self::U64(a) => dlpk::DLPackTensor::try_from(a.clone())
                .map_err(|e| ParseError::ValidationError(format!("as_dlpack: {e}"))),
            Self::Bool(a) => {
                let v: Vec<bool> = a.iter().map(|&x| x != 0).collect();
                dlpk::DLPackTensor::try_from(v)
                    .map_err(|e| ParseError::ValidationError(format!("as_dlpack bool: {e}")))
            }
            Self::C64(a) => dlpk::DLPackTensor::try_from(a.clone())
                .map_err(|e| ParseError::ValidationError(format!("as_dlpack complex64: {e}"))),
            Self::C128(a) => dlpk::DLPackTensor::try_from(a.clone())
                .map_err(|e| ParseError::ValidationError(format!("as_dlpack complex128: {e}"))),
        }
    }
}

/// Atom-id column: integer family only; default uint64.
#[derive(Clone, Debug)]
pub enum IdArray1 {
    U64(ndarray::ArcArray1<u64>),
    U32(ndarray::ArcArray1<u32>),
    U16(ndarray::ArcArray1<u16>),
    U8(ndarray::ArcArray1<u8>),
    I64(ndarray::ArcArray1<i64>),
    I32(ndarray::ArcArray1<i32>),
    I16(ndarray::ArcArray1<i16>),
    I8(ndarray::ArcArray1<i8>),
}

impl IdArray1 {
    pub fn zeros(kind: ElementKind, n: usize) -> Result<Self, ParseError> {
        Ok(match kind {
            ElementKind::UInt64 => Self::U64(ndarray::ArcArray1::zeros(n)),
            ElementKind::UInt32 => Self::U32(ndarray::ArcArray1::zeros(n)),
            ElementKind::UInt16 => Self::U16(ndarray::ArcArray1::zeros(n)),
            ElementKind::UInt8 => Self::U8(ndarray::ArcArray1::zeros(n)),
            ElementKind::Int64 => Self::I64(ndarray::ArcArray1::zeros(n)),
            ElementKind::Int32 => Self::I32(ndarray::ArcArray1::zeros(n)),
            ElementKind::Int16 => Self::I16(ndarray::ArcArray1::zeros(n)),
            ElementKind::Int8 => Self::I8(ndarray::ArcArray1::zeros(n)),
            other => {
                return Err(ParseError::ValidationError(format!(
                    "atom_ids cannot use storage dtype {}",
                    other.as_str()
                )));
            }
        })
    }

    pub fn len(&self) -> usize {
        match self {
            Self::U64(a) => a.len(),
            Self::U32(a) => a.len(),
            Self::U16(a) => a.len(),
            Self::U8(a) => a.len(),
            Self::I64(a) => a.len(),
            Self::I32(a) => a.len(),
            Self::I16(a) => a.len(),
            Self::I8(a) => a.len(),
        }
    }

    pub fn set_u64(&mut self, i: usize, v: u64) {
        match self {
            Self::U64(a) => a[i] = v,
            Self::U32(a) => a[i] = v as u32,
            Self::U16(a) => a[i] = v as u16,
            Self::U8(a) => a[i] = v as u8,
            Self::I64(a) => a[i] = v as i64,
            Self::I32(a) => a[i] = v as i32,
            Self::I16(a) => a[i] = v as i16,
            Self::I8(a) => a[i] = v as i8,
        }
    }

    pub fn get_u64(&self, i: usize) -> u64 {
        match self {
            Self::U64(a) => a[i],
            Self::U32(a) => a[i] as u64,
            Self::U16(a) => a[i] as u64,
            Self::U8(a) => a[i] as u64,
            Self::I64(a) => a[i] as u64,
            Self::I32(a) => a[i] as u64,
            Self::I16(a) => a[i] as u64,
            Self::I8(a) => a[i] as u64,
        }
    }

    pub fn as_dlpack(
        &self,
        device: dlpk::sys::DLDevice,
    ) -> Result<dlpk::DLPackTensor, ParseError> {
        if device != dlpk::sys::DLDevice::cpu() {
            return Err(ParseError::ValidationError(
                "IdArray1 is CPU-resident".into(),
            ));
        }
        match self {
            Self::U64(a) => dlpk::DLPackTensor::try_from(a.clone())
                .map_err(|e| ParseError::ValidationError(format!("{e}"))),
            Self::U32(a) => dlpk::DLPackTensor::try_from(a.clone())
                .map_err(|e| ParseError::ValidationError(format!("{e}"))),
            Self::U16(a) => dlpk::DLPackTensor::try_from(a.clone())
                .map_err(|e| ParseError::ValidationError(format!("{e}"))),
            Self::U8(a) => dlpk::DLPackTensor::try_from(a.clone())
                .map_err(|e| ParseError::ValidationError(format!("{e}"))),
            Self::I64(a) => dlpk::DLPackTensor::try_from(a.clone())
                .map_err(|e| ParseError::ValidationError(format!("{e}"))),
            Self::I32(a) => dlpk::DLPackTensor::try_from(a.clone())
                .map_err(|e| ParseError::ValidationError(format!("{e}"))),
            Self::I16(a) => dlpk::DLPackTensor::try_from(a.clone())
                .map_err(|e| ParseError::ValidationError(format!("{e}"))),
            Self::I8(a) => dlpk::DLPackTensor::try_from(a.clone())
                .map_err(|e| ParseError::ValidationError(format!("{e}"))),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn all_hosted_kinds_allocate_2d_and_dlpack() {
        for &k in ElementKind::all_hosted() {
            let mut a = Array2Storage::zeros(k, 2, 3);
            a.set_f64_row(0, [1.0, 2.0, 3.0]);
            let t = a.as_dlpack(dlpk::sys::DLDevice::cpu());
            if k == ElementKind::Float16 {
                assert!(t.is_err());
                continue;
            }
            let t = t.unwrap();
            // bool exports as 1-D length 6 (Vec<bool> path)
            if k == ElementKind::Bool {
                assert_eq!(t.shape(), &[6]);
            } else {
                assert_eq!(t.shape(), &[2, 3]);
            }
            assert_eq!(t.dtype().bits, k.dlpack_bits());
            assert_eq!(t.dtype().code as u8, k.dlpack_code());
        }
    }

    #[test]
    fn all_hosted_kinds_allocate_1d_and_dlpack() {
        for &k in ElementKind::all_hosted() {
            let mut a = Array1Storage::zeros(k, 4);
            a.set_f64(0, 1.0);
            let t = a.as_dlpack(dlpk::sys::DLDevice::cpu());
            if k == ElementKind::Float16 {
                assert!(t.is_err());
                continue;
            }
            let t = t.unwrap();
            assert_eq!(t.shape(), &[4]);
            assert_eq!(t.dtype().bits, k.dlpack_bits());
        }
    }

    #[test]
    fn reject_bfloat_and_float8() {
        assert!(ElementKind::parse("bfloat16").is_err());
        assert!(ElementKind::parse("float8_e4m3fn").is_err());
        assert!(ElementKind::parse("opaque").is_err());
    }

    #[test]
    fn accept_complex_and_float16_strings() {
        assert_eq!(ElementKind::parse("complex64").unwrap(), ElementKind::Complex64);
        assert_eq!(ElementKind::parse("float16").unwrap(), ElementKind::Float16);
    }

    #[test]
    fn storage_dtypes_json_int32_positions() {
        let j = json!({"positions": "int32", "atom_ids": "uint32"});
        let s = StorageDtypes::from_json(&j).unwrap();
        assert_eq!(s.positions, ElementKind::Int32);
        assert_eq!(s.atom_ids, ElementKind::UInt32);
    }

    #[test]
    fn id_array_all_integer_kinds() {
        for &k in &[
            ElementKind::UInt64,
            ElementKind::UInt32,
            ElementKind::UInt16,
            ElementKind::UInt8,
            ElementKind::Int64,
            ElementKind::Int32,
            ElementKind::Int16,
            ElementKind::Int8,
        ] {
            let mut ids = IdArray1::zeros(k, 2).unwrap();
            ids.set_u64(0, 7);
            assert_eq!(ids.get_u64(0), 7);
            let t = ids.as_dlpack(dlpk::sys::DLDevice::cpu()).unwrap();
            assert_eq!(t.shape(), &[2]);
        }
        assert!(IdArray1::zeros(ElementKind::Float32, 1).is_err());
    }
}
