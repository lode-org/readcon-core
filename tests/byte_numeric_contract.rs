use readcon_core::error::ParseError;
use readcon_core::frame_index::{
    FrameIndex, load_or_build, read_sidecar, sidecar_path, write_sidecar,
};
use readcon_core::iterators::{
    ConFrameIterator, MemchrLines, frames_from_bytes, read_all_frames_with_threads,
};
use readcon_core::parser::{parse_line_of_n_f64, parse_line_of_range_f64};
use readcon_core::types::AtomDatum;

const FRAME: &str = "seed\n{\"con_spec_version\":2}\n10 11 12\n90 90 90\n0 0\n0 0 0\n1\n1\n1.008\nH\nCoordinates of Component 1\n1.25 -2.5 3.75 0 42\n";

#[test]
fn byte_frames_preserve_order_identity_and_coordinates_at_every_worker_count() {
    let text = (0..32)
        .map(|i| FRAME.replace("1.25 -2.5", &format!("{}.25 -2.5", i)))
        .collect::<String>()
        .replace('\n', "\r\n");
    let expected = ConFrameIterator::new(&text)
        .collect::<Result<Vec<_>, _>>()
        .unwrap();
    assert_eq!(expected.len(), 32);
    for workers in [None, Some(0), Some(1), Some(2), Some(4)] {
        let actual = frames_from_bytes(text.as_bytes(), workers).unwrap();
        assert_eq!(actual, expected, "workers={workers:?}");
        for (i, frame) in actual.iter().enumerate() {
            let atom = &frame.atom_data[0];
            assert_eq!([atom.x, atom.y, atom.z], [i as f64 + 0.25, -2.5, 3.75]);
            assert_eq!(atom.atom_id, 42);
        }
        assert!(frames_from_bytes(b" \r\n\t", workers).unwrap().is_empty());
    }
}

#[test]
fn byte_frames_report_the_first_error_before_later_invalid_utf8() {
    let bad_number = FRAME.replace("1.25 -2.5", "nan -2.5");
    let mut bytes = [FRAME.as_bytes(), bad_number.as_bytes(), FRAME.as_bytes()].concat();
    bytes[FRAME.len() + bad_number.len()] = 0xff;
    for workers in [Some(1), Some(2), Some(4)] {
        assert!(matches!(
            frames_from_bytes(&bytes, workers),
            Err(ParseError::NonFiniteValue(token)) if token.eq_ignore_ascii_case("nan")
        ));
        let mut invalid_header = FRAME.as_bytes().to_vec();
        invalid_header[0] = 0xff;
        assert!(matches!(
            frames_from_bytes(&invalid_header, workers),
            Err(ParseError::ValidationError(message)) if message == "invalid UTF-8"
        ));
    }
}

#[test]
fn mapped_file_reads_match_byte_buffers_for_all_worker_counts() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("large.con");
    let text = FRAME.repeat(1024);
    std::fs::write(&path, text.as_bytes()).unwrap();
    for workers in [Some(1), Some(4)] {
        let frames = read_all_frames_with_threads(&path, workers).unwrap();
        assert_eq!(frames.len(), 1024);
        assert!(frames.iter().all(|frame| frame.atom_data.len() == 1));
        assert!(frames.iter().all(|frame| frame.atom_data[0].atom_id == 42));
        assert!(frames.iter().all(|frame| frame.atom_data[0].x == 1.25));
    }
}

#[test]
fn byte_line_cursor_preserves_unicode_crlf_and_an_unterminated_final_line() {
    let mut lines = MemchrLines::from_bytes("αβ\r\n\r\nlast".as_bytes());
    assert_eq!(lines.peek_line(), Some("αβ"));
    assert_eq!(lines.peek_line(), Some("αβ"));
    assert_eq!(lines.next_line(), Some("αβ"));
    assert_eq!(lines.next_line(), Some(""));
    assert_eq!(lines.next_line(), Some("last"));
    assert_eq!(lines.next_line(), None);
}

#[test]
fn long_numeric_fields_round_trip_binary64_and_apply_only_missing_defaults() {
    let input = "-0.0 1e-300 -1e300 0.1 1.7976931348623157e308 4.9406564584124654e-324";
    let expected = input
        .split_whitespace()
        .map(|s| s.parse::<f64>().unwrap().to_bits())
        .collect::<Vec<_>>();
    let actual = parse_line_of_n_f64(input, 6).unwrap();
    assert_eq!(
        actual.iter().map(|x| x.to_bits()).collect::<Vec<_>>(),
        expected
    );
    let defaults = [10., 20., 30., 40., 50., 60., 70.];
    assert_eq!(
        parse_line_of_range_f64("1 2 3 4 5", 5, 7, &defaults).unwrap(),
        vec![1., 2., 3., 4., 5., 60., 70.]
    );
    assert_eq!(
        parse_line_of_range_f64("1 2 3 4 5 6 7", 5, 7, &defaults).unwrap(),
        vec![1., 2., 3., 4., 5., 6., 7.]
    );
    for count in [5, 7] {
        let line = vec!["1"; count].join(" ");
        assert!(
            matches!(parse_line_of_n_f64(&line, 6), Err(ParseError::InvalidVectorLength { expected: 6, found }) if found == count)
        );
    }
    for count in [4, 8] {
        let line = vec!["1"; count].join(" ");
        assert!(
            matches!(parse_line_of_range_f64(&line, 5, 7, &defaults), Err(ParseError::InvalidVectorLength { expected: 7, found }) if found == count)
        );
    }
}

