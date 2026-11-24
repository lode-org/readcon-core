use readcon_core::ffi::*;
use readcon_core::iterators::ConFrameIterator;
use readcon_core::types::ConFrameBuilder;
use std::ffi::{CStr, CString};
use std::ptr;

#[test]
fn c_writer_preserves_finite_values_and_flushes_before_close() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("stencil.con");
    let name = CString::new(path.to_str().unwrap()).unwrap();
    let values = [
        0.0,
        -0.0,
        f64::from_bits(1),
        -f64::MIN_POSITIVE,
        1.5278901892825658e-28,
        1.2345678901234567e100,
        f64::MAX,
    ];
    unsafe {
        let writer = create_writer_from_path_round_trip_c(name.as_ptr());
        assert!(!writer.is_null());
        for value in values {
            let mut builder = ConFrameBuilder::new([10.0; 3], [90.0; 3]);
            builder.set_energy(value);
            builder
                .add_atom("H", value, -value, -0.0, [false; 3], 7, 1.0)
                .with_force([value, -value, -0.0]);
            let frame = builder.build().unwrap();
            let handle = (&frame as *const _) as *const RKRConFrame;
            assert_eq!(
                rkr_writer_extend(writer, &handle, 1),
                RKRStatus::RKR_STATUS_SUCCESS
            );
        }
        assert_eq!(rkr_writer_flush(writer), RKRStatus::RKR_STATUS_SUCCESS);
        let text = std::fs::read_to_string(&path).unwrap();
        let frames = ConFrameIterator::new(&text)
            .collect::<Result<Vec<_>, _>>()
            .unwrap();
        assert_eq!(frames.len(), values.len());
        for (frame, value) in frames.iter().zip(values) {
            let atom = &frame.atom_data[0];
            assert_eq!(
                [frame.x_at(0), frame.y_at(0), frame.z_at(0)].map(f64::to_bits),
                [value, -value, -0.0].map(f64::to_bits)
            );
            assert_eq!(
                atom.force().unwrap().map(f64::to_bits),
                [value, -value, -0.0].map(f64::to_bits)
            );
            assert_eq!(frame.header.energy().unwrap().to_bits(), value.to_bits());
        }
        free_rkr_writer(writer);
        assert!(create_writer_from_path_round_trip_c(ptr::null()).is_null());
        assert_eq!(
            rkr_writer_flush(ptr::null_mut()),
            RKRStatus::RKR_STATUS_NULL_POINTER
        );
    }
}

