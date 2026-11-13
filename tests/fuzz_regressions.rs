//! Headers that declare more types or atoms than the input holds.
//!
//! The reader must report the spec error for these (CON-frame.4,
//! CON-num.9), and no single allocation may grow with the declared count.
//! A count of `usize::MAX` overflows a reservation sized by it. A count of
//! `u32::MAX` gives a reservation of tens of GiB, more than most hosts can
//! map.

use readcon_core::error::ParseError;
use readcon_core::iterators::ConFrameIterator;
use readcon_core::parser::{parse_line_of_n_f64, parse_single_frame};
use readcon_core::storage_dtype::ElementKind;
use readcon_core::stream::ConFrameReader;

// The library installs mimalloc as the process allocator. An integration
// test cannot install a second one to record request sizes. These tests
// keep the spec result: a count the input cannot hold is IncompleteFrame
// or InvalidVectorLength, not a reservation that follows the declaration.

const DECLARED: [u64; 2] = [u32::MAX as u64, usize::MAX as u64];

/// A legacy one-type frame that declares `atoms` atoms and holds two.
fn frame_declaring_atoms(atoms: u64) -> String {
    format!(
        "\n\n10 10 10\n90 90 90\n\n\n1\n{atoms}\n1.008\nH\nCoordinates of Component 1\n\
         0 0 0 0 1\n1 1 1 0 2\n"
    )
}

/// A version 3 one-type frame that stores positions as `kind` and declares
/// `atoms` atoms, of which it holds two.
fn frame_declaring_atoms_as(kind: ElementKind, atoms: u64) -> String {
    format!(
        "\n{{\"con_spec_version\":3,\"units\":{{\"length\":\"angstrom\",\"energy\":\"eV\"}},\
         \"storage_dtypes\":{{\"positions\":\"{}\"}}}}\n10 10 10\n90 90 90\n\n\n1\n{atoms}\n\
         1.008\nH\nCoordinates of Component 1\n0 0 0 0 1\n1 1 1 0 2\n",
        kind.as_str()
    )
}

/// A legacy two-type frame whose counts sum past `usize::MAX`.
fn frame_whose_counts_overflow() -> String {
    format!(
        "\n\n10 10 10\n90 90 90\n\n\n2\n{} 1\n1.008 12.011\nH\nCoordinates of Component 1\n\
         0 0 0 0 1\n1 1 1 0 2\n",
        usize::MAX
    )
}

/// Every frame above that declares more atoms than it holds.
fn short_frames() -> Vec<String> {
    let mut frames: Vec<String> = DECLARED.into_iter().map(frame_declaring_atoms).collect();
    frames.push(frame_whose_counts_overflow());
    frames
}

/// A legacy frame that declares `types` types and lists one count.
fn frame_declaring_types(types: u64) -> String {
    format!(
        "\n\n10 10 10\n90 90 90\n\n\n{types}\n2\n1.008\nH\nCoordinates of Component 1\n\
         0 0 0 0 1\n1 1 1 0 2\n"
    )
}

#[test]
fn more_atoms_than_the_input_holds_is_an_incomplete_frame() {
    for atoms in DECLARED {
        let text = frame_declaring_atoms(atoms);

        let parsed = ConFrameIterator::new(&text).next();
        assert!(
            matches!(parsed, Some(Err(ParseError::IncompleteFrame))),
            "{atoms} atoms from a str: {parsed:?}"
        );

        let parsed = ConFrameIterator::from_bytes(text.as_bytes()).next();
        assert!(
            matches!(parsed, Some(Err(ParseError::IncompleteFrame))),
            "{atoms} atoms from bytes: {parsed:?}"
        );

        let parsed = parse_single_frame(&mut text.lines());
        assert!(
            matches!(parsed, Err(ParseError::IncompleteFrame)),
            "{atoms} atoms from lines: {parsed:?}"
        );
    }
}

#[test]
fn more_atoms_than_the_input_holds_is_an_incomplete_frame_in_every_dtype() {
    for &kind in ElementKind::all_hosted() {
        for atoms in DECLARED {
            let text = frame_declaring_atoms_as(kind, atoms);
            let parsed = ConFrameIterator::new(&text).next();
            assert!(
                matches!(parsed, Some(Err(ParseError::IncompleteFrame))),
                "{kind:?}, {atoms} atoms: {parsed:?}"
            );
        }
    }
}

#[test]
fn counts_that_sum_past_usize_max_are_an_incomplete_frame() {
    let text = frame_whose_counts_overflow();
    let parsed = ConFrameIterator::new(&text).next();
    assert!(
        matches!(parsed, Some(Err(ParseError::IncompleteFrame))),
        "{parsed:?}"
    );
}

#[test]
fn a_skip_over_a_short_frame_is_an_incomplete_frame() {
    for text in short_frames() {
        let skipped = ConFrameIterator::new(&text).forward();
        assert!(
            matches!(skipped, Some(Err(ParseError::IncompleteFrame))),
            "{text:?}: {skipped:?}"
        );
        let skipped = ConFrameIterator::new(&text).skip_frames(1);
        assert!(
            matches!(skipped, Err(ParseError::IncompleteFrame)),
            "{text:?}: {skipped:?}"
        );
    }
}

#[test]
fn the_stream_reader_reports_a_short_frame_as_incomplete() {
    for text in short_frames() {
        let mut reader = ConFrameReader::with_read_size(text.as_bytes(), 1);
        let item = reader.next();
        let err = item.expect("one item").expect_err("an error");
        assert!(
            matches!(
                err.downcast_ref::<ParseError>(),
                Some(ParseError::IncompleteFrame)
            ),
            "{text:?}: {err}"
        );
    }
}

#[test]
fn more_types_than_the_count_line_holds_is_a_length_error() {
    for types in DECLARED {
        let text = frame_declaring_types(types);
        let expected_types = usize::try_from(types).expect("a 64-bit usize");

        let parsed = ConFrameIterator::new(&text).next();
        assert!(
            matches!(
                parsed,
                Some(Err(ParseError::InvalidVectorLength { expected, found: 1 }))
                    if expected == expected_types
            ),
            "{types} types: {parsed:?}"
        );

        let skipped = ConFrameIterator::new(&text).forward();
        assert!(
            matches!(
                skipped,
                Some(Err(ParseError::InvalidVectorLength { expected, found: 1 }))
                    if expected == expected_types
            ),
            "{types} types, skipped: {skipped:?}"
        );
    }
}

#[test]
fn more_values_than_the_line_holds_is_a_length_error() {
    let line = "1 2 3 4 5 6";
    for n in DECLARED {
        let n = usize::try_from(n).expect("a 64-bit usize");
        let parsed = parse_line_of_n_f64(line, n);
        assert!(
            matches!(
                parsed,
                Err(ParseError::InvalidVectorLength { expected, found: 6 }) if expected == n
            ),
            "{n} values: {parsed:?}"
        );
    }
}
