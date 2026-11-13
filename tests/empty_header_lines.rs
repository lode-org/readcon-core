//! Empty header lines are part of the frame.
//!
//! Line 1 may be empty and is kept as the user line. Line 2 may be empty
//! and is then implicit version 1. A blank line after a frame is that next
//! frame's line 1 when it does not begin a velocity block.

use readcon_core::iterators::{ConFrameIterator, count_frames, read_nth_frame};
use readcon_core::types::{ConFrame, ConFrameBuilder};
use readcon_core::writer::{ConFrameWriter, binding_rewrite_frame};
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

/// A binding rewrite of an implicit spec-1 frame matches the builder.
///
/// The builder emits spec 3, default units, and the three-axis fixed mask.
/// The Fortran writer uses `write_frame_binding`. The C rewriter uses
/// `binding_rewrite_frame`. Both have to match that header, including the
/// atom id column.
#[test]
fn binding_rewrite_of_empty_header_matches_the_builder() {
    let (_path, both) = fixture("empty_header_both.con");
    let parsed = all_frames(&both);
    let frame = &parsed[0];
    assert_eq!(frame.header.spec_version, 1);
    assert_eq!(frame.atom_data[0].atom_id, 0);
    assert_eq!(frame.atom_data[0].fixed, [true, true, true]);

    let mut binding_buf = Vec::new();
    {
        let mut frame = frame.clone();
        let mut writer = ConFrameWriter::new(&mut binding_buf);
        writer.write_frame_binding(&mut frame).unwrap();
        assert_eq!(frame.header.spec_version, 1);
        assert_eq!(frame.header.prebox_header.metadata_line(), "");
    }

    let rewritten = binding_rewrite_frame(frame).unwrap();
    assert_eq!(rewritten.header.spec_version, 3);
    let mut rewrite_buf = Vec::new();
    {
        let mut writer = ConFrameWriter::new(&mut rewrite_buf);
        writer.write_frame(&rewritten).unwrap();
    }

    let mut builder = ConFrameBuilder::new(frame.header.boxl, frame.header.angles);
    builder
        .prebox_header(&frame.header.prebox_header.user)
        .postbox_header(frame.header.postbox_header.clone());
    let mass = frame.header.masses_per_type[0];
    for atom in &frame.atom_data {
        builder.add_atom(
            &atom.symbol,
            atom.x,
            atom.y,
            atom.z,
            atom.fixed,
            atom.atom_id,
            mass,
        );
    }
    let built = builder.build().unwrap();
    let mut built_buf = Vec::new();
    {
        let mut writer = ConFrameWriter::new(&mut built_buf);
        writer.write_frame(&built).unwrap();
    }

    let binding = String::from_utf8(binding_buf).unwrap();
    let rewrite = String::from_utf8(rewrite_buf).unwrap();
    let built_text = String::from_utf8(built_buf).unwrap();
    assert_eq!(binding, built_text);
    assert_eq!(rewrite, built_text);
    assert!(binding.contains(r#""con_spec_version":3"#), "{binding}");
    assert!(binding.contains(r#""con_spec_minor":1"#), "{binding}");
    assert!(binding.contains("\"units\":{"), "{binding}");
    assert!(binding.contains("0.0 0.0 0.0 7 0"), "{binding}");
}

/// A case-folded velocity label is still a section (CON-file.5).
/// The blank after that block is line 1 of the next frame.
#[test]
fn case_folded_velocity_label_keeps_the_following_empty_user_line() {
    let text = "\
generator

10.0 10.0 10.0
90.0 90.0 90.0


1
1
63.546
Cu
Coordinates of Component 1
0.0 0.0 0.0 1 0

Cu
velocities of component 1
0.1 0.2 0.3 1 0

{\"con_spec_version\":2}
10.0 10.0 10.0
90.0 90.0 90.0


1
1
63.546
Cu
Coordinates of Component 1
1.0 0.0 0.0 7 1
";
    let parsed = all_frames(text);
    assert_eq!(parsed.len(), 2);
    assert_eq!(parsed[0].header.spec_version, 1);
    assert_eq!(parsed[0].atom_data[0].velocity(), Some([0.1, 0.2, 0.3]));
    assert_eq!(parsed[1].header.prebox_header.user, "");
    assert_eq!(parsed[1].header.spec_version, 2);
    assert!(parsed[1].atom_data[0].velocity().is_none());

    let mut iter = ConFrameIterator::new(text);
    assert!(iter.forward_fast().unwrap().is_ok());
    assert!(iter.forward_fast().unwrap().is_ok());
    assert!(iter.forward_fast().is_none());
}
