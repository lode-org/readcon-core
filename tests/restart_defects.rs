//! Regressions for defects found while resuming saddle searches from CON.
use readcon_core::error::ParseError;
use readcon_core::iterators::{ConFrameIterator, frame_start_offsets};
use readcon_core::parser::{parse_declared_sections, parse_single_frame};
use readcon_core::units::{
    NATURAL_TIME_UNIT, unit_conversion_factor, validate_unit_for_quantity, velocity_file_time_unit,
    velocity_scale_to_natural,
};
use readcon_core::writer::{ConFrameWriter, WriteError};

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

fn after_empty_line1(coord: &str) -> String {
    format!(
        "{}\n{{\"con_spec_version\":3,\"units\":{{\"energy\":\"eV\",\"length\":\"angstrom\",\"mass\":\"amu\"}}}}\n\
10 10 10\n90 90 90\n\n\n1\n1\n1.008\nH\nCoordinates of Component 1\n{coord}\n",
        frame("", 0.0)
    )
}

fn error_on_second_frame(coord: &str) -> ParseError {
    let text = after_empty_line1(coord);
    let mut it = ConFrameIterator::new(&text);
    assert!(
        it.next().unwrap().is_ok(),
        "the first empty-line-1 frame is intact"
    );
    it.next()
        .expect("second frame yields a result")
        .unwrap_err()
}

fn v3_body(meta: &str, body: &str) -> String {
    format!(
        "PRE\n{meta}\n10 10 10\n90 90 90\n\n\n1\n1\n1.008\nH\nCoordinates of Component 1\n0 0 0 0 0\n{body}"
    )
}

/// Spec 1 column 4 is only 0 or 1. A bitmask that is legal on spec 2 is not.
#[test]
fn spec1_rejects_bitmask_flags() {
    for flag in [2u8, 7] {
        let text = format!(
            "\
PRE
free text
10 10 10
90 90 90


1
1
1.008
H
Coordinates of Component 1
0 0 0 {flag} 0
"
        );
        let err = ConFrameIterator::new(&text)
            .next()
            .expect("result")
            .unwrap_err();
        assert_eq!(err.class_name(), "InvalidFixedFlag", "{flag}: {err}");
        let msg = err.to_string();
        assert!(msg.contains(&flag.to_string()), "{msg}");
        assert!(msg.contains("spec 1"), "{msg}");
    }
}

/// Each bit of a spec 3 mask survives an empty line 1 between frames.
#[test]
fn empty_line1_preserves_partial_fixed_masks() {
    let text = format!(
        "{}{}{}{}",
        frame_with_fixed("", 0.0, 1, 2),
        frame_with_fixed("", 0.1, 4, 3),
        frame_with_fixed("", 0.2, 5, 6),
        frame_with_fixed("", 0.3, 6, 5),
    );
    let frames: Vec<_> = ConFrameIterator::new(&text)
        .map(|r| r.expect("parse"))
        .collect();
    assert_eq!(frames.len(), 4);
    assert_eq!(frames[0].atom_data[0].fixed, [true, false, false]);
    assert_eq!(frames[0].atom_data[1].fixed, [false, true, false]);
    assert_eq!(frames[1].atom_data[0].fixed, [false, false, true]);
    assert_eq!(frames[1].atom_data[1].fixed, [true, true, false]);
    assert_eq!(frames[2].atom_data[0].fixed, [true, false, true]);
    assert_eq!(frames[2].atom_data[1].fixed, [false, true, true]);
    assert_eq!(frames[3].atom_data[0].fixed, [false, true, true]);
    assert_eq!(frames[3].atom_data[1].fixed, [true, false, true]);
    assert!(!frames[3].has_velocities());
    assert_eq!(frames[3].atom_data[0].z, 0.3);
}

/// A velocity row whose mask does not match the coordinate row is rejected
/// when the frame asked for strict checks.
#[test]
fn velocity_fixed_mask_must_match_coordinates() {
    let text = v3_body(
        r#"{"con_spec_version":3,"con_spec_minor":1,"validate":true,"sections":["velocities"],"units":{"length":"angstrom","energy":"eV","mass":"amu","time":"fs"}}"#,
        "\nH\nVelocities of Component 1\n0.1 0 0 1 0\n",
    );
    let err = ConFrameIterator::new(&text)
        .next()
        .expect("result")
        .unwrap_err();
    match err {
        ParseError::ValidationError(msg) => {
            assert!(msg.contains("fixed mask"), "{msg}");
        }
        other => panic!("expected ValidationError, got {other:?}"),
    }
}

