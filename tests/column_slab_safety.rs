//! Slab fills match a full-frame read, and a bad size or header does not write.

use readcon_core::column_read::{
    SectionFlags, Slabs, fill_bytes, fill_bytes_threaded, fill_path, fill_path_threaded,
    layout_bytes,
};
use readcon_core::iterators::ConFrameIterator;
use readcon_core::types::ConFrame;
use std::path::Path;

const MARK: f64 = 42.0;

fn stock_frame(coord_label: &str, velocity_label: Option<&str>) -> String {
    let mut text = format!(
        "\
seed
{{\"con_spec_version\":2}}
1.0 1.0 1.0
90 90 90
0 0
0 0 0
1
1
1.0
H
{coord_label}
0.1 -0.2 0.3 0 0
"
    );
    if let Some(label) = velocity_label {
        text.push_str(&format!("\nH\n{label}\n0.1 0.4 -0.5 0 0\n"));
    }
    text
}

fn typed_frames(positions: &str, velocities: &str) -> Vec<u8> {
    let one = format!(
        "\
seed
{{\"con_spec_version\":3,\"units\":{{\"length\":\"angstrom\",\"energy\":\"eV\"}},\"storage_dtypes\":{{\"positions\":\"{positions}\",\"velocities\":\"{velocities}\"}}}}
1.0 1.0 1.0
90 90 90
0 0
0 0 0
1
1
1.0
H
Coordinates of Component 1
0.1 -0.2 0.3 0 0

H
Velocities of Component 1
0.1 0.4 -0.5 0 0
"
    );
    let mut bytes = one.into_bytes();
    bytes.extend_from_slice(&bytes.clone());
    bytes
}

fn charge_row(row: &str) -> String {
    format!(
        "\
seed
{{\"con_spec_version\":2}}
1.0 1.0 1.0
90 90 90
0 0
0 0 0
1
1
1.0
H
Coordinates of Component 1
0.1 -0.2 0.3 0 0

H
Charges of Component 1
{row}
"
    )
}

struct Filled {
    positions: Vec<f64>,
    velocities: Vec<f64>,
    forces: Vec<f64>,
    energies: Vec<f64>,
    charges: Vec<f64>,
    spins: Vec<f64>,
    magmoms: Vec<f64>,
}

fn fill_with(
    bytes: &[u8],
    n_frames: usize,
    n_atoms: usize,
    sections: SectionFlags,
    threads: Option<(&[usize], usize)>,
) -> Result<Filled, ()> {
    let n3 = n_frames * n_atoms * 3;
    let n1 = n_frames * n_atoms;
    let mut positions = vec![0.0; n3];
    let mut velocities = vec![0.0; n3];
    let mut forces = vec![0.0; n3];
    let mut energies = vec![0.0; n1];
    let mut charges = vec![0.0; n1];
    let mut spins = vec![0.0; n1];
    let mut magmoms = vec![0.0; n3];
    let slabs = Slabs {
        positions: &mut positions,
        velocities: sections.velocities.then_some(velocities.as_mut_slice()),
        forces: sections.forces.then_some(forces.as_mut_slice()),
        energies: sections.energies.then_some(energies.as_mut_slice()),
        charges: sections.charges.then_some(charges.as_mut_slice()),
        spins: sections.spins.then_some(spins.as_mut_slice()),
        magmoms: sections.magmoms.then_some(magmoms.as_mut_slice()),
        displacements: None,
        spreads: None,
    };
    let filled = match threads {
        None => fill_bytes(bytes, n_frames, n_atoms, sections, slabs),
        Some((offsets, end)) => {
            fill_bytes_threaded(bytes, n_frames, n_atoms, sections, 4, offsets, end, slabs)
        }
    };
    filled.map(|_| Filled {
        positions,
        velocities,
        forces,
        energies,
        charges,
        spins,
        magmoms,
    })
}

fn assert_matches(bytes: &[u8]) {
    let layout = layout_bytes(bytes).expect("layout");
    let frames = ConFrameIterator::from_bytes(bytes)
        .collect::<Result<Vec<ConFrame>, _>>()
        .expect("frames");
    assert_eq!(frames.len(), layout.n_frames);
    let serial = fill_with(
        bytes,
        layout.n_frames,
        layout.n_atoms,
        layout.sections,
        None,
    )
    .expect("fill_bytes");
    let threaded = fill_with(
        bytes,
        layout.n_frames,
        layout.n_atoms,
        layout.sections,
        Some((&layout.frame_offsets, layout.frames_end)),
    )
    .expect("fill_bytes_threaded");
    for (index, frame) in frames.iter().enumerate() {
        for atom in 0..layout.n_atoms {
            let at3 = (index * layout.n_atoms + atom) * 3;
            let at1 = index * layout.n_atoms + atom;
            let xyz = frame.xyz_at(atom);
            assert_eq!(serial.positions[at3..at3 + 3], xyz);
            assert_eq!(threaded.positions[at3..at3 + 3], xyz);
            if layout.sections.velocities {
                let vel = frame.velocities.as_f64_row(atom);
                assert_eq!(serial.velocities[at3..at3 + 3], vel);
                assert_eq!(threaded.velocities[at3..at3 + 3], vel);
            }
            if layout.sections.forces {
                let force = frame.forces.as_f64_row(atom);
                assert_eq!(serial.forces[at3..at3 + 3], force);
                assert_eq!(threaded.forces[at3..at3 + 3], force);
            }
            if layout.sections.energies {
                let value = frame.atom_energies.get_f64(atom);
                assert_eq!(serial.energies[at1], value);
                assert_eq!(threaded.energies[at1], value);
            }
            if layout.sections.charges {
                let value = frame.charges.get_f64(atom);
                assert_eq!(serial.charges[at1], value);
                assert_eq!(threaded.charges[at1], value);
            }
            if layout.sections.spins {
                let value = frame.spins.get_f64(atom);
                assert_eq!(serial.spins[at1], value);
                assert_eq!(threaded.spins[at1], value);
            }
            if layout.sections.magmoms {
                let row = frame.magmoms.as_f64_row(atom);
                assert_eq!(serial.magmoms[at3..at3 + 3], row);
                assert_eq!(threaded.magmoms[at3..at3 + 3], row);
            }
        }
    }
}

fn path_of(bytes: &[u8], name: &str) -> (tempfile::TempDir, std::path::PathBuf) {
    let dir = tempfile::tempdir().expect("scratch");
    let path = dir.path().join(format!("{name}.con"));
    std::fs::write(&path, bytes).expect("write");
    (dir, path)
}

fn assert_paths(bytes: &[u8]) {
    let layout = layout_bytes(bytes).expect("layout");
    let (_scratch, path) = path_of(bytes, "slab");
    let n3 = layout.n_frames * layout.n_atoms * 3;
    let mut positions = vec![0.0; n3];
    let mut velocities = vec![0.0; n3];
    let mut forces = vec![0.0; n3];
    let mut charges = vec![0.0; layout.n_frames * layout.n_atoms];
    let mut spins = vec![0.0; layout.n_frames * layout.n_atoms];
    let mut magmoms = vec![0.0; n3];
    let sections = layout.sections;
    fill_path(
        &path,
        layout.n_frames,
        layout.n_atoms,
        sections,
        Slabs {
            positions: &mut positions,
            velocities: sections.velocities.then_some(velocities.as_mut_slice()),
            forces: sections.forces.then_some(forces.as_mut_slice()),
            energies: None,
            charges: sections.charges.then_some(charges.as_mut_slice()),
            spins: sections.spins.then_some(spins.as_mut_slice()),
            magmoms: sections.magmoms.then_some(magmoms.as_mut_slice()),
            displacements: None,
            spreads: None,
        },
    )
    .expect("fill_path");
    let from_bytes = fill_with(bytes, layout.n_frames, layout.n_atoms, sections, None).unwrap();
    assert_eq!(positions, from_bytes.positions);
    if sections.velocities {
        assert_eq!(velocities, from_bytes.velocities);
    }
    if sections.forces {
        assert_eq!(forces, from_bytes.forces);
    }
    if sections.charges {
        assert_eq!(charges, from_bytes.charges);
    }
    if sections.spins {
        assert_eq!(spins, from_bytes.spins);
    }
    if sections.magmoms {
        assert_eq!(magmoms, from_bytes.magmoms);
    }
    fill_path_threaded(
        &path,
        layout.n_frames,
        layout.n_atoms,
        sections,
        4,
        &layout.frame_offsets,
        layout.frames_end,
        Slabs {
            positions: &mut positions,
            velocities: sections.velocities.then_some(velocities.as_mut_slice()),
            forces: sections.forces.then_some(forces.as_mut_slice()),
            energies: None,
            charges: sections.charges.then_some(charges.as_mut_slice()),
            spins: sections.spins.then_some(spins.as_mut_slice()),
            magmoms: sections.magmoms.then_some(magmoms.as_mut_slice()),
            displacements: None,
            spreads: None,
        },
    )
    .expect("fill_path_threaded");
    assert_eq!(positions, from_bytes.positions);
    if sections.velocities {
        assert_eq!(velocities, from_bytes.velocities);
    }
    if sections.forces {
        assert_eq!(forces, from_bytes.forces);
    }
    if sections.charges {
        assert_eq!(charges, from_bytes.charges);
    }
    if sections.spins {
        assert_eq!(spins, from_bytes.spins);
    }
    if sections.magmoms {
        assert_eq!(magmoms, from_bytes.magmoms);
    }
}

fn untouched(bytes: &[u8], n_frames: usize, short: bool) {
    let layout = layout_bytes(bytes).expect("layout");
    let n_atoms = layout.n_atoms;
    let full = n_frames * n_atoms * 3;
    let len = if short { full.saturating_sub(1) } else { full };
    let mut positions = vec![MARK; len];
    let sections = SectionFlags::default();
    assert!(fill_bytes(bytes, n_frames, n_atoms, sections, bare(&mut positions)).is_err());
    assert!(positions.iter().all(|value| *value == MARK));
    assert!(
        fill_bytes_threaded(
            bytes,
            n_frames,
            n_atoms,
            sections,
            4,
            &layout.frame_offsets,
            layout.frames_end,
            bare(&mut positions),
        )
        .is_err()
    );
    assert!(positions.iter().all(|value| *value == MARK));
    let (_scratch, path) = path_of(bytes, "refuse");
    assert!(
        fill_path(
            Path::new(&path),
            n_frames,
            n_atoms,
            sections,
            bare(&mut positions)
        )
        .is_err()
    );
    assert!(positions.iter().all(|value| *value == MARK));
    assert!(
        fill_path_threaded(
            &path,
            n_frames,
            n_atoms,
            sections,
            4,
            &layout.frame_offsets,
            layout.frames_end,
            bare(&mut positions),
        )
        .is_err()
    );
    assert!(positions.iter().all(|value| *value == MARK));
}

fn bare(positions: &mut [f64]) -> Slabs<'_> {
    Slabs {
        positions,
        velocities: None,
        forces: None,
        energies: None,
        charges: None,
        spins: None,
        magmoms: None,
        displacements: None,
        spreads: None,
    }
}

fn reader_rejects(bytes: &[u8]) {
    let err = ConFrameIterator::from_bytes(bytes)
        .next()
        .expect("a frame")
        .is_err();
    assert!(err, "the frame reader accepted a bad header");
}

fn fill_rejects(bytes: &[u8]) {
    let mut positions = vec![MARK; 3];
    let err = fill_bytes(bytes, 1, 1, SectionFlags::default(), bare(&mut positions));
    assert!(err.is_err());
    assert!(positions.iter().all(|value| *value == MARK));
}

#[test]
fn short_slabs_and_extra_frames_do_not_write() {
    let bytes = std::fs::read("resources/test/tiny_cuh2.con").expect("fixture");
    let layout = layout_bytes(&bytes).expect("layout");
    untouched(&bytes, layout.n_frames, true);
    let mut extra = bytes.clone();
    extra.extend_from_slice(&bytes);
    untouched(&extra, 1, false);
}

#[test]
fn storage_dtypes_match_the_frame_reader() {
    for (positions, velocities) in [("float32", "float32"), ("int32", "int32")] {
        let bytes = typed_frames(positions, velocities);
        assert_matches(&bytes);
        assert_paths(&bytes);
        let frame = ConFrameIterator::from_bytes(&bytes)
            .next()
            .unwrap()
            .unwrap();
        let xyz = frame.xyz_at(0);
        assert_ne!(xyz[0].to_bits(), 0.1f64.to_bits(), "{positions}");
    }
}

#[test]
fn bad_headers_and_rows_match_the_frame_reader() {
    let cases = [
        stock_frame("Coordinates BOGUS", None),
        stock_frame(
            "Coordinates of Component 1",
            Some("Velocities of Component 9"),
        ),
        stock_frame("Coordinates BOGUS", None).replace('\n', "\r\n"),
        stock_frame(
            "Coordinates of Component 1",
            Some("Velocities of Component 9"),
        )
        .replace('\n', "\r\n"),
        charge_row("0.25"),
        charge_row("0.25 99 0"),
    ];
    for text in cases {
        let bytes = text.into_bytes();
        reader_rejects(&bytes);
        fill_rejects(&bytes);
    }
}

#[test]
fn corpus_sections_match_full_frames() {
    for name in [
        "resources/test/tiny_cuh2_vel_forces.con",
        "resources/test/tiny_cuh2_charges_spins_magmoms.con",
    ] {
        let bytes = std::fs::read(name).unwrap_or_else(|_| panic!("{name}"));
        assert_matches(&bytes);
        assert_paths(&bytes);
        let layout = layout_bytes(&bytes).unwrap();
        if name.ends_with("vel_forces.con") {
            assert!(layout.sections.velocities && layout.sections.forces);
            let filled = fill_with(
                &bytes,
                layout.n_frames,
                layout.n_atoms,
                layout.sections,
                None,
            )
            .unwrap();
            assert_ne!(filled.velocities, filled.forces);
        } else {
            assert!(layout.sections.charges && layout.sections.spins && layout.sections.magmoms);
        }
    }
}

fn two_stock_frames() -> String {
    let one = stock_frame("Coordinates of Component 1", None);
    format!("{one}{one}")
}

fn rewrite_second_row(text: &str, row: &str) -> String {
    let needle = "0.1 -0.2 0.3 0 0\n";
    let first = text.find(needle).expect("first row");
    let second = text[first + needle.len()..]
        .find(needle)
        .expect("second row")
        + first
        + needle.len();
    let mut out = text.to_string();
    out.replace_range(second..second + needle.len(), row);
    out
}

fn assert_untouched(bytes: &[u8], n_frames: usize, n_atoms: usize, sections: SectionFlags) {
    let mut positions = vec![MARK; n_frames * n_atoms * 3];
    assert!(fill_bytes(bytes, n_frames, n_atoms, sections, bare(&mut positions)).is_err());
    assert!(positions.iter().all(|value| *value == MARK));
    assert!(
        fill_bytes_threaded(
            bytes,
            n_frames,
            n_atoms,
            sections,
            4,
            &[],
            0,
            bare(&mut positions),
        )
        .is_err()
    );
    assert!(positions.iter().all(|value| *value == MARK));
}

#[test]
fn a_short_unrequested_slab_is_not_indexed() {
    let one = std::fs::read("resources/test/tiny_cuh2.con").expect("fixture");
    let mut bytes = one.clone();
    bytes.extend_from_slice(&one);
    let layout = layout_bytes(&bytes).expect("layout");
    assert!(layout.n_frames >= 2);
    assert!(!layout.sections.velocities);
    let need = layout.n_frames * layout.n_atoms * 3;
    let mut positions = vec![MARK; need];
    let mut velocities = [MARK];
    let err = fill_bytes(
        &bytes,
        layout.n_frames,
        layout.n_atoms,
        layout.sections,
        Slabs {
            positions: &mut positions,
            velocities: Some(&mut velocities),
            forces: None,
            energies: None,
            charges: None,
            spins: None,
            magmoms: None,
            displacements: None,
            spreads: None,
        },
    );
    assert!(err.is_err());
    assert!(positions.iter().all(|value| *value == MARK));
    assert_eq!(velocities[0], MARK);
}

#[test]
fn a_later_frame_failure_leaves_the_slab_untouched() {
    let good = two_stock_frames();
    let layout = layout_bytes(good.as_bytes()).expect("two frames");
    assert_eq!(layout.n_frames, 2);
    let nan = rewrite_second_row(&good, "nan -0.2 0.3 0 0\n");
    let short_row = rewrite_second_row(&good, "0.1 -0.2\n");
    let mut truncated = good.as_bytes().to_vec();
    truncated.truncate(truncated.len().saturating_sub(8));
    let changed = "\
Frame
one
8.0 8.0 4.0
90.0 90.0 90.0
0 0
0 0
1
2
63.546
Cu
Coordinates of Component 1
0.0 0.0 0.0 0 0
1.0 0.0 0.0 0 1
Frame
two
8.0 8.0 4.0
90.0 90.0 90.0
0 0
0 0
1
1
63.546
Cu
Coordinates of Component 1
2.0 0.0 0.0 0 0
";
    let frames = layout.n_frames;
    let atoms = layout.n_atoms;
    let sections = layout.sections;
    for bytes in [
        nan.into_bytes(),
        short_row.into_bytes(),
        truncated,
        changed.as_bytes().to_vec(),
    ] {
        if let Ok(asked) = layout_bytes(&bytes) {
            assert_untouched(&bytes, asked.n_frames, asked.n_atoms, asked.sections);
        } else {
            assert_untouched(&bytes, frames, atoms, sections);
        }
    }
}

#[test]
fn legal_tails_and_symbol_whitespace_match_the_reader() {
    let frame = stock_frame("Coordinates of Component 1", None);
    for extra in ["\n", "\n\n", "\u{c}", "\r", "\n\r"] {
        let text = format!("{frame}{extra}");
        let bytes = text.into_bytes();
        let layout = layout_bytes(&bytes).unwrap_or_else(|_| panic!("tail {extra:?}"));
        assert_eq!(layout.n_frames, 1, "{extra:?}");
        let mut reader = ConFrameIterator::from_bytes(&bytes);
        assert!(reader.next().unwrap().is_ok(), "{extra:?}");
        assert!(reader.next().is_none(), "{extra:?}");
        assert_matches(&bytes);
    }
    let marked = frame.replacen("\nH\n", "\n\u{a0}H\u{0b}\n", 1);
    let bytes = marked.into_bytes();
    let frame = ConFrameIterator::from_bytes(&bytes)
        .next()
        .unwrap()
        .unwrap();
    assert_eq!(frame.atom_data[0].symbol.as_ref(), "H");
    let layout = layout_bytes(&bytes).expect("symbol layout");
    let mut positions = vec![0.0; layout.n_atoms * 3];
    let columns = fill_bytes(
        &bytes,
        layout.n_frames,
        layout.n_atoms,
        layout.sections,
        bare(&mut positions),
    )
    .expect("symbol fill");
    assert_eq!(columns.symbol_at(0, 0), "H");
}

#[test]
fn section_mask_and_offset_checks_refuse_before_writing() {
    let bytes = stock_frame(
        "Coordinates of Component 1",
        Some("Velocities of Component 1"),
    )
    .into_bytes();
    let layout = layout_bytes(&bytes).expect("layout");
    assert!(layout.sections.velocities);
    let need = layout.n_frames * layout.n_atoms * 3;
    let mut positions = vec![MARK; need];
    let mut velocities = vec![MARK; need];
    let err = fill_bytes(
        &bytes,
        layout.n_frames,
        layout.n_atoms,
        SectionFlags::default(),
        Slabs {
            positions: &mut positions,
            velocities: Some(&mut velocities),
            forces: None,
            energies: None,
            charges: None,
            spins: None,
            magmoms: None,
            displacements: None,
            spreads: None,
        },
    );
    assert!(err.is_err());
    assert!(positions.iter().all(|value| *value == MARK));
    assert!(velocities.iter().all(|value| *value == MARK));

    let exact = fill_bytes(
        &bytes,
        layout.n_frames,
        layout.n_atoms,
        layout.sections,
        Slabs {
            positions: &mut positions,
            velocities: Some(&mut velocities),
            forces: None,
            energies: None,
            charges: None,
            spins: None,
            magmoms: None,
            displacements: None,
            spreads: None,
        },
    );
    assert!(exact.is_ok());

    let doubled = two_stock_frames();
    let path_bytes = doubled.into_bytes();
    let wide = layout_bytes(&path_bytes).expect("two");
    let (_scratch, path) = path_of(&path_bytes, "offsets");
    let mut wrong = wide.frame_offsets.clone();
    wrong.swap(0, 1);
    let mut held = vec![MARK; wide.n_frames * wide.n_atoms * 3];
    let err = fill_path_threaded(
        &path,
        wide.n_frames,
        wide.n_atoms,
        wide.sections,
        2,
        &wrong,
        wide.frames_end,
        bare(&mut held),
    );
    assert!(err.is_err());
    assert!(held.iter().all(|value| *value == MARK));
    let err = fill_path_threaded(
        &path,
        wide.n_frames,
        wide.n_atoms,
        wide.sections,
        2,
        &wide.frame_offsets,
        wide.frames_end.saturating_add(1),
        bare(&mut held),
    );
    assert!(err.is_err());
    assert!(held.iter().all(|value| *value == MARK));
}
