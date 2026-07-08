//! Structural check: docs match the codebase role and related-work framing.

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
    assert!(t.contains("benchmarks") || t.contains("Cachegrind") || t.contains("faq"));
    assert_no_ai_tells(&t, "architecture.org");
}

#[test]
fn evolution_covers_v2_v3() {
    let t = read("evolution.org");
    assert!(t.contains("version 3") || t.contains("Version 2 to version 3"));
    assert!(t.contains("units") || t.contains("=units="));
}

#[test]
fn faq_con_and_related_work() {
    let t = read("faq.org");
    assert!(t.contains("hourglass") || t.contains("rkr_"));
    assert!(t.contains("atom_id") || t.contains("=atom_id="));
    assert!(t.contains("saddle") || t.contains("NEB") || t.contains("dimer"));
    assert!(t.contains("What CON is for"));
    // literature-backed related work
    assert!(
        t.contains("H5MD")
            && (t.contains("chillEON") || t.contains("chillEONSoftwareLong2014") || t.contains("Chill")),
        "FAQ must place CON vs H5MD with literature anchors"
    );
    assert!(
        t.contains("multi-language")
            || t.contains("multi-code")
            || t.contains("campaign")
            || t.contains("What is the stack for"),
        "FAQ must describe the multi-tool stack"
    );
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
        index.contains("H5MD") || index.contains("rare-event") || index.contains("transition-state"),
        "index should state problem domain and related formats"
    );
    assert_no_ai_tells(&index, "index.org");

    let readme = read_repo("readme_src.org");
    assert!(readme.contains("hourglass") || readme.contains("rkr_"));
    assert!(readme.contains("Cachegrind") || readme.contains("compare_readers"));
    assert!(readme.contains("atom_id") || readme.contains("=atom_id="));
    assert!(
        readme.contains("H5MD") || readme.contains("de Buyl") || readme.contains("rare-event"),
        "readme must place CON against literature-backed neighbors"
    );
    assert!(
        readme.contains("DLPack") || readme.contains("metatensor") || readme.contains("chemfiles"),
        "readme must reflect code features beyond bare parse"
    );
    assert!(
        readme.contains("rgpot")
            || readme.contains("GROMACS")
            || readme.contains("ML")
            || readme.contains("campaign"),
        "readme must name multi-consumer stack"
    );
    assert_no_ai_tells(&readme, "readme_src.org");
}

#[test]
fn references_bib_has_eon_and_h5md() {
    let bib = read_repo("docs/source/references.bib");
    assert!(bib.contains("chillEONSoftwareLong2014") || bib.contains("10.1088/0965-0393/22/5/055002"));
    assert!(bib.contains("deBuylH5MDStructuredEfficient2014") || bib.contains("10.1016/j.cpc.2014.01.018"));
}
