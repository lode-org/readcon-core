//! The position slab of a frame stored as float32.
//!
//! The writer spells the atoms of a frame, and a projected positions column
//! holds only their float32 rounding. The slab Python views must carry the
//! values the atoms keep, so a write through it and a read through an atom
//! are the same memory.

use readcon_core::iterators::{ConFrameIterator, pack_position_slab};
use readcon_core::types::ConFrame;

const ROWS: [[f64; 3]; 3] = [
    [0.1234567890123, 1.0000000123456, 2.4142135623731],
    [3.3010299956640, 0.3333333333333, 5.5555555555555],
    [6.0200000000001, 7.0000000001234, 8.9999999998765],
];

fn frames(n_frames: usize) -> Vec<ConFrame> {
    let mut text = String::new();
    for frame in 0..n_frames {
        text.push_str(
            "\n{\"con_spec_version\":3,\"con_spec_minor\":1,\
             \"units\":{\"length\":\"angstrom\",\"energy\":\"eV\"},\
             \"storage_dtypes\":{\"positions\":\"float32\"}}\n\
             20.000000 20.000000 20.000000\n90.000000 90.000000 90.000000\n\n\n\
             1\n3\n63.546000\nCu\nCoordinates of Component 1\n",
        );
        for (index, row) in ROWS.iter().enumerate() {
            let shift = frame as f64;
            text.push_str(&format!(
                "{:.13} {:.13} {:.13} 0 {index}\n",
                row[0] + shift,
                row[1] + shift,
                row[2] + shift
            ));
        }
    }
    ConFrameIterator::new(&text)
        .map(|frame| frame.expect("parse"))
        .collect()
}

#[test]
fn the_slab_holds_the_values_the_atoms_keep() {
    for n_frames in [1, 3] {
        let frames = frames(n_frames);
        for frame in &frames {
            assert_eq!(
                frame.positions.kind(),
                readcon_core::storage_dtype::ElementKind::Float32
            );
        }
        for workers in [1, 4] {
            let slab = pack_position_slab(&frames, workers).expect("one atom count");
            let want: Vec<f64> = frames
                .iter()
                .flat_map(|frame| {
                    frame
                        .atom_data
                        .iter()
                        .flat_map(|atom| [atom.x(), atom.y(), atom.z()])
                })
                .collect();
            assert_eq!(slab.len(), want.len());
            for (index, (got, want)) in slab.iter().zip(&want).enumerate() {
                assert_eq!(
                    got.to_bits(),
                    want.to_bits(),
                    "value {index}, {workers} workers"
                );
            }
        }
    }
}
