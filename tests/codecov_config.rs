//! Structural gate: multi-flag Codecov wiring for rust/python/julia/fortran.
//!
//! Drives `scripts/check_codecov_config.sh` so CI/config regressions fail
//! `cargo test` rather than only showing up after a silent dashboard gap.

use std::path::PathBuf;
use std::process::Command;

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

#[test]
fn codecov_multi_flag_config_is_wired() {
    let script = repo_root().join("scripts/check_codecov_config.sh");
    assert!(
        script.is_file(),
        "missing {}; expected structural Codecov gate",
        script.display()
    );
    let status = Command::new("bash")
        .arg(&script)
        .current_dir(repo_root())
        .status()
        .expect("failed to spawn scripts/check_codecov_config.sh");
    assert!(
        status.success(),
        "scripts/check_codecov_config.sh failed (exit {:?})",
        status.code()
    );
}

#[test]
fn codecov_yml_declares_binding_flags() {
    let yml = std::fs::read_to_string(repo_root().join("codecov.yml"))
        .expect("read codecov.yml");
    for flag in ["rust", "python", "julia", "fortran"] {
        assert!(
            yml.contains(&format!("name: {flag}")) || yml.contains(&format!("name: {flag}\n")),
            "codecov.yml missing individual flag {flag}"
        );
    }
    assert!(yml.contains("carryforward: true"));
    assert!(yml.contains("informational: true"));
    assert!(yml.contains("flags"));
}

#[test]
fn coverage_workflow_uploads_each_flag_soft_fail() {
    let wf = std::fs::read_to_string(repo_root().join(".github/workflows/coverage.yml"))
        .expect("read coverage.yml");
    // Active (uncommented) uploads
    for flag in ["rust", "python", "julia", "fortran"] {
        let needle = format!("flags: {flag}");
        assert!(
            wf.lines().any(|l| l.contains(&needle) && !l.trim_start().starts_with('#')),
            "coverage.yml missing active upload flags: {flag}"
        );
    }
    assert!(wf.contains("codecov/codecov-action"));
    assert!(wf.contains("fail_ci_if_error: false"));
    assert!(wf.contains("secrets.CODECOV_TOKEN"));
    assert!(wf.contains("cargo llvm-cov"));
    assert!(wf.contains("pytest"));
    assert!(wf.contains("Coverage")); // Julia Coverage.jl
    assert!(wf.contains("lcov"));
}
