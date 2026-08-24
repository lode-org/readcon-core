//! Structural gates for CI permission split, release action pins,
//! language-package version lockstep, and wrap source_hash lockstep.

use std::path::PathBuf;
use std::process::Command;

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn run_gate(rel: &str) {
    let script = repo_root().join(rel);
    assert!(script.is_file(), "missing {}", script.display());
    let status = Command::new("bash")
        .arg(&script)
        .current_dir(repo_root())
        .status()
        .unwrap_or_else(|e| panic!("failed to spawn {}: {e}", script.display()));
    assert!(
        status.success(),
        "{rel} failed (exit {:?})",
        status.code()
    );
}

#[test]
fn ci_docs_and_coverage_keep_oidc_off_pr_jobs() {
    run_gate("scripts/check_ci_permissions.sh");
}

#[test]
fn release_workflow_pins_actions_and_verifies_installers() {
    run_gate("scripts/check_release_pins.sh");
}

#[test]
fn language_package_versions_match_cargo() {
    run_gate("scripts/check_version_lockstep.sh");
}

#[test]
fn rpc_feature_has_no_ucx_dependency() {
    run_gate("scripts/check_rpc_no_ucx.sh");
}

#[test]
fn wrap_source_hash_matches_published_cxx_tarball() {
    run_gate("scripts/check_wrap_hash.sh");
}
