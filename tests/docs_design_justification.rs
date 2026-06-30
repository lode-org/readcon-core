//! Structural check: reviewer-facing design *why* stays present in user docs.
//! Drives real on-disk Org sources under `docs/orgmode/` (not reimplemented prose).

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
fn architecture_states_rejected_alternatives() {
    let t = read("architecture.org");
    assert!(
        t.contains("Design rationale") || t.contains("design-rationale"),
        "architecture.org needs Design rationale section"
    );
    assert!(t.contains("Rejected") || t.contains("rejected"), "name rejected alternatives");
    assert!(t.contains("hourglass") || t.contains("Hourglass") || t.contains("C ABI"));
    assert!(t.contains("readcon-db") || t.contains("campaign"));
    assert!(
        t.contains("Scoped") || t.contains("scoped"),
        "scoped superiority language required"
    );
    assert!(
        t.contains("XTC") || t.contains("binary MD") || t.contains("TRR"),
        "non-claim for binary MD"
    );
}

#[test]
fn evolution_covers_v2_v3_and_alternatives() {
    let t = read("evolution.org");
    assert!(t.contains("Version 2 to version 3") || t.contains("version 3"));
    assert!(t.contains("Alternatives considered") || t.contains("alternatives"));
    assert!(t.contains("units") || t.contains("=units="));
    assert!(t.contains("Compatibility") || t.contains("compatibility"));
}

#[test]
fn faq_answers_con_vs_xyz_ase_authority() {
    let t = read("faq.org");
    assert!(t.contains("CON vs XYZ") || t.contains("XYZ / extXYZ"));
    assert!(t.contains("ASE") && (t.contains("hand-off") || t.contains("hand off") || t.contains("calculator")));
    assert!(t.contains("authoritative") || t.contains("authority") || t.contains("Authoritative"));
    assert!(t.contains("always better") || t.contains("Scoped yes"));
}

#[test]
fn getting_started_maps_when_to_use() {
    let t = read("getting-started.org");
    assert!(t.contains("When to use what") || t.contains("when to use"));
    assert!(t.contains("readcon-db") || t.contains("campaign"));
    assert!(t.contains("chemfiles") || t.contains("XYZ"));
}

#[test]
fn faq_why_another_format_still_present() {
    let t = read("faq.org");
    assert!(t.contains("Why another atomic structure format"));
    assert!(t.contains("XYZ") && t.contains("extxyz") || t.contains("extXYZ") || t.contains("*extxyz*"));
}
