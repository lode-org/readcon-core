//! Decide which libstdc++ `std::string` the linked libchemfiles was built with.
//!
//! The official Linux prebuilt archive is GCC 4.8.5. Its `std::string` is the
//! copy-on-write ABI (`Atom` is 80 bytes). A from-source or distro build uses
//! this compiler's cxx11 string (`Atom` is 128 bytes). The scan walks atoms
//! inline, so the shim has to match the archive that will actually be linked.

use std::path::{Path, PathBuf};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum StringAbi {
    /// Old libstdc++ `std::string`, mangled as `Ss`.
    Cow,
    /// `__cxx11` `std::basic_string`.
    Cxx11,
    /// No string marker. libc++ and MSVC look like this; the ABI macro is a no-op there.
    Unknown,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CppStdlib {
    Libstdcxx,
    Libcxx,
    Msvc,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum NmStatus {
    Ok,
    SpawnFailed,
    NonZero,
}

/// What the shim should do with `_GLIBCXX_USE_CXX11_ABI`.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum AbiChoice {
    Cow,
    Cxx11,
    /// MSVC or libc++. The libstdc++ macro does not apply.
    Foreign,
    /// libstdc++ and `nm` could not prove the ABI. The build must stop.
    Fatal,
}

/// Text from `nm` on the linked libchemfiles.
///
/// A cxx11 archive wins if both markers show up. Forcing the old ABI onto a
/// library that contains `__cxx11` is what makes the scan SIGSEGV.
pub fn classify_symbol_text(text: &str) -> StringAbi {
    if text.contains("__cxx11") {
        StringAbi::Cxx11
    } else if text.contains("ERKSs") {
        StringAbi::Cow
    } else {
        StringAbi::Unknown
    }
}

/// libstdc++ with a missing, failing, or unclassifiable `nm` is fatal.
/// MSVC and libc++ do not use the macro, so they do not need `nm`.
pub fn choose_string_abi(stdlib: CppStdlib, nm: NmStatus, symbols: StringAbi) -> AbiChoice {
    match stdlib {
        CppStdlib::Libcxx | CppStdlib::Msvc => AbiChoice::Foreign,
        CppStdlib::Libstdcxx => match nm {
            NmStatus::SpawnFailed | NmStatus::NonZero => AbiChoice::Fatal,
            NmStatus::Ok => match symbols {
                StringAbi::Cow => AbiChoice::Cow,
                StringAbi::Cxx11 => AbiChoice::Cxx11,
                StringAbi::Unknown => AbiChoice::Fatal,
            },
        },
    }
}

/// Environment keys for `nm`, in the same order `cc` uses for `AR` and `CC`.
///
/// `NM_<target>` wins, then the underscored target, then `TARGET_NM` or
/// `HOST_NM`, then `NM`. An explicit value is used even when that path does
/// not exist.
pub fn nm_env_keys(target: &str, host: &str) -> Vec<String> {
    let target_u = target.replace(['-', '.'], "_");
    let kind = if !host.is_empty() && target != host {
        "TARGET"
    } else {
        "HOST"
    };
    vec![
        format!("NM_{target}"),
        format!("NM_{target_u}"),
        format!("{kind}_NM"),
        "NM".to_string(),
    ]
}

pub fn first_nm_override<'a>(
    keys: &[String],
    value_of: impl Fn(&str) -> Option<&'a str>,
) -> Option<&'a str> {
    keys.iter().find_map(|key| {
        let value = value_of(key)?.trim();
        if value.is_empty() { None } else { Some(value) }
    })
}

/// Static is `#[link(kind = "static")]` in chemfiles-sys. A `dylib` override
/// must not classify `libchemfiles.a` just because that name is listed first.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LinkKind {
    Static,
    Dynamic,
}

pub fn library_file_names(kind: LinkKind) -> &'static [&'static str] {
    match kind {
        LinkKind::Static => &["libchemfiles.a", "chemfiles.lib"],
        LinkKind::Dynamic => &["libchemfiles.so", "libchemfiles.dylib", "chemfiles.dll"],
    }
}

pub fn kind_from_link_items(items: &[&str]) -> Option<LinkKind> {
    for item in items {
        let item = item.trim();
        if item.is_empty() {
            continue;
        }
        if let Some((kind, name)) = item.split_once('=') {
            if name == "chemfiles" || name == "libchemfiles" {
                return Some(if kind == "static" {
                    LinkKind::Static
                } else {
                    LinkKind::Dynamic
                });
            }
        } else if item == "chemfiles" || item == "libchemfiles" {
            return Some(LinkKind::Dynamic);
        }
    }
    None
}

/// Directories that can hold the library Cargo will link.
///
/// `libdir` is an override's library directory. `root` is `DEP_CHEMFILES_ROOT`
/// (the install prefix of the chemfiles-sys build Cargo actually ran, or an
/// override root). `include` is the override include dir. The first one that
/// is set wins, so a stale `chemfiles-sys` output is not consulted.
pub fn library_search_dirs(
    libdir: Option<&Path>,
    root: Option<&Path>,
    include: Option<&Path>,
) -> Vec<PathBuf> {
    if let Some(dir) = libdir {
        return vec![dir.to_path_buf()];
    }
    if let Some(root) = root {
        return vec![root.join("lib"), root.join("lib64")];
    }
    let Some(include) = include else {
        return Vec::new();
    };
    let prefix = if include.file_name().and_then(|name| name.to_str()) == Some("include") {
        include.parent().unwrap_or(include)
    } else {
        include
    };
    vec![prefix.join("lib"), prefix.join("lib64")]
}

