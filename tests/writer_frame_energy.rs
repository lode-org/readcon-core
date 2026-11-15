//! A multi-frame write must keep each frame's own energy.
//!
//! The packed writer reuses one header when the atom skeleton matches.
//! Energy is per frame, so that reuse must not copy the first value.

use readcon_core::iterators::read_all_frames;
use readcon_core::types::ConFrameBuilder;
use readcon_core::writer::write_frame_refs_to_path;

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
    let path = std::env::temp_dir().join(format!(
        "readcon-frame-energy-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .expect("clock")
            .as_nanos()
    ));
    write_frame_refs_to_path(&path, &refs, 1, None, false, true).expect("write");
    let got = read_all_frames(&path).expect("read");
    let _ = std::fs::remove_file(&path);
    let energies: Vec<_> = got.iter().map(|frame| frame.header.energy()).collect();
    assert_eq!(energies, vec![Some(-1.5), Some(-1.2)]);

    // A longer energy token changes the header size. That list must
    // still round-trip instead of reusing the first header's price.
    let wide = [frame(-1.5), frame(-10.25)];
    let wide_refs: Vec<_> = wide.iter().collect();
    let wide_path = path.with_extension("wide");
    write_frame_refs_to_path(&wide_path, &wide_refs, 1, None, false, true).expect("wide write");
    let wide_got = read_all_frames(&wide_path).expect("wide read");
    let _ = std::fs::remove_file(&wide_path);
    let wide_energies: Vec<_> = wide_got
        .iter()
        .map(|frame| frame.header.energy())
        .collect();
    assert_eq!(wide_energies, vec![Some(-1.5), Some(-10.25)]);
}