#[test]
fn long_numeric_fields_reject_nonfinite_and_partial_tokens() {
    let defaults = [0.; 6];
    for token in ["NaN", "+INF", "-Infinity", "1e309"] {
        let input = format!("1 2 3 4 5 {token}");
        assert!(matches!(
            parse_line_of_n_f64(&input, 6),
            Err(ParseError::NonFiniteValue(_))
        ));
        assert!(matches!(
            parse_line_of_range_f64(&input, 5, 6, &defaults),
            Err(ParseError::NonFiniteValue(_))
        ));
    }
    for token in ["1.2abc", "1.2.3", "value", "+"] {
        let input = format!("1 2 3 4 5 {token}");
        assert!(matches!(
            parse_line_of_n_f64(&input, 6),
            Err(ParseError::InvalidNumberFormat(_))
        ));
        assert!(matches!(
            parse_line_of_range_f64(&input, 5, 6, &defaults),
            Err(ParseError::InvalidNumberFormat(_))
        ));
    }
}

#[test]
fn sidecars_never_replace_the_data_file_as_authority() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("frames.con");
    let text = FRAME.repeat(2);
    std::fs::write(&path, &text).unwrap();
    assert_eq!(read_sidecar(&path).unwrap(), None);
    let index = load_or_build(&path, &text, true).unwrap();
    assert!(!index.is_empty());
    assert_eq!(index.len(), 2);
    assert_eq!(index.range(0), Some(0..FRAME.len()));
    assert_eq!(index.range(1), Some(FRAME.len()..text.len()));
    assert_eq!(index.range(2), None);
    assert_eq!(read_sidecar(&path).unwrap(), Some(index.clone()));
    let mut wrong_length = index.clone();
    wrong_length.data_len += 1;
    assert_eq!(
        write_sidecar(&path, &wrong_length).unwrap_err().kind(),
        std::io::ErrorKind::InvalidInput
    );
    let intact = std::fs::read(sidecar_path(&path)).unwrap();
    for byte in [0, 8, intact.len() - 1] {
        let mut corrupt = intact.clone();
        corrupt[byte] ^= 1;
        std::fs::write(sidecar_path(&path), corrupt).unwrap();
        assert_eq!(read_sidecar(&path).unwrap(), None);
        assert_eq!(load_or_build(&path, &text, false).unwrap(), index);
    }
    std::fs::write(sidecar_path(&path), &intact).unwrap();
    std::fs::write(&path, FRAME).unwrap();
    assert_eq!(read_sidecar(&path).unwrap(), None);
    assert_eq!(load_or_build(&path, FRAME, true).unwrap().len(), 1);
    assert!(FrameIndex::scan("").unwrap().is_empty());
}

#[test]
fn optional_atom_sections_clear_independently_and_clones_keep_their_values() {
    let mut atom = AtomDatum::coords("H", 1., 2., 3., [false; 3], 17);
    atom.set_velocity(None);
    atom.set_force(None);
    atom.set_energy(None);
    atom.set_charge(None);
    atom.set_spin(None);
    atom.set_magmom(None);
    atom.set_displacement(None);
    atom.set_spread(None);
    let empty = atom.clone();
    atom.set_velocity(Some([1., 2., 3.]));
    atom.set_force(Some([4., 5., 6.]));
    atom.set_energy(Some(-7.));
    atom.set_charge(Some(0.5));
    atom.set_spin(Some(-0.5));
    atom.set_magmom(Some([7., 8., 9.]));
    atom.set_displacement(Some([10., 11., 12.]));
    atom.set_spread(Some([0.1, 0.2, 0.3]));
    let stored = atom.clone();
    atom.set_force(None);
    assert_eq!(atom.force(), None);
    assert_eq!(atom.velocity(), Some([1., 2., 3.]));
    assert_eq!(atom.energy(), Some(-7.));
    atom.set_velocity(None);
    atom.set_energy(None);
    atom.set_charge(None);
    atom.set_spin(None);
    atom.set_magmom(None);
    atom.set_displacement(None);
    atom.set_spread(None);
    assert_eq!(atom, empty);
    assert_eq!(stored.velocity(), Some([1., 2., 3.]));
    assert_eq!(stored.force(), Some([4., 5., 6.]));
    assert_eq!(stored.energy(), Some(-7.));
    assert_eq!(stored.charge(), Some(0.5));
    assert_eq!(stored.spin(), Some(-0.5));
    assert_eq!(stored.magmom(), Some([7., 8., 9.]));
    assert_eq!(stored.displacement(), Some([10., 11., 12.]));
    assert_eq!(stored.spread(), Some([0.1, 0.2, 0.3]));
}

#[test]
fn byte_frames_ignore_trailing_whitespace_with_parallel_workers() {
    let text = format!("{}\n\t\r\n", FRAME.repeat(3));
    let expected = ConFrameIterator::new(&text)
        .collect::<Result<Vec<_>, _>>()
        .unwrap();
    assert_eq!(expected.len(), 3);
    for workers in [Some(1), Some(2), Some(4)] {
        assert_eq!(frames_from_bytes(text.as_bytes(), workers).unwrap(), expected);
    }
}