pub fn linked_library(dirs: &[PathBuf], kind: LinkKind) -> Option<PathBuf> {
    for dir in dirs {
        for name in library_file_names(kind) {
            let path = dir.join(name);
            if path.is_file() {
                return Some(path);
            }
        }
    }
    None
}

/// Directory passed to `-I`, containing `chemfiles/exports.h`.
///
/// Accepts the include directory itself or a prefix whose `include/` child
/// holds the header.
pub fn include_dir_holding_exports(dir: &Path) -> Option<PathBuf> {
    let direct = dir.join("chemfiles/exports.h");
    if direct.is_file() {
        return Some(dir.to_path_buf());
    }
    let nested = dir.join("include/chemfiles/exports.h");
    if nested.is_file() {
        return Some(dir.join("include"));
    }
    None
}

/// Header directory from override metadata or from the live `cargo:root`.
///
/// `libdir` and `root` locate the installed headers as well as the library.
/// A set value that does not contain `exports.h` is an error for the caller;
/// this function returns `None` only when that key is unset.
pub fn include_from_metadata(
    include: Option<&Path>,
    root: Option<&Path>,
    libdir: Option<&Path>,
) -> Option<PathBuf> {
    if let Some(dir) = include {
        return include_dir_holding_exports(dir);
    }
    if let Some(root) = root {
        return include_dir_holding_exports(root);
    }
    let dir = libdir?;
    include_dir_holding_exports(dir).or_else(|| dir.parent().and_then(include_dir_holding_exports))
}

/// `rustc-link-lib` from a Cargo `links = "chemfiles"` config table that
/// applies to `target`. An exact triple beats a `cfg(...)` table.
pub fn link_kind_from_config(config: &str, target: &str) -> Option<LinkKind> {
    let mut exact: Option<LinkKind> = None;
    let mut cfg_kind: Option<LinkKind> = None;
    let mut section: Option<Section> = None;
    let mut collecting = false;
    let mut items: Vec<String> = Vec::new();
    let flush = |items: &mut Vec<String>,
                 section: &Option<Section>,
                 exact: &mut Option<LinkKind>,
                 cfg_kind: &mut Option<LinkKind>| {
        if items.is_empty() {
            return;
        }
        let borrowed: Vec<&str> = items.iter().map(String::as_str).collect();
        if let Some(kind) = kind_from_link_items(&borrowed)
            && let Some(section) = section
        {
            match section {
                Section::Exact => *exact = Some(kind),
                Section::Cfg => {
                    if cfg_kind.is_none() {
                        *cfg_kind = Some(kind);
                    }
                }
            }
        }
        items.clear();
    };
    for raw in config.lines() {
        let line = raw.split('#').next().unwrap_or("").trim();
        if line.starts_with('[') && line.ends_with(']') {
            flush(&mut items, &section, &mut exact, &mut cfg_kind);
            collecting = false;
            section = section_for(&line[1..line.len() - 1], target);
            continue;
        }
        if section.is_none() {
            continue;
        }
        if collecting {
            push_link_items(line, &mut items);
            if line.contains(']') {
                collecting = false;
                flush(&mut items, &section, &mut exact, &mut cfg_kind);
            }
            continue;
        }
        let Some(rest) = line.strip_prefix("rustc-link-lib") else {
            continue;
        };
        let rest = rest.trim_start();
        let Some(rest) = rest.strip_prefix('=') else {
            continue;
        };
        push_link_items(rest.trim(), &mut items);
        collecting = !rest.contains(']');
        if !collecting {
            flush(&mut items, &section, &mut exact, &mut cfg_kind);
        }
    }
    flush(&mut items, &section, &mut exact, &mut cfg_kind);
    exact.or(cfg_kind)
}

#[derive(Clone, Copy)]
enum Section {
    Exact,
    Cfg,
}

fn section_for(header: &str, target: &str) -> Option<Section> {
    let header = header.trim();
    let (selector, name) = header.rsplit_once('.')?;
    if name.trim() != "chemfiles" {
        return None;
    }
    let selector = selector.trim().trim_start_matches("target").trim();
    let selector = selector.strip_prefix('.').unwrap_or(selector).trim();
    let selector = unquote(selector);
    if selector == target {
        return Some(Section::Exact);
    }
    if cfg_matches(selector, target) {
        return Some(Section::Cfg);
    }
    None
}

fn unquote(text: &str) -> &str {
    text.trim().trim_matches('"').trim_matches('\'')
}

fn cfg_matches(selector: &str, target: &str) -> bool {
    let os_windows = target.contains("windows");
    let body = selector
        .strip_prefix("cfg(")
        .and_then(|rest| rest.strip_suffix(')'))
        .unwrap_or("");
    if body == "unix" {
        return !os_windows;
    }
    if body == "windows" {
        return os_windows;
    }
    if let Some(os) = body
        .strip_prefix("target_os")
        .and_then(|rest| rest.trim().strip_prefix('='))
    {
        let os = unquote(os.trim());
        return target.split('-').any(|part| part == os);
    }
    false
}

fn push_link_items(text: &str, items: &mut Vec<String>) {
    for piece in text.split([',', '[', ']']) {
        let piece = unquote(piece.trim());
        if piece.is_empty() {
            continue;
        }
        items.push(piece.to_string());
    }
}
