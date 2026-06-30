//! Structural check: assertive interchange thesis present in user docs.

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
fn architecture_hourglass_embedding_thesis() {
    let t = read("architecture.org");
    assert!(t.contains("Hourglass") || t.contains("hourglass"));
    assert!(t.contains("embed") || t.contains("Embed"));
    assert!(t.contains("XYZ"));
    assert!(t.contains("rkr_") || t.contains("C ABI"));
    assert!(
        !t.contains("not a replacement for them"),
        "must not use weak niche hedging"
    );
}

#[test]
fn evolution_covers_v2_v3_and_alternatives() {
    let t = read("evolution.org");
    assert!(t.contains("Version 2 to version 3") || t.contains("version 3"));
    assert!(t.contains("Alternatives considered") || t.contains("alternatives"));
    assert!(t.contains("units") || t.contains("=units="));
}

#[test]
fn faq_asserts_con_better_for_optimizer_interchange() {
    let t = read("faq.org");
    assert!(t.contains("CON vs XYZ") || t.contains("XYZ / extXYZ"));
    assert!(t.contains("hourglass") || t.contains("Hourglass"));
    assert!(
        t.contains("*Yes.*") || t.contains("strictly preferable"),
        "FAQ must assert CON preference for optimizer interchange"
    );
    assert!(!t.contains("No universal ranking is intended"));
}

#[test]
fn getting_started_maps_when_to_use() {
    let t = read("getting-started.org");
    assert!(t.contains("When to use what") || t.contains("when to use"));
    assert!(t.contains("readcon-db") || t.contains("campaign"));
}

#[test]
fn faq_why_another_format_still_present() {
    let t = read("faq.org");
    assert!(t.contains("Why another atomic structure format"));
}
