//! Regressions for defects found while resuming saddle searches from CON.
use readcon_core::iterators::{ConFrameIterator, frame_start_offsets};

fn frame(line1: &str, z: f64) -> String {
    format!(
        "{line1}\n{{\"con_spec_minor\":1,\"con_spec_version\":3,\"units\":{{\"energy\":\"eV\",\"length\":\"angstrom\",\"mass\":\"amu\"}}}}\n\
10 10 10\n90 90 90\n\n\n1\n2\n1.008\nH\nCoordinates of Component 1\n0 0 {z} 0 0\n0 0 1 0 1\n"
    )
}

#[test]
fn multi_frame_with_empty_line1_reads_back() {
    let text = format!("{}{}{}", frame("", 0.0), frame("", 0.5), frame("", 0.75));
    let frames: Vec<_> = ConFrameIterator::new(&text)
        .map(|r| r.expect("frame parses"))
        .collect();
    assert_eq!(frames.len(), 3);
    assert!(frames.iter().all(|f| !f.has_velocities()));
    assert_eq!(frames[2].atom_data[0].z, 0.75);
    assert_eq!(frame_start_offsets(&text).len(), 3);
    let mut it = ConFrameIterator::new(&text);
    assert_eq!(it.skip_frames(5).unwrap(), 3);
}

#[test]
fn empty_line1_frame_after_velocity_block() {
    let first = frame("", 0.0).replace("\"mass\":\"amu\"}", "\"mass\":\"amu\",\"time\":\"fs\"}")
        + "\nH\nVelocities of Component 1\n0.1 0 0 0 0\n0 0.2 0 0 1\n";
    let text = format!("{first}{}", frame("", 0.5));
    let frames: Vec<_> = ConFrameIterator::new(&text)
        .map(|r| r.expect("frame parses"))
        .collect();
    assert_eq!(frames.len(), 2);
    assert!(frames[0].has_velocities());
    assert!(!frames[1].has_velocities());
    assert_eq!(frame_start_offsets(&text).len(), 2);
}
