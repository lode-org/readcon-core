//! v3.1 specification: clause index and the worked examples.

use readcon_core::iterators::ConFrameIterator;
use std::fs;
use std::path::PathBuf;
use std::process::Command;

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn spec_text() -> String {
    fs::read_to_string(repo_root().join("docs/orgmode/spec.org")).expect("spec.org")
}

fn example(name: &str) -> String {
    let spec = spec_text();
    let marker = format!("#+name: {name}");
    let start = spec
        .find(&marker)
        .unwrap_or_else(|| panic!("missing {marker}"))
        + marker.len();
    let begin_rel = spec[start..]
        .find("#+begin_example")
        .unwrap_or_else(|| panic!("{name}: missing example"));
    let body_start = start + begin_rel + "#+begin_example".len();
    let rest = &spec[body_start..];
    let rest = rest.strip_prefix('\n').unwrap_or(rest);
    let end = rest
        .find("#+end_example")
        .unwrap_or_else(|| panic!("{name}: missing end"));
    let mut body = rest[..end].to_string();
    if !body.ends_with('\n') {
        body.push('\n');
    }
    body
}

fn one_frame(body: &str) -> readcon_core::types::ConFrame {
    let mut it = ConFrameIterator::new(body);
    let frame = it
        .next()
        .expect("a frame")
        .expect("example parses with the current reader");
    assert!(it.next().is_none(), "example is one frame");
    frame
}

#[test]
fn clause_index_matches_spec() {
    let script = repo_root().join("scripts/emit_clauses.py");
    let output = Command::new("python3")
        .arg(&script)
        .arg("--check")
        .current_dir(repo_root())
        .output()
        .expect("python3");
    assert!(
        output.status.success(),
        "emit_clauses.py --check failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );

    let tsv = fs::read_to_string(repo_root().join("docs/orgmode/clauses.tsv")).unwrap();
    let mut ids = Vec::new();
    for (n, line) in tsv.lines().enumerate() {
        if n == 0 {
            assert_eq!(line, "id\tkeyword\ttext");
            continue;
        }
        let mut parts = line.split('\t');
        let id = parts.next().unwrap();
        let keyword = parts.next().unwrap();
        let text = parts.next().unwrap();
        assert!(parts.next().is_none(), "{id}: extra tab");
        assert!(
            matches!(
                keyword,
                "MUST"
                    | "MUST NOT"
                    | "REQUIRED"
                    | "SHALL"
                    | "SHOULD"
                    | "SHOULD NOT"
                    | "MAY"
                    | "OPTIONAL"
            ),
            "{id}: {keyword}"
        );
        assert!(text.contains(keyword), "{id} text omits {keyword}");
        assert!(
            spec_text().contains(&format!("- {id} :: {keyword} :: {text}")),
            "{id} missing from spec.org"
        );
        ids.push(id.to_string());
    }
    assert!(ids.len() > 50, "clause index is too small");
    let mut sorted = ids.clone();
    sorted.sort();
    sorted.dedup();
    assert_eq!(sorted.len(), ids.len(), "duplicate clause id");
}

#[test]
fn v31_example_parses() {
    let frame = one_frame(&example("v31-frame"));
    assert_eq!(frame.header.spec_version, 3);
    assert_eq!(frame.header.natm_types, 2);
    assert_eq!(frame.atom_data.len(), 3);
    assert_eq!(&*frame.atom_data[0].symbol, "Pt");
    assert_eq!(&*frame.atom_data[1].symbol, "Pt");
    assert_eq!(&*frame.atom_data[2].symbol, "H");
    assert_eq!(
        frame
            .atom_data
            .iter()
            .map(|atom| atom.atom_id)
            .collect::<Vec<_>>(),
        vec![2, 0, 1]
    );
    assert_eq!(
        frame
            .atom_data
            .iter()
            .map(|atom| atom.fixed)
            .collect::<Vec<_>>(),
        vec![
            [false, false, false],
            [true, true, false],
            [true, true, true]
        ]
    );
    assert_eq!(frame.atom_data[0].velocity(), Some([0.01, 0.0, 0.0]));
    assert_eq!(frame.atom_data[1].velocity(), Some([0.0, 0.02, 0.0]));
    assert_eq!(frame.atom_data[2].velocity(), Some([0.0, 0.0, 0.03]));
    assert_eq!(frame.atom_data[0].force(), Some([0.1, 0.0, 0.0]));
    assert!(frame.header.sections.iter().any(|s| s == "velocities"));
    assert!(frame.header.sections.iter().any(|s| s == "forces"));
    assert_eq!(
        frame
            .header
            .metadata
            .get("con_spec_minor")
            .and_then(|v| v.as_u64()),
        Some(1)
    );
    let units = frame
        .header
        .metadata
        .get("units")
        .and_then(|v| v.get("time"))
        .and_then(|v| v.as_str());
    assert_eq!(units, Some("(amu*angstrom^2/eV)^0.5"));
    let pbc = frame
        .header
        .metadata
        .get("pbc")
        .and_then(|v| v.as_array())
        .unwrap();
    assert_eq!(
        pbc.iter().map(|v| v.as_bool().unwrap()).collect::<Vec<_>>(),
        vec![true, true, false]
    );
}

#[test]
fn v31_frame_as_v1_parses() {
    let frame = one_frame(&example("v31-as-v1"));
    assert_eq!(frame.header.spec_version, 1);
    assert_eq!(frame.atom_data.len(), 3);
    assert_eq!(
        frame
            .atom_data
            .iter()
            .map(|atom| atom.atom_id)
            .collect::<Vec<_>>(),
        vec![2, 0, 1]
    );
    assert_eq!(
        frame
            .atom_data
            .iter()
            .map(|atom| atom.fixed)
            .collect::<Vec<_>>(),
        vec![
            [false, false, false],
            [true, true, true],
            [true, true, true]
        ]
    );
    assert!(frame.atom_data.iter().all(|atom| atom.velocity().is_none()));
    assert!(frame.atom_data.iter().all(|atom| atom.force().is_none()));
}

#[test]
fn zero_atom_frame_parses() {
    let frame = one_frame(&example("zero-atom-frame"));
    assert_eq!(frame.header.spec_version, 3);
    assert_eq!(frame.header.natm_types, 0);
    assert!(frame.header.natms_per_type.is_empty());
    assert!(frame.atom_data.is_empty());
    assert!(frame.header.sections.is_empty());
}
