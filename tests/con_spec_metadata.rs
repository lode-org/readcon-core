//! Parsed JSON metadata keeps `con_spec_version`, and a rewrite is stable.

use readcon_core::iterators::ConFrameIterator;
use readcon_core::types::meta;
use readcon_core::writer::ConFrameWriter;

const V31: &str = "\
CON 3.1
{\"con_spec_version\":3,\"con_spec_minor\":1,\"units\":{\"length\":\"angstrom\",\"energy\":\"eV\",\"mass\":\"amu\"}}
10.000000 10.000000 10.000000
90.000000 90.000000 90.000000


1
1
1.007940
H
Coordinates of Component 1
0.000000 0.000000 0.000000 0 0
";

fn read_one(text: &str) -> readcon_core::types::ConFrame {
    let mut frames = ConFrameIterator::new(text);
    let frame = frames.next().unwrap().unwrap();
    assert!(frames.next().is_none());
    frame
}

fn major(frame: &readcon_core::types::ConFrame) -> Option<u64> {
    frame
        .header
        .metadata
        .get(meta::CON_SPEC_VERSION)
        .and_then(|value| value.as_u64())
}

#[test]
fn parsed_metadata_keeps_con_spec_version_and_rewrite_matches() {
    let frame = read_one(V31);
    assert_eq!(frame.header.spec_version, 3);
    assert_eq!(major(&frame), Some(3));
    assert_eq!(
        frame
            .header
            .metadata
            .get(meta::CON_SPEC_MINOR)
            .and_then(|value| value.as_u64()),
        Some(1)
    );

    let mut first = Vec::new();
    ConFrameWriter::new(&mut first).write_frame(&frame).unwrap();
    let again = read_one(std::str::from_utf8(&first).unwrap());
    assert_eq!(again.header.spec_version, 3);
    assert_eq!(major(&again), Some(3));

    let mut second = Vec::new();
    ConFrameWriter::new(&mut second)
        .write_frame(&again)
        .unwrap();
    assert_eq!(first, second);
}
