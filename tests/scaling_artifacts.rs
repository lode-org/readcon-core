//! Bench logs that the lint job reads must be well-formed text files.

use std::fs;
use std::path::{Path, PathBuf};

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
fn scaling_text_files_end_with_one_newline() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("bench/h2h/scaling");
    let mut seen = 0usize;
    visit_scaling_text(&root, &mut seen);
    assert!(seen >= 1, "expected scaling text files");
}

#[test]
fn only_the_recorded_mpi_pwrite_directory_is_exempt() {
    let keep = Path::new("bench/h2h/scaling/v0.23.3/mpi-pwrite/logs/store-ab-1-unset.log");
    let other = Path::new("bench/h2h/scaling/v0.23.3/other/note.txt");
    assert!(under_recorded_mpi_pwrite(keep));
    assert!(!under_recorded_mpi_pwrite(other));
    assert!(!under_recorded_mpi_pwrite(Path::new(
        "bench/h2h/formats/v0.23.3/1k"
    )));
}

fn under_recorded_mpi_pwrite(path: &Path) -> bool {
    let marker = ["bench", "h2h", "scaling", "v0.23.3", "mpi-pwrite"];
    let parts: Vec<_> = path
        .components()
        .filter_map(|component| component.as_os_str().to_str())
        .collect();
    parts.windows(marker.len()).any(|window| window == marker)
}

fn visit_scaling_text(dir: &Path, seen: &mut usize) {
    for entry in fs::read_dir(dir).unwrap_or_else(|err| panic!("read {}: {err}", dir.display())) {
        let path = entry.expect("dir entry").path();
        if path.is_dir() {
            // These store logs were measured without a final newline.
            if under_recorded_mpi_pwrite(&path) {
                continue;
            }
            visit_scaling_text(&path, seen);
            continue;
        }
        let ext = path.extension().and_then(|ext| ext.to_str());
        if !matches!(ext, Some("json" | "txt" | "log" | "tsv")) {
            continue;
        }
        let bytes = fs::read(&path).unwrap_or_else(|err| panic!("read {}: {err}", path.display()));
        assert!(
            bytes.ends_with(b"\n") && !bytes.ends_with(b"\n\n"),
            "{} must end with one newline",
            path.display()
        );
        *seen += 1;
    }
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
