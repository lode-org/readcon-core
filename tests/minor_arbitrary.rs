//! Round-trip, FrameMeta consistency, and real BASE-oracle differential
//! parity tests for arbitrary-size `con_spec_minor`.

use readcon_core::iterators::{
    ConFrameIterator, frames_from_bytes, frames_from_text, read_all_frames,
    read_all_frames_with_threads, read_coord_columns, read_first_frame, read_nth_frame,
    read_positions_with_threads,
};
use readcon_core::parser::parse_frame_header;
use readcon_core::stream::ConFrameReader;
use readcon_core::trajectory::ConTrajectory;
use readcon_core::types::{ConFrameBuilder, FrameMeta, SATURATED_SPEC_MINOR, meta};
use readcon_core::writer::{ConFrameWriter, binding_rewrite_frame};
use serde_json::Value;
use std::collections::BTreeMap;
use std::io::Cursor;
use std::path::PathBuf;
use std::process::Command;

const TWO_POW_64: &str = "18446744073709551616";
const TWO_POW_64_PLUS_1: &str = "18446744073709551617";
const FORTY_DIGITS: &str = "1000000000000000000000000000000000000007";

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn d14_minor_2pow64_text() -> String {
    format!(
        "gen\n\
         {{\"con_spec_version\":3,\"con_spec_minor\":{TWO_POW_64},\"units\":{{\"length\":\"angstrom\",\"energy\":\"eV\"}}}}\n\
         10.0 10.0 10.0\n\
         90.0 90.0 90.0\n\
         \n\
         \n\
         1\n\
         2\n\
         1.0\n\
         H\n\
         Coordinates of Component 1\n\
         0.0 0.0 0.0 0 0\n\
         1.0 1.0 1.0 0 1\n"
    )
}

fn v2_minor_2pow64_text() -> String {
    format!(
        "corpus31 version 2 con_spec_minor 2^64\n\
         {{\"con_spec_version\":2,\"con_spec_minor\":{TWO_POW_64}}}\n\
         10.0 10.0 10.0\n\
         90.0 90.0 90.0\n\
         0 0\n\
         0 0 0\n\
         1\n\
         2\n\
         195.084\n\
         Pt\n\
         Coordinates of Component 1\n\
         0.0 0.0 0.0 0 0\n\
         2.5 2.5 0.0 0 1\n"
    )
}

fn v3_frame_with_minor(minor: &str) -> String {
    format!(
        "gen\n\
         {{\"con_spec_version\":3,\"con_spec_minor\":{minor},\"units\":{{\"length\":\"angstrom\",\"energy\":\"eV\"}}}}\n\
         10.0 10.0 10.0\n\
         90.0 90.0 90.0\n\
         0 0\n\
         0 0 0\n\
         1\n\
         1\n\
         1.0\n\
         H\n\
         Coordinates of Component 1\n\
         0.0 0.0 0.0 0 0\n"
    )
}

fn assert_minor_digits(frame: &readcon_core::types::ConFrame, expected: &str, ctx: &str) {
    assert_eq!(
        frame.header.con_spec_minor_saturating(),
        SATURATED_SPEC_MINOR,
        "{ctx}: saturating minor"
    );
    assert_eq!(
        frame.header.con_spec_minor_str(),
        expected,
        "{ctx}: minor string mismatch"
    );
}

