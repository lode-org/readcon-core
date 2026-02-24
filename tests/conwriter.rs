mod common;
use readcon_core::iterators::ConFrameIterator;
use readcon_core::types::ConFrameBuilder;
use readcon_core::writer::ConFrameWriter;
use std::fs;
use std::path::Path;

#[test]
fn test_writer_roundtrip() {
    let fdat_original =
        fs::read_to_string(test_case!("tiny_multi_cuh2.con")).expect("Can't find test file.");
    let parser_original = ConFrameIterator::new(&fdat_original);
    let frames_original: Vec<_> = parser_original.map(|r| r.unwrap()).collect();

    // Ensure we have something to test.
    assert!(!frames_original.is_empty());

    let mut buffer: Vec<u8> = Vec::new();

    // Introduce a scope so the writer is dropped and flushes any buffered data, releasing the mutable reference to the buffer.
    {
        let mut writer = ConFrameWriter::new(&mut buffer);
        writer
            .extend(frames_original.iter())
            .expect("Failed to write to buffer.");
    } // `writer` is dropped here, ensuring all data is flushed and the mutable reference ends.

    // Convert the buffer back to a string and re-parse.
    // This move is now valid because the borrow has ended.
    let fdat_roundtrip = String::from_utf8(buffer).expect("Buffer is not valid UTF-8.");
    let parser_roundtrip = ConFrameIterator::new(&fdat_roundtrip);
    let frames_roundtrip: Vec<_> = parser_roundtrip.map(|r| r.unwrap()).collect();

    assert_eq!(
        frames_original.len(),
        frames_roundtrip.len(),
        "Number of frames should be the same after roundtrip."
    );
    assert_eq!(
        frames_original, frames_roundtrip,
        "Frame data should be identical after a read-write-read roundtrip."
    );
}

#[test]
fn test_builder_roundtrip() {
    let mut builder = ConFrameBuilder::new([15.345600, 21.702000, 100.000000], [90.0, 90.0, 90.0])
        .prebox_header(["Random Number Seed".to_string(), "Time".to_string()])
        .postbox_header(["0 0".to_string(), "218 0 1".to_string()]);
    builder.add_atom("Cu", 0.639400000000001, 0.904500000000000, 6.975299999999995, true, 0, 63.546);
    builder.add_atom("Cu", 3.196999999999999, 0.904500000000000, 6.975299999999995, true, 1, 63.546);
    builder.add_atom("H", 8.682299999999999, 9.946999999999997, 11.732999999999993, false, 2, 1.008);
    let frame = builder.build();

    let mut buffer: Vec<u8> = Vec::new();
    {
        let mut writer = ConFrameWriter::with_precision(&mut buffer, 17);
        writer.write_frame(&frame).expect("Failed to write frame.");
    }

    let fdat = String::from_utf8(buffer).expect("Buffer is not valid UTF-8.");
    let parser = ConFrameIterator::new(&fdat);
    let frames_roundtrip: Vec<_> = parser.map(|r| r.unwrap()).collect();
    assert_eq!(frames_roundtrip.len(), 1);

    let rt = &frames_roundtrip[0];
    assert_eq!(rt.header.natm_types, 2);
    assert_eq!(rt.header.natms_per_type, vec![2, 1]);
    // Verify precision 17 roundtrip preserves coordinates
    assert_eq!(rt.atom_data[0].x, 0.639400000000001);
    assert_eq!(rt.atom_data[0].y, 0.904500000000000);
    assert_eq!(rt.atom_data[2].x, 8.682299999999999);
}

#[test]
fn test_writer_precision_default_vs_high() {
    let mut builder =
        ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
    builder.add_atom("Cu", 1.23456789012345678, 0.0, 0.0, false, 0, 63.546);
    let frame = builder.build();

    // Default precision (6)
    let mut buf6: Vec<u8> = Vec::new();
    {
        let mut w = ConFrameWriter::new(&mut buf6);
        w.write_frame(&frame).unwrap();
    }
    let s6 = String::from_utf8(buf6).unwrap();
    let frames6: Vec<_> = ConFrameIterator::new(&s6)
        .map(|r| r.unwrap())
        .collect();
    // 6 decimal places means ~1e-6 precision loss
    assert!((frames6[0].atom_data[0].x - 1.234568).abs() < 1e-5);

    // High precision (17)
    let mut buf17: Vec<u8> = Vec::new();
    {
        let mut w = ConFrameWriter::with_precision(&mut buf17, 17);
        w.write_frame(&frame).unwrap();
    }
    let s17 = String::from_utf8(buf17).unwrap();
    let frames17: Vec<_> = ConFrameIterator::new(&s17)
        .map(|r| r.unwrap())
        .collect();
    // 17 decimal places preserves the full f64
    assert!((frames17[0].atom_data[0].x - 1.23456789012345678).abs() < 1e-14);
}

#[test]
fn test_builder_velocity_roundtrip() {
    let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
    builder.add_atom_with_velocity("Cu", 1.0, 2.0, 3.0, true, 0, 63.546, 0.1, 0.2, 0.3);
    builder.add_atom_with_velocity("H", 4.0, 5.0, 6.0, false, 1, 1.008, 0.4, 0.5, 0.6);
    let frame = builder.build();

    assert!(frame.has_velocities());

    let mut buffer: Vec<u8> = Vec::new();
    {
        let mut writer = ConFrameWriter::new(&mut buffer);
        writer.write_frame(&frame).expect("Failed to write frame.");
    }

    let fdat = String::from_utf8(buffer).expect("Buffer is not valid UTF-8.");
    let parser = ConFrameIterator::new(&fdat);
    let frames: Vec<_> = parser.map(|r| r.unwrap()).collect();
    assert_eq!(frames.len(), 1);
    assert!(frames[0].has_velocities());
    assert_eq!(frames[0].atom_data[0].vx, Some(0.1));
    assert_eq!(frames[0].atom_data[1].vz, Some(0.6));
}
