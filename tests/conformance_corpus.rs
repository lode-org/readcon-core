//! Clause-keyed CON conformance corpus.
//!
//! Reads `resources/conformance/manifest.toml` and checks each fixture:
//! valid files parse (with optional column-4 `expect_fixed`) and match the
//! sibling JSON under `resources/conformance/golden/`; invalid files yield
//! the named [`ParseError`] variant and must not have a golden. Clause
//! strings must appear in `docs/orgmode/spec.org`. A missing golden for a
//! valid id fails; an extra file in `golden/` fails.

use readcon_core::error::ParseError;
use readcon_core::iterators::ConFrameIterator;
use readcon_core::types::ConFrame;
use std::collections::BTreeSet;
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Kind {
    Valid,
    Invalid,
}

#[derive(Debug)]
struct Case {
    id: String,
    path: String,
    clause: String,
    kind: Kind,
    error: Option<String>,
    expect_fixed: Option<[bool; 3]>,
}

fn corpus_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("resources")
        .join("conformance")
}

fn spec_org() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("docs")
        .join("orgmode")
        .join("spec.org")
}

fn variant_name(err: &ParseError) -> &'static str {
    match err {
        ParseError::IncompleteHeader => "IncompleteHeader",
        ParseError::IncompleteFrame => "IncompleteFrame",
        ParseError::IncompleteVelocitySection => "IncompleteVelocitySection",
        ParseError::InvalidVectorLength { .. } => "InvalidVectorLength",
        ParseError::InvalidNumberFormat(_) => "InvalidNumberFormat",
        ParseError::MissingSpecVersion => "MissingSpecVersion",
        ParseError::UnsupportedSpecVersion(_) => "UnsupportedSpecVersion",
        ParseError::InvalidMetadataJson(_) => "InvalidMetadataJson",
        ParseError::IncompleteForceSection => "IncompleteForceSection",
        ParseError::IncompleteEnergySection => "IncompleteEnergySection",
        ParseError::IncompleteSection(_) => "IncompleteSection",
        ParseError::UnknownSection(_) => "UnknownSection",
        ParseError::ValidationError(_) => "ValidationError",
        ParseError::IndexOutOfBounds { .. } => "IndexOutOfBounds",
        ParseError::MassMismatch { .. } => "MassMismatch",
    }
}

fn unquote(raw: &str) -> String {
    let s = raw.trim();
    if s.len() >= 2 && s.starts_with('"') && s.ends_with('"') {
        s[1..s.len() - 1].to_string()
    } else {
        s.to_string()
    }
}

fn parse_bool3(raw: &str) -> [bool; 3] {
    let inner = raw
        .trim()
        .strip_prefix('[')
        .and_then(|s| s.strip_suffix(']'))
        .unwrap_or_else(|| panic!("expect_fixed must be a 3-bool array, got {raw}"));
    let vals: Vec<bool> = inner
        .split(',')
        .map(|tok| match tok.trim() {
            "true" => true,
            "false" => false,
            other => panic!("expect_fixed token is not a bool: {other}"),
        })
        .collect();
    assert_eq!(vals.len(), 3, "expect_fixed must have 3 bools");
    [vals[0], vals[1], vals[2]]
}

fn parse_manifest(text: &str) -> Vec<Case> {
    let mut cases = Vec::new();
    let mut current: Option<Case> = None;
    for (idx, raw) in text.lines().enumerate() {
        let line = raw.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        if line == "[[valid]]" || line == "[[invalid]]" {
            if let Some(case) = current.take() {
                cases.push(finish_case(case));
            }
            current = Some(Case {
                id: String::new(),
                path: String::new(),
                clause: String::new(),
                kind: if line == "[[valid]]" {
                    Kind::Valid
                } else {
                    Kind::Invalid
                },
                error: None,
                expect_fixed: None,
            });
            continue;
        }
        let Some((key, val)) = line.split_once('=') else {
            panic!(
                "manifest line {}: expected key = value, got {line}",
                idx + 1
            );
        };
        let key = key.trim();
        let val = val.trim();
        let Some(case) = current.as_mut() else {
            // Top-level keys (phase, spec) are documentary.
            continue;
        };
        match key {
            "id" => case.id = unquote(val),
            "path" => case.path = unquote(val),
            "clause" => case.clause = unquote(val),
            "error" => case.error = Some(unquote(val)),
            "notes" => {}
            "expect_fixed" => case.expect_fixed = Some(parse_bool3(val)),
            other => panic!("manifest line {}: unknown key {other}", idx + 1),
        }
    }
    if let Some(case) = current {
        cases.push(finish_case(case));
    }
    cases
}

fn finish_case(case: Case) -> Case {
    assert!(!case.id.is_empty(), "conformance case missing id");
    assert!(!case.path.is_empty(), "{}: missing path", case.id);
    assert!(!case.clause.is_empty(), "{}: missing clause", case.id);
    match case.kind {
        Kind::Invalid => assert!(
            case.error.as_ref().is_some_and(|e| !e.is_empty()),
            "{}: invalid case requires error",
            case.id
        ),
        Kind::Valid => assert!(
            case.error.is_none(),
            "{}: valid case must not set error",
            case.id
        ),
    }
    case
}