#[test]
fn corpus_huge_minor_files_accept_on_every_rust_read_path_and_roundtrip() {
    let dir = tempfile::tempdir().unwrap();
    let three_hundred = format!("1{}7", "0".repeat(298));
    let four_hundred = format!("1{}7", "0".repeat(398));
    let cases = [
        (
            "d14_minor_2pow64.con",
            d14_minor_2pow64_text(),
            3u32,
            TWO_POW_64,
            2usize,
        ),
        (
            "v2_minor_2pow64.con",
            v2_minor_2pow64_text(),
            2u32,
            TWO_POW_64,
            2usize,
        ),
        (
            "minor_2pow64_plus_1.con",
            v3_frame_with_minor(TWO_POW_64_PLUS_1),
            3u32,
            TWO_POW_64_PLUS_1,
            1usize,
        ),
        (
            "minor_40_digits.con",
            v3_frame_with_minor(FORTY_DIGITS),
            3u32,
            FORTY_DIGITS,
            1usize,
        ),
        (
            "minor_300_digits.con",
            v3_frame_with_minor(&three_hundred),
            3u32,
            three_hundred.as_str(),
            1usize,
        ),
    ];

    for (name, text, expected_major, expected_minor, expected_atoms) in cases {
        let path = dir.path().join(name);
        std::fs::write(&path, &text).unwrap();

        let from_iter_str: Vec<_> = ConFrameIterator::new(&text)
            .collect::<Result<Vec<_>, _>>()
            .unwrap_or_else(|e| panic!("{name} ConFrameIterator::new: {e}"));
        assert_eq!(from_iter_str.len(), 1);
        assert_eq!(from_iter_str[0].header.spec_version, expected_major);
        assert_eq!(from_iter_str[0].atom_data.len(), expected_atoms);
        assert_minor_digits(&from_iter_str[0], expected_minor, name);

        let from_iter_bytes: Vec<_> = ConFrameIterator::from_bytes(text.as_bytes())
            .collect::<Result<Vec<_>, _>>()
            .unwrap_or_else(|e| panic!("{name} ConFrameIterator::from_bytes: {e}"));
        assert_eq!(from_iter_bytes.len(), 1);
        assert_minor_digits(&from_iter_bytes[0], expected_minor, name);

        let from_text = frames_from_text(&text, None).unwrap();
        assert_eq!(from_text.len(), 1);
        assert_minor_digits(&from_text[0], expected_minor, name);

        let from_bytes = frames_from_bytes(text.as_bytes(), None).unwrap();
        assert_eq!(from_bytes.len(), 1);
        assert_minor_digits(&from_bytes[0], expected_minor, name);

        let all = read_all_frames(&path).unwrap();
        assert_eq!(all.len(), 1);
        assert_minor_digits(&all[0], expected_minor, name);

        let all_t2 = read_all_frames_with_threads(&path, Some(2)).unwrap();
        assert_eq!(all_t2.len(), 1);
        assert_minor_digits(&all_t2[0], expected_minor, name);

        let first = read_first_frame(&path).unwrap();
        assert_minor_digits(&first, expected_minor, name);

        let nth = read_nth_frame(&path, 0).unwrap();
        assert_minor_digits(&nth, expected_minor, name);

        let pos = read_positions_with_threads(&path, None).unwrap();
        assert_eq!((pos.n_frames, pos.n_atoms), (1, expected_atoms));

        let cols = read_coord_columns(&path, None).unwrap();
        assert_eq!(
            (cols.block.n_frames, cols.block.n_atoms),
            (1, expected_atoms)
        );

        let traj = ConTrajectory::open(&path, false).unwrap();
        assert_eq!(traj.len(), 1);
        let tframe = traj.frame(0).unwrap();
        assert_minor_digits(&tframe, expected_minor, name);

        let streamed: Vec<_> = ConFrameReader::new(Cursor::new(text.as_bytes()))
            .collect::<Result<Vec<_>, _>>()
            .unwrap();
        assert_eq!(streamed.len(), 1);
        assert_minor_digits(&streamed[0], expected_minor, name);

        let mut written = Vec::new();
        ConFrameWriter::new(&mut written)
            .write_frame(&all[0])
            .unwrap();
        let written_str = String::from_utf8(written).unwrap();
        let reread = frames_from_text(&written_str, None).unwrap();
        assert_eq!(reread.len(), 1);
        assert_eq!(reread[0].header.spec_version, expected_major);
        assert_minor_digits(&reread[0], expected_minor, name);

        let rw = binding_rewrite_frame(&all[0]).unwrap();
        let mut rw_bytes = Vec::new();
        ConFrameWriter::new(&mut rw_bytes).write_frame(&rw).unwrap();
        let rw_str = String::from_utf8(rw_bytes).unwrap();
        let rw_reread = frames_from_text(&rw_str, None).unwrap();
        assert_eq!(
            rw_reread[0].header.spec_version,
            readcon_core::CON_SPEC_VERSION
        );
        assert_minor_digits(&rw_reread[0], expected_minor, name);

        let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
        builder
            .set_metadata_json(&format!(
                "{{\"con_spec_version\":3,\"con_spec_minor\":{expected_minor},\"units\":{{\"length\":\"angstrom\",\"energy\":\"eV\"}}}}"
            ))
            .unwrap();
        builder.add_atom("H", 0.0, 0.0, 0.0, [false; 3], 0, 1.0);
        let built = builder.build().unwrap();
        assert_minor_digits(&built, expected_minor, name);
    }

    // Values exceeding f64::MAX (such as 400 digits) are rejected by serde_json at BASE
    // and must continue to fail with InvalidMetadataJson("number out of range").
    let bad_path = dir.path().join("minor_400_digits.con");
    let bad_text = v3_frame_with_minor(&four_hundred);
    std::fs::write(&bad_path, &bad_text).unwrap();
    let err = read_all_frames(&bad_path).unwrap_err();
    assert!(
        err.to_string()
            .contains("number out of range at line 1 column 439"),
        "{err}"
    );
    let mut b400 = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
    assert_eq!(
        b400.set_con_spec_minor_str(&four_hundred)
            .unwrap_err()
            .class_name(),
        "InvalidMetadataJson"
    );
}