/// The velocity label must name this component, not merely share the prefix.
#[test]
fn velocity_component_number_is_checked() {
    let text = v3_body(
        r#"{"con_spec_version":3,"con_spec_minor":1,"validate":true,"sections":["velocities"],"units":{"length":"angstrom","energy":"eV","mass":"amu","time":"fs"}}"#,
        "\nH\nVelocities of Component 2\n0.1 0 0 0 0\n",
    );
    let err = ConFrameIterator::new(&text)
        .next()
        .expect("result")
        .unwrap_err();
    match err {
        ParseError::ValidationError(msg) => {
            assert!(msg.contains("Velocities of Component 1"), "{msg}");
            assert!(msg.contains("Component 2"), "{msg}");
        }
        other => panic!("expected ValidationError, got {other:?}"),
    }
}

/// A block that looks like a section but is not velocities fails the velocity read.
#[test]
fn mislabeled_velocity_block_is_incomplete() {
    let text = v3_body(
        r#"{"con_spec_version":3,"sections":["velocities"],"units":{"length":"angstrom","energy":"eV","mass":"amu","time":"fs"}}"#,
        "\nH\nForces of Component 1\n0.1 0 0 0 0\n",
    );
    let err = ConFrameIterator::new(&text)
        .next()
        .expect("result")
        .unwrap_err();
    match err {
        ParseError::IncompleteSection(name) => assert_eq!(name, "velocities"),
        other => panic!("expected IncompleteSection, got {other:?}"),
    }
}

/// Column 5 past `u64::MAX` is an integer error, not a float.
#[test]
fn atom_id_past_u64_is_invalid_on_the_next_frame() {
    let err = error_on_second_frame("0 0 0 0 18446744073709551616");
    assert_eq!(err.class_name(), "InvalidNumberFormat");
    assert!(err.to_string().contains("out of range"), "{err}");
}

/// Fewer than three coordinates is a short row, not a missing frame.
#[test]
fn short_coordinate_row_on_the_next_frame() {
    let err = error_on_second_frame("0 0");
    match err {
        ParseError::InvalidVectorLength { expected, found } => {
            assert_eq!(expected, 5);
            assert_eq!(found, 2);
        }
        other => panic!("expected InvalidVectorLength, got {other:?}"),
    }
}

/// A sixth token on a coordinate row is rejected.
#[test]
fn extra_coordinate_token_on_the_next_frame() {
    let err = error_on_second_frame("0 0 0 0 1 9");
    match err {
        ParseError::InvalidVectorLength { expected, found } => {
            assert_eq!(expected, 5);
            assert_eq!(found, 6);
        }
        other => panic!("expected InvalidVectorLength, got {other:?}"),
    }
}

/// An empty coordinate line is a zero-width row.
#[test]
fn blank_coordinate_row_on_the_next_frame() {
    let err = error_on_second_frame("");
    match err {
        ParseError::InvalidVectorLength { expected, found } => {
            assert_eq!(expected, 5);
            assert_eq!(found, 0);
        }
        other => panic!("expected InvalidVectorLength, got {other:?}"),
    }
}

/// An empty energy row fails before a flag or id can be read.
#[test]
fn blank_energy_row_is_a_zero_width_scalar() {
    let text = v3_body(
        r#"{"con_spec_version":2,"sections":["energies"]}"#,
        "\nH\nEnergies of Component 1\n\n",
    );
    let err = ConFrameIterator::new(&text)
        .next()
        .expect("result")
        .unwrap_err();
    match err {
        ParseError::InvalidVectorLength { expected, found } => {
            assert_eq!(expected, 3);
            assert_eq!(found, 0);
        }
        other => panic!("expected InvalidVectorLength, got {other:?}"),
    }
}

