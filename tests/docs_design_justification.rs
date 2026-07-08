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
        // anti-product carve-outs (do not invent reasons not to adopt)
        "just another text",
        "upside is smaller",
        "never join a campaign",
        "when not to use",
        "not worth migrating",
        "MD tape replacement",
        "universal MD tape",
        "hand-rolled is fine",
        "single-code XYZ is fine",
        // historical FAQ kill-list (never reintroduce)
        "When should I use HDF5",
        "Use HDF5 for",
        "Use ~con~ for:",
        "Use con for:",
        "long-term archival and analysis",
        "con-to-data pipeline",
        "~con~-to-data pipeline",
        "complement each other",
        "When should I use CON vs XYZ",
        "XYZ/extXYZ are suitable when",
        "only positions (and optionally a lattice)",
        "millions of frames, billions of atoms",
        "< 10k frames",
        "10-30x faster",
        "10–30×",
        "HDF5 handles long-term",
        "XYZ remains appropriate for minimal",
        "How does CON + readcon-db compare to XYZ",
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
    // no format bake-off / anti-product "use X instead" sections
    assert!(!t.contains("How does CON relate to H5MD"));
    assert!(!t.contains("* CON and H5MD"));
    assert!(!t.contains("When should I use HDF5"));
    assert!(!t.contains("When should I use CON vs XYZ"));
    assert!(
        t.contains("readcon-db")
            && (t.contains("Where do large campaigns") || t.contains("campaign store")),
        "FAQ must route corpora to readcon-db, not invent HDF5 as product archival"
    );
    assert!(
        t.contains("chemfiles")
            && (t.contains("ingress") || t.contains("How do XYZ") || t.contains("foreign")),
        "FAQ must describe chemfiles as ingress into CON"
    );
    assert_no_ai_tells(&t, "faq.org");
}

#[test]
fn product_docs_ban_anti_product_carveouts() {
    // Entry surfaces that must never reintroduce origin/main kill-list copy.
    for name in [
        "faq.org",
        "migrate.org",
        "benchmarks.org",
        "getting-started.org",
        "index.org",
        "chemfiles-explain.org",
    ] {
        assert_no_ai_tells(&read(name), name);
    }
    assert_no_ai_tells(&read_repo("readme_src.org"), "readme_src.org");
}

#[test]
fn readcon_db_surface_has_docs_and_api_destinations() {
    // Campaign entry points must name hosted package docs + docs.rs API, not
    // install-only with no API destination.
    let pages = "https://lode-org.github.io/readcon-db/";
    let docsrs = "https://docs.rs/readcon-db";
    for (label, text) in [
        ("faq.org", read("faq.org")),
        ("migrate.org", read("migrate.org")),
        ("getting-started.org", read("getting-started.org")),
        ("index.org", read("index.org")),
        ("readme_src.org", read_repo("readme_src.org")),
        ("docs/source/conf.py", read_repo("docs/source/conf.py")),
    ] {
        assert!(
            text.contains("readcon-db") || text.contains("readcon_db"),
            "{label} must mention the campaign package"
        );
        assert!(
            text.contains(pages) || text.contains("lode-org.github.io/readcon-db"),
            "{label} must link hosted readcon-db docs"
        );
        assert!(
            text.contains(docsrs) || text.contains("docs.rs/readcon-db"),
            "{label} must link docs.rs readcon-db API"
        );
    }
    let conf = read_repo("docs/source/conf.py");
    assert!(
        conf.contains("readcon-db Rust API") || conf.contains("docs.rs/readcon-db"),
        "Sphinx nav must surface readcon-db Rust API"
    );
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
    assert!(t.contains("Install") || t.contains("readcon"));
    assert!(
        t.contains("tutorial") || t.contains(":doc:`tutorial`") || t.contains("tutorial.org"),
        "getting-started must point at the One Good Tutorial"
    );
    assert!(
        t.contains("migrate") || t.contains("migrate.org"),
        "getting-started must point at migration how-to"
    );
    assert!(
        t.contains("Diátaxis") || t.contains("Diataxis") || t.contains("How-to") || t.contains("howto"),
        "getting-started should map Diátaxis destinations"
    );
    assert!(
        t.contains("chemfiles") || t.contains("hourglass") || t.contains("rkr_") || t.contains("readcon-db"),
        "getting-started should mention more of the stack than bare I/O"
    );
    assert_no_ai_tells(&t, "getting-started.org");
}

#[test]
fn one_good_tutorial_is_learning_oriented() {
    let t = read("tutorial.org");
    assert!(
        t.contains("learning-oriented") || t.contains("Diátaxis *tutorial*") || t.contains("One Good"),
        "tutorial.org must declare tutorial role"
    );
    assert!(
        t.contains("iter_con") || t.contains("read_first_frame"),
        "tutorial must use real Python CON I/O APIs"
    );
    assert!(
        t.contains("tiny_multi_cuh2.con") || t.contains("resources/test/"),
        "tutorial must use in-repo fixtures"
    );
    assert!(!t.contains("iter_frames"), "Python API is iter_con, not iter_frames");
    assert!(
        t.contains("run-tutorial-core") || t.contains("tutorial_core.py") || t.contains("org-babel"),
        "tutorial.org must point at the Org Babel CI runner"
    );
    assert_no_ai_tells(&t, "tutorial.org");
}