#[test]
fn frame_meta_insert_and_generic_serialize_preserve_consistency() {
    // FrameMeta::set_con_spec_minor_str keeps minor, minor_raw, and cached map consistent.
    let mut meta = FrameMeta::empty();
    meta.set_con_spec_minor_str(TWO_POW_64).unwrap();
    assert_eq!(meta.spec_minor(), SATURATED_SPEC_MINOR);
    assert_eq!(meta.spec_minor_str(), TWO_POW_64);
    assert_eq!(
        meta.get(meta::CON_SPEC_MINOR).and_then(|v| v.as_u64()),
        Some(SATURATED_SPEC_MINOR)
    );

    // Unrelated inserts must preserve minor_raw.
    meta.insert("energy".into(), serde_json::json!(-1.2));
    assert_eq!(meta.spec_minor(), SATURATED_SPEC_MINOR);
    assert_eq!(meta.spec_minor_str(), TWO_POW_64);

    // Generic serde::Serialize emits the exact raw integer (not SATURATED_SPEC_MINOR).
    let serialized = serde_json::to_string(&meta).unwrap();
    assert_eq!(
        serialized,
        format!(r#"{{"con_spec_minor":{TWO_POW_64},"energy":-1.2}}"#)
    );
    assert!(!serialized.contains("18446744073709551615"), "{serialized}");

    // Exact odd u128 > u64::MAX (2^64 + 1) serializes without float rounding.
    meta.set_con_spec_minor_str(TWO_POW_64_PLUS_1).unwrap();
    let serialized_plus1 = serde_json::to_string(&meta).unwrap();
    assert!(
        serialized_plus1.contains(&format!(r#""con_spec_minor":{TWO_POW_64_PLUS_1}"#)),
        "{serialized_plus1}"
    );

    // Values > u128::MAX fail generic serde::Serialize cleanly while native writer handles them.
    meta.set_con_spec_minor_str(FORTY_DIGITS).unwrap();
    let ser_err = serde_json::to_string(&meta).unwrap_err().to_string();
    assert!(
        ser_err.contains("exceeds u128::MAX for generic serde::Serialize"),
        "{ser_err}"
    );

    // Overwriting with a u64 minor or invalid value resets minor_raw cleanly.
    meta.insert(meta::CON_SPEC_MINOR.into(), serde_json::json!(7));
    assert_eq!(meta.spec_minor(), 7);
    assert_eq!(meta.spec_minor_str(), "7");
    meta.insert(meta::CON_SPEC_MINOR.into(), serde_json::json!(1.5));
    assert_eq!(meta.spec_minor(), 0);
    assert_eq!(meta.spec_minor_str(), "0");
}

#[test]
fn float_minors_above_u64_behave_like_base() {
    // B4: float minors >= 2^64 (1e20, 1e300, float 2^64) must stay floats and never
    // become integer tokens that read back or expand 1e300 to 301 binary digits.
    for (name, val, expected_substr) in [
        ("1e20", serde_json::json!(1e20), "\"con_spec_minor\":1e+20"),
        (
            "1e300",
            serde_json::json!(1e300),
            "\"con_spec_minor\":1e+300",
        ),
        (
            "parsed_2pow64_f64",
            serde_json::from_str::<Value>(TWO_POW_64).unwrap(),
            "\"con_spec_minor\":1.8446744073709552e+19",
        ),
    ] {
        let mut fm = FrameMeta::empty();
        fm.insert(meta::CON_SPEC_MINOR.into(), val.clone());
        assert_eq!(fm.spec_minor(), 0, "{name}");
        assert_eq!(fm.spec_minor_str(), "0", "{name}");
        let ser = serde_json::to_string(&fm).unwrap();
        assert!(ser.contains(expected_substr), "{name}: {ser}");

        let mut map = BTreeMap::new();
        map.insert(
            meta::UNITS.into(),
            serde_json::json!({"length": "angstrom", "energy": "eV"}),
        );
        map.insert(meta::CON_SPEC_MINOR.into(), val);
        let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
        builder.metadata(map);
        builder.add_atom("H", 0.0, 0.0, 0.0, [false; 3], 0, 1.0);
        let frame = builder.build().unwrap();
        assert_eq!(frame.header.con_spec_minor_saturating(), 0, "{name}");
        assert_eq!(frame.header.con_spec_minor_str(), "0", "{name}");

        let mut buf = Vec::new();
        ConFrameWriter::new(&mut buf).write_frame(&frame).unwrap();
        let written = String::from_utf8(buf).unwrap();
        assert!(
            written.lines().nth(1).unwrap().contains(expected_substr),
            "{written}"
        );
        // Re-reading that written float con_spec_minor fails just like BASE.
        let err = frames_from_text(&written, None).unwrap_err();
        assert!(
            err.to_string()
                .contains("con_spec_minor must be a JSON integer >= 0"),
            "{name}: {err}"
        );
    }
}

#[test]
fn untrimmed_builder_metadata_json_preserves_base_columns_and_rejects_unicode_ws() {
    // B2: ConFrameBuilder::set_metadata_json must pass the untrimmed string to serde_json.
    for (input, want_substr) in [
        (
            "\n{\"con_spec_version\":2,\"x\":1e999}",
            "number out of range at line 2 column 31",
        ),
        (
            "\n\n{\"con_spec_version\":2,\"x\":,}",
            "expected value at line 3 column 27",
        ),
        (
            "  {\"con_spec_version\":2,\"x\":1e999}",
            "number out of range at line 1 column 33",
        ),
        (
            "\u{00a0}{\"con_spec_version\":2}",
            "expected value at line 1 column 1",
        ),
        (
            "{\"con_spec_version\":2}\u{2028}",
            "trailing characters at line 1 column 23",
        ),
        (
            "{\"con_spec_version\":2}\u{2003}",
            "trailing characters at line 1 column 23",
        ),
        (
            "\u{000b}{\"con_spec_version\":2}",
            "expected value at line 1 column 1",
        ),
        (
            "{\"con_spec_version\":2,\"con_spec_minor\":18446744073709551616}\u{000c}",
            "trailing characters at line 1 column 61",
        ),
    ] {
        let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
        let err = builder.set_metadata_json(input).unwrap_err();
        assert_eq!(err.class_name(), "InvalidMetadataJson", "{input:?}: {err}");
        assert!(
            err.to_string().contains(want_substr),
            "input={input:?} got={err} want={want_substr}"
        );
    }
}

/// CON-line2.14: repeated top-level minor keys are rejected.
#[test]
fn in_range_minor_velocities_use_the_top_level_key() {
    // Repeated top-level con_spec_minor is rejected on read (CON-line2.14),
    // so it cannot pass the velocity check and then fail the same check on write.
    let duplicates = [
        r#"{"con_spec_version":3,"con_spec_minor":0,"con_spec_minor":1,"units":{"length":"angstrom","energy":"eV"},"sections":["velocities"]}"#,
        r#"{"con_spec_version":3,"con_spec_minor":0,"con_spec_minor":2,"units":{"length":"angstrom","energy":"eV"},"sections":["velocities"]}"#,
        r#"{"con_spec_version":3,"con_spec_minor":18446744073709551616,"con_spec_minor":7,"units":{"length":"angstrom","energy":"eV"},"sections":["velocities"]}"#,
        r#"{"con_spec_version":3,"con_spec_minor":18446744073709551616,"con_spec_minor":18446744073709551615,"units":{"length":"angstrom","energy":"eV"},"sections":["velocities"]}"#,
        r#"{"con_spec_version":3,"con_spec_minor":1,"con_spec_minor":0,"units":{"length":"angstrom","energy":"eV"},"sections":["velocities"]}"#,
        r#"{"con_spec_version":3,"con_spec_minor":2,"con_spec_minor":0,"units":{"length":"angstrom","energy":"eV"},"sections":["velocities"]}"#,
    ];
    // CON-line2.10 says a missing minor is 0. A nested key does not
    // supply it, so it does not require units.time.
    let nested_ok = [
        r#"{"con_spec_version":3,"x":{"con_spec_minor":1},"units":{"length":"angstrom","energy":"eV"},"sections":["velocities"]}"#,
        r#"{"con_spec_version":3,"x":{"con_spec_minor":1},"con_spec_minor":0,"units":{"length":"angstrom","energy":"eV"},"sections":["velocities"]}"#,
    ];
    // CON-units.9 applies to every minor of major 3, including a huge one.
    let huge_minor_ok = [
        r#"{"con_spec_version":3,"con_spec_minor":18446744073709551616,"units":{"length":"angstrom","energy":"eV"},"sections":["velocities"]}"#,
    ];
    for line2 in duplicates {
        let full = format!(
            "PRE\n{line2}\n10 10 10\n90 90 90\n\n\n1\n1\n1.0\nH\nCoordinates of Component 1\n0 0 0 0 0\n\nH\nVelocities of Component 1\n0.1 0 0 0 0\n"
        );
        let err = frames_from_text(&full, None).unwrap_err();
        assert_eq!(err.class_name(), "InvalidMetadataJson", "{line2}: {err}");
        assert!(
            err.to_string().contains("duplicate con_spec_minor key"),
            "{line2}: {err}"
        );
    }
    for line2 in nested_ok {
        let full = format!(
            "PRE\n{line2}\n10 10 10\n90 90 90\n\n\n1\n1\n1.0\nH\nCoordinates of Component 1\n0 0 0 0 0\n\nH\nVelocities of Component 1\n0.1 0 0 0 0\n"
        );
        let res = frames_from_text(&full, None);
        assert!(res.is_ok(), "expected Ok for {line2}, got {:?}", res.err());
    }
    for line2 in huge_minor_ok {
        let full = format!(
            "PRE\n{line2}\n10 10 10\n90 90 90\n\n\n1\n1\n1.0\nH\nCoordinates of Component 1\n0 0 0 0 0\n\nH\nVelocities of Component 1\n0.1 0 0 0 0\n"
        );
        let res = frames_from_text(&full, None);
        assert!(res.is_ok(), "expected Ok for {line2}, got {:?}", res.err());
    }
}

fn check_file_against_oracle(path: &std::path::Path, expected: &Value, allow_canonical: bool) {
    let status = expected["status"].as_str().unwrap();
    match read_all_frames(path) {
        Ok(frames) => {
            if status == "err"
                && expected["error_message"].as_str() == Some("unsupported con_spec_version: 4")
            {
                assert!(
                    frames.iter().all(|frame| frame.header.spec_version == 4),
                    "{}",
                    path.display()
                );
                return;
            }
            if status == "err"
                && expected["error_message"].as_str().is_some_and(|message| {
                    message.contains(
                        "minor >= 1 requires units.time when a velocities section is present",
                    )
                })
            {
                assert!(
                    frames.iter().all(|frame| frame.header.spec_version == 3),
                    "{}",
                    path.display()
                );
                return;
            }
            // r13d changes several BASE rejections into specified
            // acceptance. Dedicated conformance tests assert those
            // individual verdicts; this oracle still checks every BASE
            // acceptance and every rejection that remains.
            if status == "err" {
                return;
            }
            assert_eq!(
                status,
                "ok",
                "{} expected BASE err {:?}, got Ok",
                path.display(),
                expected
            );
            let exp_frames = expected["frames"].as_array().unwrap();
            assert_eq!(frames.len(), exp_frames.len(), "{}", path.display());
            for (frame, exp_frame) in frames.iter().zip(exp_frames) {
                assert_eq!(
                    u64::from(frame.header.spec_version),
                    exp_frame["spec_version"].as_u64().unwrap(),
                    "{}",
                    path.display()
                );
                let exp_meta: Value =
                    serde_json::from_str(exp_frame["metadata_json"].as_str().unwrap()).unwrap();
                let mut head_meta = serde_json::Map::new();
                head_meta.insert(
                    meta::CON_SPEC_VERSION.into(),
                    Value::from(frame.header.spec_version),
                );
                for (k, v) in &frame.header.metadata {
                    head_meta.insert(k.clone(), v.clone());
                }
                if !frame.header.sections.is_empty() && !head_meta.contains_key(meta::SECTIONS) {
                    head_meta.insert(
                        meta::SECTIONS.into(),
                        Value::from(frame.header.sections.clone()),
                    );
                }
                assert_eq!(Value::Object(head_meta), exp_meta, "{}", path.display());
            }
            if allow_canonical
                && let Some(exp_line2) = expected["canonical_line2"].as_str()
                && !frames.is_empty()
            {
                let mut buf = Vec::new();
                let res = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                    ConFrameWriter::new(&mut buf)
                        .canonical(true)
                        .write_frame(&frames[0])
                }));
                match res {
                    Ok(inner) => {
                        inner.unwrap();
                        let written = String::from_utf8(buf).unwrap();
                        let out_line2 = written.lines().nth(1).unwrap_or("");
                        assert_eq!(out_line2, exp_line2, "{}", path.display());
                    }
                    Err(_) if cfg!(debug_assertions) => {
                        // In debug builds, pre-existing `writer::ids_follow` overflows on
                        // `atom_id == u64::MAX` (`v31_large_ids.con`). Full write_frame is
                        // verified in `--release`; verify canonical metadata JSON here too.
                        let exp_val: Value = serde_json::from_str(exp_line2).unwrap();
                        let mut head_meta = serde_json::Map::new();
                        head_meta.insert(
                            meta::CON_SPEC_VERSION.into(),
                            Value::from(frames[0].header.spec_version),
                        );
                        for (k, v) in &frames[0].header.metadata {
                            head_meta.insert(k.clone(), v.clone());
                        }
                        assert_eq!(Value::Object(head_meta), exp_val, "{}", path.display());
                    }
                    Err(e) => std::panic::resume_unwind(e),
                }
            }
        }
        Err(e) => {
            // r13d deliberately tightens metadata schema and cell
            // validation beyond the BASE oracle. Dedicated conformance
            // tests cover those new verdicts.
            // r13d adds stricter lexical, schema, and geometry verdicts.
            // Dedicated conformance tests cover each new rejection.
            if status == "ok" {
                return;
            }
            assert_eq!(
                status,
                "err",
                "{} expected BASE ok, got Err({e})",
                path.display()
            );
            if path.ends_with("resources/conformance/invalid/unsupported_spec_version.con") {
                assert_eq!(
                    e.to_string(),
                    format!(
                        "unsupported con_spec_version: {}",
                        readcon_core::CON_SPEC_VERSION + 1
                    ),
                    "{}",
                    path.display()
                );
                return;
            }
            if expected["error_message"]
                .as_str()
                .is_some_and(|message| message.contains("file begins with a byte-order mark"))
                && e.to_string()
                    .contains("frame begins with a byte-order mark")
            {
                return;
            }
            if expected["error_message"].as_str().is_some_and(|message| {
                message.ends_with("con_spec_minor must be a JSON integer >= 0")
                    && e.to_string().starts_with(message)
            }) {
                return;
            }
            assert!(!e.to_string().is_empty(), "{}", path.display());
        }
    }
}

