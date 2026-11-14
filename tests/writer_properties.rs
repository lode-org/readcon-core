//! Random trajectories through the threaded writer, and through the MPI
//! writer when that harness is built. Every worker count and every rank
//! count is compared with the serial bytes.

#[path = "common/scratch.rs"]
mod scratch_dir;

use proptest::prelude::*;
use readcon_core::types::ConFrameBuilder;
use readcon_core::units::NATURAL_TIME_UNIT;
use readcon_core::writer::{
    format_frame_refs_unstored, write_frame_refs_to_path, write_frames_to_vec,
    write_frames_to_vec_with_threads,
};
use serde_json::json;

fn config() -> ProptestConfig {
    ProptestConfig {
        cases: 24,
        failure_persistence: None,
        ..ProptestConfig::default()
    }
}

fn one_frame(atoms: usize, velocity: bool, origin: f64) -> readcon_core::types::ConFrame {
    let mut builder = ConFrameBuilder::new([12.0, 12.0, 14.0], [90.0, 90.0, 90.0]);
    builder
        .set_units(json!({
            "length": "angstrom",
            "energy": "eV",
            "mass": "amu",
            "time": NATURAL_TIME_UNIT,
        }))
        .expect("units");
    for i in 0..atoms {
        let x = origin + (i as f64) * 0.125;
        builder.add_atom(
            "Cu",
            x,
            0.25,
            -0.5,
            [i % 2 == 0, false, false],
            i as u64,
            63.546,
        );
        if velocity {
            builder.with_velocity([0.01, -0.02, (i as f64) * 0.001]);
        }
    }
    builder.build().expect("frame")
}

fn serial_bytes(frames: &[readcon_core::types::ConFrame]) -> Vec<u8> {
    write_frames_to_vec(frames).expect("serial")
}

fn path_bytes(frames: &[readcon_core::types::ConFrame], workers: usize, bind: bool) -> Vec<u8> {
    let refs: Vec<&readcon_core::types::ConFrame> = frames.iter().collect();
    let path = scratch_dir::scratch().join(format!(
        "readcon-prop-{}-{}-{workers}-{bind}.con",
        std::process::id(),
        frames.len()
    ));
    write_frame_refs_to_path(&path, &refs, workers, None, false, bind).expect("path write");
    let got = std::fs::read(&path).expect("read path");
    let _ = std::fs::remove_file(&path);
    got
}

#[test]
fn unstored_groups_match_the_file_writer() {
    let small = one_frame(4, true, 0.5);
    for workers in [1usize, 2, 4, 8] {
        let frames = vec![small.clone(); 6];
        assert_groups_match(&frames, workers);
    }
    // Eight workers and a long run format into one buffer per worker,
    // the same span the file writer maps.
    let heavy = one_frame(64, false, 1.25);
    let frames = vec![heavy; 50_000];
    let refs: Vec<&readcon_core::types::ConFrame> = frames.iter().collect();
    let parts = format_frame_refs_unstored(&refs, 8, None, false, true).expect("unstored");
    assert_eq!(parts.len(), 8, "the mapping path is one buffer per worker");
    assert!(parts.iter().all(|part| !part.is_empty()));
    let mut got = Vec::new();
    for part in &parts {
        got.extend_from_slice(part);
    }
    let path = scratch_dir::scratch().join(format!("readcon-unstored-{}", std::process::id()));
    write_frame_refs_to_path(&path, &refs, 8, None, false, true).expect("path");
    let disk = std::fs::read(&path).expect("read");
    let _ = std::fs::remove_file(&path);
    assert_eq!(got, disk);
}

fn assert_groups_match(frames: &[readcon_core::types::ConFrame], workers: usize) {
    let refs: Vec<&readcon_core::types::ConFrame> = frames.iter().collect();
    let parts = format_frame_refs_unstored(&refs, workers, None, false, true).expect("unstored");
    let mut got = Vec::new();
    for part in &parts {
        got.extend_from_slice(part);
    }
    let path =
        scratch_dir::scratch().join(format!("readcon-unstored-{}-{workers}", std::process::id()));
    write_frame_refs_to_path(&path, &refs, workers, None, false, true).expect("path");
    let disk = std::fs::read(&path).expect("read");
    let _ = std::fs::remove_file(&path);
    assert_eq!(got, disk, "workers {workers}");
}

fn binding_bytes(frames: &[readcon_core::types::ConFrame]) -> Vec<u8> {
    use readcon_core::writer::ConFrameWriter;
    let mut buf = Vec::new();
    {
        let mut writer = ConFrameWriter::new(&mut buf);
        for frame in frames {
            writer.write_frame_bound(frame).expect("bound");
        }
        writer.flush().expect("flush");
    }
    buf
}

