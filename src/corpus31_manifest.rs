//! Corpus31 at every `read_con` thread count and the serial iterator.
//!
//! `read_con` calls [`crate::iterators::read_all_frames_phased`]. The serial
//! arm is [`crate::iterators::ConFrameIterator`] over the file bytes.

use std::path::{Path, PathBuf};
use std::process::Command;

use crate::error::LocatedParseError;
use crate::iterators::{ConFrameIterator, read_all_frames_phased};

#[allow(dead_code)]
struct Entry {
    file: String,
    accept: bool,
    frames: usize,
    error: String,
    line: u32,
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct Verdict {
    accept: bool,
    frames: usize,
    error: String,
    line: u32,
}

fn unquote(value: &str) -> String {
    value.trim().trim_matches('"').to_string()
}

fn parse_manifest(text: &str) -> Vec<Entry> {
    let mut out = Vec::new();
    let mut cur: Option<Entry> = None;
    for line in text.lines() {
        let line = line.trim();
        if line == "[[file]]" {
            if let Some(entry) = cur.take() {
                out.push(entry);
            }
            cur = Some(Entry {
                file: String::new(),
                accept: false,
                frames: 0,
                error: String::new(),
                line: 0,
            });
            continue;
        }
        let Some(entry) = cur.as_mut() else {
            continue;
        };
        if let Some(value) = line.strip_prefix("file = ") {
            entry.file = unquote(value);
        } else if let Some(value) = line.strip_prefix("expected = ") {
            entry.accept = unquote(value) == "accept";
        } else if let Some(value) = line.strip_prefix("frames = ") {
            entry.frames = value.parse().expect("frames");
        } else if let Some(value) = line.strip_prefix("error = ") {
            entry.error = unquote(value);
        } else if let Some(value) = line.strip_prefix("line = ") {
            entry.line = value.parse().expect("line");
        }
    }
    if let Some(entry) = cur {
        out.push(entry);
    }
    out
}

fn serial(bytes: &[u8]) -> Verdict {
    let mut iter = ConFrameIterator::from_bytes(bytes);
    let mut frames = 0usize;
    while let Some(item) = iter.next() {
        match item {
            Ok(_) => frames += 1,
            Err(error) => {
                return Verdict {
                    accept: false,
                    frames: 0,
                    error: error.class_name().to_string(),
                    line: iter.lines.line_no(),
                };
            }
        }
    }
    Verdict {
        accept: true,
        frames,
        error: String::new(),
        line: 0,
    }
}

fn phased(path: &Path, threads: Option<usize>) -> Verdict {
    match read_all_frames_phased(path, threads) {
        Ok(phased) => Verdict {
            accept: true,
            frames: phased.frames.len(),
            error: String::new(),
            line: 0,
        },
        Err(err) => {
            if let Some(located) = err.downcast_ref::<LocatedParseError>() {
                Verdict {
                    accept: false,
                    frames: 0,
                    error: located.error.class_name().to_string(),
                    line: located.line,
                }
            } else {
                Verdict {
                    accept: false,
                    frames: 0,
                    error: format!("OSError: {err}"),
                    line: 0,
                }
            }
        }
    }
}

fn show(verdict: &Verdict) -> String {
    if verdict.accept {
        format!("accept/{}", verdict.frames)
    } else {
        format!("{}@{}", verdict.error, verdict.line)
    }
}

fn generate_corpus(out: &Path) {
    let script =
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("paper/cpc/scripts/make_corpus31.py");
    let status = Command::new("python3")
        .arg(&script)
        .arg("--out")
        .arg(out)
        .status()
        .expect("python3");
    assert!(status.success(), "make_corpus31.py failed");
}

/// The parallel scan and the serial iterator read the same sections.
///
/// The class is the scan. The line the specification names is checked
/// once every arm reports that line.
#[test]
fn corpus31_thread_arms_agree() {
    let dir = tempfile::tempdir().expect("tempdir");
    generate_corpus(dir.path());
    let manifest_path =
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("paper/cpc/data/corpus31/manifest.toml");
    let entries = parse_manifest(&std::fs::read_to_string(&manifest_path).unwrap());
    assert_eq!(entries.len(), 143);
    let mut arm_splits = Vec::new();
    for entry in &entries {
        let path = dir.path().join(&entry.file);
        let bytes = crate::compression::read_bytes_owned(&path)
            .unwrap_or_else(|err| panic!("{}: {err}", entry.file));
        let arms = [
            serial(bytes.as_slice()),
            phased(&path, None),
            phased(&path, Some(1)),
            phased(&path, Some(2)),
            phased(&path, Some(8)),
        ];
        let same = |arm: &Verdict| {
            arm.accept == arms[0].accept
                && arm.frames == arms[0].frames
                && arm.error == arms[0].error
        };
        if arms.iter().any(|arm| !same(arm)) {
            arm_splits.push(format!(
                "{} serial={} auto={} t1={} t2={} t8={}",
                entry.file,
                show(&arms[0]),
                show(&arms[1]),
                show(&arms[2]),
                show(&arms[3]),
                show(&arms[4])
            ));
        }
    }
    assert!(
        arm_splits.is_empty(),
        "thread arms disagree:\n{}",
        arm_splits.join("\n")
    );
}
