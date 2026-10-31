//! `ConFrameReader` gives the frames and the first error that the current
//! path gives on the whole text, for plain, gzip and zstd input.

use readcon_core::compression::{gzip_writer, read_file_contents};
use readcon_core::error::ParseError;
use readcon_core::iterators::{ConFrameIterator, ConFrameReader};
use readcon_core::types::ConFrame;
use std::error::Error;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};

/// Frames before the first error, then that error as class, line and text.
type Outcome = (Vec<ConFrame>, Option<(String, u32, String)>);

const READ_SIZES: [usize; 5] = [1, 7, 64, 4096, 1 << 20];

fn describe(e: &(dyn Error + 'static)) -> (String, u32, String) {
    match e.downcast_ref::<ParseError>() {
        Some(p) => (p.class_name().into(), p.line(), p.to_string()),
        None => ("other".into(), 0, e.to_string()),
    }
}

fn whole_text(text: &str) -> Outcome {
    let mut frames = Vec::new();
    for item in ConFrameIterator::new(text) {
        match item {
            Ok(f) => frames.push(f),
            Err(e) => return (frames, Some(describe(&e))),
        }
    }
    (frames, None)
}

fn current(path: &Path) -> Outcome {
    match read_file_contents(path) {
        Ok(contents) => whole_text(contents.as_str().unwrap()),
        Err(e) => (Vec::new(), Some(describe(&*e))),
    }
}

fn collect<R: Read>(mut reader: ConFrameReader<R>) -> Outcome {
    let mut frames = Vec::new();
    for item in reader.by_ref() {
        match item {
            Ok(f) => frames.push(f),
            Err(e) => {
                assert!(reader.next().is_none(), "the reader ends after an error");
                return (frames, Some(describe(&*e)));
            }
        }
    }
    (frames, None)
}

fn streamed(bytes: &[u8], read_size: usize) -> Outcome {
    collect(ConFrameReader::with_read_size(bytes, read_size))
}

fn assert_streams_like_whole(text: &str, what: &str) {
    let want = whole_text(text);
    for read_size in READ_SIZES {
        assert!(
            streamed(text.as_bytes(), read_size) == want,
            "{what}, read size {read_size}"
        );
    }
}

fn con_files(dir: &Path) -> Vec<PathBuf> {
    let mut paths: Vec<_> = std::fs::read_dir(dir)
        .unwrap()
        .map(|e| e.unwrap().path())
        .filter(|p| {
            matches!(
                p.extension().and_then(|e| e.to_str()),
                Some("con" | "convel")
            )
        })
        .collect();
    paths.sort();
    paths
}

fn resource(rel: &str) -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("resources")
        .join(rel)
}

fn cuh2() -> String {
    std::fs::read_to_string(resource("test/cuh2.con")).unwrap()
}

#[test]
fn every_fixture_streams_like_the_whole_text() {
    let mut n = 0;
    for dir in ["test", "conformance/valid", "conformance/invalid"] {
        for path in con_files(&resource(dir)) {
            let text = std::fs::read_to_string(&path).unwrap();
            assert_streams_like_whole(&text, &path.display().to_string());
            assert_streams_like_whole(&text.repeat(3), &format!("{} x3", path.display()));
            let gap = format!("{}\n{}{text}", text.trim_end(), " \t\n".repeat(9));
            assert_streams_like_whole(&gap, &format!("{} whitespace gap", path.display()));
            n += 1;
        }
    }
    assert!(n >= 30, "only {n} fixtures");
}

#[test]
fn every_prefix_streams_like_the_whole_text() {
    for name in ["tiny_multi_cuh2.con", "tiny_multi_cuh2.convel"] {
        let text = std::fs::read_to_string(resource("test").join(name)).unwrap();
        for len in 0..=text.len() {
            let prefix = &text[..len];
            let want = whole_text(prefix);
            for read_size in [1, 13, 1 << 20] {
                assert!(
                    streamed(prefix.as_bytes(), read_size) == want,
                    "{name} cut at {len}, read size {read_size}"
                );
            }
        }
    }
    let text = cuh2().repeat(3);
    for len in (0..=text.len()).step_by(97) {
        assert_streams_like_whole(&text[..len], &format!("cuh2 x3 cut at {len}"));
    }
}

/// `cuh2.con` five times with frame 3 broken, so it is a parse error.
fn broken_trajectory() -> String {
    let frame = cuh2();
    let bad = frame.replacen("0.63939999999999997", "0.6393999999999999x", 1);
    assert_ne!(bad, frame);
    [&frame, &frame, &bad, &frame, &frame]
        .map(String::as_str)
        .concat()
}

fn write_gzip(path: &Path, members: &[&[u8]]) {
    let mut file = std::fs::File::create(path).unwrap();
    for member in members {
        let mut enc = flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::default());
        enc.write_all(member).unwrap();
        file.write_all(&enc.finish().unwrap()).unwrap();
    }
}

