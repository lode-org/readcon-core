//! Writer round trip for finite binary64 values the uniform range misses.
//!
//! Signed zero, subnormals, and the extreme exponents go through CON text,
//! gzip, zstd, and CON-bin. The threaded writer at 1, 2, 4, and 8 workers
//! matches the serial bytes.

use proptest::prelude::*;
use readcon_core::conbin::{read_owned_f64, write_from_con};
use readcon_core::iterators::frames_from_bytes;
use readcon_core::types::{ConFrame, ConFrameBuilder};
use readcon_core::units::NATURAL_TIME_UNIT;
use readcon_core::writer::write_frames_to_vec_with_threads;
use serde_json::json;

fn config() -> ProptestConfig {
    ProptestConfig {
        cases: 16,
        failure_persistence: None,
        ..ProptestConfig::default()
    }
}

fn odd_f64() -> impl Strategy<Value = f64> {
    prop_oneof![
        1 => Just(0.0),
        1 => Just(-0.0),
        1 => Just(f64::MIN_POSITIVE),
        1 => Just(-f64::MIN_POSITIVE),
        1 => Just(f64::MIN),
        1 => Just(f64::MAX),
        1 => Just(-f64::MAX),
        1 => Just(f64::from_bits(1)),
        1 => Just(f64::from_bits(0x8000_0000_0000_0001)),
        1 => Just(f64::from_bits(0x000f_ffff_ffff_ffff)),
        8 => any::<u64>().prop_map(|bits| {
            let value = f64::from_bits(bits);
            if value.is_finite() { value } else { 0.0 }
        }),
    ]
}

fn symbol(id: usize) -> String {
    let id = (id % 24) as u8;
    let first = b'A' + (id % 26);
    let second = b'a' + (id / 26);
    format!("{}{}", first as char, second as char)
}

fn build_frames(
    species: &[Vec<usize>],
    coords: &[Vec<[f64; 3]>],
    fixed: &[Vec<[bool; 3]>],
    masses: &[f64],
    cells: &[[f64; 3]],
    angles: &[[f64; 3]],
    velocities: &[Option<Vec<[f64; 3]>>],
) -> Vec<ConFrame> {
    species
        .iter()
        .enumerate()
        .map(|(frame_index, kinds)| {
            let mut builder = ConFrameBuilder::new(cells[frame_index], angles[frame_index]);
            builder
                .set_units(json!({
                    "length": "angstrom",
                    "energy": "eV",
                    "mass": "amu",
                    "time": NATURAL_TIME_UNIT,
                }))
                .expect("units");
            for (atom, &kind) in kinds.iter().enumerate() {
                builder.add_atom(
                    &symbol(kind),
                    coords[frame_index][atom][0],
                    coords[frame_index][atom][1],
                    coords[frame_index][atom][2],
                    fixed[frame_index][atom],
                    atom as u64,
                    masses[kind % masses.len()],
                );
                if let Some(vel) = &velocities[frame_index] {
                    builder.with_velocity(vel[atom]);
                }
            }
            builder.build().expect("frame")
        })
        .collect()
}

fn bits(value: f64) -> u64 {
    value.to_bits()
}

fn assert_frames(got: &[ConFrame], expect: &[ConFrame]) {
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
                (Some(got_v), Some(expect_v)) => {
                    for index in 0..3 {
                        assert_eq!(bits(got_v[index]), bits(expect_v[index]));
                    }
                }
                (None, None) => {}
                (got_v, expect_v) => panic!("velocity {got_v:?} vs {expect_v:?}"),
            }
        }
    }
}

#[test]
fn zstd_drop_reads_back_one_frame() {
    for n in [1usize, 4, 8, 16] {
        let species = vec![0; n];
        let coords = vec![[0.0, f64::from_bits(1), f64::MAX]; n];
        let fixed = vec![[false, true, false]; n];
        let vel = vec![[-0.0, f64::MIN_POSITIVE, -f64::MAX]; n];
        let frame = build_frames(
            &[species],
            &[coords],
            &[fixed],
            &[12.0],
            &[[10.0, f64::MIN, -0.0]],
            &[[90.0, f64::from_bits(1), 90.0]],
            &[Some(vel)],
        );
        let dir = tempfile::tempdir().unwrap();
        let zst = dir.path().join("one.con.zst");
        {
            let mut writer = readcon_core::writer::ConFrameWriter::from_path_zstd(&zst).unwrap();
            writer.write_frame(&frame[0]).unwrap();
            writer.flush().unwrap();
        }
        let inflated = readcon_core::compression::read_file_bytes(&zst)
            .unwrap_or_else(|err| panic!("n={n} zstd: {err}"));
        let got = frames_from_bytes(&inflated, Some(1)).unwrap();
        assert_frames(&got, &frame);
    }
}

