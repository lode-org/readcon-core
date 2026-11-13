//! The metatensor install locator has to see both Cargo build-directory layouts.
//!
//! Cargo 1.100 nests the build-script hash (`build/metatensor-sys/<hash>/`).
//! Older Cargo used a hyphen suffix (`build/metatensor-sys-<hash>/`). The
//! hyphen-suffix scan is what `build.rs` used to do; it misses the nested
//! directory, which is why a rebuild still did not write
//! `readcon-metatensor.env`.

use std::fs;
use std::path::{Path, PathBuf};

#[path = "../support/metatensor_install.rs"]
mod metatensor_paths;

use metatensor_paths::locate;

fn touch(path: &Path) {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).unwrap();
    }
    fs::write(path, b"").unwrap();
}

fn hyphen_suffix_prefixes(build_root: &Path) -> Vec<PathBuf> {
    fs::read_dir(build_root)
        .unwrap()
        .flatten()
        .filter(|entry| {
            entry
                .file_name()
                .to_string_lossy()
                .starts_with("metatensor-sys-")
        })
        .map(|entry| entry.path())
        .collect()
}

#[test]
fn cargo_1_100_hash_directory_is_invisible_to_the_hyphen_suffix_scan() {
    let root = tempfile::tempdir().unwrap();
    let prefix = root.path().join("metatensor-sys").join("69ac7c64b1c90a14");
    let out = prefix.join("out");
    touch(&out.join("include").join("metatensor.h"));
    touch(&out.join("lib").join("libmetatensor.so"));
    let stdout = prefix.join("run").join("stdout");
    fs::create_dir_all(stdout.parent().unwrap()).unwrap();
    fs::write(
        &stdout,
        format!(
            "-- Installing: {lib}\ncargo:root={out}\ncargo:rustc-link-search=native={lib}\n",
            lib = out.join("lib").display(),
            out = out.display(),
        ),
    )
    .unwrap();

    assert!(
        hyphen_suffix_prefixes(root.path()).is_empty(),
        "the pre-1.100 scan must miss build/metatensor-sys/<hash>/"
    );
    let install = locate(root.path()).expect("nested hash directory");
    assert_eq!(install.include_dir, out.join("include"));
    assert_eq!(install.lib_dir, out.join("lib"));
    assert!(install.shared);
    assert_eq!(install.output_file, Some(stdout));
}

#[test]
fn hyphen_suffix_directory_still_resolves() {
    let root = tempfile::tempdir().unwrap();
    let out = root
        .path()
        .join("metatensor-sys-aaaaaaaaaaaaaaaa")
        .join("out");
    touch(&out.join("include").join("metatensor.h"));
    touch(&out.join("lib").join("libmetatensor.so"));

    assert_eq!(hyphen_suffix_prefixes(root.path()).len(), 1);
    let install = locate(root.path()).expect("legacy directory");
    assert_eq!(install.lib_dir, out.join("lib"));
    assert_eq!(install.include_dir, out.join("include"));
}

#[test]
fn link_search_in_the_build_script_output_wins_over_a_guessed_lib_dir() {
    let root = tempfile::tempdir().unwrap();
    let prefix = root.path().join("metatensor-sys").join("abc123");
    let out = prefix.join("out");
    let lib64 = out.join("lib64");
    touch(&out.join("include").join("metatensor.h"));
    touch(&lib64.join("libmetatensor.so"));
    fs::write(
        prefix.join("output"),
        format!(
            "cargo:rustc-link-search=native={}\ncargo:root={}\n",
            lib64.display(),
            out.display()
        ),
    )
    .unwrap();

    let install = locate(root.path()).expect("output link search");
    assert_eq!(install.lib_dir, lib64);
    assert!(install.shared);
}

#[test]
fn shared_install_is_preferred_over_a_static_archive() {
    let root = tempfile::tempdir().unwrap();
    let static_out = root
        .path()
        .join("metatensor-sys")
        .join("1111111111111111")
        .join("out");
    touch(&static_out.join("include").join("metatensor.h"));
    touch(&static_out.join("lib").join("libmetatensor.a"));
    let shared_out = root
        .path()
        .join("metatensor-sys")
        .join("2222222222222222")
        .join("out");
    touch(&shared_out.join("include").join("metatensor.h"));
    touch(&shared_out.join("lib").join("libmetatensor.so"));

    let install = locate(root.path()).expect("shared install");
    assert_eq!(install.lib_dir, shared_out.join("lib"));
    assert!(install.shared);
}
