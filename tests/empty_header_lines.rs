//! Empty header lines are part of the frame.
//!
//! Line 1 may be empty and is kept as the user line. Line 2 may be empty
//! and is then implicit version 1. A blank line after a frame is that next
//! frame's line 1 when it does not begin a velocity block.

use readcon_core::iterators::{ConFrameIterator, count_frames, read_nth_frame};
use readcon_core::types::ConFrame;
use std::path::PathBuf;

fn fixture(name: &str) -> (PathBuf, String) {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("resources/conformance/valid")
        .join(name);
    let text = std::fs::read_to_string(&path).expect("fixture");
    (path, text)
}

fn all_frames(text: &str) -> Vec<ConFrame> {
    ConFrameIterator::new(text)
        .map(|result| result.expect("frame"))
        .collect()
}

#[test]
fn empty_user_line_stays_on_one_frame_and_on_the_next_frame() {
    let (_path, one) = fixture("empty_user_line.con");
    let parsed = all_frames(&one);
    assert_eq!(parsed.len(), 1);
    assert_eq!(parsed[0].header.prebox_header.user, "");
    assert_eq!(parsed[0].header.spec_version, 2);
    assert!(
        parsed[0]
            .header
            .prebox_header
            .metadata_line()
            .starts_with('{')
    );

    let (path, two) = fixture("empty_user_line_two.con");
    let parsed = all_frames(&two);
    assert_eq!(parsed.len(), 2);
    assert!(
        parsed
            .iter()
            .all(|frame| frame.header.prebox_header.user.is_empty())
    );
    assert!(parsed.iter().all(|frame| frame.header.spec_version == 2));
    assert_eq!(count_frames(&path).unwrap(), 2);
    let second = read_nth_frame(&path, 1).unwrap();
    assert_eq!(second.header.prebox_header.user, "");
    assert_eq!(second.header.spec_version, 2);

    let mut iter = ConFrameIterator::new(&two);
    assert!(iter.forward_fast().unwrap().is_ok());
    assert!(iter.forward_fast().unwrap().is_ok());
    assert!(iter.forward_fast().is_none());
}

#[test]
fn empty_second_header_line_is_implicit_version_one() {
    let (_path, line2) = fixture("empty_line2.con");
    let parsed = all_frames(&line2);
    assert_eq!(parsed.len(), 1);
    assert_eq!(parsed[0].header.prebox_header.user, "generator");
    assert_eq!(parsed[0].header.prebox_header.metadata_line(), "");
    assert_eq!(parsed[0].header.spec_version, 1);

    let (_path, both) = fixture("empty_header_both.con");
    let parsed = all_frames(&both);
    assert_eq!(parsed.len(), 1);
    assert_eq!(parsed[0].header.prebox_header.user, "");
    assert_eq!(parsed[0].header.prebox_header.metadata_line(), "");
    assert_eq!(parsed[0].header.spec_version, 1);
    assert_eq!(parsed[0].atom_data.len(), 1);
}
