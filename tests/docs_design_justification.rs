//! Structural check: design rationale present in user docs (CPC-aligned substance).
//!
//! Guards positioning + honest speed language: definitive CON interchange,
//! hourglass ABI, Cachegrind / equal-geometry harnesses only for product claims.

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

#[test]
fn architecture_design_rationale() {
    let t = read("architecture.org");
    assert!(t.contains("hourglass") || t.contains("Hourglass") || t.contains("rkr_"));
    assert!(t.contains("readcon-db"));
    assert!(t.contains("authoritative") || t.contains("authority") || t.contains("CON text"));
    assert!(
        t.contains("definitive CON") || t.contains("interchange layer"),
        "architecture must state CON interchange positioning"
    );
    assert!(
        t.contains("Cachegrind") || t.contains("equal-geometry"),
        "architecture must point speed claims at real harnesses"
    );
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
fn faq_speed_cites_harnesses_not_vanity() {
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
        t.contains("SOTA") || t.contains("state-of-the-art") || t.contains("state of the art"),
        "FAQ must state domain-scoped SOTA / definitive interchange role"
    );
}

#[test]
fn getting_started_maps_when_to_use() {
    let t = read("getting-started.org");
    assert!(t.contains("When to use what") || t.contains("CON via"));
    assert!(
        t.contains("definitive CON") || t.contains("interchange layer"),
        "getting-started must position CON interchange"
    );
    assert!(
        t.contains("Cachegrind") || t.contains("equal-geometry") || t.contains("benchmarks"),
        "getting-started must point at measured speed evidence"
    );
}

#[test]
fn faq_why_another_format_still_present() {
    let t = read("faq.org");
    assert!(t.contains("Why another atomic structure format"));
}

#[test]
fn benchmarks_product_claim_hierarchy() {
    let t = read("benchmarks.org");
    assert!(
        t.contains("What counts as a product claim") || t.contains("product claim"),
        "benchmarks must define product-claim hierarchy"
    );
    assert!(t.contains("Cachegrind"));
    assert!(t.contains("equal-geometry") || t.contains("multiformat_traj"));
    assert!(
        t.contains("not headlines")
            || t.contains("not headline")
            || t.contains("Illustrative Criterion")
            || t.contains("illustrative / historical"),
        "Criterion / toy tables must be demoted from headlines"
    );
    assert!(
        !t.contains("2.7M atoms/s"),
        "must not promote toy 4-atom atoms/s as a bare product number"
    );
}

#[test]
fn index_and_readme_src_positioning() {
    let index = read("index.org");
    assert!(
        index.contains("Definitive CON") || index.contains("definitive CON"),
        "index hero/intro must state definitive CON interchange"
    );
    assert!(
        index.contains("Cachegrind") || index.contains("equal-geometry"),
        "index must mention honest speed harnesses"
    );

    let readme = read_repo("readme_src.org");
    assert!(
        readme.contains("definitive CON") || readme.contains("interchange layer"),
        "readme_src must state definitive CON interchange positioning"
    );
    assert!(
        readme.contains("Cachegrind") && readme.contains("equal-geometry"),
        "readme_src speed section must cite Cachegrind and equal-geometry"
    );
    assert!(
        readme.contains("Lossless CON") || readme.contains("lossless"),
        "readme_src must list lossless round-trip differentiator"
    );
    assert!(
        readme.contains("hourglass") || readme.contains("Hourglass") || readme.contains("rkr_"),
        "readme_src must mention hourglass multi-language ABI"
    );
}