proptest! {
    #![proptest_config(config())]
    #[test]
    fn odd_floats_round_trip_every_writer(
        n_frames in 1usize..4,
        n_atoms in 1usize..5,
        species in prop::collection::vec(prop::collection::vec(0usize..24, 1..5), 1..4),
        coords in prop::collection::vec(
            prop::collection::vec(prop::array::uniform3(odd_f64()), 1..5),
            1..4,
        ),
        fixed in prop::collection::vec(
            prop::collection::vec(prop::array::uniform3(any::<bool>()), 1..5),
            1..4,
        ),
        masses in prop::collection::vec(odd_f64(), 24),
        cells in prop::collection::vec(prop::array::uniform3(odd_f64()), 1..4),
        angles in prop::collection::vec(prop::array::uniform3(odd_f64()), 1..4),
        with_velocity in prop::collection::vec(any::<bool>(), 1..4),
        vel in prop::collection::vec(
            prop::collection::vec(prop::array::uniform3(odd_f64()), 1..5),
            1..4,
        ),
    ) {
        let n_frames = n_frames.min(species.len()).min(coords.len()).min(fixed.len())
            .min(cells.len()).min(angles.len()).min(with_velocity.len()).min(vel.len());
        let n_atoms = n_atoms.min(4);
        let species: Vec<Vec<usize>> = species.into_iter().take(n_frames).map(|row| {
            let mut row = row;
            row.resize(n_atoms, 0);
            row
        }).collect();
        let coords: Vec<Vec<[f64; 3]>> = coords.into_iter().take(n_frames).map(|row| {
            let mut row = row;
            row.resize(n_atoms, [0.0; 3]);
            row
        }).collect();
        let fixed: Vec<Vec<[bool; 3]>> = fixed.into_iter().take(n_frames).map(|row| {
            let mut row = row;
            row.resize(n_atoms, [false; 3]);
            row
        }).collect();
        let velocities: Vec<Option<Vec<[f64; 3]>>> = with_velocity.into_iter().take(n_frames).zip(vel).map(|(on, row)| {
            if !on {
                return None;
            }
            let mut row = row;
            row.resize(n_atoms, [0.0; 3]);
            Some(row)
        }).collect();
        let frames = build_frames(
            &species,
            &coords,
            &fixed,
            &masses,
            &cells[..n_frames],
            &angles[..n_frames],
            &velocities,
        );

        let serial = write_frames_to_vec_with_threads(&frames, 1, None, false).unwrap();
        let parsed = frames_from_bytes(&serial, Some(1)).unwrap();
        assert_frames(&parsed, &frames);
        for workers in [1usize, 2, 4, 8] {
            let threaded = write_frames_to_vec_with_threads(&frames, workers, None, false).unwrap();
            prop_assert_eq!(&threaded, &serial, "workers {}", workers);
        }

        let dir = tempfile::tempdir().unwrap();
        let con = dir.path().join("odd.con");
        std::fs::write(&con, &serial).unwrap();
        let gz = dir.path().join("odd.con.gz");
        {
            let mut writer = readcon_core::writer::ConFrameWriter::from_path_gzip(&gz).unwrap();
            for frame in &frames {
                writer.write_frame(frame).unwrap();
            }
            writer.flush().unwrap();
        }
        let inflated = readcon_core::compression::read_file_bytes(&gz).unwrap();
        assert_frames(&frames_from_bytes(&inflated, Some(1)).unwrap(), &frames);

        #[cfg(feature = "zstd")]
        {
            let zst = dir.path().join("odd.con.zst");
            {
                let mut writer = readcon_core::writer::ConFrameWriter::from_path_zstd(&zst).unwrap();
                for frame in &frames {
                    writer.write_frame(frame).unwrap();
                }
            }
            let inflated = readcon_core::compression::read_file_bytes(&zst).unwrap();
            assert_frames(&frames_from_bytes(&inflated, Some(1)).unwrap(), &frames);
        }

        let bin = dir.path().join("odd.conbin");
        write_from_con(&con, &bin, false).unwrap();
        let (_header, positions, velocities_bin) = read_owned_f64(&bin, 1).unwrap();
        let mut expect_pos = Vec::new();
        let mut expect_vel = Vec::new();
        for frame in &frames {
            for atom in &frame.atom_data {
                expect_pos.extend_from_slice(&[atom.x(), atom.y(), atom.z()]);
                expect_vel.extend_from_slice(&atom.velocity().unwrap_or([0.0; 3]));
            }
        }
        prop_assert_eq!(positions.len(), expect_pos.len());
        for (got, expect) in positions.iter().zip(expect_pos.iter()) {
            prop_assert_eq!(got.to_bits(), expect.to_bits());
        }
        for (got, expect) in velocities_bin.iter().zip(expect_vel.iter()) {
            prop_assert_eq!(got.to_bits(), expect.to_bits());
        }
    }
}
