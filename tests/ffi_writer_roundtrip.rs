use readcon_core::ffi::*;
use readcon_core::iterators::ConFrameIterator;
use readcon_core::types::ConFrameBuilder;
use std::ffi::CString;
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
                [atom.x, atom.y, atom.z].map(f64::to_bits),
                [value, -value, -0.0].map(f64::to_bits)
            );
            assert_eq!(
                atom.force.unwrap().map(f64::to_bits),
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
        free_rkr_writer(writer);
    }
}