#[test]
fn tutorial_runners_exist_in_repo() {
    let root = repo_root();
    assert!(
        root.join("scripts/run-tutorial-core.sh").is_file(),
        "missing Org Babel tutorial script"
    );
    assert!(
        root.join("scripts/run-chemfiles-notebook.sh").is_file(),
        "missing Org Babel chemfiles notebook script"
    );
    let org = fs::read_to_string(root.join("docs/orgmode/tutorial.org")).unwrap();
    assert!(
        org.contains(":tangle ../notebooks/tutorial_core.py"),
        "tutorial.org must tangle Python blocks"
    );
    assert!(
        org.contains("run-tutorial-core.sh") || org.contains("org-babel"),
        "tutorial.org must document Babel CI path"
    );
    let nb = fs::read_to_string(root.join("docs/orgmode/chemfiles-notebook.org")).unwrap();
    assert!(nb.contains(":tangle ../notebooks/chemfiles_ingress.py"));
    let wf = fs::read_to_string(root.join(".github/workflows/ci_python.yml")).unwrap();
    assert!(
        wf.contains("run-tutorial-core.sh") && wf.contains("run-chemfiles-notebook.sh"),
        "ci_python.yml must invoke Org Babel tutorial scripts"
    );
    assert!(
        wf.contains("emacs-nox") || wf.contains("emacs"),
        "ci_python.yml must install emacs for org-babel-tangle"
    );
    let core_sh = fs::read_to_string(root.join("scripts/run-tutorial-core.sh")).unwrap();
    assert!(
        core_sh.contains("tangle drift") && !core_sh.contains("falling back"),
        "run-tutorial-core.sh must drift-check and must not soft-fallback"
    );
    let cf_sh = fs::read_to_string(root.join("scripts/run-chemfiles-notebook.sh")).unwrap();
    assert!(
        cf_sh.contains("tangle drift") && !cf_sh.contains("falling back"),
        "run-chemfiles-notebook.sh must drift-check and must not soft-fallback"
    );
    assert!(
        !cf_sh.contains("trying tangled script as fallback"),
        "run-chemfiles-notebook.sh must not silently re-run tangled script after Babel miss"
    );
}

#[test]
fn howto_is_task_oriented() {
    let t = read("howto.org");
    assert!(
        t.contains("how-to") || t.contains("How-to") || t.contains("Diátaxis *how-to*"),
        "howto.org must declare how-to role"
    );
    assert!(
        t.contains("Python") && (t.contains("Rust") || t.contains("C++")),
        "howto should cover multiple languages"
    );
    assert_no_ai_tells(&t, "howto.org");
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
    assert!(
        t.contains("ASV") && (t.contains("spyglass") || t.contains("asv-spyglass")),
        "benchmarks must document Python ASV + spyglass PR path"
    );
    assert!(
        t.contains("asv.conf.json") && t.contains("benchmarks/"),
        "benchmarks must name ASV config and suite path"
    );
    assert!(!t.contains("2.7M atoms/s"));
    assert!(
        !t.contains("rgam5terra") && !t.contains("9.2×") && !t.contains("3.3 ms"),
        "benchmarks must not paste host wall-clock snapshot tables as doctrine"
    );
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
    assert!(
        index.contains(":caption: Tutorials")
            && (index.contains(":caption: How-to guides") || index.contains(":caption: How-to"))
            && index.contains(":caption: Explanation")
            && index.contains(":caption: Reference"),
        "index toctree must follow Diátaxis quadrants"
    );
    assert!(
        index.contains("tutorial\n") || index.contains("   tutorial"),
        "index must list the core tutorial page"
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
    assert!(
        readme.contains("iter_con") && !readme.contains("iter_frames"),
        "readme must use real Python API iter_con"
    );
    assert!(
        readme.contains("tutorial.org") || readme.contains("One Good Tutorial"),
        "readme must point at the One Good Tutorial"
    );
    assert!(
        (readme.contains("convert") || readme.contains("Migrate"))
            && (readme.contains("atom_id") || readme.contains("=atom_id="))
            && (readme.contains("hourglass") || readme.contains("rkr_")),
        "readme must state migration/adopt benefits tied to shipped surface"
    );
    assert!(
        readme.contains("migrate.org") || readme.contains("convert structure"),
        "readme must point at convert CLI or migrate how-to"
    );
    assert!(
        readme.contains("compare_readers")
            && (readme.contains("ASV") || readme.contains("asv") || readme.contains("Cachegrind")),
        "readme must point at peer script compare_readers and CI measurement gates (ASV/Cachegrind), not host-diary wall-clock snapshots"
    );
    assert!(
        !readme.contains("3.3 ms") && !readme.contains("9.2×") && !readme.contains("rgam5terra"),
        "readme must not embed host wall-clock snapshot numbers as product doctrine"
    );
    assert!(!readme.contains("H5MD"));
    assert!(!readme.contains("XTC"));
    assert_no_ai_tells(&readme, "readme_src.org");

    // GitHub README must link on-disk org sources (ox-md rewrites file:…org → .md)
    let readme_md = read_repo("README.md");
    assert!(
        !readme_md.contains("docs/orgmode/") || !has_orgmode_md_href(&readme_md),
        "README.md must not link docs/orgmode/*.md (only .org files exist on disk)"
    );
    for needle in [
        "docs/orgmode/spec.org",
        "docs/orgmode/benchmarks.org",
        "docs/orgmode/tutorial.org",
    ] {
        assert!(
            readme_md.contains(needle),
            "README.md must link existing {needle}"
        );
    }
}

fn has_orgmode_md_href(t: &str) -> bool {
    // Match markdown (docs/orgmode/foo.md) or bare docs/orgmode/foo.md paths.
    t.contains("docs/orgmode/")
        && t.lines().any(|line| {
            line.contains("docs/orgmode/")
                && line.contains(".md")
                && line
                    .split("docs/orgmode/")
                    .skip(1)
                    .any(|rest| rest.split(|c: char| c == ')' || c == '"' || c.is_whitespace())
                        .next()
                        .is_some_and(|p| p.ends_with(".md")))
        })
}
