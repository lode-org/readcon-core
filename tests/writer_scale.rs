//! Threaded and ranked writes stay byte-identical to the serial writer.
//!
//! The golden files are the formatter output from before the ryu change.
//! One, two and eight threads, and one, two and four MPI ranks, must
//! reproduce those bytes or the same serial binding write.

#[path = "common/scratch.rs"]
mod scratch_dir;

use readcon_core::iterators::ConFrameIterator;
use readcon_core::types::ConFrameBuilder;
use readcon_core::writer::{
    ConFrameWriter, format_coordinate_lines, recycle_format_buffer, write_frame_refs_to_path,
    write_frame_refs_with_threads, write_frames_to_vec, write_frames_to_vec_with_threads,
};
use std::fs;
use std::path::PathBuf;

fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn fixture_pairs() -> Vec<(PathBuf, PathBuf)> {
    let root = root();
    let mut pairs = Vec::new();
    for (dir, prefix) in [
        ("resources/test", "test__"),
        ("resources/conformance/valid", "valid__"),
    ] {
        let folder = root.join(dir);
        for entry in fs::read_dir(&folder).unwrap_or_else(|err| panic!("read {dir}: {err}")) {
            let entry = entry.expect("dir entry");
            let name = entry.file_name();
            let name = name.to_string_lossy();
            if !(name.ends_with(".con") || name.ends_with(".convel")) {
                continue;
            }
            let golden = root
                .join("tests/writer_golden")
                .join(format!("{prefix}{name}"));
            if golden.is_file() {
                pairs.push((entry.path(), golden));
            }
        }
    }
    pairs.sort();
    assert!(pairs.len() >= 20, "expected the golden corpus");
    pairs
}

fn parsed(text: &str) -> Vec<readcon_core::types::ConFrame> {
    ConFrameIterator::new(text)
        .collect::<Result<Vec<_>, _>>()
        .expect("fixture parses")
}

#[test]
fn ryu_output_matches_the_golden_files_byte_for_byte() {
    for (fixture, golden) in fixture_pairs() {
        let text = fs::read_to_string(&fixture).expect("fixture");
        let frames = parsed(&text);
        let got = write_frames_to_vec(&frames).expect("write");
        let expected = fs::read(&golden).expect("golden");
        assert_eq!(got, expected, "{}", fixture.display());
    }
}

#[test]
fn one_two_and_eight_threads_match_the_golden_writer() {
    for (fixture, golden) in fixture_pairs() {
        let text = fs::read_to_string(&fixture).expect("fixture");
        let frames = parsed(&text);
        let expected = fs::read(&golden).expect("golden");
        let serial = write_frames_to_vec(&frames).expect("serial");
        assert_eq!(serial, expected, "serial {}", fixture.display());
        for threads in [1usize, 2, 8] {
            let got =
                write_frames_to_vec_with_threads(&frames, threads, None, false).expect("threads");
            assert_eq!(got, serial, "{} threads {threads}", fixture.display());
            let again = String::from_utf8(got).expect("utf8");
            let round = parsed(&again);
            assert_eq!(
                round,
                frames,
                "round trip {} threads {threads}",
                fixture.display()
            );
        }
    }
}

#[cfg(feature = "mpi")]
fn binding_bytes(frames: &[readcon_core::types::ConFrame]) -> Vec<u8> {
    let mut buf = Vec::new();
    {
        let mut writer = ConFrameWriter::new(&mut buf);
        for frame in frames {
            writer.write_frame_bound(frame).expect("stamp");
        }
        writer.flush().expect("flush");
    }
    buf
}

#[cfg(feature = "mpi")]
#[test]
fn one_two_and_four_ranks_match_the_serial_writer() {
    if std::env::var("READCON_RANK_CHILD").is_ok() {
        rank_child();
        return;
    }
    let fixture = root().join("resources/test/tiny_multi_cuh2.con");
    let exe = std::env::current_exe().expect("test binary");
    for ranks in [1u32, 2, 4] {
        let out =
            scratch_dir::scratch().join(format!("readcon-rank-{ranks}-{}.con", std::process::id()));
        let status = std::process::Command::new("mpirun")
            .args([
                "-n",
                &ranks.to_string(),
                exe.to_str().expect("utf8 path"),
                "one_two_and_four_ranks_match_the_serial_writer",
                "--exact",
            ])
            .env("READCON_RANK_CHILD", ranks.to_string())
            .env("READCON_RANK_FIXTURE", &fixture)
            .env("READCON_RANK_OUT", &out)
            .status()
            .unwrap_or_else(|err| panic!("mpirun -n {ranks}: {err}"));
        assert!(status.success(), "mpirun -n {ranks} failed");
        let _ = fs::remove_file(&out);
    }
}

