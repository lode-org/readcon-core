//! Structural check: CON / readcon-core docs keep design substance, no AI tells.

use std::fs;
use std::path::PathBuf;

fn docs_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("docs/orgmode")
}

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn read(name: &str) -> String {
    let p = docs_root().join(name);
    fs::read_to_string(&p).unwrap_or_else(|e| panic!("missing {}: {e}", p.display()))
}

fn read_repo(rel: &str) -> String {
    let p = repo_root().join(rel);
    fs::read_to_string(&p).unwrap_or_else(|e| panic!("missing {}: {e}", p.display()))
}

fn assert_no_ai_tells(t: &str, file: &str) {
    let banned = [
        "not \"fastest",
        "not 'fastest",
        "not a claim of fastest",
        "not a replacement for",
        "all of computational chemistry",
        "generic MD-format supremacy",
        "within domain",
        "domain-scoped",
        "Speed (honest)",
        "Forbidden as",
        "past mistake",
        "No universal ranking is intended",
        "sit politely",
        "fidelity loss is acceptable",
        "richer sections than lean XYZ",
        "lean XYZ",
        "best of both worlds",
        "state-of-the-art",
        "State-of-the-art",
        "H5MD-grade",
        "primary goal is",
        "Is readcon-core",
        "definitive CON",
        "Definitive CON",
        "deliberately small",
        "LODE-centric",
        "LODE centric",
    ];
    for b in banned {
        assert!(!t.contains(b), "{file} still contains banned phrase: {b:?}");
    }
}

#[test]
fn architecture_design_rationale() {
    let t = read("architecture.org");
    assert!(t.contains("hourglass") || t.contains("rkr_"));
    assert!(t.contains("readcon-db"));
    assert!(t.contains("authoritative") || t.contains("CON text") || t.contains("UTF-8 CON"));
    assert!(t.contains("benchmarks") || t.contains("Cachegrind"));
    assert!(t.contains("eOn") || t.contains("transition-state") || t.contains("LODE"));
    assert_no_ai_tells(&t, "architecture.org");
}

#[test]
fn evolution_covers_v2_v3() {
    let t = read("evolution.org");
    assert!(t.contains("version 3") || t.contains("Version 2 to version 3"));
    assert!(t.contains("units") || t.contains("=units="));
}

#[test]
fn faq_con_contract() {
    let t = read("faq.org");
    assert!(t.contains("hourglass") || t.contains("rkr_"));
    assert!(t.contains("atom_id") || t.contains("=atom_id="));
    assert!(t.contains("fixed") || t.contains("constraint") || t.contains("mask"));
    assert!(t.contains("saddle") || t.contains("NEB") || t.contains("dimer"));
    assert!(
        t.contains("What CON is for") || t.contains("complete checkpoint"),
        "FAQ must state what CON is for in plain language"
    );
    assert!(t.contains("authoritative") || t.contains("UTF-8 CON") || t.contains("CON text"));
    assert!(!t.contains("When should I use CON vs XYZ"));
    assert!(!t.contains("compare to XYZ and ASE I/O"));
    assert_no_ai_tells(&t, "faq.org");
}

#[test]
fn faq_speed_cites_con_peers() {
    let t = read("faq.org");
    assert!(t.contains("Cachegrind") && t.contains("compare_readers"));
    assert!(!t.contains("10-30x faster") && !t.contains("10–30×"));
    assert_no_ai_tells(&t, "faq.org");
}

#[test]
fn getting_started_scope() {
    let t = read("getting-started.org");
    assert!(t.contains("Scope") || t.contains("readcon-core"));
    assert!(t.contains("hourglass") || t.contains("rkr_"));
    assert!(t.contains("atom_id") || t.contains("=atom_id=") || t.contains("NEB") || t.contains("eOn"));
    assert!(t.contains("benchmarks") || t.contains("Cachegrind") || t.contains("spec"));
    assert_no_ai_tells(&t, "getting-started.org");
}

#[test]
fn faq_purpose_heading() {
    let t = read("faq.org");
    assert!(
        t.contains("What CON is for") || t.contains("Why another atomic structure format"),
        "FAQ must keep a purpose heading"
    );
}

#[test]
fn benchmarks_what_we_measure() {
    let t = read("benchmarks.org");
    assert!(t.contains("What we measure") || t.contains("Cachegrind"));
    assert!(t.contains("compare_readers") || t.contains("ase.io.eon"));
    assert!(!t.contains("2.7M atoms/s"));
    assert!(!t.contains("richer sections than lean XYZ"));
    assert_no_ai_tells(&t, "benchmarks.org");
}

#[test]
fn index_and_readme_src() {
    let index = read("index.org");
    assert!(index.contains("CON") || index.contains(".con"));
    assert!(index.contains("hourglass") || index.contains("eOn") || index.contains("LODE"));
    assert!(index.contains("spec") || index.contains("Spec") || index.contains(":doc:`spec`"));
    assert_no_ai_tells(&index, "index.org");

    let readme = read_repo("readme_src.org");
    assert!(readme.contains("hourglass") || readme.contains("rkr_"));
    assert!(readme.contains("Cachegrind") || readme.contains("compare_readers"));
    assert!(readme.contains("atom_id") || readme.contains("=atom_id="));
    assert!(readme.contains("eOn") || readme.contains("NEB") || readme.contains("checkpoint"));
    assert!(readme.contains("Chemfiles owns") || readme.contains("chemfiles"));
    assert_no_ai_tells(&readme, "readme_src.org");
}
