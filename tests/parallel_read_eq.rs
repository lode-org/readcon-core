//! Parallel reads match [`readcon_core::iterators::read_all_frames`].
//!
//! The same assertions run with and without the `parallel` feature. Without
//! it, a worker count still parses on the calling thread.

use readcon_core::columns::ConPositions;
use readcon_core::error::ParseError;
use readcon_core::iterators::{
    column_walk_certified, frames_from_text, read_all_frames, read_all_frames_with_threads,
    read_coord_columns, read_positions_with_threads,
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

/// One equal-width frame of `n_atoms`, with coordinates that depend on
/// the frame index. Every frame is the same byte length, so a trajectory
/// of these takes the tiled column fast path, and the differing bytes mean
/// a wrong per-frame offset in the metadata fill would show up as a
/// coordinate mismatch rather than a copy of frame zero.
fn tiled_frame(frame: usize, n_atoms: usize) -> String {
    let mut body = String::with_capacity(n_atoms * 40 + 128);
    body.push_str(
        "\n{\"con_spec_version\":3,\"con_spec_minor\":1,\
\"units\":{\"length\":\"angstrom\",\"energy\":\"eV\"}}\n\
20.000000 20.000000 20.000000\n90.000000 90.000000 90.000000\n\n\n1\n",
    );
    body.push_str(&format!(
        "{n_atoms}\n63.546000\nCu\nCoordinates of Component 1\n"
    ));
    for atom in 0..n_atoms {
        // Each coordinate stays in `[0, 10)` and prints to a fixed eight
        // fractional digits, so the field width never changes.
        let x = ((frame + atom) % 9) as f64 + 0.111_111;
        let y = ((frame * 3 + atom) % 9) as f64 + 0.222_222;
        let z = ((frame + atom * 7) % 9) as f64 + 0.333_333;
        body.push_str(&format!("{x:.8} {y:.8} {z:.8} 0 {atom}\n"));
    }
    body
}

fn column_positions(bytes: &[u8], threads: usize, rich: bool) -> ConPositions {
    #[cfg(feature = "parallel")]
    {
        readcon_core::columns::positions_parallel(bytes, threads, rich)
            .unwrap_or_else(|err| panic!("{threads} threads rich={rich}: {err}"))
    }
    #[cfg(not(feature = "parallel"))]
    {
        let _ = threads;
        if rich {
            readcon_core::columns::positions_with_identity(bytes).unwrap()
        } else {
            readcon_core::columns::positions_from_con_bytes(bytes).unwrap()
        }
    }
}

fn assert_bits(label: &str, left: &[f64], right: &[f64]) {
    assert_eq!(left.len(), right.len(), "{label} len");
    let mismatch = left
        .iter()
        .zip(right)
        .position(|(a, b)| a.to_bits() != b.to_bits());
    assert_eq!(mismatch, None, "{label} bits differ at {mismatch:?}");
}

/// Every public column, component runs included, plus the private wide-plan
/// vectors that `PartialEq` still compares.
fn assert_vec_eq<T: PartialEq + std::fmt::Debug>(label: &str, left: &[T], right: &[T]) {
    assert_eq!(
        left.len(),
        right.len(),
        "{label} len {} vs {}",
        left.len(),
        right.len()
    );
    if let Some(index) = left.iter().zip(right).position(|(a, b)| a != b) {
        panic!(
            "{label} differ at {index}: {:?} vs {:?}",
            left[index], right[index]
        );
    }
}

fn assert_same_columns(label: &str, serial: &ConPositions, parallel: &ConPositions) {
    assert_eq!(parallel.n_frames, serial.n_frames, "{label} n_frames");
    assert_vec_eq(&format!("{label} counts"), &parallel.counts, &serial.counts);
    assert_vec_eq(&format!("{label} spans"), &parallel.spans, &serial.spans);
    assert_vec_eq(
        &format!("{label} head_ends"),
        &parallel.head_ends,
        &serial.head_ends,
    );
    assert_vec_eq(
        &format!("{label} components"),
        &parallel.components,
        &serial.components,
    );
    assert_vec_eq(&format!("{label} ids"), &parallel.ids, &serial.ids);
    assert_vec_eq(&format!("{label} flags"), &parallel.flags, &serial.flags);
    assert_eq!(parallel.stock, serial.stock, "{label} stock");
    assert_eq!(
        parallel.has_section, serial.has_section,
        "{label} has_section"
    );
    assert_bits(
        &format!("{label} positions"),
        &parallel.positions,
        &serial.positions,
    );
    assert_bits(&format!("{label} cells"), &parallel.cells, &serial.cells);
    assert_bits(&format!("{label} masses"), &parallel.masses, &serial.masses);
    assert_eq!(parallel, serial, "{label} full record");
}

/// One equal-width frame of two atom types. Coordinates change with the
/// frame index but stay a fixed width, so the file tiles and is not a
/// byte-for-byte repeat of frame 0.
fn tiled_two_type(frame: usize) -> String {
    let mut body = String::new();
    body.push_str(
        "seed\n{\"con_spec_version\":2}\n10.000000 10.000000 10.000000\n\
90.000000 90.000000 90.000000\n0 0\n0 0 0\n2\n2 2\n63.546000 1.007900\n\
Cu\nCoordinates of Component 1\n",
    );
    for atom in 0..2 {
        let x = ((frame + atom) % 9) as f64 + 0.1111_1111;
        let y = ((frame + atom) % 9) as f64 + 0.2222_2222;
        let z = ((frame + atom) % 9) as f64 + 0.3333_3333;
        body.push_str(&format!("{x:.8} {y:.8} {z:.8} 0 {atom}\n"));
    }
    body.push_str("H\nCoordinates of Component 2\n");
    for atom in 2..4 {
        let x = ((frame + atom) % 9) as f64 + 0.4444_4444;
        let y = ((frame + atom) % 9) as f64 + 0.5555_5555;
        let z = ((frame + atom) % 9) as f64 + 0.6666_6666;
        body.push_str(&format!("{x:.8} {y:.8} {z:.8} 1 {atom}\n"));
    }
    body
}

fn assert_tiled_matches_serial(label: &str, text: &str, n_frames: usize, runs_per_frame: usize) {
    let bytes = text.as_bytes();
    for &rich in &[false, true] {
        let serial = column_positions(bytes, 1, rich);
        assert_eq!(serial.n_frames, n_frames, "{label} rich={rich}");
        if rich {
            assert_eq!(
                serial.components.len(),
                n_frames * runs_per_frame,
                "{label} serial component runs"
            );
        } else {
            assert!(serial.components.is_empty(), "{label} plain read has runs");
        }
        for threads in [1usize, 2, 4, 8] {
            let parallel = column_positions(bytes, threads, rich);
            assert_same_columns(
                &format!("{label} rich={rich} threads={threads}"),
                &serial,
                &parallel,
            );
            // Identity reads keep this result. A components vector that
            // stopped after frame 0 makes the check return None and the
            // reader rebuilds the file with the frame parser.
            assert!(
                column_walk_certified(bytes, Some(threads), true),
                "{label} identity read left the fast path at {threads} threads"
            );
            assert!(
                column_walk_certified(bytes, Some(threads), false),
                "{label} plain read left the fast path at {threads} threads"
            );
        }
    }
    let dir = tempfile::tempdir().unwrap();
    let path = write_frames(dir.path(), "tiled.con", text);
    let serial_columns = read_coord_columns(&path, Some(1)).unwrap();
    assert_eq!(serial_columns.block.n_frames, n_frames, "{label}");
    assert_eq!(serial_columns.species.len(), 1, "{label} species collapsed");
    for threads in [2usize, 4, 8] {
        let parallel_columns = read_coord_columns(&path, Some(threads)).unwrap();
        assert_eq!(
            parallel_columns.species, serial_columns.species,
            "{label} species at {threads}"
        );
        assert_eq!(
            parallel_columns.atom_ids, serial_columns.atom_ids,
            "{label} atom ids at {threads}"
        );
        assert_eq!(
            parallel_columns.fixed, serial_columns.fixed,
            "{label} fixed mask at {threads}"
        );
        assert_bits(
            &format!("{label} identity positions at {threads}"),
            &parallel_columns.block.values,
            &serial_columns.block.values,
        );
        assert_bits(
            &format!("{label} identity masses at {threads}"),
            &parallel_columns.masses,
            &serial_columns.masses,
        );
        assert_bits(
            &format!("{label} identity cells at {threads}"),
            &parallel_columns.cells,
            &serial_columns.cells,
        );
    }
}

/// Regression test for the parallel tiled-column prologue. Serial and every
/// worker count return the same metadata, component runs included.
///
/// The frame counts sit on the fill's chunk edges: 1024 frames still fill
/// the tail on the caller (`rest < 1024`), 1025 is the first parallel fill,
/// 2048 divides evenly across 2/4/8 workers, and 2049 is the probe that used
/// to keep a single `("Cu", 4)` run.
#[test]
fn tiled_trajectory_positions_match_serial_at_every_width() {
    // 1024 stays under the parallel metadata fill, 1025 crosses it, 2048
    // divides across 2/4/8 workers, 2049 is the one-past-a-tile probe.
    for n_frames in [2usize, 1024, 1025, 2048, 2049, 2050] {
        let mut text = String::new();
        for frame in 0..n_frames {
            text.push_str(&tiled_frame(frame, 4));
        }
        assert_tiled_matches_serial(&format!("{n_frames} frames"), &text, n_frames, 1);
    }

    let mut two = String::new();
    for frame in 0..2049 {
        two.push_str(&tiled_two_type(frame));
    }
    assert_tiled_matches_serial("2049 two-type frames", &two, 2049, 2);

    // The full-frame reader shares the equal-span boundary scan.
    let mut text = String::new();
    for frame in 0..64 {
        text.push_str(&tiled_frame(frame, 4));
    }
    let dir = tempfile::tempdir().unwrap();
    let path = write_frames(dir.path(), "tiled.con", &text);
    assert_frames("tiled trajectory", &path);
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
