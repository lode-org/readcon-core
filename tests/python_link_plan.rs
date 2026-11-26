//! Link flags derived from a PyO3 `InterpreterConfig`.
//! Cargo does not compile `build.rs` with `cfg(test)`, so this target
//! includes the same module the build script does.

#[path = "../support/python_link.rs"]
mod python_link;

use pyo3_build_config::{BuildFlags, InterpreterConfig, PythonImplementation, PythonVersion};

use python_link::{PythonLinkPlan, python_link_plan};

fn config(
    lib_name: Option<&str>,
    lib_dir: Option<&str>,
    shared: bool,
    suppress: bool,
    prefix: Option<&str>,
    executable: Option<&str>,
    extras: &[&str],
) -> InterpreterConfig {
    InterpreterConfig {
        implementation: PythonImplementation::CPython,
        version: PythonVersion {
            major: 3,
            minor: 12,
        },
        shared,
        abi3: false,
        lib_name: lib_name.map(str::to_string),
        lib_dir: lib_dir.map(str::to_string),
        executable: executable.map(str::to_string),
        pointer_width: Some(64),
        build_flags: BuildFlags::default(),
        suppress_build_script_link_lines: suppress,
        extra_build_script_lines: extras.iter().map(|line| (*line).to_string()).collect(),
        python_framework_prefix: prefix.map(str::to_string),
    }
}

fn assert_args(plan: &PythonLinkPlan, args: &[&str]) {
    let expected: Vec<String> = args.iter().map(|arg| (*arg).to_string()).collect();
    assert_eq!(plan.args, expected);
    let mut lines = Vec::new();
    for arg in args {
        lines.push(format!("cargo:rustc-link-arg-tests={arg}"));
        lines.push(format!("cargo:rustc-link-arg-benches={arg}"));
    }
    assert_eq!(plan.cargo_lines(), lines);
    assert!(plan.is_target_scoped());
    assert!(
        plan.cargo_lines()
            .iter()
            .all(|line| !line.contains("rustc-link-search") && !line.contains("rustc-link-lib")),
        "{lines:?}"
    );
    assert!(
        plan.passthrough
            .iter()
            .all(|line| !python_link::affects_linking(line)),
        "{:?}",
        plan.passthrough
    );
}

#[test]
fn linux_shared_link_is_target_scoped() {
    let plan = python_link_plan(
        &config(
            Some("python3.12"),
            Some("/usr/lib/x86_64-linux-gnu"),
            true,
            false,
            None,
            Some("/usr/bin/python3"),
            &[],
        ),
        "linux",
        "gnu",
        false,
    );
    assert_args(
        &plan,
        &[
            "-L/usr/lib/x86_64-linux-gnu",
            "-lpython3.12",
            "-Wl,-rpath,/usr/lib/x86_64-linux-gnu",
        ],
    );
    let harness = python_link::harness_link_rs(
        &config(
            Some("python3.12"),
            Some("/usr/lib/x86_64-linux-gnu"),
            true,
            false,
            None,
            Some("/usr/bin/python3"),
            &[],
        ),
        "linux",
        false,
    );
    assert_eq!(
        harness,
        "#[link(name = \"python3.12\")]\nunsafe extern \"C\" {}\n"
    );
    assert!(!harness.contains("cargo:"));

    let mut with_libpl = plan.args.clone();
    python_link::insert_search_arg(
        &mut with_libpl,
        "/usr/lib/python3.12/config-3.12-x86_64-linux-gnu",
        "linux",
        "gnu",
    );
    assert_eq!(
        with_libpl[1],
        "-L/usr/lib/python3.12/config-3.12-x86_64-linux-gnu"
    );
    assert_eq!(
        python_link::library_path_dirs(&with_libpl),
        vec![
            "/usr/lib/x86_64-linux-gnu".to_string(),
            "/usr/lib/python3.12/config-3.12-x86_64-linux-gnu".to_string(),
        ]
    );
    assert!(python_link::has_library_arg(&with_libpl));
    python_link::require_single_line("link arg", "-lpython3.12");
}

#[test]
fn macos_framework_link_is_target_scoped() {
    let plan = python_link_plan(
        &config(
            Some("python3.12"),
            Some("/Library/Frameworks/Python.framework/Versions/3.12/lib"),
            true,
            false,
            Some("/Library/Frameworks"),
            Some("/usr/bin/python3"),
            &[],
        ),
        "macos",
        "",
        false,
    );
    assert_args(
        &plan,
        &[
            "-F/Library/Frameworks",
            "-framework",
            "Python",
            "-Wl,-rpath,/Library/Frameworks",
        ],
    );
    let harness = python_link::harness_link_rs(
        &config(
            Some("python3.12"),
            None,
            true,
            false,
            Some("/Library/Frameworks"),
            None,
            &[],
        ),
        "macos",
        false,
    );
    assert!(harness.contains("kind = \"framework\""));
    assert!(!harness.contains("cargo:"));

    let ignored = python_link_plan(
        &config(
            Some("python3.12"),
            Some("/usr/local/lib"),
            true,
            false,
            Some("None"),
            None,
            &[],
        ),
        "macos",
        "",
        false,
    );
    assert_args(
        &ignored,
        &[
            "-L/usr/local/lib",
            "-lpython3.12",
            "-Wl,-rpath,/usr/local/lib",
        ],
    );
}

