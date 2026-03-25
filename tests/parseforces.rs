mod common;
use readcon_core::iterators::ConFrameIterator;
use readcon_core::writer::ConFrameWriter;
use std::fs;
use std::path::Path;

#[test]
fn test_forces_only() {
    let fdat =
        fs::read_to_string(test_case!("tiny_cuh2_forces.con")).expect("Can't find test file.");
    let parser = ConFrameIterator::new(&fdat);
    let frames: Vec<_> = parser.map(|r| r.unwrap()).collect();

    assert_eq!(frames.len(), 1);
    let frame = &frames[0];

    // No velocities, yes forces
    assert!(!frame.has_velocities());
    assert!(frame.has_forces());

    // Check sections
    assert_eq!(frame.header.sections, vec!["forces"]);

    // Check force values
    assert_eq!(frame.atom_data[0].fx, Some(0.123456));
    assert_eq!(frame.atom_data[0].fy, Some(0.234567));
    assert_eq!(frame.atom_data[0].fz, Some(-0.345678));
    assert_eq!(frame.atom_data[3].fx, Some(4.567890));

    // Check metadata helpers
    assert_eq!(frame.header.energy(), Some(-42.5));
    assert_eq!(frame.header.potential_type(), Some("EMT"));
}

#[test]
fn test_velocities_and_forces() {
    let fdat = fs::read_to_string(test_case!("tiny_cuh2_vel_forces.con"))
        .expect("Can't find test file.");
    let parser = ConFrameIterator::new(&fdat);
    let frames: Vec<_> = parser.map(|r| r.unwrap()).collect();

    assert_eq!(frames.len(), 1);
    let frame = &frames[0];

    assert!(frame.has_velocities());
    assert!(frame.has_forces());
    assert_eq!(frame.header.sections, vec!["velocities", "forces"]);

    // Velocity values
    assert_eq!(frame.atom_data[0].vx, Some(0.001234));
    // Force values
    assert_eq!(frame.atom_data[0].fx, Some(0.123456));
    // Both present on same atom
    assert!(frame.atom_data[0].has_velocity());
    assert!(frame.atom_data[0].has_forces());
}

#[test]
fn test_forces_roundtrip() {
    let fdat =
        fs::read_to_string(test_case!("tiny_cuh2_forces.con")).expect("Can't find test file.");
    let parser = ConFrameIterator::new(&fdat);
    let frames_original: Vec<_> = parser.map(|r| r.unwrap()).collect();

    let mut buffer: Vec<u8> = Vec::new();
    {
        let mut writer = ConFrameWriter::with_precision(&mut buffer, 17);
        writer
            .extend(frames_original.iter())
            .expect("Failed to write.");
    }

    let fdat_rt = String::from_utf8(buffer).unwrap();
    let parser_rt = ConFrameIterator::new(&fdat_rt);
    let frames_rt: Vec<_> = parser_rt.map(|r| r.unwrap()).collect();

    assert_eq!(frames_original.len(), frames_rt.len());
    assert_eq!(frames_original, frames_rt);
}

#[test]
fn test_vel_forces_roundtrip() {
    let fdat = fs::read_to_string(test_case!("tiny_cuh2_vel_forces.con"))
        .expect("Can't find test file.");
    let parser = ConFrameIterator::new(&fdat);
    let frames_original: Vec<_> = parser.map(|r| r.unwrap()).collect();

    let mut buffer: Vec<u8> = Vec::new();
    {
        let mut writer = ConFrameWriter::with_precision(&mut buffer, 17);
        writer
            .extend(frames_original.iter())
            .expect("Failed to write.");
    }

    let fdat_rt = String::from_utf8(buffer).unwrap();
    let parser_rt = ConFrameIterator::new(&fdat_rt);
    let frames_rt: Vec<_> = parser_rt.map(|r| r.unwrap()).collect();

    assert_eq!(frames_original.len(), frames_rt.len());
    assert_eq!(frames_original, frames_rt);
}

#[test]
fn test_legacy_convel_still_works() {
    // Legacy .convel files without sections key must still parse correctly.
    let fdat =
        fs::read_to_string(test_case!("tiny_cuh2.convel")).expect("Can't find test file.");
    let parser = ConFrameIterator::new(&fdat);
    let frames: Vec<_> = parser.map(|r| r.unwrap()).collect();

    assert_eq!(frames.len(), 1);
    assert!(frames[0].has_velocities());
    assert!(!frames[0].has_forces());
    // Legacy detection should have populated sections
    assert_eq!(frames[0].header.sections, vec!["velocities"]);
}

#[test]
fn test_gzip_roundtrip() {
    let fdat =
        fs::read_to_string(test_case!("tiny_cuh2_forces.con")).expect("Can't find test file.");
    let parser = ConFrameIterator::new(&fdat);
    let frames_original: Vec<_> = parser.map(|r| r.unwrap()).collect();

    // Write to a gzip file in a temp dir
    let tmp = tempfile::NamedTempFile::with_suffix(".con.gz").unwrap();
    let path = tmp.path().to_owned();
    {
        let mut writer = ConFrameWriter::from_path_gzip_with_precision(&path, 17).unwrap();
        writer
            .extend(frames_original.iter())
            .expect("Failed to write gzip.");
    }

    // Read back -- transparent decompression
    let frames_rt =
        readcon_core::iterators::read_all_frames(&path).expect("Failed to read gzip.");
    assert_eq!(frames_original.len(), frames_rt.len());
    assert_eq!(frames_original, frames_rt);
}

#[test]
fn test_builder_with_forces() {
    use readcon_core::types::ConFrameBuilder;

    let mut builder =
        ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
    builder.add_atom_with_forces("Cu", 0.0, 0.0, 0.0, false, 0, 63.546, 1.0, 2.0, 3.0);
    builder.add_atom_with_forces("Cu", 1.0, 0.0, 0.0, false, 1, 63.546, 4.0, 5.0, 6.0);
    let frame = builder.build();

    assert!(frame.has_forces());
    assert!(!frame.has_velocities());
    assert_eq!(frame.header.sections, vec!["forces"]);
    assert_eq!(frame.atom_data[0].fx, Some(1.0));
    assert_eq!(frame.atom_data[1].fz, Some(6.0));
}

#[test]
fn test_builder_with_velocity_and_forces() {
    use readcon_core::types::ConFrameBuilder;

    let mut builder =
        ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
    builder.add_atom_with_velocity_and_forces(
        "Cu", 0.0, 0.0, 0.0, false, 0, 63.546,
        0.1, 0.2, 0.3, 1.0, 2.0, 3.0,
    );
    let frame = builder.build();

    assert!(frame.has_velocities());
    assert!(frame.has_forces());
    assert_eq!(frame.header.sections, vec!["velocities", "forces"]);
}
