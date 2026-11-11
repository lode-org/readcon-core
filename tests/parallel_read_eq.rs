//! Parallel reads match [`readcon_core::iterators::read_all_frames`].
//!
//! The same assertions run with and without the `parallel` feature. Without
//! it, a worker count still parses on the calling thread.

use readcon_core::error::ParseError;
use readcon_core::iterators::{
    frames_from_text, read_all_frames, read_all_frames_with_threads, read_positions_with_threads,
};
use readcon_core::types::ConFrame;
use std::error::Error;
use std::fs;
use std::path::{Path, PathBuf};

fn fixture(name: &str) -> String {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("resources/test")
        .join(name);
    fs::read_to_string(path).unwrap_or_else(|err| panic!("{name}: {err}"))
}

fn error_key(err: Box<dyn Error>) -> String {
    match err.downcast::<ParseError>() {
        Ok(parse) => format!("{parse:?}"),
        Err(other) => other.to_string(),
    }
}

fn assert_frames(label: &str, path: &Path) {
    let serial = read_all_frames(path).unwrap_or_else(|err| panic!("{label} serial: {err}"));
    for threads in [1usize, 2, 4, 8] {
        let parallel = read_all_frames_with_threads(path, Some(threads))
            .unwrap_or_else(|err| panic!("{label} threads {threads}: {err}"));
        assert_eq!(parallel, serial, "{label} threads {threads}");
    }
}

fn assert_error(label: &str, path: &Path) {
    let serial = error_key(
        read_all_frames(path).expect_err(&format!("{label} serial parsed a truncated file")),
    );
    for threads in [1usize, 2, 4, 8] {
        let parallel = error_key(
            read_all_frames_with_threads(path, Some(threads)).expect_err(&format!(
                "{label} threads {threads} parsed a truncated file"
            )),
        );
        assert_eq!(parallel, serial, "{label} threads {threads}");
    }
}

fn write_frames(dir: &Path, name: &str, text: &str) -> PathBuf {
    let path = dir.join(name);
    fs::write(&path, text).unwrap();
    path
}

#[test]
fn parallel_reads_match_serial_frames() {
    let dir = tempfile::tempdir().unwrap();
    let cases = [
        ("con", "tiny_multi_cuh2.con"),
        ("con-wide", "cuh2.con"),
        ("convel", "tiny_multi_cuh2.convel"),
        ("convel-one", "tiny_cuh2.convel"),
        ("vel-force", "tiny_cuh2_vel_forces.con"),
    ];
    for (label, name) in cases {
        let text = fixture(name);
        let repeated = text.repeat(4);
        let path = write_frames(dir.path(), name, &repeated);
        assert_frames(&format!("{label} x4"), &path);
    }

    let one = fixture("cuh2.con");
    let single = write_frames(dir.path(), "single.con", &one);
    let serial: Vec<ConFrame> = read_all_frames(&single).unwrap();
    assert_eq!(serial.len(), 1);
    assert_frames("single", &single);

    let empty = write_frames(dir.path(), "empty.con", "");
    let serial_empty = read_all_frames(&empty).unwrap();
    assert!(serial_empty.is_empty());
    assert_frames("empty", &empty);

    let truncated = write_frames(
        dir.path(),
        "truncated.con",
        &format!("{one}{}", &one[..one.len() / 2]),
    );
    assert_error("truncated con", &truncated);

    let convel = fixture("tiny_cuh2.convel");
    let truncated_convel = write_frames(
        dir.path(),
        "truncated.convel",
        &format!("{convel}{}", &convel[..convel.len() / 2]),
    );
    assert_error("truncated convel", &truncated_convel);

    let vel = fixture("tiny_cuh2_vel_forces.con");
    let truncated_vel = write_frames(
        dir.path(),
        "truncated-vel.con",
        &format!("{vel}{}", &vel[..vel.len() / 2]),
    );
    assert_error("truncated vel+force", &truncated_vel);
}

fn one_atom_frame(token: &str) -> String {
    format!(
        "seed\n{{\"con_spec_version\":2}}\n10 10 10\n90 90 90\n0 0\n0 0 0\n1\n1\n1.0\nH\nCoordinates of Component 1\n{token} 0 0 0 0\n"
    )
}

fn many_atom_frame(natoms: usize) -> String {
    let mut body = String::with_capacity(natoms * 12 + 96);
    body.push_str("seed\n{\"con_spec_version\":2}\n10 10 10\n90 90 90\n0 0\n0 0 0\n1\n");
    body.push_str(&natoms.to_string());
    body.push_str("\n1.0\nH\nCoordinates of Component 1\n");
    for _ in 0..natoms {
        body.push_str("0 0 0 0 0\n");
    }
    body
}

fn position_error(path: &Path, threads: usize) -> String {
    match read_positions_with_threads(path, Some(threads)) {
        Ok(_) => panic!("positions parsed a failing file at {threads} threads"),
        Err(err) => err.to_string(),
    }
}

/// A slow first frame lets a later worker fail before the earliest bad
/// span is parsed. The position reader must still report that earliest
/// span, at every thread count.
#[test]
fn parallel_positions_report_the_earliest_failing_frame() {
    const SLOW_ATOMS: usize = 20_000;
    let text = format!(
        "{}{}{}{}",
        many_atom_frame(SLOW_ATOMS),
        one_atom_frame("nan"),
        one_atom_frame("inf"),
        one_atom_frame("infinity"),
    );
    let dir = tempfile::tempdir().unwrap();
    let path = write_frames(dir.path(), "earliest.con", &text);
    let serial = position_error(&path, 1);
    assert!(
        serial.contains("nan"),
        "serial position read did not keep the earliest token: {serial}"
    );
    for threads in [2usize, 4, 8] {
        for _ in 0..4 {
            let parallel = position_error(&path, threads);
            assert_eq!(parallel, serial, "threads {threads}");
        }
    }
}

