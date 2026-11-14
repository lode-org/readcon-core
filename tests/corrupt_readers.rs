//! Deterministic corrupt-input checks for the CON, convel, and extxyz readers.
//!
//! Every truncated or damaged buffer must return a clean error or the frames
//! that are fully present. A short body must not come back as a successful
//! frame, and a flipped index must not panic.

use readcon_core::extxyz_scan::{XyzTables, tables_from_extxyz_bytes_with_threads};
use readcon_core::iterators::{read_all_frames_phased, read_all_frames_with_threads};
use readcon_core::types::{ConFrame, ConFrameBuilder};
use readcon_core::units::NATURAL_TIME_UNIT;
use std::path::{Path, PathBuf};

const THREADS: [usize; 2] = [1, 8];

fn frame(velocities: bool, shift: f64) -> ConFrame {
    let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
    builder
        .set_units(serde_json::json!({
            "length": "angstrom",
            "energy": "eV",
            "mass": "amu",
            "time": NATURAL_TIME_UNIT,
        }))
        .unwrap();
    let mut add = |symbol_x: f64, fixed: [bool; 3], id: u64, velocity: [f64; 3]| {
        builder.add_atom("Cu", symbol_x, 0.25, 0.125, fixed, id, 64.0);
        if velocities {
            builder.with_velocity(velocity);
        }
    };
    add(shift, [false, false, false], 1, [0.5, 0.0, shift]);
    add(shift + 1.0, [true, false, false], 2, [0.25, 0.5, shift]);
    builder.build().unwrap()
}

fn con_text(velocities: bool) -> String {
    let frames = [frame(velocities, 0.0), frame(velocities, 2.0)];
    let bytes = readcon_core::writer::write_frames_to_vec(&frames).unwrap();
    String::from_utf8(bytes).unwrap()
}

fn write(dir: &Path, name: &str, bytes: &[u8]) -> PathBuf {
    let path = dir.join(name);
    std::fs::write(&path, bytes).unwrap();
    path
}

fn read_con(path: &Path, threads: usize) -> Result<Vec<ConFrame>, String> {
    let phased = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        read_all_frames_phased(path, Some(threads)).map(|parsed| parsed.frames)
    }));
    let phased = match phased {
        Ok(result) => result.map_err(|err| err.to_string()),
        Err(_) => panic!(
            "{threads} threads panicked in the phased reader: {}",
            path.display()
        ),
    };
    let threaded = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        read_all_frames_with_threads(path, Some(threads))
    }));
    let threaded = match threaded {
        Ok(result) => result.map_err(|err| err.to_string()),
        Err(_) => panic!(
            "{threads} threads panicked in the threaded reader: {}",
            path.display()
        ),
    };
    match (&phased, &threaded) {
        (Ok(left), Ok(right)) => {
            assert_eq!(
                left,
                right,
                "{threads} threads disagreed on {}",
                path.display()
            );
            phased
        }
        (Err(_), Err(_)) => phased,
        (Ok(frames), Err(_)) | (Err(_), Ok(frames)) => panic!(
            "{threads} threads split error and {} frames for {}",
            frames.len(),
            path.display()
        ),
    }
}

fn assert_complete(label: &str, frames: &[ConFrame]) {
    for (index, frame) in frames.iter().enumerate() {
        let declared: usize = frame.header.natms_per_type.iter().sum();
        assert_eq!(
            frame.atom_data.len(),
            declared,
            "{label} frame {index} does not match its atom count"
        );
        assert!(declared > 0, "{label} frame {index} is empty");
        assert_eq!(
            frame.positions.nrows(),
            declared,
            "{label} frame {index} positions"
        );
        for atom in &frame.atom_data {
            assert!(
                atom.x().is_finite() && atom.y().is_finite() && atom.z().is_finite(),
                "{label} frame {index} coordinate"
            );
        }
        let with_velocity = frame
            .atom_data
            .iter()
            .filter(|atom| atom.velocity().is_some())
            .count();
        assert!(
            with_velocity == 0 || with_velocity == declared,
            "{label} frame {index} has a partial velocity section"
        );
    }
}

fn accept_con(label: &str, path: &Path) {
    for threads in THREADS {
        match read_con(path, threads) {
            Ok(frames) => assert_complete(&format!("{label} t{threads}"), &frames),
            Err(err) => assert!(!err.is_empty(), "{label} t{threads}"),
        }
    }
}

fn require_err(label: &str, path: &Path) {
    for threads in THREADS {
        match read_con(path, threads) {
            Ok(frames) => panic!("{label} t{threads} returned {} frames", frames.len()),
            Err(err) => assert!(!err.is_empty(), "{label}"),
        }
    }
}

