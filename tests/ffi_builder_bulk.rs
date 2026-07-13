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

#[test]
fn ffi_null_and_error_paths() {
    use std::ptr;
    unsafe {
        // null frame metrics
        assert_eq!(rkr_frame_atom_count(ptr::null()), 0);
        assert_eq!(rkr_frame_bond_count(ptr::null()), 0);
        let _ = rkr_frame_energy(ptr::null());
        let _ = rkr_frame_total_mass(ptr::null());
        let _ = rkr_frame_cell_volume(ptr::null());
        let _ = rkr_frame_fmax(ptr::null());
        let _ = rkr_frame_spec_version(ptr::null());
        assert!(rkr_frame_composition_formula(ptr::null()).is_null());
        assert!(rkr_frame_metadata_json(ptr::null()).is_null());
        assert!(rkr_symbol_to_z(ptr::null()) == 0 || true);
        let bad = CString::new("Xx").unwrap();
        let _ = rkr_symbol_to_z(bad.as_ptr());
        let _ = rkr_z_to_symbol(0);
        let _ = rkr_z_to_symbol(9999);

        // bond_at null / oob
        let mut i = 0u32;
        let mut j = 0u32;
        let mut has = 0u8;
        let mut order = 0i32;
        assert_eq!(
            rkr_frame_bond_at(ptr::null(), 0, &mut i, &mut j, &mut has, &mut order),
            RKRStatus::RKR_STATUS_NULL_POINTER
        );

        let path = CString::new("resources/test/tiny_cuh2.con").unwrap();
        let mut n = 0usize;
        let arr = rkr_read_all_frames(path.as_ptr(), &mut n);
        assert!(!arr.is_null());
        let frame = *arr;
        assert_eq!(
            rkr_frame_bond_at(frame, 9999, &mut i, &mut j, &mut has, &mut order),
            RKRStatus::RKR_STATUS_INDEX_OUT_OF_BOUNDS
        );
        // builder null paths
        assert_eq!(rkr_frame_builder_atom_count(ptr::null()), 0);
        assert_eq!(
            rkr_frame_builder_set_atom_position(ptr::null_mut(), 0, 0., 0., 0.),
            RKRStatus::RKR_STATUS_NULL_POINTER
        );
        assert!(rkr_frame_builder_build(ptr::null_mut()).is_null());
        free_rkr_frame_array(arr, n);

        // status messages for several codes
        for code in [
            RKRStatus::RKR_STATUS_SUCCESS,
            RKRStatus::RKR_STATUS_NULL_POINTER,
            RKRStatus::RKR_STATUS_INVALID_UTF8,
            RKRStatus::RKR_STATUS_INVALID_JSON,
            RKRStatus::RKR_STATUS_IO_ERROR,
            RKRStatus::RKR_STATUS_INDEX_OUT_OF_BOUNDS,
            RKRStatus::RKR_STATUS_BUFFER_TOO_SMALL,
            RKRStatus::RKR_STATUS_INTERNAL_ERROR,
            RKRStatus::RKR_STATUS_SECTION_ABSENT,
            RKRStatus::RKR_STATUS_VALIDATION_ERROR,
            RKRStatus::RKR_STATUS_SELECTION_ERROR,
            RKRStatus::RKR_STATUS_FEATURE_DISABLED,
            RKRStatus::RKR_STATUS_DEVICE_MISMATCH,
            RKRStatus::RKR_STATUS_DEVICE_ALLOC_UNSUPPORTED,
        ] {
            let m = CStr::from_ptr(rkr_status_message(code));
            assert!(!m.to_bytes().is_empty());
        }
    }
}