fn listed_con_files(root: &Path) -> BTreeSet<String> {
    let mut out = BTreeSet::new();
    for sub in ["valid", "invalid"] {
        let dir = root.join(sub);
        if !dir.is_dir() {
            continue;
        }
        for entry in fs::read_dir(&dir).unwrap_or_else(|e| panic!("read {}: {e}", dir.display())) {
            let entry = entry.expect("dirent");
            let name = entry.file_name();
            let name = name.to_string_lossy();
            if name.ends_with(".con") || name.ends_with(".convel") {
                out.insert(format!("{sub}/{name}"));
            }
        }
    }
    out
}

fn listed_golden_files(root: &Path) -> BTreeSet<String> {
    let dir = root.join("golden");
    let mut out = BTreeSet::new();
    if !dir.is_dir() {
        return out;
    }
    for entry in fs::read_dir(&dir).unwrap_or_else(|e| panic!("read {}: {e}", dir.display())) {
        let entry = entry.expect("dirent");
        let name = entry.file_name();
        let name = name.to_string_lossy();
        if name.ends_with(".json") {
            out.insert(name.into_owned());
        }
    }
    out
}

fn json_u64(val: &serde_json::Value, ctx: &str) -> u64 {
    val.as_u64()
        .unwrap_or_else(|| panic!("{ctx}: expected unsigned integer, got {val}"))
}

fn json_str(val: &serde_json::Value, ctx: &str) -> String {
    val.as_str()
        .unwrap_or_else(|| panic!("{ctx}: expected string, got {val}"))
        .to_string()
}

fn json_bool3_rows(val: &serde_json::Value, ctx: &str) -> Vec<[bool; 3]> {
    let rows = val
        .as_array()
        .unwrap_or_else(|| panic!("{ctx}: expected array of [fx, fy, fz]"));
    rows.iter()
        .enumerate()
        .map(|(i, row)| {
            let cells = row
                .as_array()
                .unwrap_or_else(|| panic!("{ctx}[{i}]: expected [fx, fy, fz]"));
            assert_eq!(cells.len(), 3, "{ctx}[{i}]: expected 3 bools");
            let bit = |j: usize| {
                cells[j]
                    .as_bool()
                    .unwrap_or_else(|| panic!("{ctx}[{i}][{j}]: expected bool"))
            };
            [bit(0), bit(1), bit(2)]
        })
        .collect()
}

fn json_f64_3_rows(val: &serde_json::Value, ctx: &str) -> Vec<[f64; 3]> {
    let rows = val
        .as_array()
        .unwrap_or_else(|| panic!("{ctx}: expected array of [x, y, z]"));
    rows.iter()
        .enumerate()
        .map(|(i, row)| {
            let cells = row
                .as_array()
                .unwrap_or_else(|| panic!("{ctx}[{i}]: expected [x, y, z]"));
            assert_eq!(cells.len(), 3, "{ctx}[{i}]: expected 3 numbers");
            let num = |j: usize| {
                cells[j]
                    .as_f64()
                    .unwrap_or_else(|| panic!("{ctx}[{i}][{j}]: expected number"))
            };
            [num(0), num(1), num(2)]
        })
        .collect()
}

fn json_u64_rows(val: &serde_json::Value, ctx: &str) -> Vec<u64> {
    let rows = val
        .as_array()
        .unwrap_or_else(|| panic!("{ctx}: expected array of integers"));
    rows.iter()
        .enumerate()
        .map(|(i, v)| json_u64(v, &format!("{ctx}[{i}]")))
        .collect()
}

fn json_str_rows(val: &serde_json::Value, ctx: &str) -> Vec<String> {
    let rows = val
        .as_array()
        .unwrap_or_else(|| panic!("{ctx}: expected array of strings"));
    rows.iter()
        .enumerate()
        .map(|(i, v)| json_str(v, &format!("{ctx}[{i}]")))
        .collect()
}

