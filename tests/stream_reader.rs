use readcon_core::compression::gzip_writer;
use readcon_core::iterators::{ConFrameIterator, read_all_frames};
use readcon_core::stream::{ConFrameReader, DEFAULT_READ_SIZE};
use readcon_core::types::ConFrame;
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};

const READ_SIZES: [usize; 6] = [1, 3, 16, 61, 4096, DEFAULT_READ_SIZE];

type Outcome = Vec<Result<ConFrame, String>>;

fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("resources")
}

/// Every `.con` and `.convel` fixture, valid or not.
fn fixtures() -> Vec<(String, Vec<u8>)> {
    let mut out = Vec::new();
    for dir in [
        "test",
        "examples",
        "conformance/valid",
        "conformance/invalid",
    ] {
        let mut paths: Vec<_> = std::fs::read_dir(root().join(dir))
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
        for p in paths {
            out.push((p.display().to_string(), std::fs::read(&p).unwrap()));
        }
    }
    out
}

/// What the in-memory iterator yields, up to and including the first error.
fn in_memory(bytes: &[u8]) -> Outcome {
    let mut out = Vec::new();
    for r in ConFrameIterator::from_bytes(bytes) {
        let failed = r.is_err();
        out.push(r.map_err(|e| e.to_string()));
        if failed {
            break;
        }
    }
    out
}

fn streamed(bytes: &[u8], read_size: usize) -> Outcome {
    ConFrameReader::with_read_size(bytes, read_size)
        .map(|r| r.map_err(|e| e.to_string()))
        .collect()
}

fn skip_counts(bytes: &[u8], read_size: Option<usize>) -> (usize, Option<String>) {
    let mut n = 0;
    let mut mem = ConFrameIterator::from_bytes(bytes);
    let mut reader = read_size.map(|s| ConFrameReader::with_read_size(bytes, s));
    loop {
        let step = match reader.as_mut() {
            Some(r) => r.forward().map(|s| s.map_err(|e| e.to_string())),
            None => mem.forward().map(|s| s.map_err(|e| e.to_string())),
        };
        match step {
            Some(Ok(())) => n += 1,
            Some(Err(e)) => return (n, Some(e)),
            None => return (n, None),
        }
    }
}

fn assert_same(name: &str, bytes: &[u8]) {
    let want = in_memory(bytes);
    let skips = skip_counts(bytes, None);
    for size in READ_SIZES {
        assert_eq!(streamed(bytes, size), want, "{name}, read size {size}");
        assert_eq!(
            skip_counts(bytes, Some(size)),
            skips,
            "{name} skip, read size {size}"
        );
    }
}

#[test]
fn fixtures_stream_as_they_parse_in_memory() {
    let all = fixtures();
    assert!(all.len() > 30);
    for (name, bytes) in &all {
        assert_same(name, bytes);
        assert_same(&format!("{name} x3"), &bytes.repeat(3));
        let crlf = String::from_utf8_lossy(bytes).replace('\n', "\r\n");
        assert_same(&format!("{name} crlf"), crlf.as_bytes());
    }
    let joined: Vec<u8> = all
        .iter()
        .filter(|(name, _)| name.contains("/test/") || name.contains("/valid/"))
        .flat_map(|(_, b)| b.iter().copied())
        .collect();
    assert_same("all valid fixtures", &joined);
}

/// A trajectory with sections, a legacy velocity block and empty header
/// lines.
/// A cut in it can fall where the parser probes past a blank line.
fn mixed_trajectory() -> Vec<u8> {
    [
        "test/tiny_multi_cuh2.con",
        "test/tiny_cuh2.convel",
        "test/tiny_cuh2_vel_forces.con",
        "conformance/valid/empty_user_line_two.con",
        "test/tiny_multi_cuh2.convel",
        "conformance/valid/zero_atom_then_frame.con",
    ]
    .iter()
    .flat_map(|p| std::fs::read(root().join(p)).unwrap())
    .collect()
}

#[test]
fn malformed_input_fails_where_the_in_memory_parse_fails() {
    let base = mixed_trajectory();
    assert!(in_memory(&base).iter().all(Result::is_ok));
    for cut in (0..base.len()).step_by(11) {
        assert_same(&format!("cut at {cut}"), &base[..cut]);
    }
    for (step, byte) in [(23, b'x'), (37, 0xff), (41, b'\n'), (53, b' ')] {
        for at in (0..base.len()).step_by(step) {
            let mut bad = base.clone();
            bad[at] = byte;
            assert_same(&format!("byte {byte:#x} at {at}"), &bad);
        }
    }
    for text in [&b""[..], b"\n", b"  \n\t\n", b"garbage\n", b"\xff\xfe\n"] {
        assert_same(&format!("{text:?}"), text);
    }
}

struct FailAfter<'a> {
    data: &'a [u8],
}

impl Read for FailAfter<'_> {
    fn read(&mut self, out: &mut [u8]) -> io::Result<usize> {
        if self.data.is_empty() {
            return Err(io::Error::other("device went away"));
        }
        self.data.read(out)
    }
}