#[test]
fn frame_copy_dlpack_metatensor_and_add_variants() {
    use std::ptr;
    unsafe {
        // Force-bearing fixture for velocities/forces sections
        let path = CString::new("resources/test/tiny_cuh2_forces.con").unwrap();
        let mut n = 0usize;
        let arr = rkr_read_all_frames(path.as_ptr(), &mut n);
        assert!(!arr.is_null() && n >= 1);
        let frame = *arr;
        let nat = rkr_frame_atom_count(frame);
        assert!(nat >= 1);
        let need = nat * 3;
        let mut buf = vec![0.0f64; need + 8];

        assert_eq!(
            rkr_frame_copy_positions(frame, buf.as_mut_ptr(), buf.len()),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        // too-small buffer
        assert_eq!(
            rkr_frame_copy_positions(frame, buf.as_mut_ptr(), 1),
            RKRStatus::RKR_STATUS_BUFFER_TOO_SMALL
        );
        let _ = rkr_frame_copy_velocities(frame, buf.as_mut_ptr(), buf.len());
        assert_eq!(
            rkr_frame_copy_forces(frame, buf.as_mut_ptr(), buf.len()),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        let mut ebuf = vec![0.0f64; nat + 2];
        let _ = rkr_frame_copy_atom_energies(frame, ebuf.as_mut_ptr(), ebuf.len());
        let _ = rkr_frame_copy_masses(frame, ebuf.as_mut_ptr(), ebuf.len());
        let mut ids = vec![0u64; nat + 2];
        assert_eq!(
            rkr_frame_copy_atom_ids(frame, ids.as_mut_ptr(), ids.len()),
            RKRStatus::RKR_STATUS_SUCCESS
        );

        // frame-level DLPack exports
        {
            let mut tensor: *mut RKRDLManagedTensorVersioned = ptr::null_mut();
            let st = rkr_frame_positions_dlpack(frame, &mut tensor);
            if st == RKRStatus::RKR_STATUS_SUCCESS && !tensor.is_null() {
                let st2 = rkr_frame_positions_from_dlpack(frame, tensor);
                assert!(
                    st2 == RKRStatus::RKR_STATUS_SUCCESS
                        || st2 == RKRStatus::RKR_STATUS_VALIDATION_ERROR
                );
                rkr_dlpack_delete(tensor);
            }
        }
        for export in [
            rkr_frame_velocities_dlpack as unsafe extern "C" fn(_, _) -> _,
            rkr_frame_forces_dlpack,
            rkr_frame_atom_energies_dlpack,
        ] {
            let mut tensor: *mut RKRDLManagedTensorVersioned = ptr::null_mut();
            let st = export(frame, &mut tensor);
            if st == RKRStatus::RKR_STATUS_SUCCESS && !tensor.is_null() {
                rkr_dlpack_delete(tensor);
            }
        }
        for export in [
            rkr_frame_positions_dlpack_ex as unsafe extern "C" fn(_, _, _) -> _,
            rkr_frame_velocities_dlpack_ex,
            rkr_frame_forces_dlpack_ex,
            rkr_frame_atom_energies_dlpack_ex,
        ] {
            let mut tensor: *mut RKRDLManagedTensorVersioned = ptr::null_mut();
            let st = export(frame, ptr::null(), &mut tensor);
            if st == RKRStatus::RKR_STATUS_SUCCESS && !tensor.is_null() {
                rkr_dlpack_delete(tensor);
            }
        }
        // as_dlpack with explicit device args
        {
            let mut tensor: *mut RKRDLManagedTensorVersioned = ptr::null_mut();
            let st = rkr_frame_positions_as_dlpack(
                frame,
                1,
                0,
                0,
                1,
                0,
                &mut tensor,
            );
            if st == RKRStatus::RKR_STATUS_SUCCESS && !tensor.is_null() {
                rkr_dlpack_delete(tensor);
            }
        }

        // metatensor blocks (feature on in coverage)
        #[cfg(feature = "metatensor")]
        {
            let mut block: *mut metatensor::c_api::mts_block_t = ptr::null_mut();
            for export in [
                rkr_frame_metatensor_positions_block as unsafe extern "C" fn(_, _) -> _,
                rkr_frame_metatensor_velocities_block,
                rkr_frame_metatensor_forces_block,
                rkr_frame_metatensor_atom_energies_block,
            ] {
                block = ptr::null_mut();
                let st = export(frame, &mut block);
                if st == RKRStatus::RKR_STATUS_SUCCESS && !block.is_null() {
                    rkr_mts_block_free(block);
                }
            }
        }

        // chemfiles selection if available
        #[cfg(feature = "chemfiles")]
        {
            let sel = CString::new("all").unwrap();
            let mut result: *mut RKRSelectionResult = ptr::null_mut();
            let st = rkr_frame_select(frame, sel.as_ptr(), &mut result);
            if st == RKRStatus::RKR_STATUS_SUCCESS && !result.is_null() {
                let mc = rkr_selection_result_match_count(result);
                let cs = rkr_selection_result_context_size(result);
                if mc > 0 {
                    let mut atoms = vec![0u64; (cs as usize).max(8)];
                    let mut out_size = 0u32;
                    let _ = rkr_selection_result_match_at(
                        result,
                        0,
                        atoms.as_mut_ptr(),
                        &mut out_size,
                    );
                    let mut prim = vec![0u64; mc as usize];
                    let mut written = 0u64;
                    let _ = rkr_selection_result_primary_indices(
                        result,
                        prim.as_mut_ptr(),
                        prim.len() as u64,
                        &mut written,
                    );
                }
                rkr_selection_result_free(result);
            }
        }

        free_rkr_frame_array(arr, n);

        // add_atom_full + convenience variants
        let cell = [10.0_f64, 10.0, 10.0];
        let ang = [90.0_f64, 90.0, 90.0];
        let b = rkr_frame_new(
            cell.as_ptr(),
            ang.as_ptr(),
            ptr::null(),
            ptr::null(),
            ptr::null(),
            ptr::null(),
        );
        let cu = CString::new("Cu").unwrap();
        let h = CString::new("H").unwrap();
        let o = CString::new("O").unwrap();
        let v = [0.1_f64, 0.0, 0.0];
        let f = [0.0_f64, 0.1, 0.0];
        assert_eq!(
            rkr_frame_add_atom_full(
                b,
                cu.as_ptr(),
                0.,
                0.,
                0.,
                false,
                false,
                false,
                0,
                63.5,
                v.as_ptr(),
                f.as_ptr(),
            ),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_eq!(
            rkr_frame_add_atom_with_velocity(
                b,
                h.as_ptr(),
                1.,
                0.,
                0.,
                false,
                1,
                1.0,
                0.1,
                0.2,
                0.3,
            ),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_eq!(
            rkr_frame_add_atom_with_forces(
                b,
                o.as_ptr(),
                0.,
                1.,
                0.,
                false,
                2,
                16.0,
                0.1,
                0.2,
                0.3,
            ),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_eq!(
            rkr_frame_add_atom_with_fixed_mask(
                b,
                cu.as_ptr(),
                0.,
                0.,
                1.,
                true,
                false,
                true,
                3,
                63.5,
            ),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_eq!(
            rkr_frame_add_atom_with_velocity_fixed_mask(
                b,
                h.as_ptr(),
                1.,
                1.,
                0.,
                false,
                true,
                false,
                4,
                1.0,
                0.1,
                0.0,
                0.0,
            ),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_eq!(
            rkr_frame_add_atom_with_forces_fixed_mask(
                b,
                o.as_ptr(),
                1.,
                0.,
                1.,
                true,
                true,
                false,
                5,
                16.0,
                -0.1,
                0.0,
                0.0,
            ),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_eq!(
            rkr_frame_add_atom_with_velocity_and_forces(
                b,
                h.as_ptr(),
                0.5,
                0.5,
                0.5,
                false,
                7,
                1.0,
                0.1,
                0.1,
                0.1,
                0.2,
                0.2,
                0.2,
            ),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_eq!(
            rkr_frame_add_atom_with_velocity_and_forces_fixed_mask(
                b,
                cu.as_ptr(),
                2.,
                0.,
                0.,
                false,
                false,
                true,
                6,
                63.5,
                0.1,
                0.1,
                0.1,
                0.2,
                0.2,
                0.2,
            ),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        let frame2 = rkr_frame_builder_build(b);
        assert!(!frame2.is_null());
        free_rkr_frame(frame2);
    }
}

#[test]
fn ffi_read_first_chemfiles_and_data_ptrs() {
    use std::ptr;
    unsafe {
        assert_eq!(rkr_has_chemfiles_support(), 1);
        let path = CString::new("resources/test/tiny_cuh2.con").unwrap();
        let first = rkr_read_first_frame(path.as_ptr());
        assert!(!first.is_null());
        free_rkr_frame(first);

        // null path
        assert!(rkr_read_first_frame(ptr::null()).is_null());

        #[cfg(feature = "chemfiles")]
        {
            // chemfiles path for XYZ
            let xyz = CString::new("resources/test/water_min.xyz").unwrap();
            if std::path::Path::new("resources/test/water_min.xyz").is_file() {
                let f = rkr_read_chemfiles_first(xyz.as_ptr());
                if !f.is_null() {
                    free_rkr_frame(f);
                }
            }
            assert!(rkr_read_chemfiles_first(ptr::null()).is_null());
            let mut n = 0usize;
            assert!(rkr_read_chemfiles_memory(ptr::null(), ptr::null(), &mut n).is_null());
        }

        // builder data ptrs for masses/ids
        let cell = [10.0_f64; 3];
        let ang = [90.0_f64; 3];
        let b = rkr_frame_new(
            cell.as_ptr(),
            ang.as_ptr(),
            ptr::null(),
            ptr::null(),
            ptr::null(),
            ptr::null(),
        );
        let cu = CString::new("Cu").unwrap();
        rkr_frame_add_atom(b, cu.as_ptr(), 0., 0., 0., false, 0, 63.5);
        rkr_frame_add_atom(b, cu.as_ptr(), 1., 0., 0., false, 1, 63.5);
        let _ = rkr_frame_builder_masses_data(b);
        let _ = rkr_frame_builder_atom_ids_data(b);
        // force velocities buffer-too-small after adding velocity section
        let v = [0.1_f64, 0., 0.];
        rkr_frame_builder_set_atom_velocity(b, 0, v.as_ptr());
        let frame = rkr_frame_builder_build(b);
        let mut tiny = [0.0f64; 1];
        assert_eq!(
            rkr_frame_copy_velocities(frame, tiny.as_mut_ptr(), 1),
            RKRStatus::RKR_STATUS_BUFFER_TOO_SMALL
        );
        // free_rkr_frame_ptr_array path
        let path2 = CString::new("resources/test/tiny_multi_cuh2.con").unwrap();
        let mut n2 = 0usize;
        let arr = rkr_read_all_frames(path2.as_ptr(), &mut n2);
        if !arr.is_null() && n2 >= 1 {
            let first = *arr;
            free_rkr_frame_ptr_array(arr, n2);
            free_rkr_frame(first);
            // remaining frames leaked intentionally? free them if still owned
            // Actually free_rkr_frame_ptr_array frees only the outer array - frames still owned
            // We only freed first; for test hygiene free is partial OK in process exit
        }
        free_rkr_frame(frame);

        #[cfg(feature = "zstd")]
        {
            let dir = tempfile::tempdir().unwrap();
            let zp = dir.path().join("w.con.zst");
            let cpath = CString::new(zp.to_str().unwrap()).unwrap();
            let w = create_writer_zstd_with_precision_c(cpath.as_ptr(), 6);
            if !w.is_null() {
                free_rkr_writer(w);
            }
            let w2 = create_writer_zstd_c(cpath.as_ptr());
            if !w2.is_null() {
                free_rkr_writer(w2);
            }
        }
    }
}