#[cfg(target_os = "linux")]
#[test]
fn c_writer_flush_reports_full_device() {
    let path = CString::new("/dev/full").unwrap();
    let mut builder = ConFrameBuilder::new([10.0; 3], [90.0; 3]);
    builder.add_atom("H", 0.0, 0.0, 0.0, [false; 3], 0, 1.0);
    let frame = builder.build().unwrap();
    unsafe {
        let writer = create_writer_from_path_round_trip_c(path.as_ptr());
        assert!(!writer.is_null());
        let handle = (&frame as *const _) as *const RKRConFrame;
        assert_eq!(
            rkr_writer_extend(writer, &handle, 1),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_eq!(rkr_writer_flush(writer), RKRStatus::RKR_STATUS_IO_ERROR);
        let message = CStr::from_ptr(rkr_last_error_message());
        assert!(
            !message.to_bytes().is_empty(),
            "flush must keep the underlying I/O message"
        );
        free_rkr_writer(writer);
    }
}

#[test]
fn c_writer_reports_repeated_atom_id() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("duplicate.con");
    let name = CString::new(path.to_str().unwrap()).unwrap();
    unsafe {
        let writer = create_writer_from_path_c(name.as_ptr());
        assert!(!writer.is_null());
        let mut builder = ConFrameBuilder::new([10.0; 3], [90.0; 3]);
        builder.add_atom("H", 0.0, 0.0, 0.0, [false; 3], 1, 1.0);
        builder.add_atom("H", 1.0, 0.0, 0.0, [false; 3], 1, 1.0);
        let frame = builder.build().unwrap();
        let handle = (&frame as *const _) as *const RKRConFrame;
        assert_eq!(
            rkr_writer_extend(writer, &handle, 1),
            RKRStatus::RKR_STATUS_IO_ERROR
        );
        let message = CStr::from_ptr(rkr_last_error_message()).to_str().unwrap();
        assert!(message.contains("atom id 1 is repeated"), "{message}");
        assert_eq!(
            CStr::from_ptr(rkr_status_message(RKRStatus::RKR_STATUS_IO_ERROR))
                .to_str()
                .unwrap(),
            "I/O error"
        );
        free_rkr_writer(writer);

        let writer = create_writer_from_path_c(name.as_ptr());
        let mut builder = ConFrameBuilder::new([10.0; 3], [90.0; 3]);
        builder.add_atom("H", 0.0, 0.0, 0.0, [false; 3], 1, 1.0);
        let frame = builder.build().unwrap();
        let handle = (&frame as *const _) as *const RKRConFrame;
        assert_eq!(
            rkr_writer_extend(writer, &handle, 1),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert!(rkr_last_error_message().is_null());
        free_rkr_writer(writer);
    }
}

#[test]
fn binding_writer_reports_repeated_atom_id() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("duplicate.con");
    let name = CString::new(path.to_str().unwrap()).unwrap();
    unsafe {
        let writer = create_writer_from_path_c(name.as_ptr());
        assert!(!writer.is_null());
        let mut builder = ConFrameBuilder::new([10.0; 3], [90.0; 3]);
        builder.add_atom("H", 0.0, 0.0, 0.0, [true, false, false], 1, 1.008);
        builder.add_atom("H", 1.0, 0.0, 0.0, [false, true, false], 1, 1.008);
        let mut frame = builder.build().unwrap();
        let handle = (&mut frame as *mut _) as *mut RKRConFrame;
        let handles = [handle];
        assert_eq!(
            rkr_writer_extend_binding(writer, handles.as_ptr(), 1),
            RKRStatus::RKR_STATUS_IO_ERROR
        );
        let message = CStr::from_ptr(rkr_last_error_message()).to_str().unwrap();
        assert!(message.contains("atom id 1 is repeated"), "{message}");
        assert_eq!(
            CStr::from_ptr(rkr_status_message(RKRStatus::RKR_STATUS_IO_ERROR))
                .to_str()
                .unwrap(),
            "I/O error"
        );
        free_rkr_writer(writer);
    }
}

#[test]
fn c_writer_round_trips_major4_velocity_and_units_time() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("velocity.con");
    let name = CString::new(path.to_str().unwrap()).unwrap();
    let velocity = [1.5, -0.25, 0.0];
    let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
    builder
        .set_units(serde_json::json!({
            "length": "angstrom",
            "energy": "eV",
            "mass": "amu",
            "time": "fs"
        }))
        .unwrap();
    builder
        .add_atom("H", 0.0, 0.0, 0.0, [false, false, false], 7, 1.008)
        .with_velocity(velocity);
    let frame = builder.build().unwrap();
    unsafe {
        let writer = create_writer_from_path_c(name.as_ptr());
        assert!(!writer.is_null());
        let handle = (&frame as *const _) as *const RKRConFrame;
        assert_eq!(
            rkr_writer_extend(writer, &handle, 1),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_eq!(rkr_writer_flush(writer), RKRStatus::RKR_STATUS_SUCCESS);
        free_rkr_writer(writer);

        let read_back = rkr_read_first_frame(name.as_ptr());
        assert!(!read_back.is_null());
        assert_eq!(rkr_frame_spec_version(read_back), 4);
        let json = rkr_frame_metadata_json(read_back);
        assert!(!json.is_null());
        let text = CStr::from_ptr(json).to_str().unwrap();
        assert!(text.contains("\"time\":\"fs\""), "{text}");
        assert!(text.contains("\"con_spec_version\":4"), "{text}");
        let mut got = [0.0; 3];
        assert_eq!(
            rkr_frame_copy_velocities(read_back, got.as_mut_ptr(), got.len()),
            RKRStatus::RKR_STATUS_SUCCESS
        );
        assert_eq!(got.map(f64::to_bits), velocity.map(f64::to_bits));
        rkr_free_string(json);
        free_rkr_frame(read_back);
    }
}
