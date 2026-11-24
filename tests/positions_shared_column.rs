//! A positions import while an exported DLPack tensor shares the column.
//!
//! A CPU export shares that column with the tensor, so the import's first
//! row write copies it. The import copies those rows onto the atoms as well.
//! Writing the tensor's buffer and deleting it must not change the atoms.

use readcon_core::ffi::{
    RKRConFrame, RKRDLManagedTensorVersioned, RKRStatus, rkr_dl_type_code, rkr_dlpack_delete,
    rkr_frame_positions_dlpack, rkr_frame_positions_from_dlpack,
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
