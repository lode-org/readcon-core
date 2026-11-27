//! Symbol and include-dir checks for the chemfiles scan shim.
//!
//! The live COW and cxx11 archives are exercised by `chemfiles_scan` under
//! `--features chemfiles` and under a from-source or download-fallback build.

#[path = "../support/chemfiles_link.rs"]
mod chemfiles_link;

use std::fs;
use std::path::{Path, PathBuf};

use chemfiles_link::{AbiChoice, CppStdlib, LinkKind, NmStatus, StringAbi};

#[test]
fn cow_symbols_select_the_old_string_abi() {
    let text = "_ZN9chemfiles22find_in_periodic_tableERKSs\n";
    assert_eq!(chemfiles_link::classify_symbol_text(text), StringAbi::Cow);
    assert!(chemfiles_link::library_file_names(LinkKind::Static).contains(&"libchemfiles.a"));
}

#[test]
fn cxx11_symbols_keep_the_compiler_string_abi() {
    let text = "_ZN9chemfiles4AtomC1ERKNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEEE\n";
    assert_eq!(chemfiles_link::classify_symbol_text(text), StringAbi::Cxx11);
}

#[test]
fn both_markers_are_a_conflict() {
    let text = "ERKSs\nNSt7__cxx1112basic_string\n";
    assert_eq!(
        chemfiles_link::classify_symbol_text(text),
        StringAbi::Conflict
    );
    assert_eq!(
        chemfiles_link::choose_string_abi(CppStdlib::Libstdcxx, NmStatus::Ok, StringAbi::Conflict),
        AbiChoice::Fatal
    );
}

#[test]
fn the_last_cxx11_abi_define_wins() {
    let groups = vec![
        "-D_GLIBCXX_USE_CXX11_ABI=0 -O2".to_string(),
        "-D_GLIBCXX_USE_CXX11_ABI=1".to_string(),
    ];
    let flags = chemfiles_link::split_cxxflags(&groups);
    assert_eq!(
        chemfiles_link::last_cxx11_abi_define(flags.iter().map(String::as_str)),
        Some("1")
    );
    assert_eq!(
        chemfiles_link::last_cxx11_abi_define(["-D_GLIBCXX_USE_CXX11_ABI"]),
        Some("1")
    );
    assert_eq!(chemfiles_link::last_cxx11_abi_define(["-O2"]), None);
}

#[test]
fn cxxflags_keys_append_the_plain_variable_first() {
    let keys =
        chemfiles_link::cxxflags_env_keys("x86_64-unknown-linux-gnu", "x86_64-unknown-linux-gnu");
    assert_eq!(keys[0], "CXXFLAGS");
    assert_eq!(
        keys.last().map(String::as_str),
        Some("CXXFLAGS_x86_64-unknown-linux-gnu")
    );
    let cross =
        chemfiles_link::cxxflags_env_keys("aarch64-unknown-linux-gnu", "x86_64-unknown-linux-gnu");
    assert_eq!(cross[1], "TARGET_CXXFLAGS");
}

#[test]
fn an_unrecognised_library_does_not_force_the_old_abi() {
    assert_eq!(
        chemfiles_link::classify_symbol_text("no string symbols here\n"),
        StringAbi::Unknown
    );
}

#[test]
fn missing_nm_is_fatal_for_libstdcxx() {
    assert_eq!(
        chemfiles_link::choose_string_abi(
            CppStdlib::Libstdcxx,
            NmStatus::SpawnFailed,
            StringAbi::Unknown
        ),
        AbiChoice::Fatal
    );
    assert_eq!(
        chemfiles_link::choose_string_abi(CppStdlib::Libstdcxx, NmStatus::NonZero, StringAbi::Cow),
        AbiChoice::Fatal
    );
    assert_eq!(
        chemfiles_link::choose_string_abi(CppStdlib::Libstdcxx, NmStatus::Ok, StringAbi::Unknown),
        AbiChoice::Fatal
    );
}

#[test]
fn msvc_and_libcxx_skip_nm() {
    assert_eq!(
        chemfiles_link::choose_string_abi(
            CppStdlib::Msvc,
            NmStatus::SpawnFailed,
            StringAbi::Unknown
        ),
        AbiChoice::Foreign
    );
    assert_eq!(
        chemfiles_link::choose_string_abi(CppStdlib::Libcxx, NmStatus::NonZero, StringAbi::Unknown),
        AbiChoice::Foreign
    );
    assert_eq!(
        chemfiles_link::choose_string_abi(CppStdlib::Libstdcxx, NmStatus::Ok, StringAbi::Cow),
        AbiChoice::Cow
    );
}

