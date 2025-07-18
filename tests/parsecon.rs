mod common;
use readcon::iterators::ConFrameIterator;
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
        assert_eq!(first_atom.symbol, "Cu");
        assert_eq!(first_atom.x, 0.63939999999999997);
        assert_eq!(first_atom.y, 0.90449999999999997);
        assert_eq!(first_atom.z, -0.00009999999999977);
        assert_eq!(first_atom.is_fixed, true);
        assert_eq!(first_atom.atom_id, 0);

        // Check the last atom
        let last_atom = &frame.atom_data.last().unwrap();
        assert_eq!(last_atom.symbol, "H");
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

    let frames: Vec<_> = parser.map(|result| result.expect("Failed to parse a frame")).collect();
    assert_eq!(frames.len(), 2, "Expected to parse 2 frames, but found {}", frames.len());

    let first_frame = &frames[0];
    assert_eq!(first_frame.header.natm_types, 2);
    assert_eq!(first_frame.header.natms_per_type, vec![2, 2]);
    assert_eq!(first_frame.header.masses_per_type, vec![63.546, 1.00793]);
    assert_eq!(first_frame.atom_data.len(), 4);

    let first_atom = &first_frame.atom_data[0];
    assert_eq!(first_atom.symbol, "Cu");
    assert_eq!(first_atom.x, 0.6394);
    assert_eq!(first_atom.y, 0.9045);
    assert_eq!(first_atom.z, 6.9753);
    assert_eq!(first_atom.is_fixed, true);
    assert_eq!(first_atom.atom_id, 0);

    let last_atom = &first_frame.atom_data.last().unwrap();
    assert_eq!(last_atom.symbol, "H");
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
    assert_eq!(second_atom.symbol, "Cu");
    assert_eq!(second_atom.x, 3.1969);
    assert_eq!(second_atom.y, 0.9045);
    assert_eq!(second_atom.z, 6.9752);
    assert_eq!(second_atom.is_fixed, true);
    assert_eq!(second_atom.atom_id, 1);
}
