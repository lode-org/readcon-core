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
    assert_eq!(
        frame.atom_data[0].force,
        Some([0.123456, 0.234567, -0.345678])
    );
    assert_eq!(frame.atom_data[3].force.unwrap()[0], 4.567890);

    // Check metadata helpers
    assert_eq!(frame.header.energy(), Some(-42.5));
    assert_eq!(frame.header.potential_type(), Some("EMT"));
}

#[test]
fn test_velocities_and_forces() {
    let fdat =
        fs::read_to_string(test_case!("tiny_cuh2_vel_forces.con")).expect("Can't find test file.");
    let parser = ConFrameIterator::new(&fdat);
    let frames: Vec<_> = parser.map(|r| r.unwrap()).collect();

    assert_eq!(frames.len(), 1);
    let frame = &frames[0];

    assert!(frame.has_velocities());
    assert!(frame.has_forces());
    assert_eq!(frame.header.sections, vec!["velocities", "forces"]);

    // Velocity values
    assert_eq!(frame.atom_data[0].velocity.unwrap()[0], 0.001234);
    // Force values
    assert_eq!(frame.atom_data[0].force.unwrap()[0], 0.123456);
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
    let fdat =
        fs::read_to_string(test_case!("tiny_cuh2_vel_forces.con")).expect("Can't find test file.");
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
    let fdat = fs::read_to_string(test_case!("tiny_cuh2.convel")).expect("Can't find test file.");
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
    let frames_rt = readcon_core::iterators::read_all_frames(&path).expect("Failed to read gzip.");
    assert_eq!(frames_original.len(), frames_rt.len());
    assert_eq!(frames_original, frames_rt);
}

#[test]
fn test_energies_roundtrip() {
    use readcon_core::types::ConFrameBuilder;
    use readcon_core::writer::ConFrameWriter;

    let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
    builder
        .add_atom("Cu", 0.1, 0.2, 0.3, [false, false, false], 0, 63.546)
        .with_force([1.0, 2.0, 3.0])
        .with_energy(-0.42);
    builder
        .add_atom("Cu", 1.1, 1.2, 1.3, [false, false, false], 1, 63.546)
        .with_force([4.0, 5.0, 6.0])
        .with_energy(-0.31);
    builder
        .add_atom("H", 2.1, 2.2, 2.3, [false, false, false], 2, 1.008)
        .with_force([7.0, 8.0, 9.0])
        .with_energy(0.07);
    let frame = builder.build();
    assert!(frame.has_energies());
    assert_eq!(frame.atom_data[0].energy, Some(-0.42));

    let tmp = tempfile::NamedTempFile::with_suffix(".con").unwrap();
    let path = tmp.path().to_owned();
    {
        let mut writer = ConFrameWriter::from_path_with_precision(&path, 17).unwrap();
        writer
            .write_frame(&frame)
            .expect("Failed to write energies frame.");
    }

    let frames_rt = readcon_core::iterators::read_all_frames(&path)
        .expect("Failed to read energies frame.");
    assert_eq!(frames_rt.len(), 1);
    let rt = &frames_rt[0];
    assert!(rt.has_energies());
    assert_eq!(rt.atom_data.len(), 3);
    for (orig, rt_atom) in frame.atom_data.iter().zip(rt.atom_data.iter()) {
        assert_eq!(orig.energy, rt_atom.energy);
        assert_eq!(orig.force, rt_atom.force);
        assert_eq!(orig.atom_id, rt_atom.atom_id);
    }
}

#[cfg(feature = "zstd")]
#[test]
fn test_zstd_roundtrip() {
    let fdat =
        fs::read_to_string(test_case!("tiny_cuh2_forces.con")).expect("Can't find test file.");
    let parser = ConFrameIterator::new(&fdat);
    let frames_original: Vec<_> = parser.map(|r| r.unwrap()).collect();

    let tmp = tempfile::NamedTempFile::with_suffix(".con.zst").unwrap();
    let path = tmp.path().to_owned();
    {
        let mut writer = ConFrameWriter::from_path_zstd_with_precision(&path, 17).unwrap();
        writer
            .extend(frames_original.iter())
            .expect("Failed to write zstd.");
    }

    let frames_rt = readcon_core::iterators::read_all_frames(&path).expect("Failed to read zstd.");
    assert_eq!(frames_original.len(), frames_rt.len());
    assert_eq!(frames_original, frames_rt);
}

#[test]
fn test_builder_with_forces() {
    use readcon_core::types::ConFrameBuilder;

    let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
    builder
        .add_atom("Cu", 0.0, 0.0, 0.0, [false, false, false], 0, 63.546)
        .with_force([1.0, 2.0, 3.0]);
    builder
        .add_atom("Cu", 1.0, 0.0, 0.0, [false, false, false], 1, 63.546)
        .with_force([4.0, 5.0, 6.0]);
    let frame = builder.build();

    assert!(frame.has_forces());
    assert!(!frame.has_velocities());
    assert_eq!(frame.header.sections, vec!["forces"]);
    assert_eq!(frame.atom_data[0].force.unwrap()[0], 1.0);
    assert_eq!(frame.atom_data[1].force.unwrap()[2], 6.0);
}

#[test]
fn test_builder_with_velocity_and_forces() {
    use readcon_core::types::ConFrameBuilder;

    let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
    builder
        .add_atom("Cu", 0.0, 0.0, 0.0, [false, false, false], 0, 63.546)
        .with_velocity([0.1, 0.2, 0.3])
        .with_force([1.0, 2.0, 3.0]);
    let frame = builder.build();

    assert!(frame.has_velocities());
    assert!(frame.has_forces());
    assert_eq!(frame.header.sections, vec!["velocities", "forces"]);
}
