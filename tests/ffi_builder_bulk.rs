//! Bulk exercise of the C ABI frame-builder and frame-metric surface.
//!
//! These paths are large and were under-instrumented when coverage only
//! enabled `rpc,python`. One coherent builder→build→read walk hits setters,
//! getters, flat arrays, DLPack exports, metrics, iterators, and writers.

use std::ffi::{CStr, CString};
use std::ptr;

use readcon_core::ffi::*;

fn builder() -> *mut RKRConFrameBuilder {
    let cell = [15.0_f64, 15.0, 15.0];
    let angles = [90.0_f64, 90.0, 90.0];
    unsafe {
        rkr_frame_new(
            cell.as_ptr(),
            angles.as_ptr(),
            ptr::null(),
            ptr::null(),
            ptr::null(),
            ptr::null(),
        )
    }
}

#[test]
fn builder_bulk_setters_getters_and_metrics() {
    let b = builder();
    assert!(!b.is_null());
    let cu = CString::new("Cu").unwrap();
    let h = CString::new("H").unwrap();

    unsafe {
        assert_eq!(
            rkr_frame_add_atom(b, cu.as_ptr(), 0.0, 0.0, 0.0, false, 0, 63.546),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_eq!(
            rkr_frame_add_atom(b, h.as_ptr(), 1.0, 1.0, 1.0, false, 1, 1.008),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_eq!(rkr_frame_builder_atom_count(b), 2);

        assert_eq!(
            rkr_frame_builder_set_atom_position(b, 0, 0.5, 0.5, 0.5),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        let vel = [0.1_f64, 0.2, 0.3];
        assert_eq!(
            rkr_frame_builder_set_atom_velocity(b, 0, vel.as_ptr()),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        let force = [-0.1_f64, -0.2, -0.3];
        assert_eq!(
            rkr_frame_builder_set_atom_force(b, 0, force.as_ptr()),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_eq!(
            rkr_frame_builder_set_atom_energy(b, 0, -1.5),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_eq!(
            rkr_frame_builder_set_atom_mass(b, 0, 63.5),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_eq!(
            rkr_frame_builder_set_atom_id(b, 0, 42),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_eq!(
            rkr_frame_builder_set_atom_fixed(b, 1, true, false, true),
            RKRStatus::RKR_STATUS_SUCCESS
        );

        let last_v = [0.01_f64, 0.02, 0.03];
        assert_eq!(
            rkr_frame_builder_set_last_velocity(b, last_v.as_ptr()),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        let last_f = [1.0_f64, 2.0, 3.0];
        assert_eq!(
            rkr_frame_builder_set_last_force(b, last_f.as_ptr()),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_eq!(
            rkr_frame_builder_set_last_energy(b, -0.25),
            RKRStatus::RKR_STATUS_SUCCESS
        );

        let pos = [0.0, 0.0, 0.0, 1.1, 1.2, 1.3];
        assert_eq!(
            rkr_frame_builder_set_positions_from_flat(b, pos.as_ptr(), pos.len()),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        let forces = [0.0, 0.0, 0.0, 0.1, 0.2, 0.3];
        assert_eq!(
            rkr_frame_builder_set_forces_from_flat(b, forces.as_ptr(), forces.len()),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        let energies = [-1.0_f64, -2.0];
        assert_eq!(
            rkr_frame_builder_set_atom_energies_from_flat(b, energies.as_ptr(), energies.len()),
            RKRStatus::RKR_STATUS_SUCCESS
        );

        let mut xyz = [0.0_f64; 3];
        assert_eq!(
            rkr_frame_builder_get_atom_position(b, 1, xyz.as_mut_ptr()),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert!((xyz[0] - 1.1).abs() < 1e-12);

        let mut e = 0.0;
        let mut has = false;
        assert_eq!(
            rkr_frame_builder_get_atom_energy(b, 0, &mut e, &mut has),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        let mut m = 0.0;
        assert_eq!(
            rkr_frame_builder_get_atom_mass(b, 0, &mut m),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        let mut has_v = false;
        let _ = rkr_frame_builder_get_atom_velocity(b, 0, xyz.as_mut_ptr(), &mut has_v);
        let mut has_f = false;
        let _ = rkr_frame_builder_get_atom_force(b, 0, xyz.as_mut_ptr(), &mut has_f);

        let meta = CString::new(
            r#"{"con_spec_version":3,"units":{"length":"angstrom","energy":"eV"}}"#,
        )
        .unwrap();
        let _ = rkr_frame_builder_set_metadata_json(b, meta.as_ptr());
        let _ = rkr_frame_builder_set_energy(b, -12.5);
        let _ = rkr_frame_builder_set_frame_index(b, 3);
        let _ = rkr_frame_builder_set_time(b, 1.5);
        let _ = rkr_frame_builder_set_timestep(b, 0.5);
        let _ = rkr_frame_builder_set_neb_bead(b, 2);
        let _ = rkr_frame_builder_set_neb_band(b, 1);
        let key = CString::new("note").unwrap();
        let val = CString::new("bulk-test").unwrap();
        let _ = rkr_frame_builder_set_string_metadata(b, key.as_ptr(), val.as_ptr());
        let skey = CString::new("scale").unwrap();
        let _ = rkr_frame_builder_set_scalar_metadata(b, skey.as_ptr(), 2.5);

        // clone still-valid builder
        let cloned = rkr_frame_builder_clone(b);
        if !cloned.is_null() {
            free_rkr_frame_builder(cloned);
        }

        for export in [
            rkr_frame_builder_positions_dlpack as unsafe extern "C" fn(_, _) -> _,
            rkr_frame_builder_velocities_dlpack,
            rkr_frame_builder_forces_dlpack,
            rkr_frame_builder_atom_energies_dlpack,
            rkr_frame_builder_masses_dlpack,
            rkr_frame_builder_atom_ids_dlpack,
        ] {
            let mut tensor: *mut RKRDLManagedTensorVersioned = ptr::null_mut();
            let st = export(b, &mut tensor);
            if st == RKRStatus::RKR_STATUS_SUCCESS && !tensor.is_null() {
                rkr_dlpack_delete(tensor);
            }
        }
        for export in [
            rkr_frame_builder_positions_dlpack_ex as unsafe extern "C" fn(_, _, _) -> _,
            rkr_frame_builder_velocities_dlpack_ex,
            rkr_frame_builder_forces_dlpack_ex,
            rkr_frame_builder_atom_energies_dlpack_ex,
            rkr_frame_builder_masses_dlpack_ex,
            rkr_frame_builder_atom_ids_dlpack_ex,
        ] {
            let mut tensor: *mut RKRDLManagedTensorVersioned = ptr::null_mut();
            let st = export(b, ptr::null(), &mut tensor);
            if st == RKRStatus::RKR_STATUS_SUCCESS && !tensor.is_null() {
                rkr_dlpack_delete(tensor);
            }
        }

        let _ = rkr_frame_builder_positions_data(b);
        let _ = rkr_frame_builder_velocities_data(b);
        let _ = rkr_frame_builder_forces_data(b);
        let _ = rkr_frame_builder_atom_energies_data(b);

        let _ = rkr_frame_builder_clear_atom_velocity(b, 0);
        let _ = rkr_frame_builder_clear_atom_force(b, 0);
        let _ = rkr_frame_builder_clear_atom_energy(b, 0);

        // build consumes the builder
        let frame = rkr_frame_builder_build(b);
        assert!(!frame.is_null());

        assert!(rkr_frame_atom_count(frame) >= 1);
        let _ = rkr_frame_energy(frame);
        let _ = rkr_frame_index_energy(frame);
        let _ = rkr_frame_total_mass(frame);
        let _ = rkr_frame_cell_volume(frame);
        let _ = rkr_frame_fmax(frame);
        let _ = rkr_frame_sections_mask(frame);
        let _ = rkr_frame_index_natoms(frame);
        let _ = rkr_frame_spec_version(frame);
        let _ = rkr_frame_frame_index(frame);
        let _ = rkr_frame_time(frame);
        let _ = rkr_frame_timestep(frame);
        let _ = rkr_frame_neb_bead(frame);
        let _ = rkr_frame_neb_band(frame);

        let formula = rkr_frame_composition_formula(frame);
        if !formula.is_null() {
            rkr_free_string(formula);
        }
        let meta_json = rkr_frame_metadata_json(frame);
        if !meta_json.is_null() {
            rkr_free_string(meta_json);
        }
        let pot = rkr_frame_potential_type(frame);
        if !pot.is_null() {
            rkr_free_string(pot);
        }
        let proj = rkr_frame_index_projection_json(frame);
        if !proj.is_null() {
            rkr_free_string(proj);
        }

        let _ = rkr_frame_atom_index_by_id(frame, 42);
        let _ = rkr_frame_bond_count(frame);

        let mut ids = [0u64; 4];
        let _ = rkr_frame_copy_atom_ids(frame, ids.as_mut_ptr(), ids.len());

        free_rkr_frame(frame);
    }

    assert_eq!(rkr_con_spec_version(), 3);
    let ver = unsafe { CStr::from_ptr(rkr_library_version()) };
    assert!(!ver.to_bytes().is_empty());
    let sym = CString::new("Cu").unwrap();
    let z = unsafe { rkr_symbol_to_z(sym.as_ptr()) };
    assert!(z > 0);
    let back = unsafe { CStr::from_ptr(rkr_z_to_symbol(z)) };
    assert_eq!(back.to_str().unwrap(), "Cu");
    let msg = unsafe { CStr::from_ptr(rkr_status_message(RKRStatus::RKR_STATUS_SUCCESS)) };
    assert!(!msg.to_bytes().is_empty());
}

#[test]
fn iterator_and_writer_surface() {
    let path = CString::new("resources/test/tiny_cuh2.con").unwrap();
    unsafe {
        let it = read_con_file_iterator(path.as_ptr());
        assert!(!it.is_null());
        let frame = con_frame_iterator_next(it);
        assert!(!frame.is_null());
        assert!(rkr_frame_atom_count(frame) >= 1);

        let cframe = rkr_frame_to_c_frame(frame);
        if !cframe.is_null() {
            free_c_frame(cframe);
        }

        let mut buf = [0i8; 128];
        let _ = rkr_frame_get_header_line(frame, true, 0, buf.as_mut_ptr(), buf.len());
        let s = rkr_frame_get_header_line_cpp(frame, true, 0);
        if !s.is_null() {
            rkr_free_string(s);
        }

        free_rkr_frame(frame);
        loop {
            let f = con_frame_iterator_next(it);
            if f.is_null() {
                break;
            }
            free_rkr_frame(f);
        }
        free_con_frame_iterator(it);

        let data = std::fs::read("resources/test/tiny_cuh2.con").unwrap();
        let it2 = read_con_buffer_iterator(data.as_ptr(), data.len());
        if !it2.is_null() {
            let f = con_frame_iterator_next(it2);
            if !f.is_null() {
                free_rkr_frame(f);
            }
            free_con_frame_iterator(it2);
        }
        let cstr = CString::new(data).unwrap();
        let it3 = read_con_string_iterator(cstr.as_ptr());
        if !it3.is_null() {
            let f = con_frame_iterator_next(it3);
            if !f.is_null() {
                free_rkr_frame(f);
            }
            free_con_frame_iterator(it3);
        }
    }

    let dir = tempfile::tempdir().unwrap();
    let out = dir.path().join("bulk.con");
    let cpath = CString::new(out.to_str().unwrap()).unwrap();
    unsafe {
        let w = create_writer_from_path_c(cpath.as_ptr());
        assert!(!w.is_null());
        let _ = rkr_writer_set_canonical(w, 1);
        let _ = rkr_writer_is_canonical(w);
        let mut n = 0usize;
        let arr = rkr_read_all_frames(path.as_ptr(), &mut n);
        assert!(!arr.is_null() && n >= 1);
        let status = rkr_writer_extend(w, arr as *const *const RKRConFrame, n);
        assert_eq!(status, RKRStatus::RKR_STATUS_SUCCESS);
        free_rkr_writer(w);
        free_rkr_frame_array(arr, n);

        let w2 = create_writer_from_path_with_precision_c(cpath.as_ptr(), 8);
        if !w2.is_null() {
            free_rkr_writer(w2);
        }
    }
}
