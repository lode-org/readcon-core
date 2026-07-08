//! Structural check: docs describe CON and the code stack, not format bake-offs.

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
        "not a claim of fastest",
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
        "only eOn",
        "only LODE",
        "only for eOn",
        "separate concern",
        "separate concerns",
        "they complement CON",
        "complement CON",
        "Neither replaces",
        "How does CON relate to H5MD",
        "CON and H5MD",
        "Related work (H5MD",
    ];
    for b in banned {
        assert!(!t.contains(b), "{file} still contains banned phrase: {b:?}");
    }
}

#[test]
fn architecture_matches_code_surface() {
    let t = read("architecture.org");
    assert!(t.contains("hourglass") || t.contains("rkr_"));
    assert!(t.contains("readcon-db") || t.contains("index_proj") || t.contains("chemfiles"));
    assert!(t.contains("DLPack") || t.contains("metatensor") || t.contains("dlpk"));
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
    assert!(t.contains("saddle") || t.contains("NEB") || t.contains("dimer"));
    assert!(t.contains("What CON is for"));
    assert!(
        t.contains("What is the stack for")
            || t.contains("campaign")
            || t.contains("multi-language")
            || t.contains("chemfiles"),
        "FAQ must describe the multi-tool stack"
    );
    // optional physics sections ship on v2/v3 declared surface (not a format major)
    assert!(
        t.contains("charges") && t.contains("spins") && t.contains("magmoms"),
        "FAQ must list charges/spins/magmoms with other optional sections"
    );
    assert!(
        !t.contains("con_spec_version: 4") && !t.contains("con_spec_version\":4"),
        "FAQ must not require format v4 for optional sections"
    );
    // no format bake-off section
    assert!(!t.contains("How does CON relate to H5MD"));
    assert!(!t.contains("* CON and H5MD"));
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
    assert!(
        t.contains("chemfiles") || t.contains("DLPack") || t.contains("index_proj") || t.contains("metatensor"),
        "getting-started should mention more of the stack than bare I/O"
    );
    assert_no_ai_tells(&t, "getting-started.org");
}

#[test]
fn faq_purpose_heading() {
    let t = read("faq.org");
    assert!(t.contains("What CON is for"));
}

#[test]
fn benchmarks_what_we_measure() {
    let t = read("benchmarks.org");
    assert!(t.contains("What we measure") || t.contains("Cachegrind"));
    assert!(t.contains("compare_readers") || t.contains("ase.io.eon"));
    assert!(!t.contains("2.7M atoms/s"));
    assert_no_ai_tells(&t, "benchmarks.org");
}

#[test]
fn index_and_readme_src() {
    let index = read("index.org");
    assert!(index.contains("CON") || index.contains(".con"));
    assert!(index.contains("hourglass") || index.contains("rkr_") || index.contains("multi-language"));
    assert!(
        index.contains("Put CON") || index.contains("put CON") || index.contains("everywhere"),
        "index must state CON-everywhere ambition"
    );
    assert!(!index.contains("Related work (H5MD"));
    assert_no_ai_tells(&index, "index.org");

    let readme = read_repo("readme_src.org");
    assert!(readme.contains("hourglass") || readme.contains("rkr_"));
    assert!(readme.contains("Cachegrind") || readme.contains("compare_readers"));
    assert!(readme.contains("atom_id") || readme.contains("=atom_id="));
    assert!(
        readme.contains("DLPack") || readme.contains("metatensor") || readme.contains("chemfiles"),
        "readme must reflect code features beyond bare parse"
    );
    assert!(
        readme.contains("everywhere")
            || readme.contains("put CON")
            || readme.contains("spreading CON")
            || readme.contains("Role in spreading"),
        "readme must state CON expansion ambition"
    );
    assert!(
        readme.contains("charges") && readme.contains("spins") && readme.contains("magmoms"),
        "readme must list optional charges/spins/magmoms sections"
    );
    assert!(!readme.contains("H5MD"));
    assert!(!readme.contains("XTC"));
    assert_no_ai_tells(&readme, "readme_src.org");
}
