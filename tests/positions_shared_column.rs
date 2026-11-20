//! A positions import while an exported DLPack tensor shares the column.
//!
//! A CPU export shares that column with the tensor, so the import's first
//! row write copies it. The import copies those rows onto the atoms as well.
//! Writing the tensor's buffer and deleting it must not change the atoms.

use readcon_core::ffi::{
    RKRConFrame, RKRDLManagedTensorVersioned, RKRStatus, rkr_dl_type_code, rkr_dlpack_delete,
    rkr_frame_positions_dlpack, rkr_frame_positions_from_dlpack, rkr_frame_xyz_f64,
};
use readcon_core::iterators::ConFrameIterator;
use readcon_core::types::ConFrame;

#[test]
fn an_import_from_the_exported_tensor_leaves_the_atoms_on_the_column() {
    let mut frame = ConFrameIterator::new(include_str!("../resources/test/tiny_cuh2.con"))
        .next()
        .expect("frame")
        .expect("parse");
    let before: Vec<[f64; 3]> = (0..frame.atom_data.len())
        .map(|index| frame.xyz_at(index))
        .collect();
    let handle = (&mut frame as *mut ConFrame).cast::<RKRConFrame>();
    let mut tensor: *mut RKRDLManagedTensorVersioned = std::ptr::null_mut();
    unsafe {
        assert_eq!(
            rkr_frame_positions_dlpack(handle, &mut tensor),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        let dl = std::ptr::addr_of_mut!((*tensor).dl_tensor);
        assert_eq!((*dl).ndim, 2);
        assert_eq!(
            std::slice::from_raw_parts((*dl).shape, 2),
            [before.len() as i64, 3]
        );
        assert_eq!((*dl).dtype.code as u8, rkr_dl_type_code::RKR_DL_FLOAT);
        assert_eq!((*dl).dtype.bits, 64);
        assert_eq!((*dl).dtype.lanes, 1);
        assert!(!(*dl).strides.is_null());
        assert_eq!(std::slice::from_raw_parts((*dl).strides, 2), [3, 1]);

        let saved_strides = (*dl).strides;
        (*dl).strides = std::ptr::null_mut();
        assert_eq!(
            rkr_frame_positions_from_dlpack(handle, tensor),
            RKRStatus::RKR_STATUS_VALIDATION_ERROR
        );
        (*dl).strides = saved_strides;

        let unsupported_strides = [1_i64, before.len() as i64];
        (*dl).strides = unsupported_strides.as_ptr() as *mut i64;
        assert_eq!(
            rkr_frame_positions_from_dlpack(handle, tensor),
            RKRStatus::RKR_STATUS_VALIDATION_ERROR
        );
        (*dl).strides = saved_strides;

        (*dl).byte_offset = 8;
        assert_eq!(
            rkr_frame_positions_from_dlpack(handle, tensor),
            RKRStatus::RKR_STATUS_VALIDATION_ERROR
        );
        (*dl).byte_offset = 0;

        (*dl).dtype.lanes = 2;
        assert_eq!(
            rkr_frame_positions_from_dlpack(handle, tensor),
            RKRStatus::RKR_STATUS_VALIDATION_ERROR
        );
        (*dl).dtype.lanes = 1;

        assert_eq!(
            rkr_frame_positions_from_dlpack(handle, tensor),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        // The tensor owns the old column now. A frame atom must not see it.
        let shared = (*tensor).dl_tensor.data.cast::<f64>();
        *shared = 1.0e6;
        rkr_dlpack_delete(tensor);
    }
    let column = frame.positions.f64_slice().expect("f64 positions");
    for i in 0..frame.atom_data.len() {
        let xyz = frame.xyz_at(i);
        assert_eq!(xyz, before[i], "atom {i} moved");
        assert_eq!(xyz, column[i * 3..i * 3 + 3], "atom {i} left the column");
    }
}

#[test]
fn a_row_write_after_import_reaches_the_atom() {
    let mut frame = ConFrameIterator::new(include_str!("../resources/test/tiny_cuh2.con"))
        .next()
        .expect("frame")
        .expect("parse");
    let handle = (&mut frame as *mut ConFrame).cast::<RKRConFrame>();
    let mut tensor: *mut RKRDLManagedTensorVersioned = std::ptr::null_mut();
    unsafe {
        assert_eq!(
            rkr_frame_positions_dlpack(handle, &mut tensor),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_eq!(
            rkr_frame_positions_from_dlpack(handle, tensor),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        rkr_dlpack_delete(tensor);
    }
    frame.positions.set_f64_row(0, [1.25, 2.5, 3.75]);
    assert_eq!(frame.x_at(0), 1.25);
    assert_eq!(frame.y_at(0), 2.5);
    assert_eq!(frame.z_at(0), 3.75);
}

fn tiny_frame() -> ConFrame {
    ConFrameIterator::new(include_str!("../resources/test/tiny_cuh2.con"))
        .next()
        .expect("frame")
        .expect("parse")
}

#[test]
fn an_exported_xyz_pointer_survives_set_f64_row() {
    let mut frame = tiny_frame();
    let handle = (&frame as *const ConFrame).cast::<RKRConFrame>();
    let mut n = 0usize;
    let ptr = unsafe { rkr_frame_xyz_f64(handle, &mut n) };
    assert_eq!(n, frame.atom_data.len());
    assert!(!ptr.is_null());
    frame.positions.set_f64_row(0, [1.25, 2.5, 3.75]);
    unsafe {
        assert_eq!(*ptr, 1.25);
        assert_eq!(*ptr.add(1), 2.5);
        assert_eq!(*ptr.add(2), 3.75);
    }
}

#[test]
fn an_exported_xyz_pointer_survives_set_x() {
    let mut frame = tiny_frame();
    let handle = (&frame as *const ConFrame).cast::<RKRConFrame>();
    let mut n = 0usize;
    let ptr = unsafe { rkr_frame_xyz_f64(handle, &mut n) };
    assert!(!ptr.is_null());
    frame.set_x_at(0, 9.0);
    unsafe {
        assert_eq!(*ptr, 9.0);
    }
    assert_eq!(frame.x_at(0), 9.0);
}

fn export_positions(handle: *mut RKRConFrame) -> *mut RKRDLManagedTensorVersioned {
    let mut tensor: *mut RKRDLManagedTensorVersioned = std::ptr::null_mut();
    unsafe {
        assert_eq!(
            rkr_frame_positions_dlpack(handle, &mut tensor),
            RKRStatus::RKR_STATUS_SUCCESS
        );
    }
    assert!(!tensor.is_null());
    tensor
}

#[test]
fn an_unknown_dtype_code_is_rejected_before_the_tensor_is_deleted() {
    let mut frame = tiny_frame();
    let handle = (&mut frame as *mut ConFrame).cast::<RKRConFrame>();
    let tensor = export_positions(handle);
    unsafe {
        let slot = std::ptr::addr_of_mut!((*tensor).dl_tensor.dtype.code).cast::<u8>();
        let old = slot.read();
        slot.write(18);
        assert_eq!(
            rkr_frame_positions_from_dlpack(handle, tensor),
            RKRStatus::RKR_STATUS_VALIDATION_ERROR
        );
        slot.write(old);
        rkr_dlpack_delete(tensor);
    }
}

#[test]
fn an_unknown_device_code_is_rejected_before_the_tensor_is_deleted() {
    let mut frame = tiny_frame();
    let handle = (&mut frame as *mut ConFrame).cast::<RKRConFrame>();
    let tensor = export_positions(handle);
    unsafe {
        let slot = std::ptr::addr_of_mut!((*tensor).dl_tensor.device.device_type).cast::<u32>();
        let old = slot.read();
        slot.write(99);
        assert_eq!(
            rkr_frame_positions_from_dlpack(handle, tensor),
            RKRStatus::RKR_STATUS_FEATURE_DISABLED
        );
        slot.write(old);
        rkr_dlpack_delete(tensor);
    }
}