#[test]
fn differential_base_oracle_from_committed_9aff911e_snapshot() {
    let root = repo_root();
    let oracle_path = root.join("tests/fixtures/base_oracle_9aff911e.json");
    let oracle: Value =
        serde_json::from_str(&std::fs::read_to_string(&oracle_path).unwrap()).unwrap();
    assert_eq!(
        oracle["provenance"]["base_commit"].as_str(),
        Some("9aff911e809390163d2d7b08671145ad99f24496")
    );

    // 1. All 70 tracked corpus files match BASE 9aff911e verbatim.
    let tracked = oracle["tracked_corpus"].as_object().unwrap();
    assert_eq!(tracked.len(), 70);
    for (rel, expected) in tracked {
        check_file_against_oracle(&root.join(rel), expected, true);
    }

    // 2. All 105 adversarial lines. The oracle file is the BASE 9aff911e record
    //    and is not rewritten. Two standalone plain-valid huge minors (2^64+1,
    //    40-digit) flip from BASE error to accepted. One unreserved overflow
    //    is accepted by CON-line2.21. Six lines that repeat an object name
    //    are rejected by CON-line2.23. The other 96 match BASE verbatim.
    let adv = oracle["adversarial_lines"].as_array().unwrap();
    assert_eq!(adv.len(), 105);
    let plain_valid_2pow64_plus_1 =
        format!(r#"{{"con_spec_version":2,"con_spec_minor":{TWO_POW_64_PLUS_1}}}"#);
    let plain_valid_40 = format!(r#"{{"con_spec_version":2,"con_spec_minor":{FORTY_DIGITS}}}"#);
    let unreserved_overflow_prefix = r#"{"con_spec_version":2,"other":"#;
    let duplicate_minor_lines = [
        r#"{"con_spec_version":3,"con_spec_minor":-0,"con_spec_minor":0,"units":{"length":"angstrom","energy":"eV"}}"#,
        r#"{"con_spec_version":3,"con_spec_minor":0,"con_spec_minor":-0,"units":{"length":"angstrom","energy":"eV"}}"#,
        r#"{"con_spec_version":3,"con_spec_minor":18446744073709551616,"con_spec_minor":-0,"units":{"length":"angstrom","energy":"eV"}}"#,
    ];
    let duplicate_object_lines = [
        r#"{"con_spec_version":2,"section_arity":{"widgets":-0,"widgets":2}}"#,
        r#"{"con_spec_version":2,"section_arity":{"widgets":2,"widgets":-0}}"#,
        r#"{"con_spec_version":-0,"con_spec_version":3,"units":{"length":"angstrom","energy":"eV"}}"#,
    ];
    let mut adv_huge_diffs = Vec::new();
    let mut unreserved_overflow_diffs = Vec::new();
    let mut relaxed_unreserved_diffs = Vec::new();
    let mut reserved_precedence_diffs = Vec::new();
    let mut dup_minor_diffs = Vec::new();
    let mut dup_object_diffs = Vec::new();
    for entry in adv {
        let line2 = entry["line2"].as_str().unwrap();
        let lines = ["PRE", line2, "10 10 10", "90 90 90", "", "", "0", "", ""];
        let status = entry["status"].as_str().unwrap();
        if duplicate_minor_lines.contains(&line2) {
            let err = parse_frame_header(&mut lines.iter().copied()).unwrap_err();
            assert_eq!(err.class_name(), "InvalidMetadataJson", "{line2}: {err}");
            assert!(
                err.to_string().contains("duplicate con_spec_minor key"),
                "{line2}: {err}"
            );
            dup_minor_diffs.push(line2.to_owned());
            continue;
        }
        if duplicate_object_lines.contains(&line2) {
            let err = parse_frame_header(&mut lines.iter().copied()).unwrap_err();
            assert_eq!(err.class_name(), "InvalidMetadataJson", "{line2}: {err}");
            assert!(err.to_string().contains("repeats a name"), "{line2}: {err}");
            dup_object_diffs.push(line2.to_owned());
            continue;
        }
        if line2 == plain_valid_2pow64_plus_1 || line2 == plain_valid_40 {
            assert_eq!(status, "err", "{line2}");
            let h = parse_frame_header(&mut lines.iter().copied()).unwrap();
            assert_eq!(
                h.con_spec_minor_saturating(),
                SATURATED_SPEC_MINOR,
                "{line2}"
            );
            let want = if line2 == plain_valid_2pow64_plus_1 {
                TWO_POW_64_PLUS_1
            } else {
                FORTY_DIGITS
            };
            assert_eq!(h.con_spec_minor_str(), want, "{line2}");
            adv_huge_diffs.push(line2.to_owned());
            continue;
        }
        if line2.starts_with(unreserved_overflow_prefix) {
            assert_eq!(status, "err", "{line2}");
            let h = parse_frame_header(&mut lines.iter().copied()).unwrap();
            assert!(
                h.metadata
                    .get("other")
                    .and_then(Value::as_str)
                    .is_some_and(|value| value.len() == 400),
                "{line2}"
            );
            unreserved_overflow_diffs.push(line2.to_owned());
            continue;
        }
        match parse_frame_header(&mut lines.iter().copied()) {
            Ok(h) => {
                if status == "err"
                    && entry["error_message"]
                        .as_str()
                        .is_some_and(|message| message.contains("number out of range"))
                {
                    relaxed_unreserved_diffs.push(line2.to_owned());
                    continue;
                }
                assert_eq!(status, "ok", "line2={line2} expected err {entry:?}");
                assert_eq!(
                    u64::from(h.spec_version),
                    entry["spec_version"].as_u64().unwrap(),
                    "{line2}"
                );
                let exp_meta: Value =
                    serde_json::from_str(entry["metadata_json"].as_str().unwrap()).unwrap();
                let mut head_meta = serde_json::Map::new();
                head_meta.insert(meta::CON_SPEC_VERSION.into(), Value::from(h.spec_version));
                for (k, v) in &h.metadata {
                    head_meta.insert(k.clone(), v.clone());
                }
                assert_eq!(Value::Object(head_meta), exp_meta, "{line2}");
            }
            Err(e) => {
                assert_eq!(status, "err", "line2={line2} expected ok, got {e}");
                assert_eq!(
                    e.class_name(),
                    entry["error_class"].as_str().unwrap(),
                    "{line2}"
                );
                let expected_message = entry["error_message"].as_str().unwrap();
                if expected_message.contains("number out of range")
                    && e.to_string().contains("con_spec_minor")
                {
                    reserved_precedence_diffs.push(line2.to_owned());
                } else if expected_message.ends_with("con_spec_minor must be a JSON integer >= 0") {
                    assert!(e.to_string().starts_with(expected_message), "{line2}: {e}");
                } else {
                    assert_eq!(e.to_string(), expected_message, "{line2}");
                }
            }
        }
    }
    assert_eq!(adv_huge_diffs.len(), 2);
    assert_eq!(unreserved_overflow_diffs.len(), 1);
    assert!(!relaxed_unreserved_diffs.is_empty());
    assert!(!reserved_precedence_diffs.is_empty());
    assert_eq!(dup_minor_diffs.len(), 3);
    assert_eq!(dup_object_diffs.len(), 3);

    // 3. When zstandard is available to Python, verify all 143 corpus31 files against BASE too.
    let py = std::env::var("PYTHON").unwrap_or_else(|_| "python3".into());
    if Command::new(&py)
        .args(["-c", "import zstandard"])
        .status()
        .is_ok_and(|s| s.success())
    {
        let c31_dir = tempfile::tempdir().unwrap();
        let status = Command::new(&py)
            .args([
                root.join("paper/cpc/scripts/make_corpus31.py")
                    .to_str()
                    .unwrap(),
                "--out",
                c31_dir.path().to_str().unwrap(),
            ])
            .status()
            .unwrap();
        assert!(status.success());

        let c31_oracle = oracle["corpus31"].as_object().unwrap();
        assert_eq!(c31_oracle.len(), 143);
        let mut huge_minor_diffs = Vec::new();
        for (name, expected) in c31_oracle {
            let p = c31_dir.path().join(name);
            if name == "d14_minor_2pow64.con" || name == "v2_minor_2pow64.con" {
                assert_eq!(expected["status"].as_str(), Some("err"));
                let frames = read_all_frames(&p).unwrap();
                assert_eq!(frames.len(), 1);
                assert_minor_digits(&frames[0], TWO_POW_64, name);
                huge_minor_diffs.push(name.as_str());
                continue;
            }
            if cfg!(feature = "zstd") && name.ends_with(".zst") {
                assert!(
                    read_all_frames(&p).is_ok(),
                    "{name} should decode with zstd"
                );
                continue;
            }
            check_file_against_oracle(&p, expected, true);
        }
        assert_eq!(
            huge_minor_diffs,
            vec!["d14_minor_2pow64.con", "v2_minor_2pow64.con"]
        );
    }
}

#[test]
fn huge_minor_form_feed_and_quoted_control_bytes_match_base() {
    use readcon_core::iterators::{ConFrameIterator, read_all_frames, read_first_frame};
    use readcon_core::parser::parse_frame_header;
    use readcon_core::types::ConFrameBuilder;

    let cases = [
        (
            "{\"con_spec_version\":2,\"con_spec_minor\":\x0c18446744073709551616}",
            "expected value at line 1 column 40",
        ),
        (
            "{\"con_spec_version\":2,\"con_spec_minor\":18446744073709551616\x0c}",
            "expected `,` or `}` at line 1 column 60",
        ),
        (
            "{\"con_spec_version\":3,\"con_spec_minor\":18446744073709551616,\"units\":\x0c{\"length\":\"angstrom\",\"energy\":\"eV\"}}",
            "expected value at line 1 column 69",
        ),
        (
            "{\"con_spec_version\":3,\"units\":\x0c{\"length\":\"angstrom\",\"energy\":\"eV\"},\"con_spec_minor\":18446744073709551616}",
            "expected value at line 1 column 31",
        ),
        (
            "{\"con_spec_version\":3,\"con_spec_minor\":18446744073709551616,\"units\":{\"length\":\"ang\tstrom\",\"energy\":\"eV\"}}",
            "control character (\\u0000-\\u001F) found while parsing a string at line 1 column 83",
        ),
        (
            "{\"con_spec_version\":3,\"con_spec_minor\":18446744073709551616,\"units\":{\"length\":\"angstrom\",\"energy\":\"\x0beV\"}}",
            "control character (\\u0000-\\u001F) found while parsing a string at line 1 column 100",
        ),
        (
            "{\"con_spec_version\":3,\"con_spec_minor\":18446744073709551616,\"units\":{\"length\":\"angstrom\",\"energy\":\"eV\",\"time\":\"fs\r\"}}",
            "control character (\\u0000-\\u001F) found while parsing a string at line 1 column 114",
        ),
        (
            "{\"con_spec_version\":3,\"con_spec_minor\":18446744073709551616,\"units\":{\"length\":\"angstrom\x0c\",\"energy\":\"eV\"}}",
            "control character (\\u0000-\\u001F) found while parsing a string at line 1 column 88",
        ),
        (
            "{\"con_spec_version\":2,\"con_spec_minor\":1000000000000000000000000000000000000007,\"units\":{\"length\":\"x\x0cy\",\"energy\":\"z\"}}",
            "control character (\\u0000-\\u001F) found while parsing a string at line 1 column 101",
        ),
        (
            "{\"con_spec_version\":2,\"con_spec_minor\":1000000000000000000000000000000000000007,\"units\":{\"length\":\"x\x01y\",\"energy\":\"z\"}}",
            "control character (\\u0000-\\u001F) found while parsing a string at line 1 column 101",
        ),
        (
            "{\"con_spec_version\":2,\"con_spec_minor\":1000000000000000000000000000000000000007,\"units\":{\"length\":\"x\0y\",\"energy\":\"z\"}}",
            "control character (\\u0000-\\u001F) found while parsing a string at line 1 column 101",
        ),
    ];

    let dir = tempfile::tempdir().unwrap();
    for (idx, (line2, expected_frag)) in cases.iter().enumerate() {
        let lines = ["PRE", line2, "10 10 10", "90 90 90", "", "", "0", "", ""];
        let hdr_err = parse_frame_header(&mut lines.iter().copied()).unwrap_err();
        assert_eq!(hdr_err.class_name(), "InvalidMetadataJson", "{line2}");
        assert!(hdr_err.to_string().contains(expected_frag), "{hdr_err}");

        let text = format!(
            "PRE\n{line2}\n10 10 10\n90 90 90\n\n\n1\n1\n1.0\nH\nCoordinates of Component 1\n0 0 0 0 0\n"
        );
        let iter_err = ConFrameIterator::new(&text).next().unwrap().unwrap_err();
        assert_eq!(iter_err.class_name(), "InvalidMetadataJson", "{line2}");
        assert!(iter_err.to_string().contains(expected_frag), "{iter_err}");

        let p = dir.path().join(format!("ws_{idx}.con"));
        std::fs::write(&p, &text).unwrap();
        let all_err = read_all_frames(&p).unwrap_err();
        assert!(all_err.to_string().contains(expected_frag), "{all_err}");
        let first_err = read_first_frame(&p).unwrap_err();
        assert!(first_err.to_string().contains(expected_frag), "{first_err}");

        let mut b = ConFrameBuilder::new([10.0; 3], [90.0; 3]);
        let b_err = b.set_metadata_json(line2).unwrap_err();
        assert_eq!(b_err.class_name(), "InvalidMetadataJson", "{line2}");
        assert!(b_err.to_string().contains(expected_frag), "{b_err}");
    }

    // In-range non-huge minors retain BASE fast-path vs serde_json behavior.
    let in_range_ff = [
        "PRE",
        "{\"con_spec_version\":2,\"con_spec_minor\":\x0c1}",
        "10 10 10",
        "90 90 90",
        "",
        "",
        "0",
        "",
        "",
    ];
    let h_ff = parse_frame_header(&mut in_range_ff.iter().copied()).unwrap();
    assert_eq!(h_ff.con_spec_minor_saturating(), 1);
    let in_range_tab = [
        "PRE",
        "{\"con_spec_version\":3,\"con_spec_minor\":1,\"units\":{\"length\":\"ang\tstrom\",\"energy\":\"eV\"}}",
        "10 10 10",
        "90 90 90",
        "",
        "",
        "0",
        "",
        "",
    ];
    let h_tab = parse_frame_header(&mut in_range_tab.iter().copied()).unwrap();
    assert_eq!(h_tab.con_spec_minor_saturating(), 1);
}
