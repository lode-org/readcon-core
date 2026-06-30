//! Structural check: design rationale present in user docs (CPC-aligned substance).

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
fn architecture_design_rationale() {
    let t = read("architecture.org");
    assert!(t.contains("hourglass") || t.contains("Hourglass") || t.contains("rkr_"));
    assert!(t.contains("readcon-db"));
    assert!(t.contains("authoritative") || t.contains("authority") || t.contains("CON text"));
    assert!(!t.contains("No universal ranking is intended"));
    assert!(!t.contains("sit politely"));
}

#[test]
fn evolution_covers_v2_v3() {
    let t = read("evolution.org");
    assert!(t.contains("version 3") || t.contains("Version 2 to version 3"));
    assert!(t.contains("units") || t.contains("=units="));
}

#[test]
fn faq_hourglass_and_con_vs_xyz() {
    let t = read("faq.org");
    assert!(t.contains("hourglass") || t.contains("Hourglass") || t.contains("rkr_"));
    assert!(t.contains("CON vs XYZ") || t.contains("XYZ / extXYZ"));
    assert!(t.contains("authoritative") || t.contains("Authoritative") || t.contains("UTF-8 CON"));
    assert!(!t.contains("No universal ranking is intended"));
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
