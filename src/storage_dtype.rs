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
use serde_json::{Value, json};

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

/// An absent 2-D section. Empty stays a null pointer instead of a 56-byte header.
#[derive(Clone, Debug, Default)]
pub struct Optional2 {
    inner: Option<Box<Array2Storage>>,
}

impl Optional2 {
    pub(crate) fn is_present(&self) -> bool {
        self.inner.is_some()
    }

    pub fn new(array: Array2Storage) -> Self {
        if array.nrows() == 0 {
            Self { inner: None }
        } else {
            Self {
                inner: Some(Box::new(array)),
            }
        }
    }
}

impl std::ops::Deref for Optional2 {
    type Target = Array2Storage;
    fn deref(&self) -> &Array2Storage {
        match self.inner.as_deref() {
            Some(array) => array,
            None => empty_rows_static(),
        }
    }
}

impl std::ops::DerefMut for Optional2 {
    fn deref_mut(&mut self) -> &mut Array2Storage {
        if self.inner.is_none() {
            self.inner = Some(Box::new(empty_rows_static().clone()));
        }
        self.inner.as_mut().unwrap()
    }
}

impl PartialEq for Optional2 {
    fn eq(&self, other: &Self) -> bool {
        std::ops::Deref::deref(self) == std::ops::Deref::deref(other)
    }
}

impl From<Array2Storage> for Optional2 {
    fn from(array: Array2Storage) -> Self {
        Self::new(array)
    }
}

/// First element of a packed allocation, or null when the array is not contiguous.
///
/// `as_ptr` copies the array's raw base. A pointer from `as_slice` is a
/// slice tag, and the next write to the allocation retires it.
fn allocation_base<A, S, D>(array: &ndarray::ArrayBase<S, D>) -> *const u8
where
    S: ndarray::RawData<Elem = A>,
    D: ndarray::Dimension,
{
    if array.is_standard_layout() {
        array.as_ptr().cast()
    } else {
        std::ptr::null()
    }
}

fn empty_rows_static() -> &'static Array2Storage {
    static EMPTY: crate::parser::ForkOnce<Array2Storage> = crate::parser::ForkOnce::new();
    EMPTY.get_or_init(|| Array2Storage::zeros(ElementKind::Float64, 0, 3))
}

#[inline]
fn read_f64_row3<T: Copy>(row: ndarray::ArrayView1<'_, T>, convert: impl Fn(T) -> f64) -> [f64; 3] {
    [
        row.first().copied().map(&convert).unwrap_or(0.0),
        row.get(1).copied().map(&convert).unwrap_or(0.0),
        row.get(2).copied().map(&convert).unwrap_or(0.0),
    ]
}

#[inline]
fn write_f64_row3<T>(
    mut row: ndarray::ArrayViewMut1<'_, T>,
    v: [f64; 3],
    convert: impl Fn(f64) -> T,
) {
    for (slot, val) in row.iter_mut().take(3).zip(v) {
        *slot = convert(val);
    }
}

impl PartialEq for Array2Storage {
    fn eq(&self, other: &Self) -> bool {
        self.kind() == other.kind()
            && self.nrows() == other.nrows()
            && self.ncols() == other.ncols()
            && (0..self.nrows()).all(|i| self.as_f64_row(i) == other.as_f64_row(i))
    }
}

fn empty_f64_rows() -> Array2Storage {
    // A process-wide Arc made every worker's frame assembly increment the
    // same atomic. That one cache line serialised an otherwise parallel
    // parse. Each thread keeps its own empty matrix, so the increment
    // stays on that thread's line. The bytes are still a zero-length
    // `(0, 3)` f64 array.
    thread_local! {
        static EMPTY: ndarray::ArcArray2<f64> =
            ndarray::Array2::<f64>::zeros((0, 3)).into_shared();
    }
    EMPTY.with(|empty| Array2Storage::F64(empty.clone()))
}

fn empty_f64_col() -> Array1Storage {
    thread_local! {
        static EMPTY: ndarray::ArcArray1<f64> = ndarray::Array1::<f64>::zeros(0).into_shared();
    }
    EMPTY.with(|empty| Array1Storage::F64(empty.clone()))
}