#[test]
fn windows_release_import_lib_is_target_scoped() {
    let plan = python_link_plan(
        &config(
            Some("python312"),
            Some(r"C:\Python312\libs"),
            true,
            false,
            None,
            Some(r"C:\Python312\python.exe"),
            &[],
        ),
        "windows",
        "msvc",
        false,
    );
    assert_args(&plan, &[r"/LIBPATH:C:\Python312\libs", "python312.lib"]);
}

#[test]
fn windows_debug_import_lib_is_target_scoped() {
    let plan = python_link_plan(
        &config(
            Some("python312_d"),
            Some(r"C:\Python312\libs"),
            true,
            false,
            None,
            Some(r"C:\Python312\python_d.exe"),
            &[],
        ),
        "windows",
        "msvc",
        false,
    );
    assert_args(&plan, &[r"/LIBPATH:C:\Python312\libs", "python312_d.lib"]);
}

#[test]
fn static_libpython_is_target_scoped() {
    let plan = python_link_plan(
        &config(
            Some("python3.12"),
            Some("/opt/py/lib"),
            false,
            false,
            None,
            Some("/opt/py/bin/python3"),
            &[],
        ),
        "linux",
        "gnu",
        false,
    );
    assert_args(
        &plan,
        &[
            "-L/opt/py/lib",
            "-Wl,-Bstatic",
            "-lpython3.12",
            "-Wl,-Bdynamic",
        ],
    );
    let harness = python_link::harness_link_rs(
        &config(
            Some("python3.12"),
            Some("/opt/py/lib"),
            false,
            false,
            None,
            None,
            &[],
        ),
        "linux",
        false,
    );
    assert!(harness.contains("kind = \"static\""));
    assert!(!harness.contains("cargo:"));
}

#[test]
fn suppressed_link_emits_nothing_package_wide() {
    let silent = python_link_plan(
        &config(
            Some("python3.12"),
            Some("/usr/lib"),
            true,
            true,
            None,
            Some("/usr/bin/python3"),
            &[],
        ),
        "linux",
        "gnu",
        false,
    );
    assert_args(&silent, &[]);
    assert!(silent.passthrough.is_empty());
    assert!(
        python_link::harness_link_rs(
            &config(
                Some("python3.12"),
                Some("/usr/lib"),
                true,
                true,
                None,
                None,
                &[],
            ),
            "linux",
            false,
        )
        .is_empty()
    );

    // `PYO3_NO_PYTHON` takes the same path even when the flag is unset.
    let no_python = python_link_plan(
        &config(
            Some("python3.12"),
            Some("/usr/lib"),
            true,
            false,
            None,
            Some("/usr/bin/python3"),
            &[],
        ),
        "linux",
        "gnu",
        true,
    );
    assert_args(&no_python, &[]);

    let retargeted = python_link_plan(
        &config(
            Some("python3.12"),
            Some("/usr/lib"),
            true,
            true,
            None,
            None,
            &[
                "cargo:rustc-link-search=native=/opt/py/lib",
                "cargo:rustc-link-lib=static=python3.12",
                "cargo:rustc-cfg=Py_DEBUG",
            ],
        ),
        "linux",
        "gnu",
        false,
    );
    assert_args(
        &retargeted,
        &[
            "-L/opt/py/lib",
            "-Wl,-Bstatic",
            "-lpython3.12",
            "-Wl,-Bdynamic",
        ],
    );
    assert_eq!(
        retargeted.passthrough,
        vec!["cargo:rustc-cfg=Py_DEBUG".to_string()]
    );
}

#[test]
fn cross_config_uses_only_the_configured_lib_dir() {
    let plan = python_link_plan(
        &config(
            Some("python3.12"),
            Some("/opt/cross/python/lib"),
            true,
            false,
            None,
            None,
            &[],
        ),
        "linux",
        "gnu",
        false,
    );
    assert_args(
        &plan,
        &[
            "-L/opt/cross/python/lib",
            "-lpython3.12",
            "-Wl,-rpath,/opt/cross/python/lib",
        ],
    );
    assert_eq!(
        plan.args.iter().filter(|arg| arg.starts_with("-L")).count(),
        1
    );
}

