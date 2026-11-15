//! A packed binding write must keep each frame's own header metadata.
//!
//! Reusing the first frame's header when only the atom skeleton matches
//! writes the first energy onto every later frame.

use readcon_core::iterators::read_all_frames;
use readcon_core::types::ConFrameBuilder;
use readcon_core::writer::write_frame_refs_to_path;

fn two_cu(energy: f64, bead: u64) -> readcon_core::types::ConFrame {
    let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
    builder
        .set_units(serde_json::json!({
            "length": "angstrom",
            "energy": "eV",
            "mass": "amu",
        }))
        .unwrap();
    builder
        .add_atom("Cu", 0.0, 0.0, 0.0, [false; 3], 0, 63.546)
        .add_atom("Cu", 1.0, 0.0, 0.0, [false; 3], 1, 63.546);
    builder.set_neb_bead(bead);
    let mut frame = builder.build().unwrap();
    frame.header.set_energy(energy);
    frame
}

fn round_trip(energies: &[f64], beads: &[u64], workers: usize) {
    let frames: Vec<_> = energies
        .iter()
        .zip(beads)
        .map(|(&energy, &bead)| two_cu(energy, bead))
        .collect();
    let refs: Vec<_> = frames.iter().collect();
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("frames.con");
    write_frame_refs_to_path(&path, &refs, workers, None, false, true).unwrap();
    let back = read_all_frames(&path).unwrap();
    assert_eq!(back.len(), energies.len());
    for (index, frame) in back.iter().enumerate() {
        assert_eq!(
            frame.header.energy(),
            Some(energies[index]),
            "frame {index} energy"
        );
        assert_eq!(
            frame.header.neb_bead(),
            Some(beads[index]),
            "frame {index} neb_bead"
        );
    }
}

fn frame(energy: f64) -> readcon_core::types::ConFrame {
    let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
    builder.add_atom("Cu", 0.0, 0.0, 0.0, [false; 3], 0, 63.546);
    builder.add_atom("Cu", 1.0, 0.0, 0.0, [false; 3], 1, 63.546);
    builder.set_energy(energy);
    builder.build().expect("frame")
}

#[test]
fn a_frame_list_keeps_each_energy() {
    let frames = [frame(-1.5), frame(-1.2)];
    let refs: Vec<_> = frames.iter().collect();
    let dir = tempfile::tempdir().expect("tempdir");
    let path = dir.path().join("frames.con");
    write_frame_refs_to_path(&path, &refs, 1, None, false, true).expect("write");
    let got = read_all_frames(&path).expect("read");
    let energies: Vec<_> = got.iter().map(|item| item.header.energy()).collect();
    assert_eq!(energies, vec![Some(-1.5), Some(-1.2)]);

    // A longer energy token changes the header size. That list must
    // still round-trip instead of reusing the first header's price.
    let wide = [frame(-1.5), frame(-10.25)];
    let wide_refs: Vec<_> = wide.iter().collect();
    let wide_path = dir.path().join("wide.con");
    write_frame_refs_to_path(&wide_path, &wide_refs, 1, None, false, true).expect("wide write");
    let wide_got = read_all_frames(&wide_path).expect("wide read");
    let wide_energies: Vec<_> = wide_got.iter().map(|item| item.header.energy()).collect();
    assert_eq!(wide_energies, vec![Some(-1.5), Some(-10.25)]);
}

#[test]
fn packed_write_keeps_each_frames_energy() {
    round_trip(&[-1.5, -1.2], &[0, 0], 1);
    round_trip(&[-1.5, -10.25], &[0, 0], 1);
    round_trip(&[-1.5, -1.2, -1.5, -1.2], &[3, 4, 3, 4], 2);
}

#[test]
fn identical_metadata_packed_write() {
    if std::env::var_os("READCON_REBENCH").is_none() {
        return;
    }
    let frame = two_cu(-1.5, 1);
    let frames = vec![frame; 64];
    let refs: Vec<_> = frames.iter().collect();
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("same.con");
    let mut samples = Vec::with_capacity(7);
    for _ in 0..7 {
        let started = std::time::Instant::now();
        write_frame_refs_to_path(&path, &refs, 1, None, false, true).unwrap();
        samples.push(started.elapsed().as_secs_f64());
    }
    samples.sort_by(|left, right| left.partial_cmp(right).unwrap());
    eprintln!("identical-metadata packed median_s {}", samples[3]);
}