/// A glued suffix and an overflowing exponent are number errors, not masks.
#[test]
fn malformed_coordinate_numbers_on_the_next_frame() {
    let glued = error_on_second_frame("0 0 1.2xyz 0 0");
    assert_eq!(glued.class_name(), "InvalidNumberFormat", "{glued}");
    assert!(glued.to_string().contains("1.2xyz"), "{glued}");

    let huge = error_on_second_frame("0 0 1e9999 0 0");
    assert_eq!(huge.class_name(), "NonFiniteValue", "{huge}");

    let sign = error_on_second_frame("0 0 + 0 0");
    assert_eq!(sign.class_name(), "InvalidNumberFormat", "{sign}");

    let word = error_on_second_frame("0 0 nope 0 0");
    assert_eq!(word.class_name(), "InvalidNumberFormat", "{word}");
}

/// An energy row is exactly three tokens. A fourth is not an id.
#[test]
fn energy_row_rejects_an_extra_token() {
    let text = v3_body(
        r#"{"con_spec_version":2,"sections":["energies"]}"#,
        "\nH\nEnergies of Component 1\n1.5 0 0 9\n",
    );
    let err = ConFrameIterator::new(&text)
        .next()
        .expect("result")
        .unwrap_err();
    match err {
        ParseError::InvalidVectorLength { expected, found } => {
            assert_eq!(expected, 3);
            assert_eq!(found, 4);
        }
        other => panic!("expected InvalidVectorLength, got {other:?}"),
    }
}

/// A declared section with no block is incomplete, including when the only
/// thing after the coordinates is whitespace.
#[test]
fn declared_section_without_a_block_errors() {
    for section in [
        "forces",
        "energies",
        "charges",
        "spins",
        "magmoms",
        "displacements",
        "spreads",
    ] {
        let meta = format!(
            r#"{{"con_spec_version":3,"units":{{"length":"angstrom","energy":"eV"}},"sections":["{section}"]}}"#
        );
        let ended = v3_body(&meta, "");
        let err = ConFrameIterator::new(&ended)
            .next()
            .expect("result")
            .unwrap_err();
        match err {
            ParseError::IncompleteSection(name) => assert_eq!(name, section),
            other => panic!("{section}: expected IncompleteSection, got {other:?}"),
        }

        let trailed = v3_body(&meta, "\n   \n");
        let err = ConFrameIterator::new(&trailed)
            .next()
            .expect("result")
            .unwrap_err();
        match err {
            ParseError::IncompleteSection(name) => assert_eq!(name, section),
            other => panic!("{section} trailing ws: expected IncompleteSection, got {other:?}"),
        }
    }
}

/// `skip_frames` surfaces the same short velocity block that `forward` does.
#[test]
fn skip_frames_returns_truncated_velocity_error() {
    let text = frame("", 0.0).replace("\"mass\":\"amu\"}", "\"mass\":\"amu\",\"time\":\"fs\"}")
        + "\nH\nVelocities of Component 1\n0.1 0 0 0 0\n";
    let err = ConFrameIterator::new(&text).skip_frames(1).unwrap_err();
    assert!(
        matches!(err, ParseError::IncompleteFrame),
        "skip_frames must return the skip error: {err:?}"
    );
}

/// A bad mask on the frame being resumed fails the raw-span read.
#[test]
fn raw_span_returns_invalid_fixed_flag() {
    let text = frame_with_fixed("seed", 0.0, 8, 0);
    let err = ConFrameIterator::new(&text)
        .next_with_raw_span(&text)
        .expect("a result")
        .unwrap_err();
    assert_eq!(err.class_name(), "InvalidFixedFlag", "{err}");
    assert!(err.to_string().contains("8"), "{err}");
}

