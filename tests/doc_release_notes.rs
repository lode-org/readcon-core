//! Examples for the notes after the tagged release.
//!
//! Short decimals, a crash-safe path publish, and a same-length rewrite.

use std::fs;
use std::path::Path;

use readcon_core::iterators::read_first_frame;
use readcon_core::types::ConFrameBuilder;
use readcon_core::writer::{rewrite_frame_refs_to_path, write_frame_refs_to_path};

fn one_atom(x: f64, fixed: [bool; 3], atom_id: u64) -> readcon_core::types::ConFrame {
    let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
    builder.add_atom("Cu", x, 0.25, 2.0, fixed, atom_id, 63.546);
    builder.build().expect("frame")
}

fn scratches(dir: &Path) -> Vec<String> {
    fs::read_dir(dir)
        .expect("dir")
        .filter_map(|item| item.ok())
        .map(|item| item.file_name().to_string_lossy().into_owned())
        .filter(|name| name.starts_with(".readcon-write-"))
        .collect()
}

#[test]
fn short_decimals_round_trip() {
    let dir = std::env::temp_dir().join(format!("rc-doc-fmt-{}", std::process::id()));
    let _ = fs::remove_dir_all(&dir);
    fs::create_dir_all(&dir).unwrap();
    let path = dir.join("short.con");
    let frame = one_atom(1.5, [false, false, false], 1);
    write_frame_refs_to_path(&path, &[&frame], 1, None, false, false).unwrap();
    let text = fs::read_to_string(&path).unwrap();
    assert!(text.contains("1.5") && text.contains("0.25") && text.contains("2.0"), "{text}");
    assert!(scratches(&dir).is_empty());
    let back = read_first_frame(&path).unwrap();
    assert_eq!(back.atom_data[0].x(), 1.5);
    let _ = fs::remove_dir_all(&dir);
}

#[test]
fn rewrite_publishes_one_complete_file() {
    let dir = std::env::temp_dir().join(format!("rc-doc-rew-{}", std::process::id()));
    let _ = fs::remove_dir_all(&dir);
    fs::create_dir_all(&dir).unwrap();
    let path = dir.join("traj.con");
    let first = one_atom(1.0, [false, false, false], 1);
    write_frame_refs_to_path(&path, &[&first], 1, None, false, false).unwrap();
    let next = one_atom(3.5, [false, false, false], 1);
    rewrite_frame_refs_to_path(&path, &[&next], 1, None, false, true, false).unwrap();
    let spare = dir.join("traj.con.rewrite");
    assert!(!spare.exists(), "keep_spare false left the spare");
    let text = fs::read_to_string(&path).unwrap();
    assert!(text.contains("3.5"), "{text}");
    assert!(scratches(&dir).is_empty());
    let _ = fs::remove_dir_all(&dir);
}
