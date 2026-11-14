/// Integration-test scratch. Cargo sets `CARGO_TARGET_TMPDIR` for these
/// binaries. A direct run of the test binary falls back to `build/test`.
pub fn scratch() -> std::path::PathBuf {
    let dir = std::env::var_os("CARGO_TARGET_TMPDIR")
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|| {
            std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("build")
                .join("test")
        });
    std::fs::create_dir_all(&dir).expect("scratch directory");
    dir
}