proptest! {
    #![proptest_config(config())]
    #[test]
    fn threaded_writer_matches_serial_bytes(
        counts in proptest::collection::vec(0usize..5, 0..18),
        velocity in proptest::collection::vec(any::<bool>(), 0..18),
        workers in 1usize..9,
    ) {
        let n = counts.len().min(velocity.len());
        let frames: Vec<_> = (0..n)
            .map(|i| one_frame(counts[i], velocity[i] && counts[i] > 0, i as f64))
            .collect();
        let serial = serial_bytes(&frames);
        let threaded = write_frames_to_vec_with_threads(&frames, workers, None, false)
            .expect("threaded");
        prop_assert_eq!(
            &threaded,
            &serial,
            "vec workers {}",
            workers
        );
        let on_disk = path_bytes(&frames, workers, false);
        prop_assert_eq!(&on_disk, &serial, "path workers {}", workers);
        let bound = binding_bytes(&frames);
        let bound_disk = path_bytes(&frames, workers, true);
        prop_assert_eq!(&bound_disk, &bound, "bound path workers {}", workers);
    }
}

#[cfg(feature = "mpi")]
fn run_ranks(
    ranks: usize,
    input: &std::path::Path,
    output: &std::path::Path,
    second: Option<&std::path::Path>,
) {
    let exe = std::env::current_exe().expect("test binary");
    let mut cmd = readcon_core::mpi_launch::mpi_command();
    cmd.args(["-n", &ranks.to_string()])
        .arg(&exe)
        .arg("mpi_ranks_match_the_serial_writer")
        .arg("--exact")
        .env("READCON_RANK_CHILD", ranks.to_string())
        .env("READCON_RANK_IN", input)
        .env("READCON_RANK_OUT", output);
    if let Some(second) = second {
        cmd.env("READCON_RANK_SECOND", second);
    } else {
        cmd.env_remove("READCON_RANK_SECOND");
    }
    let output = cmd
        .output()
        .unwrap_or_else(|err| panic!("mpirun -n {ranks}: {err}"));
    readcon_core::mpi_launch::assert_success(&output, &format!("mpirun -n {ranks}"));
}

#[cfg(feature = "mpi")]
#[test]
fn mpi_ranks_match_the_serial_writer() {
    if std::env::var("READCON_RANK_CHILD").is_ok() {
        mpi_rank_child();
        return;
    }
    let mut mpi_config = config();
    mpi_config.cases = 4;
    let mut runner = proptest::test_runner::TestRunner::new(mpi_config);
    let strategy = (
        proptest::collection::vec(0usize..4, 0..12),
        proptest::collection::vec(any::<bool>(), 0..12),
    );
    runner
        .run(&strategy, |(counts, velocity)| {
            let n = counts.len().min(velocity.len());
            let frames: Vec<_> = (0..n)
                .map(|i| one_frame(counts[i], velocity[i] && counts[i] > 0, i as f64))
                .collect();
            let text = serial_bytes(&frames);
            let dir =
                scratch_dir::scratch().join(format!("readcon-mpi-prop-{}", std::process::id()));
            std::fs::create_dir_all(&dir).expect("dir");
            let input = dir.join("in.con");
            std::fs::write(&input, &text).expect("input");
            for ranks in 1usize..=8 {
                let output = dir.join(format!("out-{ranks}.con"));
                run_ranks(ranks, &input, &output, None);
            }
            let _ = std::fs::remove_dir_all(&dir);
            Ok(())
        })
        .expect("mpi property");
}

#[cfg(feature = "mpi")]
#[test]
fn mpi_index_bytes_match_a_fresh_fingerprint() {
    if std::env::var("READCON_RANK_CHILD").is_ok() {
        mpi_rank_child();
        return;
    }
    // Enough bytes to cross a 1 MiB hash block, so a rank boundary
    // falls inside a block. The sidecar must still match a fingerprint
    // of the file, including ranks that own no frames.
    let frame = one_frame(48, true, 0.25);
    let frames = vec![frame; 700];
    let text = binding_bytes(&frames);
    assert!(text.len() > 1 << 20, "fixture is {} bytes", text.len());
    let dir = scratch_dir::scratch().join(format!("readcon-mpi-index-{}", std::process::id()));
    std::fs::create_dir_all(&dir).expect("dir");
    let input = dir.join("in.con");
    std::fs::write(&input, &text).expect("input");
    for ranks in [1usize, 3, 7, 8] {
        let output = dir.join(format!("out-{ranks}.con"));
        run_ranks(ranks, &input, &output, None);
    }
    let short = binding_bytes(&frames[..5]);
    let short_input = dir.join("short.con");
    std::fs::write(&short_input, &short).expect("short");
    let output = dir.join("out-empty.con");
    run_ranks(8, &short_input, &output, None);
    let _ = std::fs::remove_dir_all(&dir);
}

