//! Structural check: field-wide interchange ambition present in user docs.

use std::fs;
use std::path::PathBuf;

fn docs_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("docs/orgmode")
}

fn read(name: &str) -> String {
    let p = docs_root().join(name);
    fs::read_to_string(&p).unwrap_or_else(|e| panic!("missing {}: {e}", p.display()))
}

#[test]
fn architecture_field_wide_thesis() {
    let t = read("architecture.org");
    assert!(t.contains("computational chemistry") || t.contains("materials science"));
    assert!(t.contains("hourglass") || t.contains("Hourglass") || t.contains("rkr_"));
    assert!(t.contains("readcon-db"));
    assert!(t.contains("best interchange") || t.contains("Field-wide"));
}

#[test]
fn evolution_covers_v2_v3() {
    let t = read("evolution.org");
    assert!(t.contains("version 3") || t.contains("Version 2 to version 3"));
    assert!(t.contains("units") || t.contains("=units="));
}

#[test]
fn faq_asserts_field_leadership() {
    let t = read("faq.org");
    assert!(t.contains("*Yes.*") || t.contains("strictly preferable") || t.contains("state of the art"));
    assert!(t.contains("hourglass") || t.contains("Hourglass"));
    assert!(!t.contains("No universal ranking is intended"));
    assert!(t.contains("materials science") || t.contains("computational chemistry"));
}

#[test]
fn getting_started_maps_when_to_use() {
    let t = read("getting-started.org");
    assert!(t.contains("When to use what") || t.contains("CON via"));
}

#[test]
fn faq_why_another_format_still_present() {
    let t = read("faq.org");
    assert!(t.contains("Why another atomic structure format"));
}
