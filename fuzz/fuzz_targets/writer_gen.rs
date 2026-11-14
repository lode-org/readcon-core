//! Valid frames for the writer fuzz targets.
//!
//! Coordinates, cells, masses, and velocities keep every finite binary64
//! value, including signed zero, subnormals, and the extreme exponents.
//! One symbol has one mass, so the builder's type-mass rule accepts the frame.

use readcon_core::iterators::frames_from_bytes;
use readcon_core::types::{ConFrame, ConFrameBuilder};
use readcon_core::units::NATURAL_TIME_UNIT;
use readcon_core::writer::write_frames_to_vec_with_threads;

pub struct Input<'a> {
    data: &'a [u8],
    at: usize,
}

impl<'a> Input<'a> {
    pub fn new(data: &'a [u8]) -> Self {
        Self { data, at: 0 }
    }

    fn byte(&mut self) -> u8 {
        let value = self.data.get(self.at).copied().unwrap_or(0);
        self.at += 1;
        value
    }

    /// A finite `f64`. Non-finite bit patterns become `0.0`. The low bits
    /// of a selector pick the values a uniform draw almost never hits.
    pub fn finite(&mut self) -> f64 {
        match self.byte() & 7 {
            0 => -0.0,
            1 => f64::from_bits(1),
            2 => f64::from_bits(0x8000_0000_0000_0001),
            3 => f64::MIN_POSITIVE,
            4 => f64::MAX,
            5 => -f64::MAX,
            6 => f64::from_bits(0x000f_ffff_ffff_ffff),
            _ => {
                let mut buf = [0u8; 8];
                for slot in &mut buf {
                    *slot = self.byte();
                }
                let value = f64::from_le_bytes(buf);
                if value.is_finite() { value } else { 0.0 }
            }
        }
    }
}

fn symbol(id: u8) -> String {
    let id = id % 32;
    let first = b'A' + (id % 26);
    let second = b'a' + (id / 26);
    format!("{}{}", first as char, second as char)
}

fn one_frame(input: &mut Input<'_>, atoms: usize, velocities: bool) -> Option<ConFrame> {
    let mut builder = ConFrameBuilder::new(
        [input.finite(), input.finite(), input.finite()],
        [input.finite(), input.finite(), input.finite()],
    );
    builder
        .set_units(serde_json::json!({
            "length": "angstrom",
            "energy": "eV",
            "mass": "amu",
            "time": NATURAL_TIME_UNIT,
        }))
        .ok()?;
    let mut mass_of = [None; 32];
    for index in 0..atoms {
        let species = input.byte() % 32;
        let mass = *mass_of[species as usize].get_or_insert_with(|| input.finite());
        let fixed = [
            input.byte() & 1 == 1,
            input.byte() & 1 == 1,
            input.byte() & 1 == 1,
        ];
        builder.add_atom(
            &symbol(species),
            input.finite(),
            input.finite(),
            input.finite(),
            fixed,
            index as u64,
            mass,
        );
        if velocities {
            builder.with_velocity([input.finite(), input.finite(), input.finite()]);
        }
    }
    builder.build().ok()
}

/// One to four frames. `same_atoms` keeps one atom count, which CON-bin requires.
pub fn frames_from(data: &[u8], same_atoms: bool) -> Option<Vec<ConFrame>> {
    let mut input = Input::new(data);
    let frames_n = 1 + usize::from(input.byte() % 4);
    let shared_atoms = 1 + usize::from(input.byte() % 8);
    let mut frames = Vec::with_capacity(frames_n);
    for _ in 0..frames_n {
        let atoms = if same_atoms {
            shared_atoms
        } else {
            1 + usize::from(input.byte() % 8)
        };
        let velocities = input.byte() & 1 == 1;
        frames.push(one_frame(&mut input, atoms, velocities)?);
    }
    Some(frames)
}

fn bits(value: f64) -> u64 {
    value.to_bits()
}

fn same_xyz(got: [f64; 3], expect: [f64; 3]) {
    assert_eq!(bits(got[0]), bits(expect[0]), "{got:?} vs {expect:?}");
    assert_eq!(bits(got[1]), bits(expect[1]));
    assert_eq!(bits(got[2]), bits(expect[2]));
}

pub fn assert_frames(got: &[ConFrame], expect: &[ConFrame]) {
    assert_eq!(got.len(), expect.len());
    for (got, expect) in got.iter().zip(expect.iter()) {
        assert_eq!(got.header.boxl.len(), 3);
        for index in 0..3 {
            assert_eq!(
                bits(got.header.boxl[index]),
                bits(expect.header.boxl[index])
            );
            assert_eq!(
                bits(got.header.angles[index]),
                bits(expect.header.angles[index])
            );
        }
        assert_eq!(got.header.natms_per_type, expect.header.natms_per_type);
        assert_eq!(
            got.header.masses_per_type.len(),
            expect.header.masses_per_type.len()
        );
        for (got_mass, expect_mass) in got
            .header
            .masses_per_type
            .iter()
            .zip(expect.header.masses_per_type.iter())
        {
            assert_eq!(bits(*got_mass), bits(*expect_mass));
        }
        assert_eq!(got.atom_data.len(), expect.atom_data.len());
        for (got_atom, expect_atom) in got.atom_data.iter().zip(expect.atom_data.iter()) {
            assert_eq!(got_atom.symbol.as_ref(), expect_atom.symbol.as_ref());
            assert_eq!(bits(got_atom.x()), bits(expect_atom.x()));
            assert_eq!(bits(got_atom.y()), bits(expect_atom.y()));
            assert_eq!(bits(got_atom.z()), bits(expect_atom.z()));
            assert_eq!(got_atom.fixed(), expect_atom.fixed());
            assert_eq!(got_atom.atom_id, expect_atom.atom_id);
            match (got_atom.velocity(), expect_atom.velocity()) {
                (Some(got_v), Some(expect_v)) => same_xyz(got_v, expect_v),
                (None, None) => {}
                (got_v, expect_v) => panic!("velocity {got_v:?} vs {expect_v:?}"),
            }
        }
    }
}

pub fn read_plain(bytes: &[u8], expect: &[ConFrame]) {
    let got = frames_from_bytes(bytes, Some(1)).expect("plain parse");
    assert_frames(&got, expect);
}

pub fn assert_threads_match(frames: &[ConFrame]) {
    let serial = write_frames_to_vec_with_threads(frames, 1, None, false).expect("serial");
    read_plain(&serial, frames);
    for workers in [1usize, 2, 4, 8] {
        let threaded =
            write_frames_to_vec_with_threads(frames, workers, None, false).expect("threaded");
        assert_eq!(threaded, serial, "workers {workers}");
    }
}
