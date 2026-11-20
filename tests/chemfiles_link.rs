//! Symbol and include-dir checks for the chemfiles scan shim.
//!
//! The live COW and cxx11 archives are exercised by `chemfiles_scan` under
//! `--features chemfiles` and under a from-source or download-fallback build.

#[path = "../support/chemfiles_link.rs"]
mod chemfiles_link;

use std::fs;
use std::path::PathBuf;

use chemfiles_link::StringAbi;

#[test]
fn cow_symbols_select_the_old_string_abi() {
    let text = "_ZN9chemfiles22find_in_periodic_tableERKSs\n";
    assert_eq!(chemfiles_link::classify_symbol_text(text), StringAbi::Cow);
    assert!(chemfiles_link::library_file_names().contains(&"libchemfiles.a"));
}

#[test]
fn cxx11_symbols_keep_the_compiler_string_abi() {
    let text = "_ZN9chemfiles4AtomC1ERKNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEEE\n";
    assert_eq!(chemfiles_link::classify_symbol_text(text), StringAbi::Cxx11);
}

#[test]
fn cxx11_wins_when_both_markers_are_present() {
    let text = "ERKSs\nNSt7__cxx1112basic_string\n";
    assert_eq!(chemfiles_link::classify_symbol_text(text), StringAbi::Cxx11);
}

#[test]
fn an_unrecognised_library_does_not_force_the_old_abi() {
    assert_eq!(
        chemfiles_link::classify_symbol_text("no string symbols here\n"),
        StringAbi::Unknown
    );
}

#[test]
fn override_include_dir_supplies_exports_h() {
    let root = PathBuf::from(format!("/tmp/rc-chfl-inc-{}", std::process::id()));
    let _ = fs::remove_dir_all(&root);
    let include = root.join("include");
    fs::create_dir_all(include.join("chemfiles")).unwrap();
    fs::write(include.join("chemfiles/exports.h"), "/* generated */\n").unwrap();
    let from_include = chemfiles_link::include_dir_holding_exports(&include).unwrap();
    assert!(from_include.join("chemfiles/exports.h").is_file());
    let from_prefix = chemfiles_link::include_dir_holding_exports(&root).unwrap();
    assert_eq!(from_prefix, include);
    assert!(chemfiles_link::include_dir_holding_exports(&root.join("missing")).is_none());
    let _ = fs::remove_dir_all(&root);
}
