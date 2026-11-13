use readcon_core::iterators::frames_from_bytes;
use readcon_core::types::{ConFrame, ConFrameBuilder};
use readcon_core::units::NATURAL_TIME_UNIT;

const SYMBOLS: [&str; 4] = ["Cu", "H", "O", "He"];

struct Input<'a> {
    data: &'a [u8],
    at: usize,
}

impl<'a> Input<'a> {
    fn byte(&mut self) -> u8 {
        let value = self.data.get(self.at).copied().unwrap_or(0);
        self.at += 1;
        value
    }

    fn finite(&mut self) -> f64 {
        let mut buf = [0u8; 8];
        for slot in &mut buf {
            *slot = self.byte();
        }
        let value = f64::from_le_bytes(buf);
        if value.is_finite() { value } else { 0.0 }
    }
}

fn length(value: f64) -> f64 {
    let magnitude = value.abs();
    if magnitude > 0.0 && magnitude < 1.0e6 {
        magnitude
    } else {
        10.0
    }
}

fn angle(value: f64) -> f64 {
    let wrapped = value.abs() % 180.0;
    if wrapped > 0.0 && wrapped < 180.0 {
        wrapped
    } else {
        90.0
    }
}

fn mass_of(value: f64) -> f64 {
    let magnitude = value.abs();
    if magnitude > 0.0 && magnitude < 1.0e6 {
        magnitude
    } else {
        12.0
    }
}

pub fn frame_from(data: &[u8]) -> Option<ConFrame> {
    let mut input = Input { data, at: 0 };
    let mut builder = ConFrameBuilder::new(
        [
            length(input.finite()),
            length(input.finite()),
            length(input.finite()),
        ],
        [
            angle(input.finite()),
            angle(input.finite()),
            angle(input.finite()),
        ],
    );
    builder
        .set_units(serde_json::json!({
            "length": "angstrom",
            "energy": "eV",
            "mass": "amu",
            "time": NATURAL_TIME_UNIT,
        }))
        .ok()?;
    let atoms = 1 + usize::from(input.byte() % 6);
    let with_velocity = input.byte() & 1 == 1;
    let mut species_mass = [None; SYMBOLS.len()];
    for index in 0..atoms {
        let species = usize::from(input.byte()) % SYMBOLS.len();
        let mass = *species_mass[species].get_or_insert_with(|| mass_of(input.finite()));
        let fixed = [
            input.byte() & 1 == 1,
            input.byte() & 1 == 1,
            input.byte() & 1 == 1,
        ];
        builder.add_atom(
            SYMBOLS[species],
            input.finite(),
            input.finite(),
            input.finite(),
            fixed,
            index as u64,
            mass,
        );
        if with_velocity {
            builder.with_velocity([input.finite(), input.finite(), input.finite()]);
        }
    }
    builder.build().ok()
}

fn same_bits(left: f64, right: f64) -> bool {
    left.to_bits() == right.to_bits()
}

pub fn assert_frame(got: &ConFrame, expect: &ConFrame) {
    assert_eq!(got.atom_data.len(), expect.atom_data.len());
    for (got_atom, expect_atom) in got.atom_data.iter().zip(expect.atom_data.iter()) {
        assert!(same_bits(got_atom.x(), expect_atom.x()));
        assert!(same_bits(got_atom.y(), expect_atom.y()));
        assert!(same_bits(got_atom.z(), expect_atom.z()));
        assert_eq!(got_atom.fixed(), expect_atom.fixed());
        match (got_atom.velocity(), expect_atom.velocity()) {
            (Some(got_v), Some(expect_v)) => {
                assert!(same_bits(got_v[0], expect_v[0]));
                assert!(same_bits(got_v[1], expect_v[1]));
                assert!(same_bits(got_v[2], expect_v[2]));
            }
            (None, None) => {}
            (got_v, expect_v) => panic!("velocity {got_v:?} vs {expect_v:?}"),
        }
    }
    assert_eq!(got.masses.len(), expect.masses.len());
    for index in 0..got.masses.len() {
        assert!(same_bits(
            got.masses.get_f64(index),
            expect.masses.get_f64(index)
        ));
    }
    for index in 0..3 {
        assert!(same_bits(got.header.boxl[index], expect.header.boxl[index]));
        assert!(same_bits(
            got.header.angles[index],
            expect.header.angles[index]
        ));
    }
}

pub fn read_back(bytes: &[u8], expect: &ConFrame) {
    let frames = frames_from_bytes(bytes, Some(1)).expect("plain parse");
    assert_eq!(frames.len(), 1);
    assert_frame(&frames[0], expect);
}
