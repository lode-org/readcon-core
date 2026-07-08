//! Structural check: CON checkpoint positioning substance in user docs.

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
        "fidelity loss is acceptable",
        "richer sections than lean XYZ",
        "lean XYZ",
    ];
    for b in banned {
        assert!(
            !t.contains(b),
            "{file} still contains banned tell/foil: {b:?}"
        );
    }
}

#[test]
fn architecture_design_rationale() {
    let t = read("architecture.org");
    assert!(t.contains("hourglass") || t.contains("Hourglass") || t.contains("rkr_"));
    assert!(t.contains("readcon-db"));
    assert!(t.contains("authoritative") || t.contains("authority") || t.contains("CON text"));
    assert!(
        t.contains("benchmarks") || t.contains("Cachegrind") || t.contains("Measurements"),
        "architecture must point at measurements"
    );
    assert!(
        t.contains("transition-state")
            || t.contains("saddle")
            || t.contains("NEB")
            || t.contains("eOn")
            || t.contains("Objective"),
        "architecture must name the TS / eOn role"
    );
    assert_no_defensive_tells(&t, "architecture.org");
}

#[test]
fn evolution_covers_v2_v3() {
    let t = read("evolution.org");
    assert!(t.contains("version 3") || t.contains("Version 2 to version 3"));
    assert!(t.contains("units") || t.contains("=units="));
}

#[test]
fn faq_con_checkpoint_contract() {
    let t = read("faq.org");
    assert!(t.contains("hourglass") || t.contains("Hourglass") || t.contains("rkr_"));
    assert!(t.contains("atom_id") || t.contains("=atom_id="));
    assert!(
        t.contains("fixed") || t.contains("constraint") || t.contains("mask"),
        "FAQ must mention constraints / fixed mask"
    );
    assert!(
        t.contains("saddle") || t.contains("NEB") || t.contains("dimer"),
        "FAQ must name saddle/NEB/dimer use"
    );
    assert!(t.contains("authoritative") || t.contains("Authoritative") || t.contains("UTF-8 CON"));
    assert!(
        t.contains("* Objective") || t.contains("primary goal"),
        "FAQ must open with an H5MD-style Objective"
    );
    assert!(
        t.contains("Design goals") || t.contains("Completeness for TS search"),
        "FAQ must list positive design goals"
    );
    assert!(
        !t.contains("When should I use CON vs XYZ")
            && !t.contains("compare to XYZ and ASE I/O")
            && !t.contains("fidelity loss is acceptable"),
        "FAQ must not center product Q&A on XYZ comparison"
    );
    assert_no_defensive_tells(&t, "faq.org");
}

#[test]
fn faq_speed_cites_con_peers() {
    let t = read("faq.org");
    assert!(
        t.contains("Cachegrind") && t.contains("compare_readers"),
        "FAQ speed answer must cite Cachegrind and compare_readers"
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
    assert!(t.contains("Objective") || t.contains("CON via") || t.contains("readcon-core"));
    assert!(
        t.contains("hourglass") || t.contains("rkr_") || t.contains("specification"),
        "getting-started must position CON / hourglass ABI"
    );
    assert!(
        t.contains("saddle") || t.contains("NEB") || t.contains("atom_id") || t.contains("=atom_id="),
        "getting-started must name saddle/NEB payload fields"
    );
    assert!(
        t.contains("Cachegrind") || t.contains("benchmarks") || t.contains("compare_readers"),
        "getting-started must point at measured speed evidence"
    );
    assert_no_defensive_tells(&t, "getting-started.org");
}

#[test]
fn faq_objective_still_present() {
    let t = read("faq.org");
    assert!(
        t.contains("* Objective") || t.contains("primary goal"),
        "FAQ must keep an Objective section"
    );
}

#[test]
fn benchmarks_measurement_hierarchy() {
    let t = read("benchmarks.org");
    assert!(
        t.contains("Measurement hierarchy") || t.contains("Cachegrind"),
        "benchmarks must lead with measurement hierarchy"
    );
    assert!(t.contains("compare_readers") || t.contains("ase.io.eon"));
    assert!(
        t.contains("Criterion microbenches") || t.contains("local latency"),
        "Criterion tables must sit under local-latency framing"
    );
    assert!(
        !t.contains("2.7M atoms/s"),
        "must not promote toy 4-atom atoms/s as a bare product number"
    );
    assert!(
        !t.contains("richer sections than lean XYZ"),
        "benchmarks must not define CON by XYZ foil language"
    );
    assert_no_defensive_tells(&t, "benchmarks.org");
}

#[test]
fn index_and_readme_src_positioning() {
    let index = read("index.org");
    assert!(
        index.contains("hourglass")
            || index.contains("rkr_")
            || index.contains("CON / convel")
            || index.contains(".con"),
        "index must state CON / multi-language role"
    );
    assert!(
        index.contains("Objective") || index.contains("portable") || index.contains("transition-state"),
        "index must state objective in positive terms"
    );
    assert!(
        index.contains("spec") || index.contains("Spec") || index.contains(":doc:`spec`"),
        "index must point at the published format spec"
    );
    assert_no_defensive_tells(&index, "index.org");

    let readme = read_repo("readme_src.org");
    assert!(
        readme.contains("hourglass") || readme.contains("Hourglass") || readme.contains("rkr_"),
        "readme_src must mention hourglass multi-language ABI"
    );
    assert!(
        readme.contains("Cachegrind")
            && (readme.contains("compare_readers") || readme.contains("sscanf") || readme.contains("ASE")),
        "readme_src speed section must cite Cachegrind and a CON peer bench"
    );
    assert!(
        readme.contains("atom_id") || readme.contains("=atom_id=") || readme.contains("Round-trip"),
        "readme_src must state atom_id / round-trip checkpoint fields"
    );
    assert!(
        readme.contains("Objective") || readme.contains("primary goal") || readme.contains("Portable"),
        "readme_src must state objective positively"
    );
    assert_no_defensive_tells(&readme, "readme_src.org");
}