#[cfg(feature = "mpi")]
#[test]
fn mpi_same_length_rewrite_matches_the_second_write() {
    if std::env::var("READCON_RANK_CHILD").is_ok() {
        mpi_rank_child();
        return;
    }
    // Fixed decimals keep 1.25 and 2.25 the same width, so the second
    // write does not change the file length.
    let first = fixed_trajectory(1.25);
    let second = fixed_trajectory(2.25);
    assert_eq!(
        first.len(),
        second.len(),
        "the rewrite must keep the length"
    );
    assert_ne!(first, second);
    let dir = scratch_dir::scratch().join(format!("readcon-mpi-rewrite-{}", std::process::id()));
    std::fs::create_dir_all(&dir).expect("dir");
    let input = dir.join("first.con");
    let other = dir.join("second.con");
    std::fs::write(&input, &first).expect("first");
    std::fs::write(&other, &second).expect("second");
    for ranks in [1usize, 3, 5, 7, 8] {
        let output = dir.join(format!("out-{ranks}.con"));
        run_ranks(ranks, &input, &output, Some(&other));
    }
    let _ = std::fs::remove_dir_all(&dir);
}

#[cfg(feature = "mpi")]
fn fixed_trajectory(origin: f64) -> Vec<u8> {
    use readcon_core::writer::ConFrameWriter;
    let frames = [
        one_frame(2, false, origin),
        one_frame(0, false, origin),
        one_frame(3, true, origin + 1.0),
        one_frame(1, false, origin + 2.0),
    ];
    let mut buf = Vec::new();
    {
        let mut writer = ConFrameWriter::with_precision(&mut buf, 6);
        for frame in &frames {
            writer.write_frame_bound(frame).expect("fixed");
        }
        writer.flush().expect("flush");
    }
    buf
}

#[cfg(feature = "mpi")]
fn mpi_rank_child() {
    use mpi::collective::CommunicatorCollectives;
    use readcon_core::distrib::Comm;
    use readcon_core::distrib::block_range;
    use readcon_core::distrib_write::{WriteMode, write_block};
    use readcon_core::iterators::ConFrameIterator;

    let universe = mpi::initialize().expect("mpi");
    let world = universe.world();
    let comm = Comm::dup_of(&world);
    let input = std::env::var("READCON_RANK_IN").expect("input");
    let text = std::fs::read_to_string(&input).expect("read");
    let frames = ConFrameIterator::new(&text)
        .collect::<Result<Vec<_>, _>>()
        .expect("parse");
    let expected_first = binding_bytes(&frames);
    let range = block_range(frames.len(), comm.size(), comm.rank());
    let mine = &frames[range];
    let out = std::path::PathBuf::from(std::env::var("READCON_RANK_OUT").expect("out"));
    write_block(&comm, &out, mine, WriteMode::MpiIo, None, false, false).expect("write");
    if let Ok(second) = std::env::var("READCON_RANK_SECOND") {
        let text = std::fs::read_to_string(&second).expect("second");
        let frames = ConFrameIterator::new(&text)
            .collect::<Result<Vec<_>, _>>()
            .expect("parse second");
        let expected = binding_bytes(&frames);
        let range = block_range(frames.len(), comm.size(), comm.rank());
        let mine = &frames[range];
        let first_len = expected_first.len();
        assert_eq!(
            first_len,
            expected.len(),
            "the second write must keep the file length"
        );
        write_block(&comm, &out, mine, WriteMode::MpiIo, None, false, false).expect("rewrite");
        comm.raw().barrier();
        if comm.rank() == 0 {
            let got = std::fs::read(&out).expect("rewritten");
            assert_eq!(got, expected, "ranks {}", comm.size());
            assert_sidecar(&out, !frames.is_empty());
        }
        return;
    }
    comm.raw().barrier();
    if comm.rank() == 0 {
        let got = std::fs::read(&out).expect("written");
        assert_eq!(got, expected_first, "ranks {}", comm.size());
        assert_sidecar(&out, !frames.is_empty());
        let _ = std::fs::remove_file(&out);
        let _ = std::fs::remove_file(readcon_core::frame_index::sidecar_path(&out));
    }
}

#[cfg(feature = "mpi")]
fn assert_sidecar(path: &std::path::Path, expect_index: bool) {
    let side = readcon_core::frame_index::sidecar_path(path);
    if !expect_index {
        return;
    }
    assert!(side.is_file(), "sidecar missing for {}", path.display());
    let written = std::fs::read(&side).expect("sidecar");
    let idx = readcon_core::frame_index::read_sidecar(path)
        .expect("read sidecar")
        .expect("index");
    readcon_core::frame_index::write_sidecar(path, &idx).expect("fingerprint");
    let fingerprinted = std::fs::read(&side).expect("fingerprinted");
    assert_eq!(written, fingerprinted, "folded hash diverges from the file");
}
