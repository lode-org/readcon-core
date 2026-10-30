use readcon_core::error::ParseError;
use readcon_core::frame_index::{read_sidecar, sidecar_path};
use readcon_core::iterators::read_all_frames;
use readcon_core::trajectory::ConTrajectory;
use std::io::Write;
use std::path::{Path, PathBuf};

mod common;

fn scratch(name: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("rc-traj-{}-{name}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

fn assert_matches_read_all(path: &Path, write_index: bool) -> ConTrajectory {
    let expected = read_all_frames(path).unwrap();
    let traj = ConTrajectory::open(path, write_index).unwrap();
    assert_eq!(traj.len(), expected.len(), "{}", path.display());
    for (i, want) in expected.iter().enumerate() {
        assert_eq!(
            &traj.frame(i).unwrap(),
            want,
            "frame {i} of {}",
            path.display()
        );
    }
    let n = expected.len();
    for bad in [n, n + 1, usize::MAX] {
        match traj.frame(bad) {
            Err(ParseError::IndexOutOfBounds { index, len }) => assert_eq!((index, len), (bad, n)),
            other => panic!("frame {bad}: {other:?}"),
        }
    }
    traj
}

#[test]
fn fixtures_match_read_all_frames() {
    let dir = scratch("fixtures");
    for name in [
        "tiny_multi_cuh2.con",
        "tiny_multi_cuh2.convel",
        "tiny_cuh2_vel_forces.con",
    ] {
        let path = dir.join(name);
        std::fs::copy(test_case!(name), &path).unwrap();
        assert_matches_read_all(&path, false);
        assert!(!sidecar_path(&path).exists());
    }
    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn mapped_file_with_and_without_sidecar() {
    let dir = scratch("mapped");
    let path = dir.join("long.con");
    let one = std::fs::read_to_string(test_case!("tiny_multi_cuh2.con")).unwrap();
    std::fs::write(&path, one.repeat(400)).unwrap();
    assert!(std::fs::metadata(&path).unwrap().len() > 64 * 1024);

    let cold = assert_matches_read_all(&path, false);
    assert_eq!(cold.len(), 800);
    assert!(!sidecar_path(&path).exists());

    assert_matches_read_all(&path, true);
    assert!(read_sidecar(&path).unwrap().is_some());
    let warm = assert_matches_read_all(&path, true);
    assert_eq!(warm.frame(799).unwrap(), cold.frame(799).unwrap());

    std::fs::write(&path, one.repeat(3)).unwrap();
    assert!(read_sidecar(&path).unwrap().is_none());
    assert_eq!(assert_matches_read_all(&path, false).len(), 6);
    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn gzip_is_indexed_in_memory() {
    let dir = scratch("gzip");
    let path = dir.join("long.con.gz");
    let one = std::fs::read_to_string(test_case!("tiny_multi_cuh2.con")).unwrap();
    let mut enc = flate2::write::GzEncoder::new(
        std::fs::File::create(&path).unwrap(),
        flate2::Compression::default(),
    );
    enc.write_all(one.repeat(50).as_bytes()).unwrap();
    enc.finish().unwrap();
    assert_eq!(assert_matches_read_all(&path, true).len(), 100);
    assert!(!sidecar_path(&path).exists());
    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn empty_file_and_bad_frame() {
    let dir = scratch("edge");
    let empty = dir.join("empty.con");
    std::fs::write(&empty, "").unwrap();
    let traj = ConTrajectory::open(&empty, false).unwrap();
    assert!(traj.is_empty());
    assert!(matches!(
        traj.frame(0),
        Err(ParseError::IndexOutOfBounds { index: 0, len: 0 })
    ));

    let text = std::fs::read_to_string(test_case!("tiny_multi_cuh2.con")).unwrap();
    let cut = dir.join("cut.con");
    let end = text.strip_suffix('\n').unwrap().rfind('\n').unwrap() + 1;
    std::fs::write(&cut, &text[..end]).unwrap();
    assert!(ConTrajectory::open(&cut, false).is_err());
    assert!(ConTrajectory::open(&dir.join("missing.con"), false).is_err());

    let bad = dir.join("bad.con");
    std::fs::write(&bad, text.replacen("6.9752", "6.9x52", 1)).unwrap();
    let traj = ConTrajectory::open(&bad, false).unwrap();
    assert_eq!(traj.len(), 2);
    assert!(traj.frame(0).is_ok());
    assert!(traj.frame(1).is_err());
    let _ = std::fs::remove_dir_all(&dir);
}
