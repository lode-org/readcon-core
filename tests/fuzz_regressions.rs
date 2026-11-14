//! Headers that declare more types or atoms than the input holds.
//!
//! The reader must report the spec error for these (CON-frame.4,
//! CON-num.9), and no single allocation may grow with the declared count.
//! A count of `usize::MAX` overflows a reservation sized by it. A count of
//! `u32::MAX` gives a reservation of tens of GiB, more than most hosts can
//! map.

use readcon_core::error::{LocatedParseError, ParseError};
use readcon_core::iterators::{ConFrameIterator, read_positions_with_threads};
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

fn extxyz_does_not_panic(bytes: &[u8]) {
    for threads in [1usize, 8] {
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            readcon_core::extxyz_scan::tables_from_extxyz_bytes_with_threads(bytes, threads)
        }));
        assert!(
            result.is_ok(),
            "extxyz reader panicked at {threads} threads"
        );
    }
}

#[test]
fn extxyz_huge_stride_does_not_panic() {
    let bytes = include_bytes!("fuzz_data/extxyz_huge_stride.bin");
    // The corpus is included as bytes. A trailing newline is a different input.
    assert_ne!(bytes.last().copied(), Some(b'\n'));
    extxyz_does_not_panic(bytes);
}

#[test]
fn extxyz_huge_count_does_not_allocate() {
    extxyz_does_not_panic(include_bytes!("fuzz_data/extxyz_huge_count.bin"));
}

#[test]
fn extxyz_wide_property_does_not_reserve_past_the_file() {
    // 100 atoms times a 4096-wide column is more lanes than the file has
    // bytes. The scanner must reject it instead of reserving that product.
    let bytes = b"\
100
Lattice=\"1 0 0 0 1 0 0 0 1\" Properties=species:S:1:pos:R:3:q:R:4096
Cu 0 0 0
";
    extxyz_does_not_panic(bytes);
}

fn resident_bytes() -> usize {
    let status = std::fs::read_to_string("/proc/self/status").expect("status");
    for line in status.lines() {
        let Some(rest) = line.strip_prefix("VmRSS:") else {
            continue;
        };
        let kb: usize = rest.split_whitespace().next().unwrap().parse().unwrap();
        return kb.saturating_mul(1024);
    }
    0
}

#[test]
fn extxyz_ten_to_the_fifteenth_is_an_error_without_allocating() {
    // 10^15 fits in `usize` and used to be reserved up front. That
    // reservation aborts. The reader now rejects the count.
    let bytes = b"\
1000000000000000
Lattice=\"1 0 0 0 1 0 0 0 1\" Properties=species:S:1:pos:R:3
Cu 0 0 0
";
    for threads in [1usize, 8] {
        let before = resident_bytes();
        let result =
            readcon_core::extxyz_scan::tables_from_extxyz_bytes_with_threads(bytes, threads);
        let after = resident_bytes();
        let err = result.expect_err("a 10^15 count is not a frame");
        assert!(
            err.contains("atoms"),
            "t{threads} error was {err}, rss {before} -> {after}"
        );
        assert!(
            after < before.saturating_add(8 << 20),
            "t{threads} resident {before} -> {after}"
        );
    }
}

#[test]
fn extxyz_stream_huge_count_does_not_allocate() {
    // A streaming layout (species, then pos) used to reserve the parsed
    // count before noticing the file cannot hold that many atoms.
    let bytes = b"\
80000000000000009887
Lattice=\"1 0 0 0 1 0 0 0 1\" Properties=species:S:1:pos:R:3
";
    extxyz_does_not_panic(bytes);
}

#[test]
fn conbin_huge_column_does_not_allocate() {
    // Minimized crash: CONBIN01, version 1, velocity flag, one frame,
    // 50_000_000 atoms, payload offset 40. The file is only the header.
    // `read_owned_f64` used to reserve both columns from that count.
    let bytes = include_bytes!("fuzz_data/conbin_huge_column.bin");
    assert_eq!(bytes.len(), 40);
    let dir = std::env::temp_dir().join(format!(
        "conbin-huge-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .expect("clock")
            .as_nanos()
    ));
    std::fs::create_dir_all(&dir).unwrap();
    let path = dir.join("huge.conbin");
    std::fs::write(&path, bytes).unwrap();
    for threads in [1usize, 2] {
        let before = resident_bytes();
        let err = readcon_core::conbin::read_owned_f64(&path, threads).unwrap_err();
        let after = resident_bytes();
        assert!(
            matches!(err, ParseError::IncompleteFrame),
            "t{threads}: {err:?}"
        );
        assert!(
            after < before.saturating_add(8 << 20),
            "t{threads} resident {before} -> {after}"
        );
    }
    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn column_walker_does_not_reserve_a_declared_atom_count() {
    // One coordinate row and a header that says 50_000_000 atoms. The
    // column walker used to reserve that count before it counted rows.
    let text = frame_declaring_atoms(50_000_000);
    let dir = std::env::temp_dir().join(format!(
        "column-huge-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .expect("clock")
            .as_nanos()
    ));
    std::fs::create_dir_all(&dir).unwrap();
    let path = dir.join("huge.con");
    std::fs::write(&path, text.as_bytes()).unwrap();
    for threads in [1usize, 2] {
        let before = resident_bytes();
        let err = read_positions_with_threads(&path, Some(threads)).unwrap_err();
        let after = resident_bytes();
        let located = err
            .downcast_ref::<LocatedParseError>()
            .expect("located parse error");
        assert!(
            matches!(located.error, ParseError::IncompleteFrame),
            "t{threads}: {located:?}"
        );
        assert!(
            after < before.saturating_add(8 << 20),
            "t{threads} resident {before} -> {after}"
        );
    }
    let _ = std::fs::remove_dir_all(&dir);
}