#[cfg(feature = "mpi")]
fn rank_child() {
    use mpi::collective::CommunicatorCollectives;
    use readcon_core::distrib::Comm;
    use readcon_core::distrib::block_range;
    use readcon_core::distrib_write::{WriteMode, write_block};

    let universe = mpi::initialize().expect("mpi");
    let world = universe.world();
    let comm = Comm::dup_of(&world);
    let fixture = std::env::var("READCON_RANK_FIXTURE").expect("fixture");
    let text = fs::read_to_string(&fixture).expect("read");
    let frames = parsed(&text);
    let serial = binding_bytes(&frames);
    let range = block_range(frames.len(), comm.size(), comm.rank());
    let mine = &frames[range];
    let out = PathBuf::from(std::env::var("READCON_RANK_OUT").expect("out"));
    write_block(&comm, &out, mine, WriteMode::MpiIo, None, false, false).expect("write");
    comm.raw().barrier();
    if comm.rank() == 0 {
        let got = fs::read(&out).expect("written");
        assert_eq!(got, serial, "ranks {}", comm.size());
        let side = readcon_core::frame_index::sidecar_path(&out);
        let written = fs::read(&side).expect("sidecar");
        let idx = readcon_core::frame_index::read_sidecar(&out)
            .expect("read sidecar")
            .expect("index");
        readcon_core::frame_index::write_sidecar(&out, &idx).expect("fingerprint");
        let fingerprinted = fs::read(&side).expect("fingerprinted sidecar");
        assert_eq!(
            written, fingerprinted,
            "the ranked sidecar must match a fingerprint of the file"
        );
    }
    // Same length as the file just written. Rank 0 must not truncate
    // it; the bytes are the serial writer again.
    write_block(&comm, &out, mine, WriteMode::MpiIo, None, false, false).expect("rewrite");
    comm.raw().barrier();
    if comm.rank() == 0 {
        let rewritten = fs::read(&out).expect("rewritten");
        assert_eq!(
            rewritten,
            serial,
            "same-length rewrite ranks {}",
            comm.size()
        );
        let spare = out.with_file_name(format!(
            "{}.rewrite",
            out.file_name().unwrap().to_string_lossy()
        ));
        assert!(
            !spare.exists(),
            "the default ranked write leaves no .rewrite file"
        );
        let _ = fs::remove_file(&out);
        let _ = fs::remove_file(readcon_core::frame_index::sidecar_path(&out));
    }
}

fn wide_frame(
    n: usize,
    velocities: bool,
    id_of: impl Fn(usize) -> u64,
) -> readcon_core::types::ConFrame {
    let mut builder = ConFrameBuilder::new([20.0, 20.0, 20.0], [90.0, 90.0, 90.0]);
    if velocities {
        builder
            .set_units(serde_json::json!({
                "length": "angstrom",
                "energy": "eV",
                "mass": "amu",
                "time": "(amu*angstrom^2/eV)^0.5"
            }))
            .expect("units");
    }
    for i in 0..n {
        let x = (i % 100) as f64 * 0.2;
        let y = ((i / 100) % 50) as f64 * 0.4;
        let z = (i / 5000) as f64 + if i % 2 == 0 { 0.125 } else { -0.5 };
        builder.add_atom("Cu", x, y, z, [false, i % 7 == 0, false], id_of(i), 63.546);
        if velocities {
            builder.with_velocity([0.01 * (i % 11) as f64, -0.02, (i % 3) as f64]);
        }
    }
    builder.build().expect("wide frame")
}

