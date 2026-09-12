use readcon_core::iterators::ConFrameIterator;
use readcon_core::types::ConFrameBuilder;
use readcon_core::writer::{ConFrameWriter, FloatFormat};

#[test]
fn round_trip_preserves_every_numeric_section() {
    let values = [
        0.001_527_890_189_282_565_8,
        -0.001_527_890_189_282_565_8,
        0.0,
        -0.0,
        f64::MIN_POSITIVE,
        f64::from_bits(1),
        -f64::from_bits(1),
        1.234_567_890_123_456_7e-100,
        1.234_567_890_123_456_7e100,
        f64::MAX,
        -f64::MAX,
    ];
    for canonical in [false, true] {
        for value in values {
            let mut builder = ConFrameBuilder::new(
                [10.001_527_890_189_283, 20.0, 30.0],
                [89.123_456_789_012_35, 90.0, 90.0],
            );
            builder.set_energy(value);
            builder
                .add_atom(
                    "H",
                    value,
                    -value,
                    -0.0,
                    [true, false, true],
                    7,
                    1.001_527_890_189_282_6,
                )
                .with_velocity([value, -value, -0.0])
                .with_force([value, -value, -0.0])
                .with_energy(value)
                .with_charge(value)
                .with_spin(value)
                .with_magmom([value, -value, -0.0]);
            let frame = builder.build().unwrap();
            let mut buffer = Vec::new();
            {
                let mut writer =
                    ConFrameWriter::with_float_format(&mut buffer, FloatFormat::RoundTrip)
                        .canonical(canonical);
                writer.write_frame(&frame).unwrap();
            }
            let text = String::from_utf8(buffer).unwrap();
            let mut frames = ConFrameIterator::new(&text);
            let actual = frames.next().unwrap().unwrap();
            assert!(frames.next().is_none());
            assert_eq!(actual, frame, "value {value:e}, canonical {canonical}");
            let atom = &actual.atom_data[0];
            let stored = [atom.x, atom.y, atom.z];
            let expected = [value, -value, -0.0];
            for vector in [
                stored,
                atom.force.unwrap(),
                atom.velocity.unwrap(),
                atom.magmom.unwrap(),
            ] {
                assert_eq!(vector.map(f64::to_bits), expected.map(f64::to_bits));
            }
            for scalar in [
                atom.energy.unwrap(),
                atom.charge.unwrap(),
                atom.spin.unwrap(),
                actual.header.energy().unwrap(),
            ] {
                assert_eq!(scalar.to_bits(), value.to_bits());
            }
        }
    }
}
