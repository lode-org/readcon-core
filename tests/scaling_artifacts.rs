//! Bench logs that the lint job reads must be well-formed text files.

use std::fs;
use std::path::PathBuf;

#[test]
fn scaling_json_files_end_with_a_newline() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("bench/h2h/scaling");
    let mut seen = 0usize;
    for entry in fs::read_dir(&root).unwrap_or_else(|err| panic!("read {}: {err}", root.display()))
    {
        let entry = entry.expect("dir entry");
        if !entry.path().is_dir() {
            continue;
        }
        for file in fs::read_dir(entry.path()).expect("round dir") {
            let file = file.expect("file");
            let path = file.path();
            if path.extension().and_then(|ext| ext.to_str()) != Some("json") {
                continue;
            }
            let bytes =
                fs::read(&path).unwrap_or_else(|err| panic!("read {}: {err}", path.display()));
            assert!(
                bytes.ends_with(b"\n"),
                "{} does not end with a newline",
                path.display()
            );
            seen += 1;
        }
    }
    assert!(seen >= 1, "expected scaling json logs");
}

#[test]
fn reader_exchange_log_has_no_trailing_whitespace() {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("bench/h2h/reader-exchange/perf21/reader-exchange.log");
    let text =
        fs::read_to_string(&path).unwrap_or_else(|err| panic!("read {}: {err}", path.display()));
    for (number, line) in text.lines().enumerate() {
        assert!(
            !line.ends_with(' ') && !line.ends_with('\t'),
            "{}:{} has trailing whitespace",
            path.display(),
            number + 1
        );
    }
}
