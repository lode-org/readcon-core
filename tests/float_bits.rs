//! Binary64 round trip (CON-num.6) and fast-float agreement with `f64::from_str`
//! on the conformance corpus coordinate rows.

use readcon_core::iterators::ConFrameIterator;
use readcon_core::types::ConFrameBuilder;
use readcon_core::writer::{ConFrameWriter, FloatFormat};
use std::fs;
use std::path::Path;

#[test]
fn corpus_coordinate_rows_match_std_parse() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("resources/conformance/valid");
    for entry in fs::read_dir(&root).unwrap() {
        let path = entry.unwrap().path();
        if path.extension().and_then(|ext| ext.to_str()) != Some("con") {
            continue;
        }
        let text = fs::read_to_string(&path).unwrap();
        let frames: Vec<_> = ConFrameIterator::new(&text)
            .map(|frame| frame.expect("valid corpus frame"))
            .collect();
        let mut from_atoms = Vec::new();
        for frame in &frames {
            for atom in &frame.atom_data {
                from_atoms.push((atom.x.to_bits(), atom.y.to_bits(), atom.z.to_bits()));
            }
        }
        let mut from_std = Vec::new();
        for line in text.lines() {
            let toks: Vec<&str> = line.split_whitespace().collect();
            if toks.len() < 4 {
                continue;
            }
            let (Ok(x), Ok(y), Ok(z)) = (
                toks[0].parse::<f64>(),
                toks[1].parse::<f64>(),
                toks[2].parse::<f64>(),
            ) else {
                continue;
            };
            // Column 4 is the integer fixed-flag, which separates a coordinate
            // row from box, angle, and mass lines.
            if toks[3].bytes().any(|b| !b.is_ascii_digit()) {
                continue;
            }
            from_std.push((x.to_bits(), y.to_bits(), z.to_bits()));
        }
        assert_eq!(
            from_std,
            from_atoms,
            "fast-float coordinates diverged from std parse in {}",
            path.display()
        );
    }
}

#[test]
fn round_trip_writer_preserves_binary64_bits() {
    let mut values = vec![
        0.0,
        -0.0,
        1.0,
        -1.0,
        f64::MIN,
        f64::MAX,
        f64::MIN_POSITIVE,
        f64::EPSILON,
        1.234_567_890_123_456_7,
        f64::from_bits(1),
        f64::from_bits(0x000f_ffff_ffff_ffff),
    ];
    let mut state = 0x1234_5678_9abc_def0u64;
    for _ in 0..4096 {
        state = state.wrapping_mul(6364136223846793005).wrapping_add(1);
        let value = f64::from_bits(state);
        if value.is_finite() {
            values.push(value);
        }
    }

    let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
    for (i, value) in values.iter().copied().enumerate() {
        builder.add_atom("Cu", value, -value, 0.0, [false; 3], i as u64, 63.546);
    }
    let frame = builder.build().expect("frame");
    let mut buf = Vec::new();
    {
        let mut writer = ConFrameWriter::with_float_format(&mut buf, FloatFormat::RoundTrip);
        writer.write_frame(&frame).expect("write");
    }
    let text = String::from_utf8(buf).expect("utf-8");
    let back = ConFrameIterator::new(&text)
        .next()
        .expect("frame")
        .expect("parse");
    assert_eq!(back.atom_data.len(), values.len());
    for (atom, value) in back.atom_data.iter().zip(values.iter().copied()) {
        assert_eq!(atom.x.to_bits(), value.to_bits(), "{value:e}");
        assert_eq!(atom.y.to_bits(), (-value).to_bits(), "{value:e}");
        assert_eq!(atom.z.to_bits(), 0.0f64.to_bits());
    }
}
