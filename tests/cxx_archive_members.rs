//! The cxx archive's changed members are library sources, and the
//! archive configures with Meson `-Dwith_tests=true`.
//!
//! A paper path that differs from the base archive still fails, because
//! it is not a library source.

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

fn archive_base(manifest: &Path) -> String {
    let output = Command::new("git")
        .args(["rev-parse", "HEAD^"])
        .current_dir(manifest)
        .output()
        .expect("git rev-parse");
    assert!(
        output.status.success(),
        "unable to derive a local archive base commit"
    );
    String::from_utf8(output.stdout)
        .expect("utf8 rev-parse")
        .trim()
        .to_string()
}

fn is_allowed_non_library_member(path: &str) -> bool {
    matches!(
        path,
        ".zenodo.json"
            | "CHANGELOG.md"
            | "Cargo.lock"
            | "README.md"
            | "VERSION"
            | "pyproject.toml"
            | "pyproject.chemfiles.toml"
            | "docs/source/architecture.rst"
            | "docs/source/benchmarks.rst"
            | "docs/source/contributing.rst"
            | "docs/orgmode/architecture.org"
            | "docs/orgmode/benchmarks.org"
            | "docs/orgmode/contributing.org"
            | "pixi.toml"
            | "readme_src.org"
            | ".github/workflows/c_lib_tarball.yml"
            | ".github/workflows/ci_clippy.yml"
            | "scripts/package-clib.sh"
    )
}

fn is_library_source(path: &str) -> bool {
    if path.starts_with("src/") || path.starts_with("include/") {
        return true;
    }
    // Crate manifest. The exclusion list lives here, and the wrap script
    // appends the workspace table before it packs the archive.
    // The manifest, and the pre-normalization copy cargo package embeds.
    // The exclusion commit edits this file. A later tree that already
    // excludes those paths will not show it as a change.
    if path == "Cargo.toml" || path == "Cargo.toml.orig" || path == "build.rs" {
        return true;
    }
    // C/C++ wrap surface the package script overlays onto the crate.
    path == "CMakeLists.txt"
        || path == "meson.build"
        || path == "meson_options.txt"
        || path == "scripts/meson_cargo_build.py"
        || path == "scripts/run_tsan_python_stress.sh"
        || path == "scripts/tsan_canary.py"
        || path == "scripts/tsan_python_launcher.c"
        || path.starts_with("tests/c/")
        || path.starts_with("cmake/")
        || path.starts_with("examples/")
        || path.starts_with("third_party/")
}

fn files_in(root: &Path) -> BTreeMap<String, Vec<u8>> {
    let mut out = BTreeMap::new();
    let mut stack = vec![root.to_path_buf()];
    while let Some(dir) = stack.pop() {
        for entry in fs::read_dir(&dir).unwrap() {
            let entry = entry.unwrap();
            let path = entry.path();
            if path.is_dir() {
                stack.push(path);
                continue;
            }
            let rel = path
                .strip_prefix(root)
                .unwrap()
                .to_string_lossy()
                .replace('\\', "/");
            out.insert(rel, fs::read(&path).unwrap());
        }
    }
    out
}

fn package(source: &Path, output: &Path) -> PathBuf {
    let _ = fs::remove_dir_all(output);
    fs::create_dir_all(output).unwrap();
    let status = Command::new("bash")
        .arg(source.join("scripts/package-cxx.sh"))
        .arg(output)
        .current_dir(source)
        .env("CARGO_NET_OFFLINE", "true")
        .env_remove("CARGO_TARGET_DIR")
        .env_remove("RUSTFLAGS")
        .env_remove("LD_PRELOAD")
        .env_remove("RUSTUP_TOOLCHAIN")
        .status()
        .expect("package-cxx");
    assert!(
        status.success(),
        "package-cxx failed for {}",
        source.display()
    );
    let mut archives: Vec<PathBuf> = fs::read_dir(output)
        .unwrap()
        .map(|entry| entry.unwrap().path())
        .filter(|path| path.extension().and_then(|ext| ext.to_str()) == Some("gz"))
        .collect();
    assert_eq!(
        archives.len(),
        1,
        "expected one archive in {}",
        output.display()
    );
    archives.pop().unwrap()
}

