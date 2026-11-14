//! The Python and Rust frame writers stay byte-identical.

#[path = "../bench/h2h/frames_guard.rs"]
mod frames_guard;

use std::fs;
use std::path::PathBuf;
use std::process::Command;

#[test]
fn python_and_rust_frames_are_byte_identical() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let one = fs::read_to_string(root.join("resources/test/cuh2.con")).unwrap();
    let rust = frames_guard::distinct_frames(&one, 3);
    let script = r#"
import pathlib, sys
sys.path.insert(0, "bench/h2h")
from frames_guard import distinct_frames
text = pathlib.Path("resources/test/cuh2.con").read_text()
sys.stdout.write(distinct_frames(text, 3))
"#;
    let output = Command::new("python3")
        .current_dir(&root)
        .arg("-c")
        .arg(script)
        .output()
        .expect("python3");
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let python = String::from_utf8(output.stdout).unwrap();
    assert_eq!(rust.len(), python.len());
    assert_eq!(rust, python);
}
