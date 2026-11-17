//! A positions import while an exported DLPack tensor shares the column.
//!
//! The atoms of a parsed frame address its position column. A CPU export
//! shares that column with the tensor, so the import's first row write
//! copies it. Atoms left on the old column read the tensor's buffer, and
//! freed memory once the tensor is deleted.

use readcon_core::ffi::{
    RKRConFrame, RKRDLManagedTensorVersioned, RKRStatus, rkr_dlpack_delete,
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
    let before: Vec<[f64; 3]> = frame
        .atom_data
        .iter()
        .map(|atom| [atom.x(), atom.y(), atom.z()])
        .collect();
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
        // The tensor owns the old column now. A frame atom must not see it.
        let shared = (*tensor).dl_tensor.data.cast::<f64>();
        *shared = 1.0e6;
        rkr_dlpack_delete(tensor);
    }
    let column = frame.positions.f64_slice().expect("f64 positions");
    for (i, atom) in frame.atom_data.iter().enumerate() {
        let xyz = [atom.x(), atom.y(), atom.z()];
        assert_eq!(xyz, before[i], "atom {i} moved");
        assert_eq!(xyz, column[i * 3..i * 3 + 3], "atom {i} left the column");
    }
}
