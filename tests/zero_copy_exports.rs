//! The float64 CPU DLPack exports of a frame share its columns: the tensor
//! data pointer is the column's buffer, on every call. Counted by pointer
//! identity, not by timing.

use readcon_core::ffi::*;
use readcon_core::storage_dtype::{Array1Storage, Array2Storage};
use readcon_core::types::{ConFrame, ConFrameBuilder};
use std::ptr;

type Export = unsafe extern "C" fn(
    *const RKRConFrame,
    *const RKRDlpackExportOptions,
    *mut *mut RKRDLManagedTensorVersioned,
) -> RKRStatus;

fn frame(shift: f64) -> ConFrame {
    let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
    for (i, symbol) in ["Cu", "Cu", "H"].into_iter().enumerate() {
        let x = shift + i as f64;
        builder
            .add_atom(symbol, x, x + 0.25, x + 0.5, [false; 3], i as u64, 1.0)
            .with_velocity([x, -x, 0.5])
            .with_force([-x, x, 0.25])
            .with_energy(x * 0.125);
    }
    builder.build().unwrap()
}

fn rows_ptr(column: &Array2Storage) -> *const f64 {
    match column {
        Array2Storage::F64(a) => a.as_ptr(),
        _ => panic!("expected an f64 column"),
    }
}

fn energies_ptr(frame: &ConFrame) -> *const f64 {
    match &*frame.atom_energies {
        Array1Storage::F64(a) => a.as_ptr(),
        _ => panic!("expected f64 energies"),
    }
}

fn export(
    handle: *const RKRConFrame,
    f: Export,
    opts: *const RKRDlpackExportOptions,
) -> *mut RKRDLManagedTensorVersioned {
    let mut t = ptr::null_mut();
    assert_eq!(
        unsafe { f(handle, opts, &mut t) },
        RKRStatus::RKR_STATUS_SUCCESS
    );
    assert!(!t.is_null());
    t
}

fn data(t: *mut RKRDLManagedTensorVersioned) -> *const f64 {
    unsafe { (*t).dl_tensor.data as *const f64 }
}

fn values(t: *mut RKRDLManagedTensorVersioned, len: usize) -> Vec<f64> {
    unsafe { std::slice::from_raw_parts(data(t), len).to_vec() }
}

fn exports(frame: &ConFrame) -> [(Export, *const f64, usize); 4] {
    [
        (rkr_frame_positions_dlpack_ex, rows_ptr(&frame.positions), 9),
        (
            rkr_frame_velocities_dlpack_ex,
            rows_ptr(&frame.velocities),
            9,
        ),
        (rkr_frame_forces_dlpack_ex, rows_ptr(&frame.forces), 9),
        (rkr_frame_atom_energies_dlpack_ex, energies_ptr(frame), 3),
    ]
}

const F32: RKRDlpackExportOptions = RKRDlpackExportOptions {
    dtype: RKRDLDataType {
        code: rkr_dl_type_code::RKR_DL_FLOAT,
        bits: 32,
        lanes: 1,
    },
    device: RKRDLDevice {
        device_type: rkr_dl_device_type::RKR_DL_CPU,
        device_id: 0,
    },
};

#[test]
fn float64_exports_point_at_the_frame_columns() {
    let frame = frame(0.0);
    let columns = exports(&frame);
    let handle = Box::into_raw(Box::new(frame)) as *mut RKRConFrame;
    let explicit = RKRDlpackExportOptions::default();
    for (f, column, _) in columns {
        let first = export(handle, f, ptr::null());
        let second = export(handle, f, &explicit);
        assert_eq!(data(first), column);
        assert_eq!(data(second), column);
        assert_ne!(
            unsafe { (*first).flags } & dlpk::sys::DLPACK_FLAG_BITMASK_READ_ONLY,
            0
        );
        unsafe {
            rkr_dlpack_delete(first);
            rkr_dlpack_delete(second);
        }
    }
    unsafe { free_rkr_frame(handle) };
}

#[test]
fn a_float32_request_is_a_new_cast_buffer() {
    let frame = frame(0.0);
    let columns = exports(&frame);
    let handle = Box::into_raw(Box::new(frame)) as *mut RKRConFrame;
    for (f, column, len) in columns {
        let shared = export(handle, f, ptr::null());
        let cast = export(handle, f, &F32);
        assert_ne!(data(cast) as *const u8, column as *const u8);
        let cast_values =
            unsafe { std::slice::from_raw_parts((*cast).dl_tensor.data as *const f32, len) };
        let expected: Vec<f32> = values(shared, len).iter().map(|&x| x as f32).collect();
        assert_eq!(cast_values, expected.as_slice());
        unsafe {
            rkr_dlpack_delete(shared);
            rkr_dlpack_delete(cast);
        }
    }
    unsafe { free_rkr_frame(handle) };
}

