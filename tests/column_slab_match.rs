//! Column slabs agree with a full-frame read of the same bytes.

use readcon_core::column_read::{Slabs, fill_bytes, layout_bytes};
use readcon_core::iterators::ConFrameIterator;

fn assert_match(bytes: &[u8]) {
    let layout = layout_bytes(bytes).expect("layout");
    let n3 = layout.n_frames * layout.n_atoms * 3;
    let mut positions = vec![0.0; n3];
    let mut velocities = vec![0.0; n3];
    let mut forces = vec![0.0; n3];
    let columns = fill_bytes(
        bytes,
        layout.n_frames,
        layout.n_atoms,
        layout.sections,
        Slabs {
            positions: &mut positions,
            velocities: layout
                .sections
                .velocities
                .then_some(velocities.as_mut_slice()),
            forces: layout.sections.forces.then_some(forces.as_mut_slice()),
            energies: None,
            charges: None,
            spins: None,
            magmoms: None,
            displacements: None,
            spreads: None,
        },
    )
    .expect("fill");
    let frames = ConFrameIterator::from_bytes(bytes)
        .collect::<Result<Vec<_>, _>>()
        .expect("frames");
    assert_eq!(frames.len(), columns.n_frames);
    for (index, frame) in frames.iter().enumerate() {
        for atom in 0..columns.n_atoms {
            let at = (index * columns.n_atoms + atom) * 3;
            let xyz = frame.xyz_at(atom);
            assert_eq!(&positions[at..at + 3], &xyz);
            let item = &frame.atom_data[atom];
            assert_eq!(item.symbol.as_ref(), columns.symbol_at(index, atom));
            assert_eq!(item.atom_id, columns.id_at(index, atom));
            if layout.sections.velocities {
                let vel = item.velocity().expect("velocity");
                assert_eq!(&velocities[at..at + 3], &vel);
            }
            if layout.sections.forces {
                let force = item.force().expect("force");
                assert_eq!(&forces[at..at + 3], &force);
            }
        }
    }
}

#[test]
fn corpus_column_reads_match_full_frames() {
    for name in [
        "resources/test/tiny_cuh2.con",
        "resources/test/tiny_multi_cuh2.con",
        "resources/test/tiny_cuh2.convel",
        "resources/test/tiny_multi_cuh2.convel",
        "resources/test/tiny_cuh2_forces.con",
    ] {
        let bytes = std::fs::read(name).expect(name);
        assert_match(&bytes);
    }
}