/// Two different failures. Every thread count returns the earlier one,
/// and a one-frame file stays a single frame.
#[test]
fn parallel_frames_keep_order_and_the_earliest_error() {
    let good = many_atom_frame(3);
    let marked = good.replace("0 0 0 0 0\n", "1 2 3 0 0\n");
    let text = format!(
        "{good}{marked}{}{}",
        one_atom_frame("nan"),
        one_atom_frame("inf")
    );
    let serial = frames_from_text(&text, Some(1))
        .expect_err("serial frames")
        .to_string();
    assert!(
        serial.contains("nan"),
        "serial frame read did not keep the earliest token: {serial}"
    );
    for threads in [2usize, 4, 8] {
        let parallel = frames_from_text(&text, Some(threads))
            .expect_err("parallel frames")
            .to_string();
        assert_eq!(parallel, serial, "threads {threads}");
    }

    let dir = tempfile::tempdir().unwrap();
    let one = write_frames(dir.path(), "one.con", &good);
    let serial_one = read_all_frames(&one).unwrap();
    assert_eq!(serial_one.len(), 1);
    for threads in [1usize, 2, 4, 8] {
        let parallel = read_all_frames_with_threads(&one, Some(threads)).unwrap();
        assert_eq!(parallel, serial_one, "one frame threads {threads}");
        let positions = read_positions_with_threads(&one, Some(threads)).unwrap();
        assert_eq!(positions.n_frames, 1);
        assert_eq!(positions.n_atoms, 3);
        assert_eq!(positions.values.len(), 9);
    }

    let ordered = format!("{good}{marked}{good}");
    let ordered_path = write_frames(dir.path(), "ordered.con", &ordered);
    let serial_frames = frames_from_text(&ordered, Some(1)).unwrap();
    assert_eq!(serial_frames.len(), 3);
    assert_ne!(serial_frames[0], serial_frames[1]);
    let serial_positions = read_positions_with_threads(&ordered_path, Some(1)).unwrap();
    for threads in [2usize, 4, 8] {
        let parallel = frames_from_text(&ordered, Some(threads)).unwrap();
        assert_eq!(parallel, serial_frames, "order threads {threads}");
        let positions = read_positions_with_threads(&ordered_path, Some(threads)).unwrap();
        assert_eq!(positions.n_frames, serial_positions.n_frames);
        assert_eq!(
            positions.values, serial_positions.values,
            "positions threads {threads}"
        );
    }

    let malformed = format!("{good}not a frame\n1 2 3\n{}", one_atom_frame("inf"));
    let serial_bad = frames_from_text(&malformed, Some(1))
        .expect_err("serial malformed")
        .to_string();
    for threads in [2usize, 4, 8] {
        let parallel = frames_from_text(&malformed, Some(threads))
            .expect_err("parallel malformed")
            .to_string();
        assert_eq!(parallel, serial_bad, "malformed threads {threads}");
    }

    let chopped = format!("{good}{}", &good[..good.len() / 2]);
    let serial_chop = frames_from_text(&chopped, Some(1))
        .expect_err("serial truncated")
        .to_string();
    for threads in [2usize, 4, 8] {
        let parallel = frames_from_text(&chopped, Some(threads))
            .expect_err("parallel truncated")
            .to_string();
        assert_eq!(parallel, serial_chop, "truncated threads {threads}");
        let dir = tempfile::tempdir().unwrap();
        let path = write_frames(dir.path(), "chop.con", &chopped);
        let serial_pos = position_error(&path, 1);
        assert_eq!(
            position_error(&path, threads),
            serial_pos,
            "truncated positions"
        );
    }
}

/// A failure in the middle must not change later slots when the ranges move.
#[cfg(feature = "parallel")]
#[test]
fn parallel_slots_keep_file_order_around_a_bad_frame() {
    use readcon_core::iterators::parse_frames_parallel_with_threads;

    let good = many_atom_frame(4);
    let shifted = good.replace("0 0 0 0 0\n", "4 5 6 0 1\n");
    let text = format!("{good}{shifted}{}{good}", one_atom_frame("nan"));
    let serial = parse_frames_parallel_with_threads(&text, Some(1));
    assert!(serial.iter().any(|item| item.is_err()));
    assert!(matches!(serial.first(), Some(Ok(_))));
    for threads in [2usize, 4, 8] {
        let parallel = parse_frames_parallel_with_threads(&text, Some(threads));
        assert_eq!(parallel.len(), serial.len(), "threads {threads}");
        for (index, (left, right)) in serial.iter().zip(parallel.iter()).enumerate() {
            match (left, right) {
                (Ok(a), Ok(b)) => assert_eq!(a, b, "threads {threads} frame {index}"),
                (Err(a), Err(b)) => {
                    assert_eq!(
                        a.to_string(),
                        b.to_string(),
                        "threads {threads} frame {index}"
                    )
                }
                _ => panic!("threads {threads} frame {index} kind changed"),
            }
        }
    }
}
