//! Target-scoped libpython link arguments.
//!
//! `pyo3` is an extension module, so the cdylib must not link libpython.
//! Test and bench binaries start an interpreter and do. These arguments are
//! linker flags. Callers print each one as `cargo:rustc-link-arg-tests` and
//! `cargo:rustc-link-arg-benches`.

use pyo3_build_config::InterpreterConfig;

/// Linker flags for the test and bench binaries.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PythonLinkPlan {
    pub args: Vec<String>,
    /// Non-link `cargo:` lines from a suppressed config. Printed unchanged.
    pub passthrough: Vec<String>,
}

impl PythonLinkPlan {
    /// `cargo:rustc-link-arg-tests` and `cargo:rustc-link-arg-benches` lines.
    pub fn cargo_lines(&self) -> Vec<String> {
        let mut lines = Vec::with_capacity(self.args.len() * 2);
        for arg in &self.args {
            lines.push(format!("cargo:rustc-link-arg-tests={arg}"));
            lines.push(format!("cargo:rustc-link-arg-benches={arg}"));
        }
        lines
    }

    /// Every emitted link line is a test or bench link arg.
    pub fn is_target_scoped(&self) -> bool {
        self.cargo_lines().iter().all(|line| {
            line.starts_with("cargo:rustc-link-arg-tests=")
                || line.starts_with("cargo:rustc-link-arg-benches=")
        }) && !self
            .cargo_lines()
            .iter()
            .any(|line| line.contains("rustc-link-search") || line.contains("rustc-link-lib"))
    }
}

/// Link flags for `config` on `os` / `env_name`.
///
/// `no_python` is the `PYO3_NO_PYTHON` switch. It suppresses libpython the
/// same way `suppress_build_script_link_lines` does. Nothing in the plan is
/// a package-wide `cargo:rustc-link-search` or `cargo:rustc-link-lib`.
pub fn python_link_plan(
    config: &InterpreterConfig,
    os: &str,
    env_name: &str,
    no_python: bool,
) -> PythonLinkPlan {
    if no_python || config.suppress_build_script_link_lines {
        return suppressed_plan(&config.extra_build_script_lines, os, env_name);
    }
    if let Some(prefix) = config.python_framework_prefix.as_deref() {
        if is_apple(os) && framework_prefix_ok(prefix) {
            return PythonLinkPlan {
                args: vec![
                    format!("-F{prefix}"),
                    "-framework".to_string(),
                    "Python".to_string(),
                    format!("-Wl,-rpath,{prefix}"),
                ],
                passthrough: Vec::new(),
            };
        }
    }
    let mut args = Vec::new();
    if let Some(dir) = nonempty(config.lib_dir.as_deref()) {
        args.push(search_flag(dir, os, env_name));
    }
    if let Some(name) = nonempty(config.lib_name.as_deref()) {
        args.extend(lib_flags(name, config.shared, os, env_name));
    }
    if config.shared && os != "windows" {
        if let Some(dir) = nonempty(config.lib_dir.as_deref()) {
            args.push(format!("-Wl,-rpath,{dir}"));
        }
    }
    PythonLinkPlan {
        args,
        passthrough: Vec::new(),
    }
}

/// `#[link]` compiled only into the library test harness.
///
/// `cargo:rustc-link-arg-tests` does not reach `cargo test --lib`.
pub fn harness_link_rs(config: &InterpreterConfig, os: &str, no_python: bool) -> String {
    if no_python || config.suppress_build_script_link_lines {
        return String::new();
    }
    if let Some(prefix) = config.python_framework_prefix.as_deref() {
        if is_apple(os) && framework_prefix_ok(prefix) {
            return "#[link(name = \"Python\", kind = \"framework\")]\n\
                unsafe extern \"C\" {}\n"
                .to_string();
        }
    }
    let Some(name) = nonempty(config.lib_name.as_deref()) else {
        return String::new();
    };
    if !lib_name_ok(name) {
        return String::new();
    }
    if config.shared {
        format!("#[link(name = \"{name}\")]\nunsafe extern \"C\" {{}}\n")
    } else {
        format!("#[link(name = \"{name}\", kind = \"static\")]\nunsafe extern \"C\" {{}}\n")
    }
}

pub fn lib_name_ok(name: &str) -> bool {
    !name.is_empty()
        && name
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '.' || c == '_' || c == '-')
}

pub fn has_library_arg(args: &[String]) -> bool {
    args.iter().any(|arg| {
        arg.starts_with("-l")
            || arg == "-framework"
            || (arg.ends_with(".lib") && !arg.starts_with("/LIBPATH:"))
    })
}