fn require_equal(label: &str, path: &Path, golden: &[ConFrame]) {
    for threads in THREADS {
        match read_con(path, threads) {
            Ok(frames) => assert_eq!(frames, golden, "{label} t{threads}"),
            Err(err) => panic!("{label} t{threads}: {err}"),
        }
    }
}

fn extxyz_text() -> String {
    "\
2
Lattice=\"10 0 0 0 10 0 0 0 10\" Properties=species:S:1:pos:R:3:masses:R:1 pbc=\"T T T\"
Cu 0.0 0.25 0.125 64.0
Cu 1.0 0.25 0.125 64.0
2
Lattice=\"10 0 0 0 10 0 0 0 10\" Properties=species:S:1:pos:R:3:masses:R:1 pbc=\"T T T\"
Cu 2.0 0.25 0.125 64.0
Cu 3.0 0.25 0.125 64.0
"
    .to_string()
}

fn read_extxyz(bytes: &[u8], threads: usize) -> Result<XyzTables, String> {
    let outcome = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        tables_from_extxyz_bytes_with_threads(bytes, threads)
    }));
    match outcome {
        Ok(result) => result,
        Err(_) => panic!("{threads} threads panicked in the extxyz reader"),
    }
}

fn assert_extxyz_complete(label: &str, got: &XyzTables) {
    if got.n_frames == 0 {
        return;
    }
    let atoms = got.n_frames * got.n_atoms;
    assert_eq!(got.positions.len(), atoms * 3, "{label} positions");
    assert_eq!(got.masses.len(), atoms, "{label} masses");
    assert!(
        got.positions.iter().all(|value| value.is_finite()),
        "{label} coordinate"
    );
}

fn assert_extxyz_equal(label: &str, got: &XyzTables, golden: &XyzTables) {
    assert_eq!(got.n_frames, golden.n_frames, "{label} frames");
    assert_eq!(got.n_atoms, golden.n_atoms, "{label} atoms");
    assert_extxyz_complete(label, got);
    for (index, (left, right)) in got
        .positions
        .iter()
        .zip(golden.positions.iter())
        .enumerate()
    {
        assert_eq!(left.to_bits(), right.to_bits(), "{label} pos {index}");
    }
}

fn rcz1(bytes: &[u8]) -> Option<(usize, usize)> {
    let at = bytes.windows(4).position(|window| window == b"RCZ1")?;
    if at + 6 > bytes.len() {
        return None;
    }
    let count = u16::from_le_bytes([bytes[at + 4], bytes[at + 5]]) as usize;
    Some((at, count))
}

fn index_end(bytes: &[u8], at: usize, count: usize) -> usize {
    let rows = 8 * count;
    let end = at + 6 + 16 * count + rows;
    end.min(bytes.len())
}

fn copper(n: usize) -> ConFrame {
    let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
    for index in 0..n {
        builder.add_atom(
            "Cu",
            index as f64,
            0.25,
            0.125,
            [false, false, false],
            index as u64 + 1,
            64.0,
        );
    }
    builder.build().unwrap()
}

fn indexed(dir: &Path, name: &str, frame: &ConFrame) -> PathBuf {
    let bytes = readcon_core::writer::write_frames_to_vec(std::slice::from_ref(frame)).unwrap();
    let path = dir.join(name);
    readcon_core::compression::write_gzip_members_limited(&path, &bytes, 2, 2).unwrap();
    path
}

#[test]
fn a_smaller_indexed_frame_reuses_the_atom_spare() {
    let dir = tempfile::tempdir().unwrap();
    let wide = indexed(dir.path(), "wide.con.gz", &copper(1200));
    let small = indexed(dir.path(), "small.con.gz", &copper(8));
    let loaded = read_con(&wide, 8).expect("wide");
    assert_eq!(loaded[0].atom_data.len(), 1200);
    let c_frame = unsafe {
        readcon_core::ffi::rkr_frame_to_c_frame(
            &loaded[0] as *const ConFrame as *const readcon_core::ffi::RKRConFrame,
        )
    };
    assert!(!c_frame.is_null());
    unsafe { readcon_core::ffi::free_c_frame(c_frame) };
    drop(loaded);
    let loaded = read_con(&small, 8).expect("small");
    assert_eq!(loaded[0].atom_data.len(), 8);
    assert_eq!(loaded[0].atom_data[7].atom_id, 8);
    drop(loaded);
}