/// Before the source error, the reader must give the frames that
/// `from_bytes` gives over `data`, and skip what its `forward` skips.
fn assert_source_error_after(name: &str, data: &[u8], read_sizes: &[usize]) {
    let frames: Vec<ConFrame> = in_memory(data).into_iter().map_while(Result::ok).collect();
    let mut mem = ConFrameIterator::from_bytes(data);
    let skips = std::iter::from_fn(|| mem.forward())
        .map_while(Result::ok)
        .count();
    for &size in read_sizes {
        let mut reader = ConFrameReader::with_read_size(FailAfter { data }, size);
        for (i, want) in frames.iter().enumerate() {
            let got = reader.next().unwrap();
            assert_eq!(
                got.as_ref().ok(),
                Some(want),
                "{name}, frame {i}, read size {size}"
            );
        }
        let err = reader.next().unwrap().unwrap_err();
        assert!(err.downcast_ref::<io::Error>().is_some(), "{name}: {err}");
        assert!(err.to_string().contains("device went away"));
        assert!(reader.next().is_none());

        let mut reader = ConFrameReader::with_read_size(FailAfter { data }, size);
        for _ in 0..skips {
            assert!(
                reader.forward().unwrap().is_ok(),
                "{name} skip, read size {size}"
            );
        }
        let err = reader.forward().unwrap().unwrap_err();
        assert!(
            err.downcast_ref::<io::Error>().is_some(),
            "{name} skip: {err}"
        );
        assert!(reader.forward().is_none());
    }
}

#[test]
fn a_read_error_after_a_whole_file_comes_after_its_last_frame() {
    let one = std::fs::read(root().join("test/tiny_cuh2.convel")).unwrap();
    let two = one.repeat(2);
    assert_eq!(in_memory(&one).len(), 1);
    assert_eq!(in_memory(&two).len(), 2);
    let mut sizes = READ_SIZES.to_vec();
    sizes.extend([64, one.len() - 1, one.len(), two.len()]);
    for (name, text) in [("one frame", &one), ("two frames", &two)] {
        assert_source_error_after(name, text, &sizes);
        let trimmed = text.strip_suffix(b"\n").unwrap();
        assert_source_error_after(&format!("{name}, no final newline"), trimmed, &sizes);
    }
}

#[test]
fn a_read_error_ends_the_stream_after_the_frames_before_it() {
    let base = mixed_trajectory();
    for cut in (0..base.len()).step_by(11) {
        assert_source_error_after(&format!("cut at {cut}"), &base[..cut], &READ_SIZES);
    }
}

fn assert_open_matches(path: &Path, want: &[ConFrame]) {
    let got: Vec<ConFrame> = ConFrameReader::open(path)
        .unwrap()
        .map(|r| r.unwrap())
        .collect();
    assert_eq!(got, want, "{}", path.display());
}

#[test]
fn open_decodes_gzip_members_and_plain_files() {
    let dir = tempfile::tempdir().unwrap();
    let text = mixed_trajectory().repeat(40);
    let want: Vec<ConFrame> = in_memory(&text).into_iter().map(Result::unwrap).collect();
    let plain = dir.path().join("t.con");
    std::fs::write(&plain, &text).unwrap();
    assert_eq!(read_all_frames(&plain).unwrap(), want);
    assert_open_matches(&plain, &want);
    // Two gzip members, split inside a frame.
    let gz = dir.path().join("t.con.gz");
    let half = text.len() / 2 + 7;
    let mut bytes = Vec::new();
    for part in [&text[..half], &text[half..]] {
        let one = dir.path().join("part.gz");
        let mut enc = gzip_writer(&one).unwrap();
        enc.write_all(part).unwrap();
        enc.finish().unwrap();
        bytes.extend(std::fs::read(&one).unwrap());
    }
    std::fs::write(&gz, bytes).unwrap();
    assert_open_matches(&gz, &want);
    let mut truncated = std::fs::read(&gz).unwrap();
    truncated.truncate(truncated.len() / 3);
    std::fs::write(&gz, truncated).unwrap();
    let results: Vec<_> = ConFrameReader::open(&gz).unwrap().collect();
    let (last, ok) = results.split_last().unwrap();
    assert!(ok.iter().all(Result::is_ok) && !ok.is_empty());
    assert!(last.is_err());
    assert!(ConFrameReader::open(&dir.path().join("missing.con")).is_err());
}

#[cfg(feature = "zstd")]
#[test]
fn open_decodes_zstd() {
    let dir = tempfile::tempdir().unwrap();
    let text = mixed_trajectory().repeat(40);
    let want: Vec<ConFrame> = in_memory(&text).into_iter().map(Result::unwrap).collect();
    let path = dir.path().join("t.con.zst");
    let mut enc = readcon_core::compression::zstd_writer(&path).unwrap();
    enc.write_all(&text).unwrap();
    drop(enc);
    assert_open_matches(&path, &want);
}