#[test]
fn scoped_link_cargo_colon_directives() {
    let plan = python_link_plan(
        &config(
            Some("python3.12"),
            Some("/usr/lib"),
            true,
            true,
            None,
            None,
            &[
                "cargo::rustc-link-search=native=/opt/py/lib",
                "cargo::rustc-link-search=framework=/Library/Frameworks",
                "cargo::rustc-link-lib=python3.12",
                "cargo::rustc-link-lib=framework=Python",
                "cargo::rustc-link-arg=-Wl,-rpath,/opt/py/lib",
                "cargo::rustc-cdylib-link-arg=-lpython3.12",
                "cargo::rustc-link-arg-cdylib=-Wl,--no-as-needed",
                "cargo::rustc-link-arg-bins=-ldl",
                "cargo::rustc-link-arg-examples=-lm",
                "cargo::rustc-link-arg-staticlib=-lutil",
                "cargo::rustc-link-arg-tests=-pthread",
                "cargo::rustc-link-arg-benches=-lrt",
                "cargo::rustc-link-arg-bin=readcon=-lc",
                "cargo::rustc-flags=-L/opt/flags -lstatic=python3.12",
                "cargo::rustc-cfg=Py_DEBUG",
            ],
        ),
        "linux",
        "gnu",
        false,
    );
    assert_args(
        &plan,
        &[
            "-L/opt/py/lib",
            "-F/Library/Frameworks",
            "-lpython3.12",
            "-framework",
            "Python",
            "-Wl,-rpath,/opt/py/lib",
            "-lpython3.12",
            "-Wl,--no-as-needed",
            "-ldl",
            "-lm",
            "-lutil",
            "-pthread",
            "-lrt",
            "-lc",
            "-L/opt/flags",
            "-Wl,-Bstatic",
            "-lpython3.12",
            "-Wl,-Bdynamic",
        ],
    );
    assert_eq!(
        plan.passthrough,
        vec!["cargo::rustc-cfg=Py_DEBUG".to_string()]
    );
}

#[test]
fn scoped_link_kind_modifiers() {
    let plan = python_link_plan(
        &config(
            Some("python3.12"),
            None,
            true,
            true,
            None,
            None,
            &[
                "cargo::rustc-link-lib=static:-bundle=python3.12:py",
                "cargo::rustc-link-lib=dylib:+verbatim=libpython3.12.so",
                "cargo:rustc-link-lib=static:+whole-archive,-bundle=util",
            ],
        ),
        "linux",
        "gnu",
        false,
    );
    assert_args(
        &plan,
        &[
            "-Wl,-Bstatic",
            "-lpy",
            "-Wl,-Bdynamic",
            "-l:libpython3.12.so",
            "-Wl,-Bstatic",
            "-Wl,--whole-archive",
            "-lutil",
            "-Wl,--no-whole-archive",
            "-Wl,-Bdynamic",
        ],
    );
    assert!(plan.passthrough.is_empty());

    let windows = python_link_plan(
        &config(
            Some("python312"),
            None,
            true,
            true,
            None,
            None,
            &[
                "cargo::rustc-link-lib=static:-bundle=python312",
                "cargo::rustc-link-lib=dylib:+verbatim=python312.dll",
            ],
        ),
        "windows",
        "msvc",
        false,
    );
    assert_args(&windows, &["python312.lib", "python312.dll"]);
}

#[test]
fn scoped_link_lib_rename_is_the_linker_name() {
    let plan = python_link_plan(
        &config(
            Some("python3.12"),
            None,
            true,
            true,
            None,
            None,
            &[
                "cargo::rustc-link-lib=dylib=orig:new",
                "cargo::rustc-link-lib=static=python3.12:py",
            ],
        ),
        "linux",
        "gnu",
        false,
    );
    assert_args(&plan, &["-lnew", "-Wl,-Bstatic", "-lpy", "-Wl,-Bdynamic"]);
}

#[test]
#[should_panic(expected = "cannot be scoped to tests and benches")]
fn scoped_link_lib_empty_rename_is_rejected() {
    python_link_plan(
        &config(
            Some("python3.12"),
            None,
            true,
            true,
            None,
            None,
            &["cargo::rustc-link-lib=python3.12:"],
        ),
        "linux",
        "gnu",
        false,
    );
}

#[test]
#[should_panic(expected = "cannot be scoped to tests and benches")]
fn scoped_link_lib_empty_name_is_rejected() {
    python_link_plan(
        &config(
            Some("python3.12"),
            None,
            true,
            true,
            None,
            None,
            &["cargo::rustc-link-lib=:py"],
        ),
        "linux",
        "gnu",
        false,
    );
}

#[test]
fn scoped_link_lib_dir_none() {
    let suppressed = python_link_plan(
        &config(
            Some("python3.12"),
            None,
            true,
            true,
            None,
            None,
            &["cargo::rustc-link-lib=python3.12"],
        ),
        "linux",
        "gnu",
        false,
    );
    assert_args(&suppressed, &["-lpython3.12"]);
    assert!(suppressed.passthrough.is_empty());

    let plain = python_link_plan(
        &config(
            Some("python3.12"),
            None,
            true,
            false,
            None,
            Some("/usr/bin/python3"),
            &[],
        ),
        "linux",
        "gnu",
        false,
    );
    assert_args(&plain, &["-lpython3.12"]);
    assert!(plain.args.iter().all(|arg| !arg.starts_with("-L")));
}

#[test]
#[should_panic(expected = "cannot be scoped to tests and benches")]
fn scoped_link_unknown_directive_rejected() {
    python_link_plan(
        &config(
            Some("python3.12"),
            Some("/usr/lib"),
            true,
            true,
            None,
            None,
            &["cargo::rustc-link-foo=bar"],
        ),
        "linux",
        "gnu",
        false,
    );
}
