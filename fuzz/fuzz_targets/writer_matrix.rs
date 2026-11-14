//! Every writer, then every reader, for one generated trajectory.
//!
//! Finite values, constraints, velocities, and empty frames must come back
//! bit-exact. NaN and infinity are spelled and rejected on read (CON-num.1).
//! CON-bin keeps positions and velocities only. A missing velocity is +0.0.
//! Rank ownership is a split of the frames in this process: each rank formats
//! with the binding writer, and the concatenation matches one binding write.

#![no_main]

use libfuzzer_sys::fuzz_target;
use readcon_core::compression::read_file_bytes;
use readcon_core::conbin::{read_owned_f64, write_from_con};
use readcon_core::error::ParseError;
use readcon_core::iterators::{frames_from_bytes, read_all_frames, read_all_frames_with_threads};
use readcon_core::types::{ConFrame, ConFrameBuilder};
use readcon_core::units::NATURAL_TIME_UNIT;
use readcon_core::writer::{
    ConFrameWriter, write_frame_refs_to_path, write_frames_to_vec_with_threads,
};

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

    fn float(&mut self, non_finite: bool) -> f64 {
        if non_finite && self.byte() % 5 == 0 {
            return match self.byte() % 4 {
                0 => f64::NAN,
                1 => f64::INFINITY,
                2 => f64::NEG_INFINITY,
                _ => -0.0,
            };
        }
        match self.byte() & 7 {
            0 => -0.0,
            1 => f64::from_bits(1),
            2 => f64::MIN_POSITIVE,
            3 => f64::MAX,
            4 => -f64::MAX,
            5 => f64::from_bits(0x000f_ffff_ffff_ffff),
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
    let id = id % 12;
    let first = b'A' + (id % 26);
    format!("{}{}", first as char, id)
}

fn one_frame(
    input: &mut Input<'_>,
    atoms: usize,
    non_finite: bool,
    velocities: bool,
) -> Option<ConFrame> {
    let mut builder = ConFrameBuilder::new(
        [
            input.float(non_finite),
            input.float(false),
            input.float(false),
        ],
        [90.0, 90.0, 90.0],
    );
    builder
        .set_units(serde_json::json!({
            "length": "angstrom",
            "energy": "eV",
            "mass": "amu",
            "time": NATURAL_TIME_UNIT,
        }))
        .ok()?;
    let species_n = 1 + usize::from(input.byte() % 5);
    let mut mass_of = [None; 12];
    for index in 0..atoms {
        let species = if species_n == 1 {
            0
        } else {
            // Uneven runs: most atoms stay on species 0, then one each.
            if index + 1 < species_n { index } else { 0 }
        };
        let species = (species % 12) as u8;
        let mass = *mass_of[species as usize].get_or_insert_with(|| {
            let mass = input.float(false).abs();
            if mass == 0.0 { 1.0 } else { mass }
        });
        let fixed = [
            input.byte() & 1 == 1,
            input.byte() & 1 == 1,
            input.byte() & 1 == 1,
        ];
        builder.add_atom(
            &symbol(species),
            input.float(non_finite),
            input.float(non_finite),
            input.float(non_finite),
            fixed,
            index as u64,
            mass,
        );
        if velocities {
            builder.with_velocity([
                input.float(non_finite),
                input.float(non_finite),
                input.float(non_finite),
            ]);
        }
    }
    builder.build().ok()
}

fn frames_of(data: &[u8]) -> Option<(Vec<ConFrame>, bool)> {
    let mut input = Input { data, at: 0 };
    let non_finite = input.byte() & 1 == 1;
    let frames_n = 1 + usize::from(input.byte() % 3);
    let velocities = input.byte() & 1 == 1;
    let mut frames = Vec::new();
    for index in 0..frames_n {
        let atoms = if index == 0 && input.byte() % 7 == 0 {
            0
        } else {
            1 + usize::from(input.byte() % 6)
        };
        frames.push(one_frame(&mut input, atoms, non_finite, velocities)?);
    }
    // The selector only asks for a non-finite draw. `-0.0` is finite, and a
    // draw can still land on a finite value, so the file is non-finite only
    // when a stored number actually is.
    let non_finite = frames.iter().any(frame_non_finite);
    Some((frames, non_finite))
}

fn frame_non_finite(frame: &ConFrame) -> bool {
    frame.header.boxl.iter().any(|v| !v.is_finite())
        || frame.header.angles.iter().any(|v| !v.is_finite())
        || frame.header.masses_per_type.iter().any(|v| !v.is_finite())
        || frame.atom_data.iter().any(|atom| {
            !atom.x().is_finite()
                || !atom.y().is_finite()
                || !atom.z().is_finite()
                || atom
                    .velocity()
                    .is_some_and(|v| v.iter().any(|n| !n.is_finite()))
        })
}

fn bits(value: f64) -> u64 {
    value.to_bits()
}

fn assert_same(got: &[ConFrame], expect: &[ConFrame]) {
    assert_eq!(got.len(), expect.len());
    for (got, expect) in got.iter().zip(expect.iter()) {
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
        assert_eq!(got.atom_data.len(), expect.atom_data.len());
        for (got_mass, expect_mass) in got
            .header
            .masses_per_type
            .iter()
            .zip(expect.header.masses_per_type.iter())
        {
            assert_eq!(bits(*got_mass), bits(*expect_mass));
        }
        for (got_atom, expect_atom) in got.atom_data.iter().zip(expect.atom_data.iter()) {
            assert_eq!(got_atom.symbol.as_ref(), expect_atom.symbol.as_ref());
            assert_eq!(bits(got_atom.x()), bits(expect_atom.x()));
            assert_eq!(bits(got_atom.y()), bits(expect_atom.y()));
            assert_eq!(bits(got_atom.z()), bits(expect_atom.z()));
            assert_eq!(got_atom.fixed(), expect_atom.fixed());
            assert_eq!(got_atom.atom_id, expect_atom.atom_id);
            match (got_atom.velocity(), expect_atom.velocity()) {
                (Some(got_v), Some(expect_v)) => {
                    assert_eq!(got_v.map(bits), expect_v.map(bits));
                }
                (None, None) => {}
                (got_v, expect_v) => panic!("velocity {got_v:?} vs {expect_v:?}"),
            }
        }
    }
}

fn expect_non_finite(bytes: &[u8]) {
    let err = frames_from_bytes(bytes, Some(1)).expect_err("non-finite text");
    assert!(matches!(err, ParseError::NonFiniteValue(_)), "{err:?}");
}

fn binding_bytes(frames: &[&ConFrame]) -> Vec<u8> {
    let mut out = Vec::new();
    for frame in frames {
        let mut one = Vec::new();
        {
            let mut writer = ConFrameWriter::new(&mut one);
            writer.write_frame_bound(frame).expect("bound");
            writer.flush().expect("flush");
        }
        out.extend_from_slice(&one);
    }
    out
}

fn ranked_bytes(frames: &[&ConFrame], ranks: usize) -> Vec<u8> {
    let ranks = ranks.max(1);
    let chunk = frames.len().div_ceil(ranks);
    let mut out = Vec::new();
    for rank in 0..ranks {
        let start = rank * chunk;
        if start >= frames.len() {
            continue;
        }
        let end = (start + chunk).min(frames.len());
        out.extend_from_slice(&binding_bytes(&frames[start..end]));
    }
    out
}

fuzz_target!(|data: &[u8]| {
    if data.len() > 2048 {
        return;
    }
    let Some((frames, non_finite)) = frames_of(data) else {
        return;
    };
    let refs: Vec<&ConFrame> = frames.iter().collect();
    let serial = write_frames_to_vec_with_threads(&frames, 1, None, false).expect("serial");
    let threaded = write_frames_to_vec_with_threads(&frames, 4, None, false).expect("threaded");
    assert_eq!(serial, threaded);
    let bound = binding_bytes(&refs);
    let ranks = 1 + usize::from(data.first().copied().unwrap_or(0) % 4);
    assert_eq!(ranked_bytes(&refs, ranks), bound);

    if non_finite {
        expect_non_finite(&serial);
        expect_non_finite(&bound);
        return;
    }
    assert_same(
        &frames_from_bytes(&serial, Some(1)).expect("plain"),
        &frames,
    );
    assert_same(
        &frames_from_bytes(&serial, Some(2)).expect("parallel"),
        &frames,
    );
    assert_same(
        &frames_from_bytes(&bound, Some(1)).expect("bound parse"),
        &frames,
    );

    let Ok(dir) = tempfile::tempdir() else {
        return;
    };
    let path = dir.path().join("out.con");
    write_frame_refs_to_path(&path, &refs, 2, None, false, false).expect("path");
    assert_same(&read_all_frames(&path).expect("read path"), &frames);
    assert_same(
        &read_all_frames_with_threads(&path, Some(2)).expect("threads"),
        &frames,
    );

    let gz = dir.path().join("out.con.gz");
    {
        let mut writer = ConFrameWriter::from_path_gzip(&gz).expect("gzip");
        for frame in &frames {
            writer.write_frame(frame).expect("gzip frame");
        }
        writer.flush().expect("gzip flush");
    }
    let inflated = read_file_bytes(&gz).expect("inflate gzip");
    assert_eq!(inflated, serial);
    assert_same(
        &frames_from_bytes(&inflated, Some(1)).expect("gzip parse"),
        &frames,
    );

    let zst = dir.path().join("out.con.zst");
    {
        let mut writer = ConFrameWriter::from_path_zstd(&zst).expect("zstd");
        for frame in &frames {
            writer.write_frame(frame).expect("zstd frame");
        }
        writer.flush().expect("zstd flush");
    }
    let inflated = read_file_bytes(&zst).expect("inflate zstd");
    assert_eq!(inflated, serial);
    assert_same(
        &frames_from_bytes(&inflated, Some(1)).expect("zstd parse"),
        &frames,
    );

    let same_atoms = frames
        .windows(2)
        .all(|pair| pair[0].atom_data.len() == pair[1].atom_data.len());
    let bin = dir.path().join("out.conbin");
    if same_atoms {
        write_from_con(&path, &bin, false).expect("conbin");
        let (_header, positions, velocities) = read_owned_f64(&bin, 1).expect("read conbin");
        let mut expect_pos = Vec::new();
        let mut expect_vel = Vec::new();
        for frame in &frames {
            for atom in &frame.atom_data {
                expect_pos.extend_from_slice(&[atom.x(), atom.y(), atom.z()]);
                expect_vel.extend_from_slice(&atom.velocity().unwrap_or([0.0; 3]));
            }
        }
        assert_eq!(positions.len(), expect_pos.len());
        for (got, expect) in positions.iter().zip(expect_pos.iter()) {
            assert_eq!(bits(*got), bits(*expect));
        }
        for (got, expect) in velocities.iter().zip(expect_vel.iter()) {
            assert_eq!(bits(*got), bits(*expect));
        }
    } else {
        let err = write_from_con(&path, &bin, false).expect_err("mixed atoms");
        assert!(matches!(err, ParseError::InvalidCount(_)), "{err:?}");
    }
});
