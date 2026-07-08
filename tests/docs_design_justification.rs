//! Structural check: design rationale and positioning substance in user docs.

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

/// AI-style defensive scope disclaimers that belong nowhere in product docs.
fn assert_no_defensive_tells(t: &str, file: &str) {
    let banned = [
        "not \"fastest",
        "not 'fastest",
        "not a claim of fastest",
        "not a replacement for",
        "Not “fastest",
        "Not \"fastest",
        "all of computational chemistry",
        "generic MD-format supremacy",
        "within domain",
        "domain-scoped",
        "Speed (honest)",
        "Forbidden as",
        "past mistake",
        "No universal ranking is intended",
        "sit politely",
    ];
    for b in banned {
        assert!(
            !t.contains(b),
            "{file} still contains defensive/AI tell: {b:?}"
        );
    }
}

#[test]
fn architecture_design_rationale() {
    let t = read("architecture.org");
    assert!(t.contains("hourglass") || t.contains("Hourglass") || t.contains("rkr_"));
    assert!(t.contains("readcon-db"));
    assert!(t.contains("authoritative") || t.contains("authority") || t.contains("CON text"));
    assert!(t.contains("Cachegrind") || t.contains("equal-geometry"));
    assert_no_defensive_tells(&t, "architecture.org");
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
    assert_no_defensive_tells(&t, "faq.org");
}

#[test]
fn faq_speed_cites_harnesses() {
    let t = read("faq.org");
    assert!(
        t.contains("Cachegrind") && t.contains("equal-geometry"),
        "FAQ speed answer must cite Cachegrind and equal-geometry"
    );
    assert!(
        t.contains("multiformat_traj") || t.contains("compare_readers"),
        "FAQ speed answer must name an in-repo harness"
    );
    assert!(
        !t.contains("10-30x faster") && !t.contains("10–30×"),
        "FAQ must not headline unmeasured pure-Python 10–30× claims"
    );
    assert!(
        !t.contains("Is readcon-core \"SOTA\"") && !t.contains("Is readcon-core “SOTA”"),
        "FAQ must not carry a self-congratulatory SOTA Q&A"
    );
    assert_no_defensive_tells(&t, "faq.org");
}

#[test]
fn getting_started_maps_when_to_use() {
    let t = read("getting-started.org");
    assert!(t.contains("When to use what") || t.contains("CON via"));
    assert!(
        t.contains("hourglass") || t.contains("rkr_") || t.contains("interchange"),
        "getting-started must position CON interchange / hourglass ABI"
    );
    assert!(
        t.contains("Cachegrind") || t.contains("equal-geometry") || t.contains("benchmarks"),
        "getting-started must point at measured speed evidence"
    );
    assert_no_defensive_tells(&t, "getting-started.org");
}

#[test]
fn faq_why_another_format_still_present() {
    let t = read("faq.org");
    assert!(t.contains("Why another atomic structure format"));
}

#[test]
fn benchmarks_measurement_hierarchy() {
    let t = read("benchmarks.org");
    assert!(
        t.contains("Measurement hierarchy") || t.contains("Cachegrind"),
        "benchmarks must lead with measurement hierarchy"
    );
    assert!(t.contains("equal-geometry") || t.contains("multiformat_traj"));
    assert!(
        t.contains("Criterion microbenches") || t.contains("local latency"),
        "Criterion tables must sit under local-latency framing"
    );
    assert!(
        !t.contains("2.7M atoms/s"),
        "must not promote toy 4-atom atoms/s as a bare product number"
    );
    assert_no_defensive_tells(&t, "benchmarks.org");
}

#[test]
fn index_and_readme_src_positioning() {
    let index = read("index.org");
    assert!(
        index.contains("hourglass") || index.contains("CON / convel") || index.contains(".con"),
        "index must state CON / multi-language role"
    );
    assert!(
        index.contains("Cachegrind") || index.contains("equal-geometry"),
        "index must mention measurement harnesses"
    );
    assert_no_defensive_tells(&index, "index.org");

    let readme = read_repo("readme_src.org");
    assert!(
        readme.contains("hourglass") || readme.contains("Hourglass") || readme.contains("rkr_"),
        "readme_src must mention hourglass multi-language ABI"
    );
    assert!(
        readme.contains("Cachegrind") && (readme.contains("equal-geometry") || readme.contains("multiformat_traj") || readme.contains("compare_readers")),
        "readme_src speed section must cite Cachegrind and a peer harness"
    );
    assert!(
        readme.contains("Round-trip") || readme.contains("round-trip") || readme.contains("atom_id"),
        "readme_src must state round-trip / atom_id fidelity"
    );
    assert_no_defensive_tells(&readme, "readme_src.org");
}