impl Array2Storage {
    pub fn zeros(kind: ElementKind, n: usize, c: usize) -> Self {
        use ElementKind::*;
        if n == 0 && c == 3 && kind == Float64 {
            return empty_f64_rows();
        }
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

    /// Build an f64 `(n, c)` SoA from a flat row-major buffer (`len == n * c`).
    ///
    /// Prefer this on the parse hot path: fill a plain `Vec<f64>` (no per-row
    /// `ArcArray` uniqueness checks), then wrap once. `perf` on multi-frame
    /// cuh2 parse showed `OwnedArcRepr::try_ensure_unique` at ~16% of cycles
    /// when writing via repeated `set_f64_row` / `as_slice_memory_order_mut`.
    pub fn from_f64_row_major(n: usize, c: usize, data: Vec<f64>) -> Self {
        debug_assert_eq!(data.len(), n.saturating_mul(c));
        let arr = ndarray::Array2::from_shape_vec((n, c), data)
            .expect("from_f64_row_major: shape must match buffer length");
        Self::F64(arr.into_shared())
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

    /// Contiguous f64 row-major slice when storage is float64. None otherwise.
    pub fn f64_slice(&self) -> Option<&[f64]> {
        match self {
            Self::F64(a) => a.as_slice_memory_order(),
            _ => None,
        }
    }

    /// Row-major `[x0, y0, z0, x1, ...]` doubles of a float64 `(n, 3)` block.
    ///
    /// `None` for another dtype, another column count, or a layout that is
    /// not row-major. A Fortran-ordered `(n, 3)` block is contiguous, but its
    /// memory order is column by column, so [`Self::f64_slice`] would hand
    /// out the x values of every atom first.
    pub fn f64_rows3(&self) -> Option<&[f64]> {
        match self {
            Self::F64(a) if a.ncols() == 3 && a.is_standard_layout() => a.as_slice(),
            _ => None,
        }
    }

    /// Row `i`, or `None` when `i` is past the last row or the block does
    /// not have exactly three columns.
    pub fn try_f64_row(&self, i: usize) -> Option<[f64; 3]> {
        (i < self.nrows() && self.ncols() == 3).then(|| self.as_f64_row(i))
    }

    /// Contiguous mutable f64 row-major slice when storage is float64.
    ///
    /// Shared `ArcArray` storage is copied before the mutable slice is
    /// returned. The slice's borrow ends with the reference, so a pointer
    /// saved from it is not a way to write the block later.
    pub fn f64_mut_slice(&mut self) -> Option<&mut [f64]> {
        match self {
            Self::F64(a) => a.as_slice_memory_order_mut(),
            _ => None,
        }
    }

    /// Writable pointer to the first element of a unique contiguous f64 block.
    ///
    /// [`Self::f64_slice`] retags that block as shared. A pointer saved from
    /// the slice cannot be written afterwards. This is the array's own
    /// pointer after the storage is made unique. A write through it stays
    /// valid while the allocation stays where it is.
    pub fn f64_allocation_ptr(&mut self) -> Option<*mut f64> {
        match self {
            Self::F64(array) if array.is_standard_layout() => Some(array.as_mut_ptr()),
            _ => None,
        }
    }

    /// Address of the first element of the packed f64 allocation.
    ///
    /// The pointer is the array's raw base. It is not taken from a slice, so
    /// a caller may export it and then run [`Self::set_f64_row`]. `None` when
    /// the storage is empty or not a packed f64 block.
    pub fn f64_base_ptr(&self) -> Option<*const f64> {
        match self {
            Self::F64(array) if array.is_standard_layout() && !array.is_empty() => {
                Some(array.as_ptr())
            }
            _ => None,
        }
    }

    /// Take the contiguous f64 allocation, leaving an empty matrix.
    ///
    /// `None` when the storage is shared or not a packed f64 block. The
    /// returned `Vec` is the same allocation, so pointers into it stay valid
    /// when the `Vec` is moved and not reallocated.
    #[cfg(feature = "python-bindings")]
    pub(crate) fn take_contiguous_f64(&mut self) -> Option<Vec<f64>> {
        let stolen = std::mem::replace(self, empty_f64_rows());
        match stolen {
            Self::F64(array) => match array.try_into_owned_nocopy() {
                Ok(owned) => {
                    let (vec, offset) = owned.into_raw_vec_and_offset();
                    if offset.unwrap_or(0) == 0 {
                        Some(vec)
                    } else {
                        *self = Self::from_f64_row_major(vec.len(), 1, vec);
                        None
                    }
                }
                Err(array) => {
                    *self = Self::F64(array);
                    None
                }
            },
            other => {
                *self = other;
                None
            }
        }
    }

    /// Pointer to the first element of the contiguous SoA block, or null.
    ///
    /// The address is the allocation's raw base. A slice pointer would be
    /// retired by the next write to this storage.
    pub fn data_ptr(&self) -> *const u8 {
        match self {
            Self::F64(a) => allocation_base(a),
            Self::F32(a) => allocation_base(a),
            Self::F16(a) => allocation_base(a),
            Self::I8(a) => allocation_base(a),
            Self::I16(a) => allocation_base(a),
            Self::I32(a) => allocation_base(a),
            Self::I64(a) => allocation_base(a),
            Self::U8(a) | Self::Bool(a) => allocation_base(a),
            Self::U16(a) => allocation_base(a),
            Self::U32(a) => allocation_base(a),
            Self::U64(a) => allocation_base(a),
            Self::C64(a) => allocation_base(a),
            Self::C128(a) => allocation_base(a),
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
    /// Columns past `ncols()` read as `0.0`.
    pub fn as_f64_row(&self, i: usize) -> [f64; 3] {
        match self {
            Self::F64(a) => read_f64_row3(a.row(i), |x| x),
            Self::F32(a) => read_f64_row3(a.row(i), |x| x as f64),
            Self::F16(a) => read_f64_row3(a.row(i), half::f16::to_f64),
            Self::I8(a) => read_f64_row3(a.row(i), |x| x as f64),
            Self::I16(a) => read_f64_row3(a.row(i), |x| x as f64),
            Self::I32(a) => read_f64_row3(a.row(i), |x| x as f64),
            Self::I64(a) => read_f64_row3(a.row(i), |x| x as f64),
            Self::U8(a) | Self::Bool(a) => read_f64_row3(a.row(i), |x| x as f64),
            Self::U16(a) => read_f64_row3(a.row(i), |x| x as f64),
            Self::U32(a) => read_f64_row3(a.row(i), |x| x as f64),
            Self::U64(a) => read_f64_row3(a.row(i), |x| x as f64),
            Self::C64(a) => read_f64_row3(a.row(i), |x| x[0] as f64),
            Self::C128(a) => read_f64_row3(a.row(i), |x| x[0]),
        }
    }

    #[inline]
    pub fn set_f64_row(&mut self, i: usize, v: [f64; 3]) {
        match self {
            Self::F64(a) => {
                // Row-major (N,3) layout: three stores at i*3 without ndarray
                // row view machinery on the coordinate hot path. A
                // Fortran-ordered block is contiguous too, but row i is not
                // at i*3 there.
                let row_major = a.ncols() == 3 && a.is_standard_layout();
                if let Some(s) = row_major.then(|| a.as_slice_mut()).flatten() {
                    let o = i * 3;
                    s[o] = v[0];
                    s[o + 1] = v[1];
                    s[o + 2] = v[2];
                } else {
                    write_f64_row3(a.row_mut(i), v, |x| x);
                }
            }
            Self::F32(a) => write_f64_row3(a.row_mut(i), v, |x| x as f32),
            Self::F16(a) => write_f64_row3(a.row_mut(i), v, half::f16::from_f64),
            Self::I8(a) => write_f64_row3(a.row_mut(i), v, |x| x as i8),
            Self::I16(a) => write_f64_row3(a.row_mut(i), v, |x| x as i16),
            Self::I32(a) => write_f64_row3(a.row_mut(i), v, |x| x as i32),
            Self::I64(a) => write_f64_row3(a.row_mut(i), v, |x| x as i64),
            Self::U8(a) => write_f64_row3(a.row_mut(i), v, |x| x as u8),
            Self::Bool(a) => write_f64_row3(a.row_mut(i), v, |x| (x != 0.0) as u8),
            Self::U16(a) => write_f64_row3(a.row_mut(i), v, |x| x as u16),
            Self::U32(a) => write_f64_row3(a.row_mut(i), v, |x| x as u32),
            Self::U64(a) => write_f64_row3(a.row_mut(i), v, |x| x as u64),
            Self::C64(a) => write_f64_row3(a.row_mut(i), v, |x| [x as f32, 0.0]),
            Self::C128(a) => write_f64_row3(a.row_mut(i), v, |x| [x, 0.0]),
        }
    }

    pub fn as_dlpack(&self, device: dlpk::sys::DLDevice) -> Result<dlpk::DLPackTensor, ParseError> {
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
                "float16 as_dlpack blocked on half/dlpk version skew; storage still allocates"
                    .into(),
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

/// An absent 1-D section. Empty stays a null pointer instead of a matrix header.
#[derive(Clone, Debug)]
pub struct Optional1 {
    inner: Option<Box<Array1Storage>>,
}

impl Optional1 {
    pub(crate) fn is_present(&self) -> bool {
        self.inner.is_some()
    }

    pub fn new(array: Array1Storage) -> Self {
        if array.is_empty() {
            Self { inner: None }
        } else {
            Self {
                inner: Some(Box::new(array)),
            }
        }
    }
}

impl std::ops::Deref for Optional1 {
    type Target = Array1Storage;
    fn deref(&self) -> &Array1Storage {
        match self.inner.as_deref() {
            Some(array) => array,
            None => empty_col_static(),
        }
    }
}

impl std::ops::DerefMut for Optional1 {
    fn deref_mut(&mut self) -> &mut Array1Storage {
        if self.inner.is_none() {
            self.inner = Some(Box::new(empty_col_static().clone()));
        }
        self.inner.as_mut().unwrap()
    }
}

impl PartialEq for Optional1 {
    fn eq(&self, other: &Self) -> bool {
        std::ops::Deref::deref(self) == std::ops::Deref::deref(other)
    }
}

impl From<Array1Storage> for Optional1 {
    fn from(array: Array1Storage) -> Self {
        Self::new(array)
    }
}

fn empty_col_static() -> &'static Array1Storage {
    static EMPTY: crate::parser::ForkOnce<Array1Storage> = crate::parser::ForkOnce::new();
    EMPTY.get_or_init(|| Array1Storage::zeros(ElementKind::Float64, 0))
}

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
        if n == 0 && kind == Float64 {
            return empty_f64_col();
        }
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

    /// One-shot f64 column from a owned buffer (parse/assembly hot path).
    pub fn from_f64_vec(data: Vec<f64>) -> Self {
        Self::F64(ndarray::Array1::from(data).into_shared())
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

    pub fn is_empty(&self) -> bool {
        self.len() == 0
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

    /// Contiguous f64 slice when storage is float64.
    pub fn f64_slice(&self) -> Option<&[f64]> {
        match self {
            Self::F64(a) => a.as_slice(),
            _ => None,
        }
    }

    /// Pointer to the first element of the contiguous SoA block, or null.
    ///
    /// The address is the allocation's raw base. A slice pointer would be
    /// retired by the next write to this storage.
    pub fn data_ptr(&self) -> *const u8 {
        match self {
            Self::F64(a) => allocation_base(a),
            Self::F32(a) => allocation_base(a),
            Self::F16(a) => allocation_base(a),
            Self::I8(a) => allocation_base(a),
            Self::I16(a) => allocation_base(a),
            Self::I32(a) => allocation_base(a),
            Self::I64(a) => allocation_base(a),
            Self::U8(a) | Self::Bool(a) => allocation_base(a),
            Self::U16(a) => allocation_base(a),
            Self::U32(a) => allocation_base(a),
            Self::U64(a) => allocation_base(a),
            Self::C64(a) => allocation_base(a),
            Self::C128(a) => allocation_base(a),
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

    pub fn as_dlpack(&self, device: dlpk::sys::DLDevice) -> Result<dlpk::DLPackTensor, ParseError> {
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
                "float16 as_dlpack blocked on half/dlpk version skew; storage still allocates"
                    .into(),
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

    pub fn is_empty(&self) -> bool {
        self.len() == 0
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

    pub fn as_dlpack(&self, device: dlpk::sys::DLDevice) -> Result<dlpk::DLPackTensor, ParseError> {
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

    fn fortran_rows(rows: &[[f64; 3]]) -> Array2Storage {
        use ndarray::ShapeBuilder;
        let n = rows.len();
        let mut column_major = Vec::with_capacity(n * 3);
        for axis in 0..3 {
            column_major.extend(rows.iter().map(|row| row[axis]));
        }
        let array = ndarray::Array2::from_shape_vec((n, 3).f(), column_major).unwrap();
        Array2Storage::F64(array.into_shared())
    }

    #[test]
    fn set_f64_row_writes_the_row_of_a_fortran_ordered_block() {
        let mut block = fortran_rows(&[[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]);
        block.set_f64_row(0, [7.0, 8.0, 9.0]);
        assert_eq!(block.as_f64_row(0), [7.0, 8.0, 9.0]);
        assert_eq!(block.as_f64_row(1), [4.0, 5.0, 6.0]);
    }

    #[test]
    fn rows3_is_row_major_three_column_f64_only() {
        let fortran = fortran_rows(&[[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]);
        assert!(fortran.f64_slice().is_some());
        assert!(fortran.f64_rows3().is_none());
        let narrow = Array2Storage::from_f64_row_major(4, 1, vec![1.0, 2.0, 3.0, 4.0]);
        assert!(narrow.f64_rows3().is_none());
        assert_eq!(narrow.try_f64_row(0), None);
        let rows = Array2Storage::from_f64_row_major(1, 3, vec![1.0, 2.0, 3.0]);
        assert_eq!(rows.f64_rows3(), Some(&[1.0, 2.0, 3.0][..]));
        assert_eq!(rows.try_f64_row(0), Some([1.0, 2.0, 3.0]));
        assert_eq!(rows.try_f64_row(1), None);
        assert_eq!(Array2Storage::zeros_f64(0, 3).try_f64_row(0), None);
    }

    #[test]
    fn all_hosted_kinds_allocate_2d_and_dlpack() {
        for &k in ElementKind::all_hosted() {
            let mut a = Array2Storage::zeros(k, 2, 3);
            assert!(!a.data_ptr().is_null());
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
            assert!(!a.data_ptr().is_null());
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
        assert_eq!(
            ElementKind::parse("complex64").unwrap(),
            ElementKind::Complex64
        );
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

    #[test]
    fn as_f64_row_and_set_f64_row_handle_short_and_wide_columns() {
        for &kind in &[
            ElementKind::Float64,
            ElementKind::Float32,
            ElementKind::Int32,
        ] {
            let mut short = Array2Storage::zeros(kind, 2, 2);
            short.set_f64_row(0, [1.0, 2.0, 3.0]);
            short.set_f64_row(1, [4.0, 5.0, 6.0]);
            assert_eq!(short.as_f64_row(0), [1.0, 2.0, 0.0]);
            assert_eq!(short.as_f64_row(1), [4.0, 5.0, 0.0]);

            let mut wide = Array2Storage::zeros(kind, 2, 4);
            wide.set_f64_row(0, [1.0, 2.0, 3.0]);
            wide.set_f64_row(1, [4.0, 5.0, 6.0]);
            assert_eq!(wide.as_f64_row(0), [1.0, 2.0, 3.0]);
            assert_eq!(wide.as_f64_row(1), [4.0, 5.0, 6.0]);
        }
    }
}