#[test]
fn a_flipped_member_length_does_not_panic() {
    let dir = tempfile::tempdir().unwrap();
    let text = con_text(false);
    let golden = {
        let path = write(dir.path(), "plain.con", text.as_bytes());
        read_con(&path, 1).unwrap()
    };
    let gz = dir.path().join("members.con.gz");
    readcon_core::compression::write_gzip_members_limited(&gz, text.as_bytes(), 2, 2).unwrap();
    let bytes = std::fs::read(&gz).unwrap();
    let (at, count) = rcz1(&bytes).expect("index");
    assert!(count >= 2);
    let plain_at = at + 6 + 8 * count;
    let mut corrupt = bytes.clone();
    for index in 0..count {
        let slot = plain_at + 8 * index;
        corrupt[slot..slot + 8].copy_from_slice(&(1u64 << 63).to_le_bytes());
    }
    let path = write(dir.path(), "length.con.gz", &corrupt);
    for threads in THREADS {
        let outcome =
            std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| read_con(&path, threads)));
        match outcome {
            Ok(Ok(frames)) => assert_eq!(frames, golden, "t{threads}"),
            Ok(Err(_)) => {}
            Err(_) => panic!("t{threads} panicked on a flipped plain length"),
        }
    }
    let row_at = plain_at + 8 * count;
    if row_at + 8 * count <= bytes.len() {
        let mut rows = bytes.clone();
        for index in 0..count {
            let slot = row_at + 8 * index + 4;
            rows[slot..slot + 4].copy_from_slice(&u32::MAX.to_le_bytes());
        }
        let path = write(dir.path(), "rows.con.gz", &rows);
        for threads in THREADS {
            let outcome =
                std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| read_con(&path, threads)));
            match outcome {
                Ok(Ok(frames)) => assert_eq!(frames, golden, "rows t{threads}"),
                Ok(Err(_)) => {}
                Err(_) => panic!("t{threads} panicked on a flipped row count"),
            }
        }
    }
}

fn cut_every_byte(label: &str, bytes: &[u8], dir: &std::path::Path) {
    for len in 0..bytes.len() {
        let path = write(dir, &format!("{label}-{len}.cut"), &bytes[..len]);
        accept_con(&format!("{label} cut {len}"), &path);
    }
}

#[test]
fn plain_con_truncation_stays_clean() {
    let dir = tempfile::tempdir().unwrap();
    let con = con_text(false);
    let path = write(dir.path(), "two.con", con.as_bytes());
    let golden = read_con(&path, 1).expect("con");
    assert_eq!(golden.len(), 2);
    cut_every_byte("con", con.as_bytes(), dir.path());
}

#[test]
fn plain_convel_truncation_stays_clean() {
    let dir = tempfile::tempdir().unwrap();
    let convel = con_text(true);
    let path = write(dir.path(), "two.convel", convel.as_bytes());
    let golden = read_con(&path, 1).expect("convel");
    assert!(golden.iter().all(|frame| frame.has_velocities()));
    cut_every_byte("convel", convel.as_bytes(), dir.path());
}

#[test]
fn extxyz_truncation_stays_clean() {
    let xyz = extxyz_text();
    let golden = read_extxyz(xyz.as_bytes(), 1).expect("extxyz");
    for len in 0..xyz.len() {
        for threads in THREADS {
            match read_extxyz(&xyz.as_bytes()[..len], threads) {
                Ok(tables) => {
                    assert_extxyz_complete(&format!("extxyz cut {len} t{threads}"), &tables)
                }
                Err(err) => assert!(!err.is_empty()),
            }
        }
    }
    let _ = golden;
}

#[test]
fn gzip_truncation_stays_clean() {
    let dir = tempfile::tempdir().unwrap();
    let con = con_text(false);
    let gz = dir.path().join("two.con.gz");
    readcon_core::compression::write_gzip_members_limited(&gz, con.as_bytes(), 2, 2).unwrap();
    let gz_bytes = std::fs::read(&gz).unwrap();
    cut_every_byte("gz", &gz_bytes, dir.path());
}

#[test]
fn gzip_index_bitflips_stay_clean() {
    let dir = tempfile::tempdir().unwrap();
    let con = con_text(false);
    let gz = dir.path().join("two.con.gz");
    readcon_core::compression::write_gzip_members_limited(&gz, con.as_bytes(), 2, 2).unwrap();
    let gz_bytes = std::fs::read(&gz).unwrap();
    let (at, count) = rcz1(&gz_bytes).expect("gzip index");
    let end = index_end(&gz_bytes, at, count);
    for offset in at..end {
        for bit in 0..8 {
            let mut flipped = gz_bytes.clone();
            flipped[offset] ^= 1 << bit;
            let path = write(dir.path(), "flip.con.gz", &flipped);
            accept_con(&format!("gz bit {offset}:{bit}"), &path);
        }
    }
}

#[cfg(feature = "zstd")]
#[test]
fn zstd_truncation_and_bitflips_stay_clean() {
    let dir = tempfile::tempdir().unwrap();
    let con = con_text(false);
    let zst = dir.path().join("two.con.zst");
    readcon_core::compression::write_zstd_members_limited(&zst, con.as_bytes(), 2, 2).unwrap();
    let zst_bytes = std::fs::read(&zst).unwrap();
    cut_every_byte("zst", &zst_bytes, dir.path());
    if let Some((at, count)) = rcz1(&zst_bytes) {
        let end = index_end(&zst_bytes, at, count);
        for offset in at..end {
            for bit in 0..8 {
                let mut flipped = zst_bytes.clone();
                flipped[offset] ^= 1 << bit;
                let path = write(dir.path(), "flip.con.zst", &flipped);
                accept_con(&format!("zst bit {offset}:{bit}"), &path);
            }
        }
    }
}

