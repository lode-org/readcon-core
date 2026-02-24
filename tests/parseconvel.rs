mod common;
use readcon_core::iterators::ConFrameIterator;
use std::fs;
use std::path::Path;

#[test]
fn test_convel_single_frame() {
    let fdat =
        fs::read_to_string(test_case!("tiny_cuh2.convel")).expect("Can't find convel test file.");
    let parser = ConFrameIterator::new(&fdat);

    let frames: Vec<_> = parser
        .map(|r| r.expect("Failed to parse convel frame"))
        .collect();
    assert_eq!(frames.len(), 1);

    let frame = &frames[0];
    assert_eq!(frame.header.natm_types, 2);
    assert_eq!(frame.atom_data.len(), 4);
    assert!(frame.has_velocities());

    // Check coordinate data is still correct
    let first_atom = &frame.atom_data[0];
    assert_eq!(&*first_atom.symbol, "Cu");
    assert!((first_atom.x - 0.6394).abs() < 1e-4);
    assert!(first_atom.is_fixed);

    // Check velocity data
    assert_eq!(first_atom.vx, Some(0.001234));
    assert_eq!(first_atom.vy, Some(0.002345));
    assert_eq!(first_atom.vz, Some(-0.003456));

    let last_atom = &frame.atom_data[3];
    assert_eq!(&*last_atom.symbol, "H");
    assert_eq!(last_atom.vx, Some(0.045678));
    assert_eq!(last_atom.vy, Some(-0.056789));
    assert_eq!(last_atom.vz, Some(-0.06789));
    assert!(!last_atom.is_fixed);
}

#[test]
fn test_convel_multi_frame() {
    let fdat = fs::read_to_string(test_case!("tiny_multi_cuh2.convel"))
        .expect("Can't find multi convel test file.");
    let parser = ConFrameIterator::new(&fdat);

    let frames: Vec<_> = parser
        .map(|r| r.expect("Failed to parse convel frame"))
        .collect();
    assert_eq!(
        frames.len(),
        2,
        "Expected 2 frames in multi-frame convel"
    );

    // Both frames should have velocities
    assert!(frames[0].has_velocities());
    assert!(frames[1].has_velocities());

    // Frame 1 velocities
    assert_eq!(frames[0].atom_data[0].vx, Some(0.001234));
    assert_eq!(frames[0].atom_data[0].vy, Some(0.002345));
    assert_eq!(frames[0].atom_data[0].vz, Some(-0.003456));

    // Frame 2 velocities (different from frame 1)
    assert_eq!(frames[1].atom_data[0].vx, Some(0.001111));
    assert_eq!(frames[1].atom_data[0].vy, Some(0.002222));
    assert_eq!(frames[1].atom_data[0].vz, Some(-0.003333));

    // Frame 2 coordinates differ from frame 1
    assert!((frames[0].atom_data[2].x - 8.6823).abs() < 1e-4);
    assert!((frames[1].atom_data[2].x - 8.8549).abs() < 1e-4);
}

#[test]
fn test_con_files_have_no_velocities() {
    let fdat =
        fs::read_to_string(test_case!("tiny_cuh2.con")).expect("Can't find con test file.");
    let parser = ConFrameIterator::new(&fdat);

    let frames: Vec<_> = parser
        .map(|r| r.expect("Failed to parse con frame"))
        .collect();
    assert_eq!(frames.len(), 1);
    assert!(!frames[0].has_velocities());

    for atom in &frames[0].atom_data {
        assert_eq!(atom.vx, None);
        assert_eq!(atom.vy, None);
        assert_eq!(atom.vz, None);
        assert!(!atom.has_velocity());
    }
}

#[test]
fn test_convel_forward_skip() {
    let fdat = fs::read_to_string(test_case!("tiny_multi_cuh2.convel"))
        .expect("Can't find multi convel test file.");
    let mut parser = ConFrameIterator::new(&fdat);

    // Skip first frame
    let skip_result = parser.forward();
    assert!(skip_result.is_some());
    assert!(skip_result.unwrap().is_ok());

    // Parse second frame
    let second = parser.next();
    assert!(second.is_some());
    let frame = second.unwrap().expect("second frame should parse");
    assert!(frame.has_velocities());
    assert_eq!(frame.atom_data[0].vx, Some(0.001111));

    // No more frames
    assert!(parser.next().is_none());
}
