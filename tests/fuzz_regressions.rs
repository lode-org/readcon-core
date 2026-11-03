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
use readcon_core::stream::ConFrameReader;
use readcon_core::types::AtomDatum;
use std::alloc::{GlobalAlloc, Layout, System};
use std::cell::Cell;

/// Forwards to [`System`] and records the largest request on each thread.
struct LargestRequest;

thread_local! {
    static LARGEST: Cell<usize> = const { Cell::new(0) };
}

fn note(size: usize) {
    // The slot is gone while a thread exits, and nothing is measured then.
    let _ = LARGEST.try_with(|largest| largest.set(largest.get().max(size)));
}

// SAFETY: every method forwards its arguments unchanged to `System`.
unsafe impl GlobalAlloc for LargestRequest {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        note(layout.size());
        unsafe { System.alloc(layout) }
    }

    unsafe fn alloc_zeroed(&self, layout: Layout) -> *mut u8 {
        note(layout.size());
        unsafe { System.alloc_zeroed(layout) }
    }

    unsafe fn realloc(&self, ptr: *mut u8, layout: Layout, new_size: usize) -> *mut u8 {
        note(new_size);
        unsafe { System.realloc(ptr, layout, new_size) }
    }

    unsafe fn dealloc(&self, ptr: *mut u8, layout: Layout) {
        unsafe { System.dealloc(ptr, layout) }
    }
}

#[global_allocator]
static ALLOCATOR: LargestRequest = LargestRequest;

/// The result of `f` and the largest single allocation it asked for.
fn largest_request<T>(f: impl FnOnce() -> T) -> (T, usize) {
    LARGEST.with(|largest| largest.set(0));
    let out = f();
    (out, LARGEST.with(Cell::get))
}

/// Each atom line takes at least one byte of input, so storage sized by
/// the input stays under one [`AtomDatum`] per input byte.
fn input_bound(text: &str) -> usize {
    text.len() * size_of::<AtomDatum>()
}

const DECLARED: [u64; 2] = [u32::MAX as u64, usize::MAX as u64];

/// A legacy one-type frame that declares `atoms` atoms and holds two.
fn frame_declaring_atoms(atoms: u64) -> String {
    format!(
        "\n\n10 10 10\n90 90 90\n\n\n1\n{atoms}\n1.008\nH\nCoordinates of Component 1\n\
         0 0 0 0 1\n1 1 1 0 2\n"
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
        let bound = input_bound(&text);

        let (parsed, largest) = largest_request(|| ConFrameIterator::new(&text).next());
        assert!(
            matches!(parsed, Some(Err(ParseError::IncompleteFrame))),
            "{atoms} atoms from a str: {parsed:?}"
        );
        assert!(
            largest <= bound,
            "{atoms} atoms from a str: {largest} bytes"
        );

        let (parsed, largest) =
            largest_request(|| ConFrameIterator::from_bytes(text.as_bytes()).next());
        assert!(
            matches!(parsed, Some(Err(ParseError::IncompleteFrame))),
            "{atoms} atoms from bytes: {parsed:?}"
        );
        assert!(
            largest <= bound,
            "{atoms} atoms from bytes: {largest} bytes"
        );

        let (parsed, largest) = largest_request(|| parse_single_frame(&mut text.lines()));
        assert!(
            matches!(parsed, Err(ParseError::IncompleteFrame)),
            "{atoms} atoms from lines: {parsed:?}"
        );
        assert!(
            largest <= bound,
            "{atoms} atoms from lines: {largest} bytes"
        );
    }
}

#[test]
fn counts_that_sum_past_usize_max_are_an_incomplete_frame() {
    let text = frame_whose_counts_overflow();
    let (parsed, largest) = largest_request(|| ConFrameIterator::new(&text).next());
    assert!(
        matches!(parsed, Some(Err(ParseError::IncompleteFrame))),
        "{parsed:?}"
    );
    assert!(largest <= input_bound(&text), "{largest} bytes");
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
        let (item, largest) = largest_request(|| reader.next());
        let err = item.expect("one item").expect_err("an error");
        assert!(
            matches!(
                err.downcast_ref::<ParseError>(),
                Some(ParseError::IncompleteFrame)
            ),
            "{text:?}: {err}"
        );
        assert!(largest <= input_bound(&text), "{text:?}: {largest} bytes");
    }
}

#[test]
fn more_types_than_the_count_line_holds_is_a_length_error() {
    for types in DECLARED {
        let text = frame_declaring_types(types);
        let bound = input_bound(&text);
        let expected_types = usize::try_from(types).expect("a 64-bit usize");

        let (parsed, largest) = largest_request(|| ConFrameIterator::new(&text).next());
        assert!(
            matches!(
                parsed,
                Some(Err(ParseError::InvalidVectorLength { expected, found: 1 }))
                    if expected == expected_types
            ),
            "{types} types: {parsed:?}"
        );
        assert!(largest <= bound, "{types} types: {largest} bytes");

        let (skipped, largest) = largest_request(|| ConFrameIterator::new(&text).forward());
        assert!(
            matches!(
                skipped,
                Some(Err(ParseError::InvalidVectorLength { expected, found: 1 }))
                    if expected == expected_types
            ),
            "{types} types, skipped: {skipped:?}"
        );
        assert!(largest <= bound, "{types} types, skipped: {largest} bytes");
    }
}

#[test]
fn more_values_than_the_line_holds_is_a_length_error() {
    let line = "1 2 3 4 5 6";
    for n in DECLARED {
        let n = usize::try_from(n).expect("a 64-bit usize");
        let (parsed, largest) = largest_request(|| parse_line_of_n_f64(line, n));
        assert!(
            matches!(
                parsed,
                Err(ParseError::InvalidVectorLength { expected, found: 6 }) if expected == n
            ),
            "{n} values: {parsed:?}"
        );
        assert!(
            largest <= line.len() * size_of::<f64>(),
            "{n} values: {largest} bytes"
        );
    }
}
