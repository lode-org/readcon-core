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
    assert!(status.success(), "{rel} failed (exit {:?})", status.code());
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

#[test]
fn release_upload_refuses_an_existing_asset() {
    use std::os::unix::fs::PermissionsExt;

    let root = repo_root();
    let bin = root.join("target").join("fake-gh-asset-guard");
    std::fs::create_dir_all(&bin).unwrap();
    let gh = bin.join("gh");
    std::fs::write(
        &gh,
        "#!/bin/sh\nprintf '%s\n' already.tar.gz already.tar.gz.sha256\n",
    )
    .unwrap();
    let mut perms = std::fs::metadata(&gh).unwrap().permissions();
    perms.set_mode(0o755);
    std::fs::set_permissions(&gh, perms).unwrap();

    let script = root.join("scripts/reject_existing_release_assets.sh");
    let path = format!(
        "{}:{}",
        bin.display(),
        std::env::var("PATH").unwrap_or_default()
    );
    let blocked = Command::new("bash")
        .arg(&script)
        .arg("v0.0.0-test")
        .arg("dist/already.tar.gz")
        .env("PATH", &path)
        .status()
        .unwrap();
    assert!(
        !blocked.success(),
        "an existing asset name must fail the upload"
    );

    let fresh = Command::new("bash")
        .arg(&script)
        .arg("v0.0.0-test")
        .arg("dist/new.tar.gz")
        .env("PATH", &path)
        .status()
        .unwrap();
    assert!(fresh.success(), "a new asset name must be allowed");
}

fn write_fake_curl(dir: &std::path::Path, tag_status: &str) {
    use std::os::unix::fs::PermissionsExt;

    std::fs::create_dir_all(dir).unwrap();
    let curl = dir.join("curl");
    std::fs::write(
        &curl,
        format!(
            "#!/bin/sh\nurl=\nfor a in \"$@\"; do url=\"$a\"; done\ncase \"$url\" in\n  *releases/tags/*) printf '{tag_status}'; exit 0 ;;\nesac\nexit 22\n"
        ),
    )
    .unwrap();
    let mut perms = std::fs::metadata(&curl).unwrap().permissions();
    perms.set_mode(0o755);
    std::fs::set_permissions(&curl, perms).unwrap();
}

#[test]
fn published_tag_without_checksum_asset_fails() {
    let root = repo_root();
    let present = root.join("target").join("fake-curl-tag-present");
    let absent = root.join("target").join("fake-curl-tag-absent");
    write_fake_curl(&present, "200");
    write_fake_curl(&absent, "404");
    let script = root.join("scripts/check_wrap_hash.sh");

    let missing = Command::new("bash")
        .arg(&script)
        .current_dir(&root)
        .env(
            "PATH",
            format!(
                "{}:{}",
                present.display(),
                std::env::var("PATH").unwrap_or_default()
            ),
        )
        .status()
        .unwrap();
    assert!(
        !missing.success(),
        "a published tag with no checksum asset must fail"
    );

    let unpublished = Command::new("bash")
        .arg(&script)
        .current_dir(&root)
        .env(
            "PATH",
            format!(
                "{}:{}",
                absent.display(),
                std::env::var("PATH").unwrap_or_default()
            ),
        )
        .status()
        .unwrap();
    assert!(
        unpublished.success(),
        "a missing tag may still lack checksum assets"
    );
}