/// Line 9 of a zero-atom frame must be whitespace. A token is `InvalidCount`.
#[test]
fn zero_atom_token_on_line_9_errors() {
    let text = "\
za
{\"con_spec_version\":3,\"units\":{\"length\":\"angstrom\",\"energy\":\"eV\"}}
10 10 10
90 90 90


0

not-whitespace
";
    let err = ConFrameIterator::new(text)
        .next()
        .expect("result")
        .unwrap_err();
    match err {
        ParseError::InvalidCount(msg) => {
            assert!(msg.contains("lines 8 and 9"), "{msg}");
        }
        other => panic!("expected InvalidCount, got {other:?}"),
    }
}

/// Callers that only have a `Peekable` line iterator keep the legacy rule:
/// a real velocity block is read, and an empty line 1 is not a frame boundary.
#[test]
fn peekable_line_stream_still_uses_the_legacy_blank_rule() {
    let text = "\
seed
{\"con_spec_version\":2}
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
    let mut lines = text.lines().peekable();
    let mut parsed = parse_single_frame(&mut lines).expect("coordinates");
    let n = parse_declared_sections(&mut lines, &mut parsed.header, &mut parsed.atom_data)
        .expect("velocity block");
    assert_eq!(n, 1);
    assert_eq!(parsed.atom_data[0].velocity, Some([0.5, 0.0, 0.0]));
    assert_eq!(parsed.atom_data[1].velocity, Some([0.0, 0.25, 0.0]));

    let restarted = format!("{}{}", frame("", 0.0), frame("", 0.5));
    let mut lines = restarted.lines().peekable();
    let mut first = parse_single_frame(&mut lines).expect("first frame");
    let err = parse_declared_sections(&mut lines, &mut first.header, &mut first.atom_data)
        .expect_err("empty line 1 is a velocity opener on the default stream");
    match err {
        ParseError::IncompleteSection(name) => assert_eq!(name, "velocities"),
        other => panic!("expected IncompleteSection, got {other:?}"),
    }
}

/// The writer refuses the same zero-atom section claim the reader refuses.
#[test]
fn writer_rejects_zero_atom_frame_with_sections() {
    let text = frame("seed", 0.0);
    let mut parsed = ConFrameIterator::new(&text)
        .next()
        .expect("result")
        .expect("parse");
    parsed.atom_data.clear();
    parsed.header.natm_types = 0;
    parsed.header.natms_per_type.clear();
    parsed.header.masses_per_type.clear();
    parsed.header.sections.push("velocities".into());
    let mut buf = Vec::new();
    let err = ConFrameWriter::new(&mut buf)
        .write_frame(&parsed)
        .unwrap_err();
    match err {
        WriteError::Format(ParseError::InvalidCount(msg)) => {
            assert!(msg.contains("zero-atom"), "{msg}");
        }
        other => panic!("expected InvalidCount, got {other:?}"),
    }
}

/// A per-type count of 0 is not a zero-atom frame and is not writable.
#[test]
fn writer_rejects_zero_per_type_count() {
    let text = frame("seed", 0.0);
    let mut parsed = ConFrameIterator::new(&text)
        .next()
        .expect("result")
        .expect("parse");
    parsed.header.natms_per_type = vec![0];
    let mut buf = Vec::new();
    let err = ConFrameWriter::new(&mut buf)
        .write_frame(&parsed)
        .unwrap_err();
    match err {
        WriteError::Format(ParseError::InvalidCount(msg)) => {
            assert!(msg.contains("per-type"), "{msg}");
        }
        other => panic!("expected InvalidCount, got {other:?}"),
    }
}

fn units_meta(value: serde_json::Value) -> serde_json::Map<String, serde_json::Value> {
    value.as_object().expect("object").clone()
}

/// `units.time` follows the minor, unless an override replaces it.
#[test]
fn velocity_time_unit_override_and_missing_time() {
    let mut meta = units_meta(serde_json::json!({
        "con_spec_minor": 1,
        "units": {"length": "angstrom", "energy": "eV", "time": "fs"}
    }));
    assert_eq!(
        velocity_file_time_unit(3, &meta, Some("ps")).unwrap(),
        "ps",
        "an override replaces the file label"
    );
    let bad = velocity_file_time_unit(3, &meta, Some("eV")).unwrap_err();
    assert_eq!(bad.class_name(), "ValidationError", "{bad}");

    meta.get_mut("units")
        .and_then(|units| units.as_object_mut())
        .expect("units")
        .insert("time".into(), serde_json::json!(""));
    let empty = velocity_file_time_unit(3, &meta, None).unwrap_err();
    assert_eq!(empty.class_name(), "InvalidUnits", "{empty}");
    assert!(empty.to_string().contains("units.time"), "{empty}");

    meta.get_mut("units")
        .and_then(|units| units.as_object_mut())
        .expect("units")
        .insert("time".into(), serde_json::json!(1));
    let numeric = velocity_file_time_unit(3, &meta, None).unwrap_err();
    assert_eq!(numeric.class_name(), "InvalidUnits", "{numeric}");

    let mut bare = units_meta(serde_json::json!({
        "con_spec_minor": 1,
        "units": {"length": "angstrom", "energy": "eV"}
    }));
    let missing = velocity_file_time_unit(3, &bare, None).unwrap_err();
    assert!(missing.to_string().contains("units.time"), "{missing}");

    bare.insert("con_spec_minor".into(), serde_json::json!("1"));
    assert_eq!(
        velocity_file_time_unit(3, &bare, None).unwrap(),
        NATURAL_TIME_UNIT,
        "a non-integer minor is minor 0, which ignores the missing time key"
    );
}

/// File velocities scale into the natural time unit. A non-time label and an
/// expression that overflows the scale are both rejected.
#[test]
fn velocity_scale_to_natural_unit() {
    let fs = velocity_scale_to_natural("fs").unwrap();
    let via_natural = unit_conversion_factor(NATURAL_TIME_UNIT, "fs").unwrap();
    assert!(
        (fs - via_natural).abs() < 1e-9,
        "fs scale {fs} vs natural-to-fs {via_natural}"
    );
    let stored = 0.5_f64;
    let natural = stored * fs;
    assert!(natural > stored, "fs is shorter than the natural unit");
    let identity = velocity_scale_to_natural(NATURAL_TIME_UNIT).unwrap();
    assert!((identity - 1.0).abs() < 1e-12, "{identity}");

    let not_time = velocity_scale_to_natural("angstrom").unwrap_err();
    assert_eq!(not_time.class_name(), "ValidationError", "{not_time}");

    // (1e-15)^-22 overflows and (1e-15)^23 underflows, so the product is
    // not a finite time scale. The reader must not turn that into a velocity.
    let overflow = velocity_scale_to_natural("fs^-22*fs^23").unwrap_err();
    assert_eq!(overflow.class_name(), "InvalidUnits", "{overflow}");
    assert!(overflow.to_string().contains("zero scale"), "{overflow}");
}

/// Velocity and force unit names are checked, including on a v3 header.
#[test]
fn velocity_and_force_units_are_checked() {
    validate_unit_for_quantity("velocity", "angstrom/fs").unwrap();
    validate_unit_for_quantity("force", "eV/angstrom").unwrap();
    assert!(validate_unit_for_quantity("velocity", "eV").is_err());
    assert!(validate_unit_for_quantity("force", "fs").is_err());
    let unknown = validate_unit_for_quantity("temperature", "fs").unwrap_err();
    assert!(
        unknown.to_string().contains("unknown quantity"),
        "{unknown}"
    );

    let ok = v3_body(
        r#"{"con_spec_version":3,"units":{"length":"angstrom","energy":"eV","velocity":"angstrom/fs","force":"eV/angstrom"}}"#,
        "",
    );
    assert!(
        ConFrameIterator::new(&ok).next().unwrap().is_ok(),
        "legal velocity and force units"
    );

    let bad_velocity = v3_body(
        r#"{"con_spec_version":3,"units":{"length":"angstrom","energy":"eV","velocity":"eV"}}"#,
        "",
    );
    let err = ConFrameIterator::new(&bad_velocity)
        .next()
        .unwrap()
        .unwrap_err();
    assert_eq!(err.class_name(), "InvalidUnits", "{err}");
    assert!(err.to_string().contains("velocity"), "{err}");

    let bad_time = v3_body(
        r#"{"con_spec_version":3,"units":{"length":"angstrom","energy":"eV","time":1}}"#,
        "",
    );
    let err = ConFrameIterator::new(&bad_time)
        .next()
        .unwrap()
        .unwrap_err();
    assert_eq!(err.class_name(), "InvalidUnits", "{err}");
    assert!(err.to_string().contains("time"), "{err}");

    let empty_energy = v3_body(
        r#"{"con_spec_version":3,"units":{"length":"angstrom","energy":"  "}}"#,
        "",
    );
    let err = ConFrameIterator::new(&empty_energy)
        .next()
        .unwrap()
        .unwrap_err();
    assert_eq!(err.class_name(), "InvalidUnits", "{err}");

    let length_number = v3_body(
        r#"{"con_spec_version":3,"units":{"length":1,"energy":"eV"}}"#,
        "",
    );
    let err = ConFrameIterator::new(&length_number)
        .next()
        .unwrap()
        .unwrap_err();
    assert_eq!(err.class_name(), "InvalidUnits", "{err}");
    assert!(err.to_string().contains("length"), "{err}");
}
