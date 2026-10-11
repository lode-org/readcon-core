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

fn write_executable(path: &std::path::Path, body: &str) {
    use std::os::unix::fs::PermissionsExt;

    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).unwrap();
    }
    std::fs::write(path, body).unwrap();
    let mut perms = std::fs::metadata(path).unwrap().permissions();
    perms.set_mode(0o755);
    std::fs::set_permissions(path, perms).unwrap();
}

#[test]
fn missing_checksum_asset_fails() {
    let root = repo_root();
    let bin = root.join("target").join("fake-curl-missing-sha");
    write_executable(&bin.join("curl"), "#!/bin/sh\nexit 22\n");
    let output = Command::new("bash")
        .arg(root.join("scripts/check_wrap_hash.sh"))
        .current_dir(&root)
        .env(
            "PATH",
            format!(
                "{}:{}",
                bin.display(),
                std::env::var("PATH").unwrap_or_default()
            ),
        )
        .output()
        .unwrap();
    let err = String::from_utf8_lossy(&output.stderr);
    assert!(
        !output.status.success(),
        "a missing .sha256 asset must fail the wrap check\n{err}"
    );
    assert!(
        err.contains("checksum is missing"),
        "expected a missing-checksum error, got {err}"
    );
}

#[test]
fn wrap_pin_must_match_the_staged_and_uploaded_asset() {
    let root = repo_root();
    let dir = root.join("target").join("wrap-asset-gate");
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let pin = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
    let wrap = dir.join("wrap");
    std::fs::write(&wrap, format!("source_hash = sha256:{pin}\n")).unwrap();
    let good = dir.join("good.tar.gz");
    std::fs::write(&good, b"cxx-bytes").unwrap();
    let good_hash = {
        let digest = Command::new("sha256sum").arg(&good).output().unwrap();
        String::from_utf8(digest.stdout)
            .unwrap()
            .split_whitespace()
            .next()
            .unwrap()
            .to_string()
    };
    let pinned = dir.join("pinned.wrap");
    std::fs::write(&pinned, format!("source_hash = sha256:{good_hash}\n")).unwrap();
    let dest = dir.join("dest");
    let ok = Command::new("bash")
        .arg(root.join("scripts/check_release_wrap_asset.sh"))
        .arg(&dest)
        .env("CHECK_WRAP_FILE", &pinned)
        .env("CHECK_WRAP_TARBALL", &good)
        .status()
        .unwrap();
    assert!(ok.success(), "a tarball that matches the pin must pass");
    assert!(dest.join("readcon-core-cxx-0.17.0.tar.gz").is_file());

    let bad_dest = dir.join("bad-dest");
    let bad = Command::new("bash")
        .arg(root.join("scripts/check_release_wrap_asset.sh"))
        .arg(&bad_dest)
        .env("CHECK_WRAP_FILE", &wrap)
        .env("CHECK_WRAP_TARBALL", &good)
        .status()
        .unwrap();
    assert!(!bad.success(), "a tarball that misses the pin must fail");
    assert!(!bad_dest.join("readcon-core-cxx-0.17.0.tar.gz").exists());

    let gh_dir = dir.join("bin");
    write_executable(
        &gh_dir.join("gh"),
        "#!/bin/sh\nprev=\nfor a in \"$@\"; do\n  if [ \"$prev\" = --dir ]; then out=\"$a\"; fi\n  if [ \"$prev\" = --pattern ]; then name=\"$a\"; fi\n  prev=\"$a\"\ndone\ncp \"$FAKE_RELEASE_ASSET\" \"$out/$name\"\n",
    );
    let confirm = Command::new("bash")
        .arg(root.join("scripts/check_release_wrap_asset.sh"))
        .arg("--confirm")
        .arg("v0.0.0-test")
        .env("CHECK_WRAP_FILE", &pinned)
        .env("FAKE_RELEASE_ASSET", &good)
        .env(
            "PATH",
            format!(
                "{}:{}",
                gh_dir.display(),
                std::env::var("PATH").unwrap_or_default()
            ),
        )
        .status()
        .unwrap();
    assert!(
        confirm.success(),
        "uploaded bytes that match the pin must pass"
    );
    let rejected = Command::new("bash")
        .arg(root.join("scripts/check_release_wrap_asset.sh"))
        .arg("--confirm")
        .arg("v0.0.0-test")
        .env("CHECK_WRAP_FILE", &wrap)
        .env("FAKE_RELEASE_ASSET", &good)
        .env(
            "PATH",
            format!(
                "{}:{}",
                gh_dir.display(),
                std::env::var("PATH").unwrap_or_default()
            ),
        )
        .status()
        .unwrap();
    assert!(
        !rejected.success(),
        "uploaded bytes that miss the pin must fail"
    );
}