#[test]
fn line_endings_counts_and_nonfinite_stay_clean() {
    let dir = tempfile::tempdir().unwrap();
    let con = con_text(false);
    let convel = con_text(true);
    let xyz = extxyz_text();
    let con_path = write(dir.path(), "two.con", con.as_bytes());
    let vel_path = write(dir.path(), "two.convel", convel.as_bytes());
    let con_golden = read_con(&con_path, 1).expect("con");
    let vel_golden = read_con(&vel_path, 1).expect("convel");
    let xyz_golden = read_extxyz(xyz.as_bytes(), 1).expect("extxyz");

    let crlf = write(dir.path(), "crlf.con", con.replace('\n', "\r\n").as_bytes());
    require_equal("crlf", &crlf, &con_golden);
    let crlf_vel = write(
        dir.path(),
        "crlf.convel",
        convel.replace('\n', "\r\n").as_bytes(),
    );
    require_equal("crlf convel", &crlf_vel, &vel_golden);
    let crlf_xyz = xyz.replace('\n', "\r\n");
    for threads in THREADS {
        let tables = read_extxyz(crlf_xyz.as_bytes(), threads).expect("crlf extxyz");
        assert_extxyz_equal(&format!("crlf t{threads}"), &tables, &xyz_golden);
    }

    let bare = con.trim_end_matches('\n');
    let bare_path = write(dir.path(), "bare.con", bare.as_bytes());
    require_equal("missing newline", &bare_path, &con_golden);
    let bare_xyz = xyz.trim_end_matches('\n');
    for threads in THREADS {
        let tables = read_extxyz(bare_xyz.as_bytes(), threads).expect("bare extxyz");
        assert_extxyz_equal(&format!("bare t{threads}"), &tables, &xyz_golden);
    }

    let mut short = con.clone();
    let count_at = short.find("\n2\n64").expect("atom count");
    short.replace_range(count_at + 1..count_at + 2, "5");
    let short_path = write(dir.path(), "short.con", short.as_bytes());
    require_err("header claims more atoms", &short_path);

    let mut bad = con.clone();
    bad.replace_range(count_at + 1..count_at + 2, "x");
    require_err(
        "bad atom count",
        &write(dir.path(), "bad.con", bad.as_bytes()),
    );
    let mut zero = con.clone();
    zero.replace_range(count_at + 1..count_at + 2, "0");
    require_err(
        "zero atom count",
        &write(dir.path(), "zero.con", zero.as_bytes()),
    );
    let mut negative = con.clone();
    negative.replace_range(count_at + 1..count_at + 2, "-");
    require_err(
        "negative atom count",
        &write(dir.path(), "neg.con", negative.as_bytes()),
    );

    let xyz_short = xyz.replacen("2\n", "5\n", 1);
    for threads in THREADS {
        assert!(
            read_extxyz(xyz_short.as_bytes(), threads).is_err(),
            "extxyz short t{threads}"
        );
    }
    let xyz_bad = xyz.replacen("2\n", "x\n", 1);
    for threads in THREADS {
        assert!(
            read_extxyz(xyz_bad.as_bytes(), threads).is_err(),
            "extxyz bad count t{threads}"
        );
    }

    let nan = con.replacen("0.0", "nan", 1);
    require_err("nan", &write(dir.path(), "nan.con", nan.as_bytes()));
    let inf = con.replacen("0.0", "inf", 1);
    require_err("inf", &write(dir.path(), "inf.con", inf.as_bytes()));
    let neg_inf = con.replacen("0.0", "-inf", 1);
    require_err(
        "neg inf",
        &write(dir.path(), "ninf.con", neg_inf.as_bytes()),
    );
    let xyz_nan = xyz.replacen("0.0", "nan", 1);
    for threads in THREADS {
        if let Ok(tables) = read_extxyz(xyz_nan.as_bytes(), threads) {
            assert!(
                tables.positions.iter().any(|value| value.is_nan()),
                "extxyz nan t{threads} dropped the value"
            );
        }
    }
    let xyz_inf = xyz.replacen("0.0", "inf", 1);
    for threads in THREADS {
        if let Ok(tables) = read_extxyz(xyz_inf.as_bytes(), threads) {
            assert!(
                tables.positions.iter().any(|value| value.is_infinite()),
                "extxyz inf t{threads} dropped the value"
            );
        }
    }
}