/// Insert one search flag ahead of the libraries, skipping duplicates.
pub fn insert_search_arg(args: &mut Vec<String>, dir: &str, os: &str, env_name: &str) {
    let Some(dir) = nonempty(Some(dir)) else {
        return;
    };
    let flag = search_flag(dir, os, env_name);
    if args.iter().any(|arg| arg == &flag) {
        return;
    }
    let at = args
        .iter()
        .position(|arg| !is_search_arg(arg))
        .unwrap_or(args.len());
    args.insert(at, flag);
}

pub fn library_path_dirs(args: &[String]) -> Vec<String> {
    args.iter()
        .filter_map(|arg| {
            arg.strip_prefix("-L")
                .or_else(|| arg.strip_prefix("/LIBPATH:"))
                .map(str::to_string)
        })
        .collect()
}

pub fn require_single_line(what: &str, value: &str) {
    if value.chars().any(|c| c == '\n' || c == '\r' || c == '\0') {
        panic!("pyo3-build-config {what} is not a single line");
    }
}

fn suppressed_plan(lines: &[String], os: &str, env_name: &str) -> PythonLinkPlan {
    let mut args = Vec::new();
    let mut passthrough = Vec::new();
    for line in lines {
        if let Some(flag) = line.strip_prefix("cargo:rustc-link-arg-tests=") {
            args.push(flag.to_string());
            continue;
        }
        if let Some(flag) = line.strip_prefix("cargo:rustc-link-arg-benches=") {
            args.push(flag.to_string());
            continue;
        }
        if let Some(flag) = line.strip_prefix("cargo:rustc-link-arg=") {
            args.push(flag.to_string());
            continue;
        }
        if let Some(spec) = line.strip_prefix("cargo:rustc-link-lib=") {
            args.extend(flags_from_link_lib(spec, os, env_name));
            continue;
        }
        if let Some(spec) = line.strip_prefix("cargo:rustc-link-search=") {
            if let Some(flag) = flag_from_link_search(spec, os, env_name) {
                args.push(flag);
            }
            continue;
        }
        if line.starts_with("cargo:rustc-link")
            || line.starts_with("cargo:rustc-cdylib-link-arg=")
            || line.starts_with("cargo:rustc-link-arg-")
        {
            panic!("refusing to apply a pyo3 link directive outside tests and benches: {line}");
        }
        if line.starts_with("cargo:") {
            passthrough.push(line.clone());
        }
    }
    PythonLinkPlan { args, passthrough }
}

fn flags_from_link_lib(spec: &str, os: &str, env_name: &str) -> Vec<String> {
    let (kind, name) = spec.split_once('=').unwrap_or(("", spec));
    let name = name.rsplit_once(':').map(|(_, real)| real).unwrap_or(name);
    if name.is_empty() {
        return Vec::new();
    }
    if kind == "framework" {
        return vec!["-framework".to_string(), name.to_string()];
    }
    if is_msvc(os, env_name) {
        return vec![format!("{name}.lib")];
    }
    if kind == "static" {
        return static_unix_flags(name);
    }
    vec![format!("-l{name}")]
}

fn flag_from_link_search(spec: &str, os: &str, env_name: &str) -> Option<String> {
    let (kind, path) = spec.split_once('=').unwrap_or(("native", spec));
    let path = nonempty(Some(path))?;
    if is_msvc(os, env_name) {
        return Some(format!("/LIBPATH:{path}"));
    }
    if kind == "framework" {
        return Some(format!("-F{path}"));
    }
    Some(format!("-L{path}"))
}

fn lib_flags(name: &str, shared: bool, os: &str, env_name: &str) -> Vec<String> {
    if is_msvc(os, env_name) {
        return vec![format!("{name}.lib")];
    }
    if shared {
        return vec![format!("-l{name}")];
    }
    static_unix_flags(name)
}

fn static_unix_flags(name: &str) -> Vec<String> {
    vec![
        "-Wl,-Bstatic".to_string(),
        format!("-l{name}"),
        "-Wl,-Bdynamic".to_string(),
    ]
}

fn search_flag(dir: &str, os: &str, env_name: &str) -> String {
    if is_msvc(os, env_name) {
        format!("/LIBPATH:{dir}")
    } else {
        format!("-L{dir}")
    }
}

fn is_search_arg(arg: &str) -> bool {
    arg.starts_with("-L") || arg.starts_with("/LIBPATH:") || arg.starts_with("-F")
}

fn is_apple(os: &str) -> bool {
    os == "macos" || os == "ios"
}

fn is_msvc(os: &str, env_name: &str) -> bool {
    os == "windows" && env_name == "msvc"
}

fn framework_prefix_ok(prefix: &str) -> bool {
    let trimmed = prefix.trim();
    !trimmed.is_empty() && trimmed != "None"
}

fn nonempty(value: Option<&str>) -> Option<&str> {
    value.filter(|text| !text.is_empty())
}