fn extract(archive: &Path, dest: &Path) -> PathBuf {
    let _ = fs::remove_dir_all(dest);
    fs::create_dir_all(dest).unwrap();
    let status = Command::new("tar")
        .args(["-xzf"])
        .arg(archive)
        .arg("-C")
        .arg(dest)
        .status()
        .expect("tar");
    assert!(status.success());
    let mut dirs: Vec<PathBuf> = fs::read_dir(dest)
        .unwrap()
        .map(|entry| entry.unwrap().path())
        .filter(|path| path.is_dir())
        .collect();
    assert_eq!(dirs.len(), 1);
    dirs.pop().unwrap()
}

#[test]
fn changed_archive_members_are_library_sources() {
    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    if !manifest.join(".git").exists() || !manifest.join("scripts/package-cxx.sh").exists() {
        eprintln!("skipping archive member check outside a git checkout with package-cxx.sh");
        return;
    }
    // Compile-time: Cargo sets this while it builds an integration test.
    // It is not in the test process environment.
    let scratch = std::path::PathBuf::from(env!("CARGO_TARGET_TMPDIR"))
        .join(format!("cxx-members-{}", std::process::id()));
    let _ = fs::remove_dir_all(&scratch);
    fs::create_dir_all(&scratch).unwrap();
    let base = archive_base(&manifest);
    let base_src = scratch.join("base");
    let head_src = scratch.join("head");
    let mut trees = Worktrees {
        manifest: manifest.clone(),
        paths: Vec::new(),
    };
    trees.add(&base_src, &base);
    trees.add(&head_src, "HEAD");
    let base_tree = extract(
        &package(&base_src, &scratch.join("base-out")),
        &scratch.join("base-tree"),
    );
    let head_tree = extract(
        &package(&head_src, &scratch.join("head-out")),
        &scratch.join("head-tree"),
    );
    let base_files = files_in(&base_tree);
    let head_files = files_in(&head_tree);
    let mut bad_changes = Vec::new();
    for (path, bytes) in &head_files {
        match base_files.get(path) {
            Some(old) if old == bytes => {}
            _ if is_library_source(path) => {}
            _ if is_allowed_non_library_member(path) => {}
            _ => bad_changes.push(path.clone()),
        }
    }
    assert!(
        bad_changes.is_empty(),
        "changed archive members are not library sources: {bad_changes:?}"
    );
    let mut dropped_library = Vec::new();
    for path in base_files.keys() {
        if !head_files.contains_key(path)
            && (path.starts_with("src/") || path.starts_with("include/"))
        {
            dropped_library.push(path.clone());
        }
    }
    assert!(
        dropped_library.is_empty(),
        "library sources missing from the package: {dropped_library:?}"
    );
    assert!(
        !head_files.contains_key("scripts/check_shared_library_identity.py"),
        "the shared-library identity helper must stay out of the archive"
    );
    configure_with_tests(&head_tree, &scratch.join("meson-head"));
    drop(trees);
    let _ = fs::remove_dir_all(&scratch);
}

/// A Meson consumer of the archive can configure its tests.
fn configure_with_tests(tree: &Path, build: &Path) {
    if Command::new("meson").arg("--version").output().is_err() {
        eprintln!("meson is not installed; skipping the -Dwith_tests=true configure");
        return;
    }
    let output = Command::new("meson")
        .arg("setup")
        .arg(build)
        .arg("-Dwith_tests=true")
        .current_dir(tree)
        .output()
        .expect("meson setup");
    assert!(
        output.status.success(),
        "meson setup -Dwith_tests=true failed on the archive:\n{}\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
}

struct Worktrees {
    manifest: PathBuf,
    paths: Vec<PathBuf>,
}

impl Worktrees {
    fn add(&mut self, dest: &Path, rev: &str) {
        let status = Command::new("git")
            .args(["worktree", "add", "--detach"])
            .arg(dest)
            .arg(rev)
            .current_dir(&self.manifest)
            .status()
            .expect("git worktree");
        assert!(status.success(), "worktree {rev}");
        self.paths.push(dest.to_path_buf());
    }
}

impl Drop for Worktrees {
    fn drop(&mut self) {
        for path in &self.paths {
            let _ = Command::new("git")
                .args(["worktree", "remove", "--force"])
                .arg(path)
                .current_dir(&self.manifest)
                .status();
        }
    }
}