#[test]
fn files_stream_like_the_current_path() {
    let dir = tempfile::tempdir().unwrap();
    let five = cuh2().repeat(5);
    let tiny = std::fs::read_to_string(resource("test/tiny_multi_cuh2.convel")).unwrap();
    let cut = &five[..five.len() - 5000];
    let broken = broken_trajectory();
    let mut cases = Vec::new();
    for (name, text) in [
        ("five", five.as_str()),
        ("tiny", tiny.as_str()),
        ("cut", cut),
        ("broken", broken.as_str()),
    ] {
        let plain = dir.path().join(format!("{name}.con"));
        std::fs::write(&plain, text).unwrap();
        let gz = dir.path().join(format!("{name}.con.gz"));
        let mut enc = gzip_writer(&gz).unwrap();
        enc.write_all(text.as_bytes()).unwrap();
        enc.finish().unwrap();
        let members = dir.path().join(format!("{name}.members.con.gz"));
        let (a, b) = text.as_bytes().split_at(text.len() / 3);
        write_gzip(&members, &[a, b]);
        cases.extend([plain, gz, members]);
        #[cfg(feature = "zstd")]
        {
            let zst = dir.path().join(format!("{name}.con.zst"));
            let mut enc = readcon_core::compression::zstd_writer(&zst).unwrap();
            enc.write_all(text.as_bytes()).unwrap();
            drop(enc);
            cases.push(zst);
        }
    }
    for path in &cases {
        let want = current(path);
        let name = path.file_name().unwrap().to_str().unwrap();
        if name.starts_with("five") {
            assert_eq!((want.0.len(), &want.1), (5, &None), "{name}");
        }
        if name.starts_with("broken") {
            assert_eq!(want.0.len(), 2, "{name}");
            assert!(want.1.is_some(), "{name}");
        }
        if name.starts_with("cut") {
            assert_eq!(want.0.len(), 4, "{name}");
            assert!(want.1.is_some(), "{name}");
        }
        assert!(
            collect(ConFrameReader::open(path).unwrap()) == want,
            "{name}"
        );
        for read_size in [1, 4096] {
            let src = readcon_core::compression::open_decoded(path).unwrap();
            assert!(
                collect(ConFrameReader::with_read_size(src, read_size)) == want,
                "{name}, read size {read_size}"
            );
        }
    }
}

/// The frames of the text a gzip decoder gives before it fails, then its
/// error, or the parse error when `parse_error` is set.
fn decoded_then_error(path: &Path, parse_error: bool) -> Outcome {
    let mut text = Vec::new();
    let file = std::fs::File::open(path).unwrap();
    let err = flate2::read::MultiGzDecoder::new(file)
        .read_to_end(&mut text)
        .unwrap_err()
        .to_string();
    assert_eq!(read_file_contents(path).err().unwrap().to_string(), err);
    let (frames, parsed) = whole_text(std::str::from_utf8(&text).unwrap());
    if parse_error {
        return (frames, parsed);
    }
    (frames, Some(("other".into(), 0, err)))
}

#[test]
fn truncated_gzip_gives_every_decoded_frame_then_the_error() {
    let dir = tempfile::tempdir().unwrap();
    let broken = broken_trajectory();
    // Bytes kept of the gzip file, and the frames that decode.
    let cases: [(_, _, fn(usize) -> usize, _, _); 5] = [
        ("five", cuh2().repeat(5), |n| n - 1, Some(5), false),
        ("trailer", cuh2().repeat(5), |n| n - 8, Some(5), false),
        ("eighty", cuh2().repeat(80), |n| n - 1, Some(80), false),
        ("half", cuh2().repeat(80), |n| n / 2, None, false),
        ("broken", broken, |n| n - 1, Some(2), true),
    ];
    for (name, text, keep, frames, parse_error) in cases {
        let gz = dir.path().join(format!("{name}.con.gz"));
        write_gzip(&gz, &[text.as_bytes()]);
        let bytes = std::fs::read(&gz).unwrap();
        std::fs::write(&gz, &bytes[..keep(bytes.len())]).unwrap();
        let want = decoded_then_error(&gz, parse_error);
        match frames {
            Some(n) => assert_eq!(want.0.len(), n, "{name}"),
            None => assert!((1..80).contains(&want.0.len()), "{name}"),
        }
        assert!(want.1.is_some(), "{name}");
        assert!(
            collect(ConFrameReader::open(&gz).unwrap()) == want,
            "{name}"
        );
        for read_size in READ_SIZES {
            let src = readcon_core::compression::open_decoded(&gz).unwrap();
            assert!(
                collect(ConFrameReader::with_read_size(src, read_size)) == want,
                "{name}, read size {read_size}"
            );
        }
    }
}

#[cfg(not(feature = "zstd"))]
#[test]
fn zstd_without_the_feature_fails_to_open_as_the_current_path() {
    let dir = tempfile::tempdir().unwrap();
    let zst = dir.path().join("x.con.zst");
    std::fs::write(&zst, [0x28, 0xb5, 0x2f, 0xfd, 0, 0]).unwrap();
    let want = read_file_contents(&zst).err().unwrap().to_string();
    let got = ConFrameReader::open(&zst).err().unwrap().to_string();
    assert_eq!(got, want);
}
