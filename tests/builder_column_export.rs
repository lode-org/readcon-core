//! Each builder column export is the allocation base.
//!
//! A pointer from a slice is retired by the next in-place setter. These
//! tests export the pointer and then call every setter for that column.

use std::ffi::CString;
use std::ptr;

use readcon_core::ffi::{
    RKRDLDataType, RKRDLDevice, RKRDlpackExportOptions, RKRStatus, free_rkr_frame_builder,
    rkr_dl_device_type, rkr_dl_type_code, rkr_dlpack_delete, rkr_frame_add_atom_full,
    rkr_frame_builder_atom_energies_data, rkr_frame_builder_atom_ids_data,
    rkr_frame_builder_atom_ids_dlpack_ex, rkr_frame_builder_displacements_data,
    rkr_frame_builder_forces_data, rkr_frame_builder_masses_data, rkr_frame_builder_positions_data,
    rkr_frame_builder_set_atom_displacement, rkr_frame_builder_set_atom_energies_from_flat,
    rkr_frame_builder_set_atom_energy, rkr_frame_builder_set_atom_force,
    rkr_frame_builder_set_atom_id, rkr_frame_builder_set_atom_mass,
    rkr_frame_builder_set_atom_position, rkr_frame_builder_set_atom_spread,
    rkr_frame_builder_set_atom_velocity, rkr_frame_builder_set_displacements_from_flat,
    rkr_frame_builder_set_forces_from_flat, rkr_frame_builder_set_last_displacement,
    rkr_frame_builder_set_last_energy, rkr_frame_builder_set_last_force,
    rkr_frame_builder_set_last_spread, rkr_frame_builder_set_last_velocity,
    rkr_frame_builder_set_positions_from_flat, rkr_frame_builder_set_spreads_from_flat,
    rkr_frame_builder_spreads_data, rkr_frame_builder_velocities_data, rkr_frame_new,
};

