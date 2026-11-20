/// Integration-test scratch. Cargo bakes `CARGO_TARGET_TMPDIR` into these
/// binaries while it compiles them. The variable is not set in the test
/// process, and this does not fall back into the source tree.
pub fn scratch() -> std::path::PathBuf {
    let dir = std::path::PathBuf::from(env!("CARGO_TARGET_TMPDIR"));
    std::fs::create_dir_all(&dir).expect("scratch directory");
    dir
}
