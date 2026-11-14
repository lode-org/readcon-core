// Link and runtime search path for libmetatensor.so.
// build.rs writes readcon-metatensor.env next to libreadcon_core.so.
// C, C++, and Fortran programs that link that shared library search the
// recorded directory when they link and when they run.

fn metatensor_lib_dirs(library_dirs: &[std::path::PathBuf]) -> Vec<std::path::PathBuf> {
    let mut extra = Vec::new();
    for dir in library_dirs {
        let Ok(text) = std::fs::read_to_string(dir.join("readcon-metatensor.env")) else {
            continue;
        };
        for line in text.lines() {
            let Some(path) = line.strip_prefix("READCON_METATENSOR_LIB_DIR=") else {
                continue;
            };
            let path = std::path::PathBuf::from(path);
            if path.is_dir() && !extra.contains(&path) {
                extra.push(path);
            }
        }
    }
    extra
}

fn link_flags_for(library_dirs: &[std::path::PathBuf]) -> Vec<String> {
    let mut flags = Vec::new();
    for dir in library_dirs {
        flags.push(format!("-L{}", dir.display()));
        flags.push(format!("-Wl,-rpath,{}", dir.display()));
    }
    let metatensor = metatensor_lib_dirs(library_dirs);
    for dir in &metatensor {
        flags.push(format!("-L{}", dir.display()));
        flags.push(format!("-Wl,-rpath,{}", dir.display()));
        flags.push(format!("-Wl,-rpath-link,{}", dir.display()));
    }
    flags.push("-lreadcon_core".to_string());
    if !metatensor.is_empty() {
        flags.push("-lmetatensor".to_string());
    }
    flags
}

#[test]
fn empty_dirs_link_only_the_core_library() {
    assert_eq!(link_flags_for(&[]), vec!["-lreadcon_core".to_string()]);
    assert!(runtime_library_path(&[]).is_empty());
    assert!(metatensor_lib_dirs(&[]).is_empty());
}

#[test]
fn env_file_adds_the_metatensor_directory() {
    let dir = std::env::temp_dir().join(format!("rc-mts-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let nested = dir.join("mts");
    std::fs::create_dir_all(&nested).unwrap();
    std::fs::write(
        dir.join("readcon-metatensor.env"),
        format!("READCON_METATENSOR_LIB_DIR={}\n", nested.display()),
    )
    .unwrap();
    let flags = link_flags_for(std::slice::from_ref(&dir));
    assert!(flags.iter().any(|flag| flag == "-lmetatensor"));
    assert!(flags.iter().any(|flag| flag.contains("rpath-link")));
    let path = runtime_library_path(std::slice::from_ref(&dir));
    assert!(path.contains(&nested.display().to_string()));
    let _ = std::fs::remove_dir_all(&dir);
}

fn runtime_library_path(library_dirs: &[std::path::PathBuf]) -> String {
    let mut dirs = library_dirs.to_vec();
    dirs.extend(metatensor_lib_dirs(library_dirs));
    dirs.iter()
        .map(|path| path.display().to_string())
        .collect::<Vec<_>>()
        .join(":")
}