fn builder() -> *mut readcon_core::ffi::RKRConFrameBuilder {
    let cell = [10.0, 10.0, 10.0];
    let angles = [90.0, 90.0, 90.0];
    let symbol = CString::new("Cu").unwrap();
    let velocity = [0.1, 0.2, 0.3];
    let force = [0.4, 0.5, 0.6];
    unsafe {
        let builder = rkr_frame_new(
            cell.as_ptr(),
            angles.as_ptr(),
            ptr::null(),
            ptr::null(),
            ptr::null(),
            ptr::null(),
        );
        assert!(!builder.is_null());
        for index in 0..2 {
            assert_eq!(
                rkr_frame_add_atom_full(
                    builder,
                    symbol.as_ptr(),
                    index as f64,
                    0.0,
                    0.0,
                    false,
                    false,
                    false,
                    index,
                    63.5,
                    velocity.as_ptr(),
                    force.as_ptr(),
                ),
                RKRStatus::RKR_STATUS_SUCCESS
            );
        }
        let row = [0.0, 0.0, 0.0];
        assert_eq!(
            rkr_frame_builder_set_atom_displacement(builder, 0, row.as_ptr()),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_eq!(
            rkr_frame_builder_set_atom_spread(builder, 0, row.as_ptr()),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_eq!(
            rkr_frame_builder_set_atom_energy(builder, 0, 0.0),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        builder
    }
}

#[test]
fn exported_positions_survive_set_positions_from_flat_and_set_atom_position() {
    let builder = builder();
    let ptr = unsafe { rkr_frame_builder_positions_data(builder) };
    assert!(!ptr.is_null());
    let flat = [1.25, 2.5, 3.75, 4.0, 5.0, 6.0];
    unsafe {
        assert_eq!(
            rkr_frame_builder_set_positions_from_flat(builder, flat.as_ptr(), flat.len()),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_eq!(*ptr, 1.25);
        assert_eq!(*ptr.add(1), 2.5);
        assert_eq!(*ptr.add(2), 3.75);
        assert_eq!(
            rkr_frame_builder_set_atom_position(builder, 0, 9.0, 8.0, 7.0),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_eq!(*ptr, 9.0);
        assert_eq!(*ptr.add(1), 8.0);
        assert_eq!(*ptr.add(2), 7.0);
        free_rkr_frame_builder(builder);
    }
}

#[test]
fn exported_velocities_survive_set_atom_velocity_and_set_last_velocity() {
    let builder = builder();
    let ptr = unsafe { rkr_frame_builder_velocities_data(builder) };
    assert!(!ptr.is_null());
    let row = [1.5, 2.5, 3.5];
    let last = [4.5, 5.5, 6.5];
    unsafe {
        assert_eq!(
            rkr_frame_builder_set_atom_velocity(builder, 0, row.as_ptr()),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_eq!(*ptr, 1.5);
        assert_eq!(*ptr.add(2), 3.5);
        assert_eq!(
            rkr_frame_builder_set_last_velocity(builder, last.as_ptr()),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_eq!(*ptr.add(3), 4.5);
        assert_eq!(*ptr.add(5), 6.5);
        free_rkr_frame_builder(builder);
    }
}

#[test]
fn exported_forces_survive_every_force_setter() {
    let builder = builder();
    let ptr = unsafe { rkr_frame_builder_forces_data(builder) };
    assert!(!ptr.is_null());
    let flat = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0];
    let row = [7.0, 8.0, 9.0];
    let last = [0.25, 0.5, 0.75];
    unsafe {
        assert_eq!(
            rkr_frame_builder_set_forces_from_flat(builder, flat.as_ptr(), flat.len()),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_eq!(*ptr, 1.0);
        assert_eq!(
            rkr_frame_builder_set_atom_force(builder, 0, row.as_ptr()),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_eq!(*ptr, 7.0);
        assert_eq!(
            rkr_frame_builder_set_last_force(builder, last.as_ptr()),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_eq!(*ptr.add(3), 0.25);
        free_rkr_frame_builder(builder);
    }
}

#[test]
fn exported_displacements_survive_every_displacement_setter() {
    let builder = builder();
    let ptr = unsafe { rkr_frame_builder_displacements_data(builder) };
    assert!(!ptr.is_null());
    let flat = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0];
    let row = [7.0, 8.0, 9.0];
    let last = [0.25, 0.5, 0.75];
    unsafe {
        assert_eq!(
            rkr_frame_builder_set_displacements_from_flat(builder, flat.as_ptr(), flat.len()),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_eq!(*ptr, 1.0);
        assert_eq!(
            rkr_frame_builder_set_atom_displacement(builder, 0, row.as_ptr()),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_eq!(*ptr, 7.0);
        assert_eq!(
            rkr_frame_builder_set_last_displacement(builder, last.as_ptr()),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_eq!(*ptr.add(3), 0.25);
        free_rkr_frame_builder(builder);
    }
}

#[test]
fn exported_spreads_survive_every_spread_setter() {
    let builder = builder();
    let ptr = unsafe { rkr_frame_builder_spreads_data(builder) };
    assert!(!ptr.is_null());
    let flat = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0];
    let row = [0.5, 0.5, 0.5];
    let last = [0.25, 0.25, 0.25];
    unsafe {
        assert_eq!(
            rkr_frame_builder_set_spreads_from_flat(builder, flat.as_ptr(), flat.len()),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_eq!(*ptr, 1.0);
        assert_eq!(
            rkr_frame_builder_set_atom_spread(builder, 0, row.as_ptr()),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_eq!(*ptr, 0.5);
        assert_eq!(
            rkr_frame_builder_set_last_spread(builder, last.as_ptr()),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_eq!(*ptr.add(3), 0.25);
        free_rkr_frame_builder(builder);
    }
}

#[test]
fn exported_energies_survive_every_energy_setter() {
    let builder = builder();
    let ptr = unsafe { rkr_frame_builder_atom_energies_data(builder) };
    assert!(!ptr.is_null());
    let flat = [1.5, 2.5];
    unsafe {
        assert_eq!(
            rkr_frame_builder_set_atom_energies_from_flat(builder, flat.as_ptr(), flat.len()),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_eq!(*ptr, 1.5);
        assert_eq!(
            rkr_frame_builder_set_atom_energy(builder, 0, 9.0),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_eq!(*ptr, 9.0);
        assert_eq!(
            rkr_frame_builder_set_last_energy(builder, 4.0),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_eq!(*ptr.add(1), 4.0);
        free_rkr_frame_builder(builder);
    }
}

#[test]
fn exported_masses_survive_set_atom_mass() {
    let builder = builder();
    let ptr = unsafe { rkr_frame_builder_masses_data(builder) };
    assert!(!ptr.is_null());
    unsafe {
        assert_eq!(
            rkr_frame_builder_set_atom_mass(builder, 0, 12.0),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_eq!(*ptr, 12.0);
        free_rkr_frame_builder(builder);
    }
}

#[test]
fn an_exported_atom_id_tensor_keeps_its_values_after_set_atom_id() {
    let builder = builder();
    let column = unsafe { rkr_frame_builder_atom_ids_data(builder) };
    assert!(!column.is_null());
    let mut tensor = ptr::null_mut();
    unsafe {
        let opts = RKRDlpackExportOptions {
            dtype: RKRDLDataType {
                code: rkr_dl_type_code::RKR_DL_UINT,
                bits: 64,
                lanes: 1,
            },
            device: RKRDLDevice {
                device_type: rkr_dl_device_type::RKR_DL_CPU,
                device_id: 0,
            },
        };
        assert_eq!(
            rkr_frame_builder_atom_ids_dlpack_ex(builder, &opts, &mut tensor),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert!(!tensor.is_null());
        let data = std::ptr::addr_of!((*tensor).dl_tensor.data).read();
        let exported = data.cast::<u64>();
        assert!(!exported.is_null());
        assert_ne!(exported.cast_const(), column);
        assert_eq!(*exported, 0);
        assert_eq!(*exported.add(1), 1);
        assert_eq!(
            rkr_frame_builder_set_atom_id(builder, 0, 42),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_eq!(*exported, 0);
        assert_eq!(*exported.add(1), 1);
        assert_eq!(*column, 42);
        rkr_dlpack_delete(tensor);
        free_rkr_frame_builder(builder);
    }
}

#[test]
fn exported_atom_ids_survive_set_atom_id() {
    let builder = builder();
    let ptr = unsafe { rkr_frame_builder_atom_ids_data(builder) };
    assert!(!ptr.is_null());
    unsafe {
        assert_eq!(
            rkr_frame_builder_set_atom_id(builder, 0, 42),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_eq!(*ptr, 42);
        free_rkr_frame_builder(builder);
    }
}
