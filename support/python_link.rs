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
    /// Non-link cargo directives from a suppressed config. Printed unchanged.
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
    if let Some(prefix) = config.python_framework_prefix.as_deref()
        && is_apple(os)
        && framework_prefix_ok(prefix)
    {
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
    let mut args = Vec::new();
    if let Some(dir) = nonempty(config.lib_dir.as_deref()) {
        args.push(search_flag(dir, os, env_name));
    }
    if let Some(name) = nonempty(config.lib_name.as_deref()) {
        args.extend(lib_flags(name, config.shared, os, env_name));
    }
    if config.shared
        && os != "windows"
        && let Some(dir) = nonempty(config.lib_dir.as_deref())
    {
        args.push(format!("-Wl,-rpath,{dir}"));
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
    if let Some(prefix) = config.python_framework_prefix.as_deref()
        && is_apple(os)
        && framework_prefix_ok(prefix)
    {
        return "#[link(name = \"Python\", kind = \"framework\")]\n\
            unsafe extern \"C\" {}\n"
            .to_string();
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

/// True when `line` is a cargo directive that changes how a target is linked.
pub fn affects_linking(line: &str) -> bool {
    let Some(body) = cargo_body(line) else {
        return false;
    };
    let key = body.split_once('=').map(|(key, _)| key).unwrap_or(body);
    link_affecting(key)
}

fn suppressed_plan(lines: &[String], os: &str, env_name: &str) -> PythonLinkPlan {
    let mut args = Vec::new();
    let mut passthrough = Vec::new();
    for line in lines {
        let Some(body) = cargo_body(line) else {
            continue;
        };
        let Some((key, value)) = body.split_once('=') else {
            if link_affecting(body) {
                reject_unscoped(line);
            }
            passthrough.push(line.clone());
            continue;
        };
        if !link_affecting(key) {
            passthrough.push(line.clone());
            continue;
        }
        match scope_link_directive(key, value, os, env_name) {
            Ok(flags) => args.extend(flags),
            Err(()) => reject_unscoped(line),
        }
    }
    PythonLinkPlan { args, passthrough }
}

fn reject_unscoped(line: &str) -> ! {
    panic!(
        "refusing to apply a pyo3 link directive that cannot be scoped to tests and benches: {line}"
    );
}

fn cargo_body(line: &str) -> Option<&str> {
    if let Some(rest) = line.strip_prefix("cargo::") {
        return Some(rest);
    }
    line.strip_prefix("cargo:")
}

fn link_affecting(key: &str) -> bool {
    key == "rustc-flags"
        || key == "rustc-cdylib-link-arg"
        || key.starts_with("rustc-link-")
        || key.starts_with("rustc-cdylib-link-")
}

fn scope_link_directive(
    key: &str,
    value: &str,
    os: &str,
    env_name: &str,
) -> Result<Vec<String>, ()> {
    if value.is_empty() {
        return Err(());
    }
    match key {
        "rustc-link-arg"
        | "rustc-link-arg-tests"
        | "rustc-link-arg-benches"
        | "rustc-link-arg-bins"
        | "rustc-link-arg-examples"
        | "rustc-link-arg-cdylib"
        | "rustc-link-arg-staticlib"
        | "rustc-cdylib-link-arg" => Ok(vec![value.to_string()]),
        "rustc-link-arg-bin" => {
            let (bin, flag) = value.split_once('=').ok_or(())?;
            if bin.is_empty() || flag.is_empty() {
                return Err(());
            }
            Ok(vec![flag.to_string()])
        }
        "rustc-link-lib" => flags_from_link_lib(value, os, env_name),
        "rustc-link-search" => Ok(vec![flag_from_link_search(value, os, env_name)?]),
        "rustc-flags" => flags_from_rustc_flags(value, os, env_name),
        _ => Err(()),
    }
}

struct ParsedLib<'a> {
    kind: &'a str,
    name: &'a str,
    verbatim: bool,
    whole_archive: bool,
}

fn parse_link_lib(spec: &str) -> Result<ParsedLib<'_>, ()> {
    let (kind_part, name_part) = match spec.split_once('=') {
        Some((kind, name)) => (kind, name),
        None => ("", spec),
    };
    let (kind, modifiers) = match kind_part.split_once(':') {
        Some((kind, mods)) => (kind, mods),
        None => (kind_part, ""),
    };
    // `-l [KIND[:MODIFIERS]=]NAME[:RENAME]` passes RENAME to the linker.
    // `rustc -l dylib=orig:new --print=link-args` emits `-lnew`. An empty
    // side (`:py` or `python3.12:`) is not a name.
    let name = match name_part.split_once(':') {
        Some((name, rename)) => {
            if name.is_empty() || rename.is_empty() {
                return Err(());
            }
            rename
        }
        None => name_part,
    };
    if name.is_empty() || !matches!(kind, "" | "dylib" | "static" | "framework") {
        return Err(());
    }
    let mut verbatim = false;
    let mut whole_archive = false;
    if !modifiers.is_empty() {
        for modifier in modifiers.split(',') {
            if modifier.len() < 2 {
                return Err(());
            }
            let (sign, body) = modifier.split_at(1);
            let enable = match sign {
                "+" => true,
                "-" => false,
                _ => return Err(()),
            };
            match body {
                "verbatim" => verbatim = enable,
                "whole-archive" => whole_archive = enable,
                "bundle" | "as-needed" => {}
                _ => return Err(()),
            }
        }
    }
    if kind == "framework" && whole_archive {
        return Err(());
    }
    Ok(ParsedLib {
        kind,
        name,
        verbatim,
        whole_archive,
    })
}

fn flags_from_link_lib(spec: &str, os: &str, env_name: &str) -> Result<Vec<String>, ()> {
    let parsed = parse_link_lib(spec)?;
    if parsed.kind == "framework" {
        return Ok(vec!["-framework".to_string(), parsed.name.to_string()]);
    }
    if is_msvc(os, env_name) {
        let filename = if parsed.verbatim {
            parsed.name.to_string()
        } else {
            format!("{}.lib", parsed.name)
        };
        if parsed.whole_archive {
            return Ok(vec![format!("/WHOLEARCHIVE:{filename}")]);
        }
        return Ok(vec![filename]);
    }
    let lib = if parsed.verbatim {
        format!("-l:{}", parsed.name)
    } else {
        format!("-l{}", parsed.name)
    };
    if is_apple(os) {
        // ld64 has no -Bstatic and no --whole-archive. Static is a plain -l.
        // -force_load needs the archive path, which this directive does not carry.
        if parsed.whole_archive {
            panic!(
                "ld64 has no --whole-archive; +whole-archive needs the archive path for -Wl,-force_load"
            );
        }
        return Ok(vec![lib]);
    }
    if parsed.kind == "static" {
        let mut flags = vec!["-Wl,-Bstatic".to_string()];
        if parsed.whole_archive {
            flags.push("-Wl,--whole-archive".to_string());
        }
        flags.push(lib);
        if parsed.whole_archive {
            flags.push("-Wl,--no-whole-archive".to_string());
        }
        flags.push("-Wl,-Bdynamic".to_string());
        return Ok(flags);
    }
    if parsed.whole_archive {
        return Ok(vec![
            "-Wl,--whole-archive".to_string(),
            lib,
            "-Wl,--no-whole-archive".to_string(),
        ]);
    }
    Ok(vec![lib])
}

fn flag_from_link_search(spec: &str, os: &str, env_name: &str) -> Result<String, ()> {
    let (kind, path) = spec.split_once('=').unwrap_or(("native", spec));
    if !matches!(
        kind,
        "" | "native" | "dependency" | "crate" | "all" | "framework"
    ) {
        return Err(());
    }
    let Some(path) = nonempty(Some(path)) else {
        return Err(());
    };
    if is_msvc(os, env_name) {
        if kind == "framework" {
            return Err(());
        }
        return Ok(format!("/LIBPATH:{path}"));
    }
    if kind == "framework" {
        Ok(format!("-F{path}"))
    } else {
        Ok(format!("-L{path}"))
    }
}

fn flags_from_rustc_flags(value: &str, os: &str, env_name: &str) -> Result<Vec<String>, ()> {
    let mut tokens = value.split_whitespace();
    let mut flags = Vec::new();
    while let Some(token) = tokens.next() {
        let (kind, spec) = if let Some(spec) = token.strip_prefix("-l") {
            ("lib", spec)
        } else if let Some(spec) = token.strip_prefix("-L") {
            ("search", spec)
        } else {
            return Err(());
        };
        let spec = if spec.is_empty() {
            let Some(next) = tokens.next() else {
                return Err(());
            };
            if next.starts_with('-') {
                return Err(());
            }
            next
        } else {
            spec
        };
        if kind == "lib" {
            flags.extend(flags_from_link_lib(spec, os, env_name)?);
        } else {
            flags.push(flag_from_link_search(spec, os, env_name)?);
        }
    }
    if flags.is_empty() { Err(()) } else { Ok(flags) }
}

fn lib_flags(name: &str, shared: bool, os: &str, env_name: &str) -> Vec<String> {
    if is_msvc(os, env_name) {
        return vec![format!("{name}.lib")];
    }
    if shared {
        return vec![format!("-l{name}")];
    }
    static_unix_flags(name, os)
}

fn static_unix_flags(name: &str, os: &str) -> Vec<String> {
    if is_apple(os) {
        return vec![format!("-l{name}")];
    }
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