#[test]
fn an_export_keeps_its_values_after_the_frame_is_freed() {
    let frame = frame(0.0);
    let columns = exports(&frame);
    let handle = Box::into_raw(Box::new(frame)) as *mut RKRConFrame;
    let held: Vec<_> = columns
        .iter()
        .map(|&(f, _, len)| (export(handle, f, ptr::null()), len))
        .collect();
    let before: Vec<Vec<f64>> = held.iter().map(|&(t, len)| values(t, len)).collect();
    unsafe { free_rkr_frame(handle) };
    for ((t, len), expected) in held.into_iter().zip(before) {
        assert_eq!(values(t, len), expected);
        unsafe { rkr_dlpack_delete(t) };
    }
}

#[test]
fn writing_positions_leaves_an_earlier_export_unchanged() {
    let target = frame(0.0);
    let old_column = rows_ptr(&target.positions);
    let handle = Box::into_raw(Box::new(target)) as *mut RKRConFrame;
    let source = Box::into_raw(Box::new(frame(5.0))) as *mut RKRConFrame;

    let held = export(handle, rkr_frame_positions_dlpack_ex, ptr::null());
    let before = values(held, 9);
    let new_values = export(source, rkr_frame_positions_dlpack_ex, ptr::null());
    assert_eq!(
        unsafe { rkr_frame_positions_from_dlpack(handle, new_values) },
        RKRStatus::RKR_STATUS_SUCCESS
    );

    assert_eq!(data(held), old_column);
    assert_eq!(values(held, 9), before);
    let after = export(handle, rkr_frame_positions_dlpack_ex, ptr::null());
    assert_ne!(data(after), old_column);
    assert_eq!(values(after, 9), values(new_values, 9));
    let frame = unsafe { &*(handle as *const ConFrame) };
    assert_eq!(data(after), rows_ptr(&frame.positions));
    assert_eq!(frame.x_at(2), 7.0);
    unsafe {
        rkr_dlpack_delete(held);
        rkr_dlpack_delete(new_values);
        rkr_dlpack_delete(after);
        free_rkr_frame(handle);
        free_rkr_frame(source);
    }
}

#[test]
fn a_store_into_the_shared_export_shows_on_the_frame() {
    let text = std::fs::read_to_string("resources/test/tiny_cuh2.con").unwrap();
    let parsed = readcon_core::iterators::ConFrameIterator::new(&text)
        .next()
        .unwrap()
        .unwrap();
    let handle = Box::into_raw(Box::new(parsed)) as *mut RKRConFrame;
    let held = export(handle, rkr_frame_positions_dlpack_ex, ptr::null());
    let frame = unsafe { &mut *(handle as *mut ConFrame) };
    // The export is the positions column. A store through that pointer is
    // what a later read of the frame returns. `set_x_at` copies a column
    // an export still shares, so the in-place store is this pointer.
    assert_eq!(data(held), rows_ptr(&frame.positions));
    unsafe { (data(held) as *mut f64).write(42.0) };
    assert_eq!(frame.x_at(0), 42.0);
    assert_eq!(values(held, 1), [42.0]);
    unsafe {
        rkr_dlpack_delete(held);
        free_rkr_frame(handle);
    }
}

#[test]
fn concurrent_exports_of_one_frame_share_its_columns() {
    let frame = frame(0.0);
    let columns = exports(&frame).map(|(f, column, len)| (f, column as usize, len));
    let handle = Box::into_raw(Box::new(frame)) as usize;
    let barrier = std::sync::Barrier::new(8);
    std::thread::scope(|scope| {
        for _ in 0..8 {
            scope.spawn(|| {
                barrier.wait();
                for _ in 0..200 {
                    for (f, column, len) in columns {
                        let t = export(handle as *const RKRConFrame, f, ptr::null());
                        assert_eq!(data(t) as usize, column);
                        assert_eq!(values(t, len).len(), len);
                        unsafe { rkr_dlpack_delete(t) };
                    }
                }
            });
        }
    });
    unsafe { free_rkr_frame(handle as *mut RKRConFrame) };
}

#[test]
fn concurrent_exports_of_one_locked_array_share_its_buffer() {
    use readcon_core::array::Array;
    let array = std::sync::Arc::new(std::sync::RwLock::new(
        ndarray::ArrayD::from_shape_vec(ndarray::IxDyn(&[4, 3]), (0..12).map(f64::from).collect())
            .unwrap(),
    ));
    let buffer = array.read().unwrap().as_ptr() as usize;
    let barrier = std::sync::Barrier::new(8);
    std::thread::scope(|scope| {
        for _ in 0..8 {
            scope.spawn(|| {
                barrier.wait();
                for _ in 0..200 {
                    let tensor = array
                        .as_dlpack(
                            dlpk::sys::DLDevice::cpu(),
                            None,
                            dlpk::sys::DLPackVersion::current(),
                        )
                        .unwrap();
                    assert_eq!(tensor.data_ptr::<f64>().unwrap() as usize, buffer);
                }
            });
        }
    });
    array.try_write().expect("every export was deleted")[[0, 0]] = 1.0;
}
