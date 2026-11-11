//! Writer bytes stay equal to the previous formatter on the fixture corpus.
//!
//! Each golden file is the writer output captured before the formatting
//! change. The test parses the fixture, writes it, and compares those bytes,
//! then parses the written text and checks the frames match.

use readcon_core::iterators::ConFrameIterator;
use readcon_core::writer::ConFrameWriter;
use std::fs;
use std::path::PathBuf;

fn manifest_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn fixture_pairs() -> Vec<(PathBuf, PathBuf)> {
    let root = manifest_dir();
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
            if !golden.is_file() {
                continue;
            }
            pairs.push((entry.path(), golden));
        }
    }
    pairs.sort();
    assert!(
        pairs.len() >= 20,
        "expected the fixture corpus, got {}",
        pairs.len()
    );
    pairs
}

fn write_frames(text: &str) -> Vec<u8> {
    let frames = ConFrameIterator::new(text)
        .collect::<Result<Vec<_>, _>>()
        .expect("fixture parses");
    let mut buf = Vec::new();
    {
        let mut writer = ConFrameWriter::new(&mut buf);
        writer.extend(frames.iter()).expect("write");
        writer.flush().expect("flush");
    }
    buf
}

#[test]
fn writer_matches_saved_bytes_and_round_trips() {
    for (fixture, golden) in fixture_pairs() {
        let text = fs::read_to_string(&fixture).expect("read fixture");
        let written = write_frames(&text);
        let expected = fs::read(&golden).expect("read golden");
        assert_eq!(
            written,
            expected,
            "writer bytes differ for {}",
            fixture.display()
        );
        let again = String::from_utf8(written).expect("utf8");
        let original: Vec<_> = ConFrameIterator::new(&text)
            .map(|frame| frame.expect("parse"))
            .collect();
        let round: Vec<_> = ConFrameIterator::new(&again)
            .map(|frame| frame.expect("reparse"))
            .collect();
        assert_eq!(original, round, "round trip {}", fixture.display());
    }
}
