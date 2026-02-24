mod common;
use readcon_core::iterators::{self, ConFrameIterator};
use std::fs;
use std::path::Path;

#[test]
fn test_cuh2_parsing() {
    let fdat = fs::read_to_string(test_case!("cuh2.con")).expect("Can't find test.");
    let parser = ConFrameIterator::new(&fdat);

    let mut frames_found = 0;
    for result in parser {
        let frame = result.expect("Failed to parse frame in file");

        frames_found += 1;
        println!("Parsed frame: {:?}", frame.header);

        assert_eq!(frame.header.natm_types, 2);
        assert_eq!(frame.header.natms_per_type, vec![216, 2]);
        assert_eq!(frame.header.masses_per_type, vec![63.546, 1.00793]);
        assert_eq!(frame.atom_data.len(), 218);

        // Check the first atom
        let first_atom = &frame.atom_data[0];
        assert_eq!(&*first_atom.symbol, "Cu");
        assert_eq!(first_atom.x, 0.63939999999999997);
        assert_eq!(first_atom.y, 0.90449999999999997);
        assert_eq!(first_atom.z, -0.00009999999999977);
        assert_eq!(first_atom.is_fixed, true);
        assert_eq!(first_atom.atom_id, 0);

        // Check the last atom
        let last_atom = &frame.atom_data.last().unwrap();
        assert_eq!(&*last_atom.symbol, "H");
        assert_eq!(last_atom.x, 7.94209999999999994);
        assert_eq!(last_atom.y, 9.94699999999999918);
        assert_eq!(last_atom.z, 4.75760000000000094);
        assert_eq!(last_atom.is_fixed, false);
        assert_eq!(last_atom.atom_id, 217);
    }

    assert!(frames_found == 1);
}

#[test]
fn test_multi_parsing() {
    let fdat = fs::read_to_string(test_case!("tiny_multi_cuh2.con")).expect("Can't find test.");
    let parser = ConFrameIterator::new(&fdat);

    let frames: Vec<_> = parser
        .map(|result| result.expect("Failed to parse a frame"))
        .collect();
    assert_eq!(
        frames.len(),
        2,
        "Expected to parse 2 frames, but found {}",
        frames.len()
    );

    let first_frame = &frames[0];
    assert_eq!(first_frame.header.natm_types, 2);
    assert_eq!(first_frame.header.natms_per_type, vec![2, 2]);
    assert_eq!(first_frame.header.masses_per_type, vec![63.546, 1.00793]);
    assert_eq!(first_frame.atom_data.len(), 4);

    let first_atom = &first_frame.atom_data[0];
    assert_eq!(&*first_atom.symbol, "Cu");
    assert_eq!(first_atom.x, 0.6394);
    assert_eq!(first_atom.y, 0.9045);
    assert_eq!(first_atom.z, 6.9753);
    assert_eq!(first_atom.is_fixed, true);
    assert_eq!(first_atom.atom_id, 0);

    let last_atom = &first_frame.atom_data.last().unwrap();
    assert_eq!(&*last_atom.symbol, "H");
    assert_eq!(last_atom.x, 7.9421);
    assert_eq!(last_atom.y, 9.947);
    assert_eq!(last_atom.z, 11.733);
    assert_eq!(last_atom.is_fixed, false);
    assert_eq!(last_atom.atom_id, 3);

    let second_frame = &frames[1];
    assert_eq!(second_frame.header.natm_types, 2);
    assert_eq!(second_frame.header.natms_per_type, vec![2, 2]);
    assert_eq!(second_frame.header.masses_per_type, vec![63.546, 1.00793]);
    assert_eq!(second_frame.atom_data.len(), 4);

    let second_atom = &second_frame.atom_data[1];
    assert_eq!(&*second_atom.symbol, "Cu");
    assert_eq!(second_atom.x, 3.1969);
    assert_eq!(second_atom.y, 0.9045);
    assert_eq!(second_atom.z, 6.9752);
    assert_eq!(second_atom.is_fixed, true);
    assert_eq!(second_atom.atom_id, 1);
}

#[test]
fn test_iterator_forward() {
    let fdat = fs::read_to_string(test_case!("tiny_multi_cuh2.con")).expect("Can't find test.");
    let mut parser = ConFrameIterator::new(&fdat);
    // --- Test Case 1: forward -> next ---
    let forward_result = parser.forward();
    assert!(
        forward_result.is_some(),
        "Forward should succeed on the first frame"
    );
    assert!(
        forward_result.unwrap().is_ok(),
        "Forward result should be Ok"
    );
    let second_frame_result = parser.next();
    assert!(
        second_frame_result.is_some(),
        "Should be able to get the second frame after forwarding"
    );
    let second_frame = second_frame_result
        .unwrap()
        .expect("Parsing second frame should succeed");
    assert_eq!(second_frame.atom_data.len(), 4);
    let second_atom = &second_frame.atom_data[1];
    assert_eq!(&*second_atom.symbol, "Cu");
    assert_eq!(second_atom.x, 3.1969);
    assert_eq!(second_atom.y, 0.9045);
    assert_eq!(second_atom.z, 6.9752);
    assert_eq!(second_atom.is_fixed, true);
    assert_eq!(second_atom.atom_id, 1);
    assert!(
        parser.next().is_none(),
        "There should be no more frames after the second one"
    );

    // --- Test Case 2: next -> forward -> next ---
    let mut parser2 = ConFrameIterator::new(&fdat);
    let first_frame_result = parser2.next();
    assert!(
        first_frame_result.is_some(),
        "Should be able to get the first frame"
    );
    first_frame_result
        .unwrap()
        .expect("Parsing first frame should succeed");
    let forward_result_2 = parser2.forward();
    assert!(
        forward_result_2.is_some(),
        "Forward should succeed on the second frame"
    );
    assert!(
        forward_result_2.unwrap().is_ok(),
        "Forward result should be Ok"
    );
    assert!(
        parser2.next().is_none(),
        "There should be no more frames after forwarding past the last one"
    );
}

#[test]
fn test_read_first_frame() {
    let path = test_case!("cuh2.con");
    let frame = iterators::read_first_frame(&path).expect("read_first_frame should succeed");
    assert_eq!(frame.header.natm_types, 2);
    assert_eq!(frame.atom_data.len(), 218);
    assert_eq!(&*frame.atom_data[0].symbol, "Cu");
    assert_eq!(frame.atom_data[0].atom_id, 0);
}

#[test]
fn test_read_first_frame_multi() {
    // read_first_frame on a multi-frame file should return only the first
    let path = test_case!("tiny_multi_cuh2.con");
    let frame = iterators::read_first_frame(&path).expect("read_first_frame should succeed");
    assert_eq!(frame.atom_data.len(), 4);
    assert_eq!(&*frame.atom_data[0].symbol, "Cu");
    assert_eq!(frame.atom_data[0].x, 0.6394);
}

#[test]
fn test_read_all_frames_matches_iterator() {
    let path = test_case!("tiny_multi_cuh2.con");
    let frames = iterators::read_all_frames(&path).expect("read_all_frames should succeed");
    assert_eq!(frames.len(), 2);
    assert_eq!(frames[0].atom_data.len(), 4);
    assert_eq!(frames[1].atom_data.len(), 4);
}
