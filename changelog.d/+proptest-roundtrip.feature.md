`tests/proptest_roundtrip.rs` writes random frames as text, `.con`, `.convel` and gzip files, and as zstd with the `zstd` feature.
Each frame carries a random subset of the eight optional per-atom sections.
Every frame read back must equal the frame written.
