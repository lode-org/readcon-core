//! Regressions for defects found while resuming saddle searches from CON.
use readcon_core::error::ParseError;
use readcon_core::iterators::{ConFrameIterator, frame_start_offsets};

fn frame(line1: &str, z: f64) -> String {
    format!(
        "{line1}\n{{\"con_spec_minor\":1,\"con_spec_version\":3,\"units\":{{\"energy\":\"eV\",\"length\":\"angstrom\",\"mass\":\"amu\"}}}}\n\
10 10 10\n90 90 90\n\n\n1\n2\n1.008\nH\nCoordinates of Component 1\n0 0 {z} 0 0\n0 0 1 0 1\n"
    )
}

fn frame_with_fixed(line1: &str, z: f64, fixed0: u8, fixed1: u8) -> String {
    format!(
        "{line1}\n{{\"con_spec_minor\":1,\"con_spec_version\":3,\"units\":{{\"energy\":\"eV\",\"length\":\"angstrom\",\"mass\":\"amu\"}}}}\n\
10 10 10\n90 90 90\n\n\n1\n2\n1.008\nH\nCoordinates of Component 1\n0 0 {z} {fixed0} 0\n0 0 1 {fixed1} 1\n"
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

#[test]
fn skip_empty_line1_with_partial_next_header_is_incomplete() {
    // Empty line 1, then only the metadata line — not a full header.
    let text = format!("{}\n{{\"con_spec_version\":3}}\n", frame("", 0.0));
    let mut it = ConFrameIterator::new(&text);
    assert!(it.forward().unwrap().is_ok());
    let err = it.forward().unwrap().unwrap_err();
    assert!(
        matches!(
            err,
            ParseError::IncompleteFrame | ParseError::IncompleteHeader
        ),
        "unexpected error: {err:?}"
    );
}

/// A blank line with only whitespace after it is EOF, not a section (CON-frame.5).
#[test]
fn blank_then_whitespace_eof_is_not_a_section_on_skip() {
    let text = format!("{}\n   \n\t\n", frame("", 0.0).trim_end());
    let mut it = ConFrameIterator::new(&text);
    assert!(it.forward().unwrap().is_ok());
    assert!(it.forward().is_none());
    let frames: Vec<_> = ConFrameIterator::new(&text)
        .map(|r| r.expect("parse"))
        .collect();
    assert_eq!(frames.len(), 1);
    assert!(!frames[0].has_velocities());
}

/// Last line is a blank with no trailing newline — still not a velocity block.
#[test]
fn terminal_blank_without_newline_is_not_a_section() {
    let mut text = frame("", 0.0);
    text.push('\n');
    text.push_str("   ");
    let frames: Vec<_> = ConFrameIterator::new(&text)
        .map(|r| r.expect("parse"))
        .collect();
    assert_eq!(frames.len(), 1);
    assert!(!frames[0].has_velocities());
    let mut it = ConFrameIterator::new(&text);
    assert!(it.forward().unwrap().is_ok());
    assert!(it.forward().is_none());
}

/// Blank + component label opens a section on skip; a truncated block is IncompleteFrame.
#[test]
fn skip_truncated_velocity_block_after_blank_errors() {
    let text = frame("", 0.0).replace("\"mass\":\"amu\"}", "\"mass\":\"amu\",\"time\":\"fs\"}")
        + "\nH\nVelocities of Component 1\n0.1 0 0 0 0\n"; // missing second atom row
    let mut it = ConFrameIterator::new(&text);
    let err = it.forward().unwrap().unwrap_err();
    assert!(
        matches!(err, ParseError::IncompleteFrame),
        "skip must fail when the velocity-shaped block is short: {err:?}"
    );
}

/// Forces use the same " of Component" label shape; skip must consume them, then
/// the next empty-line-1 frame remains a separate frame.
#[test]
fn skip_force_block_then_empty_line1_frame() {
    let first = "\
\n{\"con_spec_minor\":1,\"con_spec_version\":3,\"sections\":[\"forces\"],\"units\":{\"energy\":\"eV\",\"length\":\"angstrom\",\"mass\":\"amu\"}}
10 10 10
90 90 90


1
2
1.008
H
Coordinates of Component 1
0 0 0 0 0
0 0 1 0 1

H
Forces of Component 1
0.1 0 0 0 0
0 0.2 0 0 1
";
    let text = format!("{first}{}", frame("", 0.5));
    let frames: Vec<_> = ConFrameIterator::new(&text)
        .map(|r| r.expect("frame parses"))
        .collect();
    assert_eq!(frames.len(), 2);
    assert!(frames[0].atom_data.iter().any(|a| a.force.is_some()));
    assert!(!frames[1].has_velocities());
    assert_eq!(frames[1].atom_data[0].z, 0.5);
    let mut it = ConFrameIterator::new(&text);
    assert_eq!(it.skip_frames(2).unwrap(), 2);
    assert_eq!(frame_start_offsets(&text).len(), 2);
}

/// Fixed-flag masks round-trip across an empty-line-1 multi-frame restart.
#[test]
fn empty_line1_preserves_fixed_masks_across_frames() {
    let text = format!(
        "{}{}",
        frame_with_fixed("", 0.0, 7, 0),
        frame_with_fixed("", 0.25, 0, 7)
    );
    let frames: Vec<_> = ConFrameIterator::new(&text)
        .map(|r| r.expect("parse"))
        .collect();
    assert_eq!(frames.len(), 2);
    assert_eq!(frames[0].atom_data[0].fixed, [true, true, true]);
    assert_eq!(frames[0].atom_data[1].fixed, [false, false, false]);
    assert_eq!(frames[1].atom_data[0].fixed, [false, false, false]);
    assert_eq!(frames[1].atom_data[1].fixed, [true, true, true]);
}

/// A 3.0 velocity frame whose `units.time` says fs still stores natural-unit
/// velocities; the next empty-line-1 frame must not be eaten as more velocities.
#[test]
fn v30_fs_label_velocity_then_empty_line1_frame() {
    let first = "\
seed
{\"con_spec_version\":3,\"con_spec_minor\":0,\"units\":{\"energy\":\"eV\",\"length\":\"angstrom\",\"mass\":\"amu\",\"time\":\"fs\"}}
10 10 10
90 90 90


1
2
1.008
H
Coordinates of Component 1
0 0 0 0 0
0 0 1 0 1

H
Velocities of Component 1
0.5 0 0 0 0
0 0.25 0 0 1
";
    let text = format!("{first}{}", frame("", 0.5));
    let frames: Vec<_> = ConFrameIterator::new(&text)
        .map(|r| r.expect("parse"))
        .collect();
    assert_eq!(frames.len(), 2);
    assert!(frames[0].has_velocities());
    let v0 = frames[0].atom_data[0].velocity.expect("v0");
    assert!(
        (v0[0] - 0.5).abs() < 1e-12,
        "3.0 must not scale by the fs label"
    );
    assert!(!frames[1].has_velocities());
    assert_eq!(frames[1].atom_data[0].z, 0.5);
}

/// Zero-atom frames cannot declare sections — restart metadata must not claim any.
#[test]
fn zero_atom_frame_with_declared_sections_errors() {
    let text = "\
za
{\"con_spec_version\":3,\"con_spec_minor\":1,\"sections\":[\"velocities\"],\"units\":{\"energy\":\"eV\",\"length\":\"angstrom\",\"mass\":\"amu\",\"time\":\"fs\"}}
10 10 10
90 90 90


0

";
    let err = ConFrameIterator::new(text)
        .next()
        .expect("one result")
        .unwrap_err();
    match err {
        ParseError::InvalidCount(msg) => {
            assert!(msg.contains("zero-atom"), "{msg}");
        }
        other => panic!("expected InvalidCount, got {other:?}"),
    }
}

/// After skipping a velocity-shaped block, an empty-line-1 frame with a bad
/// per-type count must surface InvalidCount from forward_fast.
#[test]
fn skip_velocity_then_empty_line1_with_bad_counts() {
    let first = frame("", 0.0).replace("\"mass\":\"amu\"}", "\"mass\":\"amu\",\"time\":\"fs\"}")
        + "\nH\nVelocities of Component 1\n0.1 0 0 0 0\n0 0.2 0 0 1\n";
    let bad_next = "\n{\"con_spec_version\":3,\"con_spec_minor\":1,\"units\":{\"energy\":\"eV\",\"length\":\"angstrom\",\"mass\":\"amu\"}}\n\
10 10 10\n90 90 90\n\n\n1\n0\n"; // per-type count 0 is invalid
    let text = format!("{first}{bad_next}");
    let mut it = ConFrameIterator::new(&text);
    assert!(it.forward().unwrap().is_ok());
    let err = it.forward().unwrap().unwrap_err();
    assert!(
        matches!(err, ParseError::InvalidCount(_)),
        "expected InvalidCount, got {err:?}"
    );
}

/// Truncated header after the first six lines (empty line 1 already consumed as
/// the start) yields IncompleteHeader from forward_fast.
#[test]
fn skip_truncated_after_header_prefix_errors() {
    // Six header lines then EOF — advance_lines(6) ok, line 7 missing.
    let text = "l1\n{\"con_spec_version\":2}\n10 10 10\n90 90 90\n\n\n";
    let mut it = ConFrameIterator::new(text);
    let err = it.forward().unwrap().unwrap_err();
    assert!(
        matches!(
            err,
            ParseError::IncompleteHeader | ParseError::IncompleteFrame
        ),
        "unexpected {err:?}"
    );
}

/// Spaces after the last coordinate line with no newline: blank-without-EOL path
/// in forward_fast (next_eol is None).
#[test]
fn trailing_spaces_without_newline_on_skip() {
    let mut text = frame("", 0.0);
    // Append only spaces (no extra blank newline): the next "line" is spaces
    // with no EOL, which forward_fast treats as a blank terminator.
    text.push_str("   ");
    let mut it = ConFrameIterator::new(&text);
    assert!(it.forward().unwrap().is_ok());
    assert!(it.forward().is_none());
    let frames: Vec<_> = ConFrameIterator::new(&text)
        .map(|r| r.expect("parse"))
        .collect();
    assert_eq!(frames.len(), 1);
}

/// Invalid natm_types token after an empty line 1 prefix on the second frame.
#[test]
fn skip_empty_line1_then_bad_natm_types() {
    let text = format!(
        "{}\n{{\"con_spec_version\":3}}\n10 10 10\n90 90 90\n\n\nbad\n",
        frame("", 0.0)
    );
    let mut it = ConFrameIterator::new(&text);
    assert!(it.forward().unwrap().is_ok());
    let err = it.forward().unwrap().unwrap_err();
    assert!(
        matches!(
            err,
            ParseError::InvalidCount(_) | ParseError::InvalidNumberFormat(_)
        ),
        "unexpected {err:?}"
    );
}

/// Missing masses line after per-type counts.
#[test]
fn skip_missing_masses_line_errors() {
    let text = format!(
        "{}\n{{\"con_spec_version\":3}}\n10 10 10\n90 90 90\n\n\n1\n2\n",
        frame("", 0.0)
    );
    let mut it = ConFrameIterator::new(&text);
    assert!(it.forward().unwrap().is_ok());
    let err = it.forward().unwrap().unwrap_err();
    assert!(
        matches!(
            err,
            ParseError::IncompleteFrame | ParseError::IncompleteHeader
        ),
        "unexpected {err:?}"
    );
}

/// Bad per-type count line (wrong arity) after empty line 1.
#[test]
fn skip_empty_line1_then_bad_per_type_counts() {
    let text = format!(
        "{}\n{{\"con_spec_version\":3}}\n10 10 10\n90 90 90\n\n\n2\n1\n",
        frame("", 0.0)
    );
    let mut it = ConFrameIterator::new(&text);
    assert!(it.forward().unwrap().is_ok());
    let err = it.forward().unwrap().unwrap_err();
    assert!(
        matches!(
            err,
            ParseError::InvalidCount(_)
                | ParseError::InvalidNumberFormat(_)
                | ParseError::IncompleteHeader
                | ParseError::InvalidVectorLength { .. }
        ),
        "unexpected {err:?}"
    );
}

/// Empty line 1 then header that ends after natm_types (line 8 missing).
#[test]
fn skip_empty_line1_missing_per_type_counts() {
    let text = format!(
        "{}\n{{\"con_spec_version\":3}}\n10 10 10\n90 90 90\n\n\n1\n",
        frame("", 0.0)
    );
    let mut it = ConFrameIterator::new(&text);
    assert!(it.forward().unwrap().is_ok());
    let err = it.forward().unwrap().unwrap_err();
    assert!(
        matches!(
            err,
            ParseError::IncompleteHeader | ParseError::IncompleteFrame
        ),
        "unexpected {err:?}"
    );
}
