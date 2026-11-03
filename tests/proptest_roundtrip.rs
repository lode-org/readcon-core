use proptest::prelude::*;
use readcon_core::iterators::{ConFrameIterator, read_all_frames};
use readcon_core::types::ConFrameBuilder;
use readcon_core::units::NATURAL_TIME_UNIT;
use readcon_core::writer::{ConFrameWriter, FloatFormat};
use serde_json::json;
use std::ops::Range;

const SYMBOLS: [&str; 4] = ["H", "C", "O", "Cu"];
// IUPAC abridged standard atomic weights, as in the crate's own fixtures.
const MASSES: [f64; 4] = [1.008, 12.011, 15.999, 63.546];
// Up to two atoms of each symbol, so a frame can hold a type more than once.
const MAX_ATOMS_PER_FRAME: usize = SYMBOLS.len() * 2;
// Either sign and a full mantissa; tests/float_bits.rs covers the extremes
// of binary64.
const VALUES: Range<f64> = -1.0..1.0;
// A spread is a standard deviation, so it is never negative.
const SPREADS: Range<f64> = 0.0..1.0;

#[derive(Debug, Clone)]
struct FrameInput {
    symbols: Vec<usize>,
    coords: Vec<[f64; 3]>,
    fixed: Vec<[bool; 3]>,
    velocities: Vec<[f64; 3]>,
    forces: Vec<[f64; 3]>,
    atom_energies: Vec<f64>,
    charges: Vec<f64>,
    spins: Vec<f64>,
    magmoms: Vec<[f64; 3]>,
    displacements: Vec<[f64; 3]>,
    spreads: Vec<[f64; 3]>,
    sections: [bool; 8],
    frame_energy: Option<f64>,
    canonical: bool,
}

fn frame_strategy() -> impl Strategy<Value = FrameInput> {
    (1usize..(MAX_ATOMS_PER_FRAME + 1)).prop_flat_map(|n| {
        (
            prop::collection::vec(0usize..SYMBOLS.len(), n),
            prop::collection::vec(prop::array::uniform3(VALUES), n),
            prop::collection::vec(prop::array::uniform3(any::<bool>()), n),
            prop::collection::vec(prop::array::uniform3(VALUES), n),
            prop::collection::vec(prop::array::uniform3(VALUES), n),
            prop::collection::vec(VALUES, n),
            prop::collection::vec(VALUES, n),
            prop::collection::vec(VALUES, n),
            prop::collection::vec(prop::array::uniform3(VALUES), n),
            prop::collection::vec(prop::array::uniform3(VALUES), n),
            (
                prop::collection::vec(prop::array::uniform3(SPREADS), n),
                prop::array::uniform8(any::<bool>()),
                prop::option::of(VALUES),
                any::<bool>(),
            ),
        )
            .prop_map(
                |(
                    symbols,
                    coords,
                    fixed,
                    velocities,
                    forces,
                    atom_energies,
                    charges,
                    spins,
                    magmoms,
                    displacements,
                    tail,
                )| FrameInput {
                    spreads: tail.0,
                    sections: tail.1,
                    frame_energy: tail.2,
                    canonical: tail.3,
                    symbols,
                    coords,
                    fixed,
                    velocities,
                    forces,
                    atom_energies,
                    charges,
                    spins,
                    magmoms,
                    displacements,
                },
            )
    })
}

fn build_frame(input: &FrameInput) -> readcon_core::types::ConFrame {
    let max_abs = input
        .coords
        .iter()
        .flat_map(|xyz| xyz.iter())
        .fold(0.0_f64, |acc, v| acc.max(v.abs()));
    // Longer than the span of the coordinates, 2 * max_abs.
    let cell_len = max_abs.mul_add(2.0, 1.0);
    let mut builder = ConFrameBuilder::new([cell_len; 3], [90.0, 90.0, 90.0]);
    builder
        .set_units(json!({
            "length": "angstrom",
            "energy": "eV",
            "mass": "amu",
            "time": NATURAL_TIME_UNIT,
        }))
        .unwrap();
    if let Some(energy) = input.frame_energy {
        builder.set_energy(energy);
    }
    for i in 0..input.symbols.len() {
        let symbol_idx = input.symbols[i];
        builder.add_atom(
            SYMBOLS[symbol_idx],
            input.coords[i][0],
            input.coords[i][1],
            input.coords[i][2],
            input.fixed[i],
            i as u64,
            MASSES[symbol_idx],
        );
        if input.sections[0] {
            builder.with_velocity(input.velocities[i]);
        }
        if input.sections[1] {
            builder.with_force(input.forces[i]);
        }
        if input.sections[2] {
            builder.with_energy(input.atom_energies[i]);
        }
        if input.sections[3] {
            builder.with_charge(input.charges[i]);
        }
        if input.sections[4] {
            builder.with_spin(input.spins[i]);
        }
        if input.sections[5] {
            builder.with_magmom(input.magmoms[i]);
        }
        if input.sections[6] {
            builder.with_displacement(input.displacements[i]);
        }
        if input.sections[7] {
            builder.with_spread(input.spreads[i]);
        }
    }
    builder.build().expect("valid generated frame")
}

fn roundtrip_text(
    frame: &readcon_core::types::ConFrame,
    canonical: bool,
) -> readcon_core::types::ConFrame {
    let mut out = Vec::new();
    {
        let mut writer = ConFrameWriter::with_float_format(&mut out, FloatFormat::RoundTrip)
            .canonical(canonical);
        writer.write_frame(frame).expect("write text frame");
    }
    let text = String::from_utf8(out).expect("utf8 writer output");
    let mut parsed = ConFrameIterator::new(&text);
    let got = parsed.next().expect("frame present").expect("reparse");
    assert!(parsed.next().is_none());
    got
}

fn roundtrip_path(
    frame: &readcon_core::types::ConFrame,
    suffix: &str,
) -> readcon_core::types::ConFrame {
    let tmp = tempfile::NamedTempFile::with_suffix(suffix).expect("tmpfile");
    let path = tmp.path().to_path_buf();
    if suffix.ends_with(".gz") {
        let mut writer = ConFrameWriter::from_path_gzip(&path).expect("gzip");
        writer.write_frame(frame).expect("write gzip");
    } else if suffix.ends_with(".zst") {
        #[cfg(feature = "zstd")]
        {
            let mut writer = ConFrameWriter::from_path_zstd(&path).expect("zstd");
            writer.write_frame(frame).expect("write zstd");
        }
        #[cfg(not(feature = "zstd"))]
        panic!("zstd suffix used without feature");
    } else {
        let mut writer = ConFrameWriter::from_path(&path).expect("writer");
        writer.write_frame(frame).expect("write path");
    }
    let mut frames = read_all_frames(&path).expect("read path");
    assert_eq!(frames.len(), 1);
    frames.pop().unwrap()
}

proptest! {
    #[test]
    fn roundtrip_every_supported_format(input in frame_strategy()) {
        let frame = build_frame(&input);

        let rt_text = roundtrip_text(&frame, input.canonical);
        prop_assert_eq!(&rt_text, &frame);

        let rt_con = roundtrip_path(&frame, ".con");
        prop_assert_eq!(&rt_con, &frame);

        let rt_convel = roundtrip_path(&frame, ".convel");
        prop_assert_eq!(&rt_convel, &frame);

        let rt_gzip = roundtrip_path(&frame, ".con.gz");
        prop_assert_eq!(&rt_gzip, &frame);

        #[cfg(feature = "zstd")]
        {
            let rt_zstd = roundtrip_path(&frame, ".con.zst");
            prop_assert_eq!(&rt_zstd, &frame);
        }
    }
}
