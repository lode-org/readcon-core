use std::path::PathBuf;

// Kanged and expanded from [1]
macro_rules! test_case {
    ($fname:expr) => {
        Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("resources")
            .join("test")
            .join($fname)
    };
}

// References
// [1]: https://stackoverflow.com/a/74550371/1895378
