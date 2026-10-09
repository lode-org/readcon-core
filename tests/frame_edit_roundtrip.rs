use readcon_core::error::ParseError;
use readcon_core::iterators::ConFrameIterator;
use readcon_core::types::{ConFrame, ConFrameBuilder};
use readcon_core::writer::{ConFrameWriter, FloatFormat};
use serde_json::json;

fn builder() -> ConFrameBuilder {
    let mut builder = ConFrameBuilder::new([12.0; 3], [90.0; 3]);
    for (id, x) in [(11, 1.25), (29, 2.5)] {
        builder
            .add_atom("H", x, 0.0, 0.0, [false; 3], id, 1.008)
            .with_force([x, -x, 0.0]);
    }
    builder
}

fn roundtrip(frames: &[ConFrame], canonical: bool) -> Vec<ConFrame> {
    let mut bytes = Vec::new();
    {
        let mut writer = ConFrameWriter::with_float_format(&mut bytes, FloatFormat::RoundTrip)
            .canonical(canonical);
        writer.extend(frames.iter()).unwrap();
        writer.flush().unwrap();
    }
    let text = String::from_utf8(bytes).unwrap();
    ConFrameIterator::new(&text).map(Result::unwrap).collect()
}

#[test]
fn edited_mode_and_spread_sections_survive_a_trajectory() {
    let mut builder = builder();
    builder.clear_atom_displacement(0).unwrap();
    builder.clear_atom_spread(1).unwrap();
    let mut frames = vec![builder.clone().build().unwrap()];
    let displacement = [0.125, -0.25, 0.375];
    let spread = [0.5, 0.25, 0.0];
    builder.set_atom_displacement(1, displacement).unwrap();
    builder.set_atom_spread(0, spread).unwrap();
    frames.push(builder.clone().build().unwrap());

    assert!(matches!(
        builder.set_atom_displacement(2, displacement),
        Err(ParseError::IndexOutOfBounds { index: 2, len: 2 })
    ));
    assert!(matches!(
        builder.clear_atom_spread(2),
        Err(ParseError::IndexOutOfBounds { index: 2, len: 2 })
    ));
    for invalid in [-1.0, f64::NAN, f64::INFINITY] {
        assert!(matches!(
            builder.set_atom_spread(0, [invalid, 0.0, 0.0]),
            Err(ParseError::ValidationError(message))
                if message == "spreads: atom 0 has a negative or non-finite spread"
        ));
    }
    assert_eq!(builder.clone().build().unwrap(), frames[1]);

    builder.clear_atom_displacement(1).unwrap();
    builder.clear_atom_spread(0).unwrap();
    frames.push(builder.clone().build().unwrap());
    builder.clear_displacements_section().clear_spreads_section();
    frames.push(builder.clone().build().unwrap());
    builder.set_atom_displacement(0, displacement).unwrap();
    builder.set_atom_spread(1, spread).unwrap();
    frames.push(builder.build().unwrap());

    for canonical in [false, true] {
        let decoded = roundtrip(&frames, canonical);
        assert_eq!(decoded, frames);
        for index in [0, 3] {
            for atom in &decoded[index].atom_data {
                assert_eq!(atom.displacement, None);
                assert_eq!(atom.spread, None);
            }
        }
        for (index, mode_atom, spread_atom) in [(1, 1, 0), (4, 0, 1)] {
            assert_eq!(decoded[index].atom_data[mode_atom].displacement, Some(displacement));
            assert_eq!(decoded[index].atom_data[1 - mode_atom].displacement, Some([0.0; 3]));
            assert_eq!(decoded[index].atom_data[spread_atom].spread, Some(spread));
            assert_eq!(decoded[index].atom_data[1 - spread_atom].spread, Some([0.0; 3]));
        }
        for atom in &decoded[2].atom_data {
            assert_eq!(atom.displacement, Some([0.0; 3]));
            assert_eq!(atom.spread, Some([0.0; 3]));
        }
        for frame in decoded {
            assert_eq!(frame.atom_data[0].force, Some([1.25, -1.25, 0.0]));
            assert_eq!(frame.atom_data[1].force, Some([2.5, -2.5, 0.0]));
        }
    }
}

#[test]
fn cached_nested_metadata_preserves_values_and_zero_signs() {
    let metadata = [
        json!({"details": {"mode": [0.0, 2.0], "label": "a"}}),
        json!({"details": {"mode": [-0.0, 2.0], "label": "a"}}),
        json!({"details": {"mode": [-0.0, 2.0], "label": "a"}}),
        json!({"details": {"mode": [-0.0, 2.0, 3.0], "label": "a"}}),
        json!({"details": {"mode": [-0.0, 2.0, 3.0], "label": "b"}}),
        json!({"details": {"mode": [0.0, 2.0], "source": "b"}}),
    ];
    let frames: Vec<_> = metadata
        .iter()
        .map(|value| {
            let mut builder = builder();
            builder.set_metadata_json(&value.to_string()).unwrap();
            builder.build().unwrap()
        })
        .collect();
    for canonical in [false, true] {
        let decoded = roundtrip(&frames, canonical);
        assert_eq!(decoded, frames);
        for (frame, expected) in decoded.iter().zip(metadata.iter()) {
            let actual = &frame.header.metadata["details"];
            assert_eq!(actual, &expected["details"]);
            assert_eq!(
                actual["mode"][0].as_f64().unwrap().to_bits(),
                expected["details"]["mode"][0].as_f64().unwrap().to_bits()
            );
        }
    }
}