#[test]
fn nm_override_uses_the_explicit_tool() {
    let keys = chemfiles_link::nm_env_keys("x86_64-unknown-linux-gnu", "x86_64-unknown-linux-gnu");
    assert_eq!(
        keys,
        vec![
            "NM_x86_64-unknown-linux-gnu".to_string(),
            "NM_x86_64_unknown_linux_gnu".to_string(),
            "HOST_NM".to_string(),
            "NM".to_string(),
        ]
    );
    let cross =
        chemfiles_link::nm_env_keys("aarch64-unknown-linux-gnu", "x86_64-unknown-linux-gnu");
    assert_eq!(cross[2], "TARGET_NM");
    let chosen = chemfiles_link::first_nm_override(&keys, |key| {
        if key == "NM" {
            Some("/definitely/missing/nm")
        } else {
            None
        }
    });
    assert_eq!(chosen, Some("/definitely/missing/nm"));
}

#[test]
fn dylib_link_does_not_select_the_static_archive() {
    let dir = tempfile::tempdir().unwrap();
    fs::write(dir.path().join("libchemfiles.a"), b"static").unwrap();
    fs::write(dir.path().join("libchemfiles.so"), b"shared").unwrap();
    let dirs = vec![dir.path().to_path_buf()];
    let shared = chemfiles_link::linked_library(&dirs, LinkKind::Dynamic).unwrap();
    assert_eq!(shared.file_name().unwrap(), "libchemfiles.so");
    let archive = chemfiles_link::linked_library(&dirs, LinkKind::Static).unwrap();
    assert_eq!(archive.file_name().unwrap(), "libchemfiles.a");
}

#[test]
fn libdir_and_root_hide_a_stale_chemfiles_sys_output() {
    let stale = Path::new("stale-chemfiles-sys/out");
    let live = Path::new("live-root");
    let libdir = Path::new("override-lib");
    let dirs = chemfiles_link::library_search_dirs(Some(libdir), Some(stale), None);
    assert_eq!(dirs, vec![PathBuf::from(libdir)]);
    assert!(!dirs.iter().any(|dir| dir.starts_with(stale)));
    let dirs = chemfiles_link::library_search_dirs(None, Some(live), Some(stale));
    assert_eq!(
        dirs,
        vec![
            PathBuf::from("live-root/lib"),
            PathBuf::from("live-root/lib64")
        ]
    );
    let kind = chemfiles_link::link_kind_from_config(
        "[target.x86_64-unknown-linux-gnu.chemfiles]\nrustc-link-lib = [\"dylib=chemfiles\"]\n",
        "x86_64-unknown-linux-gnu",
    );
    assert_eq!(kind, Some(LinkKind::Dynamic));
    let kind = chemfiles_link::link_kind_from_config(
        "[target.'cfg(unix)'.chemfiles]\nrustc-link-lib = [\"static=chemfiles\"]\n",
        "x86_64-unknown-linux-gnu",
    );
    assert_eq!(kind, Some(LinkKind::Static));
}

#[test]
fn override_include_dir_supplies_exports_h() {
    let root = tempfile::tempdir().unwrap();
    let include = root.path().join("include");
    fs::create_dir_all(include.join("chemfiles")).unwrap();
    fs::write(include.join("chemfiles/exports.h"), "/* generated */\n").unwrap();
    let from_include = chemfiles_link::include_dir_holding_exports(&include).unwrap();
    assert!(from_include.join("chemfiles/exports.h").is_file());
    let from_prefix = chemfiles_link::include_dir_holding_exports(root.path()).unwrap();
    assert_eq!(from_prefix, include);
    assert!(chemfiles_link::include_dir_holding_exports(&root.path().join("missing")).is_none());
    let from_libdir =
        chemfiles_link::include_from_metadata(None, None, Some(&root.path().join("lib")));
    assert_eq!(from_libdir.unwrap(), include);
    let from_root = chemfiles_link::include_from_metadata(None, Some(root.path()), None);
    assert_eq!(from_root.unwrap(), include);
}