fn assert_matches_golden(case_id: &str, frame: &ConFrame, golden: &serde_json::Value) {
    let obj = golden
        .as_object()
        .unwrap_or_else(|| panic!("{case_id}: golden must be a JSON object"));
    let field = |name: &str| {
        obj.get(name)
            .unwrap_or_else(|| panic!("{case_id}: golden missing {name}"))
    };

    let got_id = json_str(field("id"), &format!("{case_id}.id"));
    assert_eq!(got_id, case_id, "{case_id}: golden id must match manifest");

    let n_atoms = json_u64(field("n_atoms"), &format!("{case_id}.n_atoms")) as usize;
    let spec_version = json_u64(field("spec_version"), &format!("{case_id}.spec_version")) as u32;
    let fixed = json_bool3_rows(field("fixed"), &format!("{case_id}.fixed"));
    let positions = json_f64_3_rows(field("positions"), &format!("{case_id}.positions"));
    let atom_ids = json_u64_rows(field("atom_ids"), &format!("{case_id}.atom_ids"));
    let symbols = json_str_rows(field("symbols"), &format!("{case_id}.symbols"));

    assert_eq!(n_atoms, frame.atom_data.len(), "{case_id}: n_atoms");
    assert_eq!(
        spec_version, frame.header.spec_version,
        "{case_id}: spec_version"
    );
    assert_eq!(fixed.len(), n_atoms, "{case_id}: fixed length");
    assert_eq!(positions.len(), n_atoms, "{case_id}: positions length");
    assert_eq!(atom_ids.len(), n_atoms, "{case_id}: atom_ids length");
    assert_eq!(symbols.len(), n_atoms, "{case_id}: symbols length");

    let got_fixed: Vec<[bool; 3]> = frame.atom_data.iter().map(|a| a.fixed).collect();
    let got_positions: Vec<[f64; 3]> = frame.atom_data.iter().map(|a| [a.x, a.y, a.z]).collect();
    let got_ids: Vec<u64> = frame.atom_data.iter().map(|a| a.atom_id).collect();
    let got_symbols: Vec<String> = frame
        .atom_data
        .iter()
        .map(|a| a.symbol.to_string())
        .collect();

    assert_eq!(got_fixed, fixed, "{case_id}: fixed");
    assert_eq!(got_positions, positions, "{case_id}: positions");
    assert_eq!(got_ids, atom_ids, "{case_id}: atom_ids");
    assert_eq!(got_symbols, symbols, "{case_id}: symbols");
}

#[test]
fn conformance_corpus_matches_manifest() {
    let root = corpus_root();
    let manifest_path = root.join("manifest.toml");
    let text = fs::read_to_string(&manifest_path).unwrap_or_else(|e| {
        panic!("read {}: {e}", manifest_path.display());
    });
    let cases = parse_manifest(&text);
    assert!(
        !cases.is_empty(),
        "manifest.toml lists no [[valid]] / [[invalid]] cases"
    );

    let spec = fs::read_to_string(spec_org()).expect("docs/orgmode/spec.org readable");
    let listed: BTreeSet<String> = cases.iter().map(|c| c.path.clone()).collect();
    let on_disk = listed_con_files(&root);
    assert_eq!(
        listed, on_disk,
        "manifest paths must match .con files under valid/ and invalid/"
    );

    let valid_goldens: BTreeSet<String> = cases
        .iter()
        .filter(|c| c.kind == Kind::Valid)
        .map(|c| format!("{}.json", c.id))
        .collect();
    let on_disk_goldens = listed_golden_files(&root);
    assert_eq!(
        valid_goldens, on_disk_goldens,
        "golden/ must contain exactly one JSON file per valid manifest id"
    );
    for case in cases.iter().filter(|c| c.kind == Kind::Invalid) {
        let extra = root.join("golden").join(format!("{}.json", case.id));
        assert!(
            !extra.exists(),
            "{}: invalid case must not have a golden",
            case.id
        );
    }

    for case in &cases {
        assert!(
            spec.contains(&case.clause),
            "{}: clause {:?} not found in spec.org",
            case.id,
            case.clause
        );
        let fixture = root.join(&case.path);
        let body = fs::read_to_string(&fixture)
            .unwrap_or_else(|e| panic!("{}: read {}: {e}", case.id, fixture.display()));
        let parsed = ConFrameIterator::new(&body).next();
        match case.kind {
            Kind::Valid => {
                let frame = parsed
                    .unwrap_or_else(|| panic!("{}: valid fixture produced no frame", case.id))
                    .unwrap_or_else(|e| {
                        panic!(
                            "{}: expected parse, got {} ({e})",
                            case.id,
                            variant_name(&e)
                        )
                    });
                if let Some(want) = case.expect_fixed {
                    assert_eq!(
                        frame.atom_data[0].fixed, want,
                        "{}: column-4 decode mismatch",
                        case.id
                    );
                }
                let golden_path = root.join("golden").join(format!("{}.json", case.id));
                let golden_text = fs::read_to_string(&golden_path).unwrap_or_else(|e| {
                    panic!("{}: missing golden {}: {e}", case.id, golden_path.display());
                });
                let golden: serde_json::Value = serde_json::from_str(&golden_text)
                    .unwrap_or_else(|e| panic!("{}: golden JSON: {e}", case.id));
                assert_matches_golden(&case.id, &frame, &golden);
            }
            Kind::Invalid => {
                let err = match parsed {
                    Some(Err(e)) => e,
                    Some(Ok(_)) => panic!(
                        "{}: expected {}, file parsed",
                        case.id,
                        case.error.as_deref().unwrap()
                    ),
                    None => panic!("{}: invalid fixture produced no result", case.id),
                };
                let got = variant_name(&err);
                let want = case.error.as_deref().unwrap();
                assert_eq!(got, want, "{}: typed ParseError mismatch ({err})", case.id);
            }
        }
    }
}
