//! The published metadata schema (schema/con-metadata.schema.json) accepts
//! every metadata line the reference writer emits and rejects the invalid
//! shapes the spec calls out.
mod common;
use readcon_core::iterators::ConFrameIterator;
use readcon_core::writer::ConFrameWriter;
use std::fs;
use std::path::Path;

fn schema_validator() -> jsonschema::Validator {
    let schema_path = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("schema")
        .join("con-metadata.schema.json");
    let schema_text = fs::read_to_string(schema_path).expect("schema file readable");
    let schema: serde_json::Value =
        serde_json::from_str(&schema_text).expect("schema is valid JSON");
    jsonschema::validator_for(&schema).expect("schema compiles as draft 2020-12")
}

fn assert_valid(validator: &jsonschema::Validator, doc: &str) {
    let instance: serde_json::Value = serde_json::from_str(doc).expect("instance parses");
    assert!(
        validator.is_valid(&instance),
        "expected schema acceptance for {doc}"
    );
}

fn assert_invalid(validator: &jsonschema::Validator, doc: &str) {
    let instance: serde_json::Value = serde_json::from_str(doc).expect("instance parses");
    assert!(
        !validator.is_valid(&instance),
        "expected schema rejection for {doc}"
    );
}

#[test]
fn spec_examples_validate() {
    let v = schema_validator();
    // Minimal v2 (spec: Version 2+ files)
    assert_valid(&v, r#"{"con_spec_version":2}"#);
    // Declared sections + validation mode (spec: Section declaration)
    assert_valid(
        &v,
        r#"{"con_spec_version":2,"sections":["velocities","forces"],"validate":true}"#,
    );
    // Frame topology (spec: bonds)
    assert_valid(
        &v,
        r#"{"con_spec_version":2,"bonds":[[0,1],[0,2],{"i":1,"j":2,"order":1}]}"#,
    );
    // v3 with required units and recommended keys (spec: Examples)
    assert_valid(
        &v,
        r#"{"con_spec_version":3,"generator":"eOn 3.1","units":{"length":"angstrom","energy":"eV"},"frame_index":7,"energy":-42.5,"pbc":[true,true,false]}"#,
    );
    // storage_dtypes with hosted element types (spec: Storage dtypes)
    assert_valid(
        &v,
        r#"{"con_spec_version":3,"units":{"length":"angstrom","energy":"eV"},"storage_dtypes":{"positions":"float32","atom_ids":"uint64"}}"#,
    );
    // Unknown keys are permitted and preserved
    assert_valid(&v, r#"{"con_spec_version":2,"x_custom":{"anything":[1,2]}}"#);
}

#[test]
fn spec_violations_rejected() {
    let v = schema_validator();
    // v3 requires units with length and energy
    assert_invalid(&v, r#"{"con_spec_version":3}"#);
    assert_invalid(
        &v,
        r#"{"con_spec_version":3,"units":{"length":"angstrom"}}"#,
    );
    // Unsupported spec versions
    assert_invalid(&v, r#"{"con_spec_version":1}"#);
    assert_invalid(&v, r#"{"con_spec_version":4}"#);
    // pbc must have exactly three booleans
    assert_invalid(&v, r#"{"con_spec_version":2,"pbc":[true,true]}"#);
    // Dtypes without a host are rejected in storage_dtypes
    assert_invalid(
        &v,
        r#"{"con_spec_version":3,"units":{"length":"angstrom","energy":"eV"},"storage_dtypes":{"positions":"bfloat16"}}"#,
    );
    // bonds entries are pairs or {i, j} objects
    assert_invalid(&v, r#"{"con_spec_version":2,"bonds":[[0]]}"#);
}

#[test]
fn reference_writer_output_validates() {
    let v = schema_validator();
    for name in [
        "tiny_cuh2.con",
        "tiny_cuh2.convel",
        "tiny_cuh2_forces.con",
        "tiny_multi_cuh2.con",
    ] {
        let fdat = fs::read_to_string(test_case!(name)).expect("test file readable");
        let frames: Vec<_> = ConFrameIterator::new(&fdat)
            .map(|r| r.expect("test file parses"))
            .collect();
        assert!(!frames.is_empty());

        let mut buffer: Vec<u8> = Vec::new();
        {
            let mut writer = ConFrameWriter::new(&mut buffer);
            writer.extend(frames.iter()).expect("write to buffer");
        }
        let written = String::from_utf8(buffer).expect("writer output is UTF-8");

        // Every frame's line 2 the writer emits must satisfy the schema.
        let mut validated = 0;
        for frame in ConFrameIterator::new(&written).map(|r| r.expect("roundtrip parses")) {
            let line = frame.header.prebox_header.metadata_line();
            if line.trim_start().starts_with('{') {
                assert_valid(&v, line);
                validated += 1;
            }
        }
        assert!(validated > 0, "{name}: writer emitted no JSON metadata line");
    }
}
