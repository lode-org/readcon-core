//! Threaded and ranked writes stay byte-identical to the serial writer.
//!
//! The golden files are the formatter output from before the ryu change.
//! One, two and eight threads, and one, two and four MPI ranks, must
//! reproduce those bytes or the same serial binding write.

use readcon_core::iterators::ConFrameIterator;
use readcon_core::writer::{ConFrameWriter, write_frames_to_vec, write_frames_to_vec_with_threads};
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
            std::env::temp_dir().join(format!("readcon-rank-{ranks}-{}.con", std::process::id()));
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
    write_block(&comm, &out, mine, WriteMode::MpiIo, None).expect("write");
    comm.raw().barrier();
    if comm.rank() == 0 {
        let got = fs::read(&out).expect("written");
        assert_eq!(got, serial, "ranks {}", comm.size());
        let _ = fs::remove_file(&out);
    }
}