fn mapped_bytes(frame: &readcon_core::types::ConFrame, workers: usize) -> Vec<u8> {
    let path = scratch_dir::scratch().join(format!(
        "readcon-wide-map-{}-{}-{}.con",
        workers,
        std::process::id(),
        frame.atom_data.len()
    ));
    let file = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(true)
        .open(&path)
        .expect("create");
    let mut writer = ConFrameWriter::new(Vec::<u8>::new())
        .parallel_atoms(workers)
        .map_rows(true)
        .mapped_file(file);
    writer
        .write_frame(frame)
        .unwrap_or_else(|err| panic!("mapped write workers {workers}: {err}"));
    drop(writer);
    let got = fs::read(&path).expect("read back");
    let _ = fs::remove_file(&path);
    got
}

/// Wide rows with velocities, and with ids that are not `0..n`, match the
/// serial writer when the caller forces the shared mapping. That is the
/// path a runner with no spare physical core would otherwise skip.
#[test]
fn wide_mapping_matches_serial_for_velocities_and_gapped_ids() {
    let cases = [
        wide_frame(4096, true, |i| i as u64),
        wide_frame(4096, true, |i| (i as u64) + 3),
        wide_frame(5000, false, |i| i as u64),
    ];
    for (case, frame) in cases.into_iter().enumerate() {
        let serial = write_frames_to_vec(std::slice::from_ref(&frame)).expect("serial");
        for workers in [2usize, 8] {
            let got = mapped_bytes(&frame, workers);
            assert_eq!(got, serial, "case {case} workers {workers}");
        }
        if case == 0 {
            // A fixed number of decimal places still matches the serial
            // writer, and it takes the wide-file branch that passes precision
            // through.
            let refs = [&frame];
            let fixed = write_frame_refs_with_threads(&refs, 1, Some(6), false).expect("decimals");
            let path = scratch_dir::scratch()
                .join(format!("readcon-wide-decimals-{}.con", std::process::id()));
            write_frame_refs_to_path(&path, &refs, 8, Some(6), false, false).expect("decimals");
            let got = fs::read(&path).expect("read back");
            let _ = fs::remove_file(&path);
            assert_eq!(got, fixed, "decimal places");
        }
        // A short buffer goes back to the pool, then a wide format has to
        // grow it. The bytes stay the coordinate block of the serial frame.
        let short = format_coordinate_lines(&frame.atom_data[..2]).expect("short");
        recycle_format_buffer(short);
        let lines = format_coordinate_lines(&frame.atom_data).expect("grown");
        let text = std::str::from_utf8(&serial).expect("utf8");
        let marker = "Coordinates of Component 1\n";
        let start = text.find(marker).expect("coords") + marker.len();
        let end = text[start..]
            .find("\n\n")
            .map(|at| start + at + 1)
            .unwrap_or(text.len());
        assert_eq!(lines, text.as_bytes()[start..end], "case {case}");
        recycle_format_buffer(lines);
    }
    let duplicated = wide_frame(4096, false, |i| if i == 10 { 0 } else { i as u64 });
    let path = scratch_dir::scratch().join(format!("readcon-wide-dup-{}.con", std::process::id()));
    let file = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(true)
        .open(&path)
        .expect("create");
    let err = ConFrameWriter::new(Vec::<u8>::new())
        .parallel_atoms(8)
        .map_rows(true)
        .mapped_file(file)
        .write_frame(&duplicated);
    let _ = fs::remove_file(&path);
    assert!(
        err.is_err(),
        "a repeated atom id is rejected on the mapped path"
    );
}

#[test]
fn a_zero_atom_frame_cannot_declare_sections() {
    let mut frame = wide_frame(1, false, |i| i as u64);
    frame.header.natm_types = 0;
    frame.atom_data.clear();
    frame.header.natms_per_type.clear();
    frame.header.masses_per_type.clear();
    frame.header.sections.push("velocities".into());
    let err = ConFrameWriter::new(Vec::<u8>::new()).write_frame(&frame);
    assert!(err.is_err(), "a zero-atom frame cannot declare sections");
}

#[test]
fn a_per_type_count_of_zero_is_rejected() {
    let mut frame = wide_frame(1, false, |i| i as u64);
    frame.header.natms_per_type = vec![0];
    let err = ConFrameWriter::new(Vec::<u8>::new()).write_frame(&frame);
    assert!(err.is_err(), "each per-type count must be >= 1");
}
