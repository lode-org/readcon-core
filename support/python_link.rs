//! Which libpython the `python` feature's test binary should link.
//!
//! The extension module is built with PyO3's `extension-module` feature, so
//! the cdylib does not link libpython. The Rust test binary does. Linux and
//! macOS take the stem of sysconfig `LDLIBRARY`. Windows CPython leaves that
//! variable empty; MSVC uses `pythonXY.lib` instead.

/// sysconfig / `sys` values the probe reads. Empty strings mean "unset".
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct PythonSysconfig {
    pub ldlibrary: String,
    pub libdir: String,
    pub base_prefix: String,
    pub py_version_nodot: String,
}

/// Link line for `python_test_link.rs`, or no line at all.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PythonLink {
    /// `name` is the linker stem (`python3.12`, `python312`).
    /// `search_dir` is set only for an MSVC import library.
    Named {
        name: String,
        search_dir: Option<String>,
    },
    /// This target does not need a libpython link line.
    Skip,
}

/// Linux and macOS reported an empty `LDLIBRARY`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ProbeError {
    EmptyLdlibrary,
}

/// Parse the tab-separated block printed by the Windows sysconfig script.
pub fn parse_sysconfig_lines(text: &str) -> PythonSysconfig {
    let mut cfg = PythonSysconfig::default();
    for line in text.lines() {
        let Some((key, value)) = line.split_once('\t') else {
            continue;
        };
        match key {
            "LDLIBRARY" => cfg.ldlibrary = value.to_string(),
            "LIBDIR" => cfg.libdir = value.to_string(),
            "BASE_PREFIX" => cfg.base_prefix = value.to_string(),
            "PY_VERSION_NODOT" => cfg.py_version_nodot = value.to_string(),
            _ => {}
        }
    }
    cfg
}

/// Decide the test-binary link for `target_os` / `target_env`.
///
/// `exists` is consulted only for Windows MSVC import libraries. An empty
/// `LDLIBRARY` on Linux or macOS is [`ProbeError::EmptyLdlibrary`]. On MSVC,
/// a missing `pythonXY.lib` is [`PythonLink::Skip`]: the wheel does not link
/// libpython, and there is no import library for this target.
pub fn probe_python_link(
    target_os: &str,
    target_env: &str,
    cfg: &PythonSysconfig,
    mut exists: impl FnMut(&str) -> bool,
) -> Result<PythonLink, ProbeError> {
    if target_os == "windows" && target_env == "msvc" {
        return Ok(msvc_python_link(cfg, &mut exists));
    }
    let name = unix_link_name(&cfg.ldlibrary)?;
    Ok(PythonLink::Named {
        name,
        search_dir: None,
    })
}

/// Body of `OUT_DIR/python_test_link.rs`.
pub fn link_file(link: &PythonLink) -> String {
    match link {
        PythonLink::Named { name, .. } => link_snippet(name),
        PythonLink::Skip => String::new(),
    }
}

/// `/LIBPATH` argument for the MSVC test binary.
pub fn msvc_libpath_arg(dir: &str) -> String {
    format!("/LIBPATH:{dir}")
}

fn link_snippet(name: &str) -> String {
    format!("#[link(name = \"{name}\")]\nunsafe extern \"C\" {{}}\n")
}

/// Stem of `LDLIBRARY`, matching the historical Unix probe.
fn unix_link_name(ldlibrary: &str) -> Result<String, ProbeError> {
    let mut name = ldlibrary.trim();
    if let Some(rest) = name.strip_prefix("lib") {
        name = rest;
    }
    for ext in [".so", ".a", ".dylib"] {
        if let Some((stem, _)) = name.split_once(ext) {
            name = stem;
            break;
        }
    }
    if name.is_empty() {
        Err(ProbeError::EmptyLdlibrary)
    } else {
        Ok(name.to_string())
    }
}

fn msvc_python_link(cfg: &PythonSysconfig, exists: &mut impl FnMut(&str) -> bool) -> PythonLink {
    let Some(resolved) = find_msvc_import_lib(cfg, exists) else {
        return PythonLink::Skip;
    };
    let search_dir = Some(resolved.dir).filter(|dir| !dir.is_empty());
    PythonLink::Named {
        name: resolved.name,
        search_dir,
    }
}

struct MsvcImportLib {
    name: String,
    dir: String,
}

/// `pythonXY.lib` in sysconfig `LIBDIR`, then `{base_prefix}\libs`.
fn find_msvc_import_lib(
    cfg: &PythonSysconfig,
    exists: &mut impl FnMut(&str) -> bool,
) -> Option<MsvcImportLib> {
    let ver = cfg.py_version_nodot.trim();
    if ver.is_empty() {
        return None;
    }
    let file = format!("python{ver}.lib");
    let mut candidates = Vec::new();
    let libdir = cfg.libdir.trim();
    if !libdir.is_empty() {
        candidates.push(win_join(libdir, &file));
    }
    let base = cfg.base_prefix.trim();
    if !base.is_empty() {
        candidates.push(win_join(&win_join(base, "libs"), &file));
    }
    for path in candidates {
        if exists(&path) {
            return Some(MsvcImportLib {
                name: format!("python{ver}"),
                dir: win_parent(&path),
            });
        }
    }
    None
}

fn win_join(dir: &str, child: &str) -> String {
    let dir = dir.trim_end_matches(['\\', '/']);
    format!("{dir}\\{child}")
}

fn win_parent(path: &str) -> String {
    path.rsplit_once('\\')
        .map(|(dir, _)| dir.to_string())
        .unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::{
        ProbeError, PythonLink, PythonSysconfig, link_file, msvc_libpath_arg,
        parse_sysconfig_lines, probe_python_link,
    };

    #[test]
    fn linux_ldlibrary_shapes_keep_the_existing_stem() {
        for (ldlibrary, stem) in [
            ("libpython3.12.so\n", "python3.12"),
            ("libpython3.12.so.1.0\n", "python3.12"),
            ("libpython3.12.a\n", "python3.12"),
        ] {
            let cfg = PythonSysconfig {
                ldlibrary: ldlibrary.into(),
                libdir: "/usr/lib/x86_64-linux-gnu".into(),
                base_prefix: "/usr".into(),
                py_version_nodot: "312".into(),
            };
            let mut called = false;
            let link = probe_python_link("linux", "gnu", &cfg, |_| {
                called = true;
                true
            })
            .unwrap();
            assert!(!called, "{ldlibrary}");
            assert_eq!(
                link,
                PythonLink::Named {
                    name: stem.into(),
                    search_dir: None,
                },
                "{ldlibrary}"
            );
        }
        let cfg = PythonSysconfig {
            ldlibrary: "libpython3.12.so\n".into(),
            ..PythonSysconfig::default()
        };
        let link = probe_python_link("linux", "gnu", &cfg, |_| true).unwrap();
        assert_eq!(
            link_file(&link),
            "#[link(name = \"python3.12\")]\nunsafe extern \"C\" {}\n"
        );
    }

    #[test]
    fn macos_ldlibrary_shape_strips_the_dylib_suffix() {
        let cfg = PythonSysconfig {
            ldlibrary: "libpython3.12.dylib\n".into(),
            libdir: "/usr/local/opt/python@3.12/Frameworks/Python.framework/Versions/3.12/lib"
                .into(),
            base_prefix: "/usr/local/opt/python@3.12/Frameworks/Python.framework/Versions/3.12"
                .into(),
            py_version_nodot: "312".into(),
        };
        let mut called = false;
        let link = probe_python_link("macos", "", &cfg, |_| {
            called = true;
            true
        })
        .unwrap();
        assert!(!called);
        assert_eq!(
            link,
            PythonLink::Named {
                name: "python3.12".into(),
                search_dir: None,
            }
        );
        assert_eq!(
            link_file(&link),
            "#[link(name = \"python3.12\")]\nunsafe extern \"C\" {}\n"
        );
    }

    #[test]
    fn linux_empty_ldlibrary_is_an_error() {
        let cfg = PythonSysconfig {
            ldlibrary: "\n".into(),
            base_prefix: r"C:\Python312".into(),
            py_version_nodot: "312".into(),
            ..PythonSysconfig::default()
        };
        let err = probe_python_link("linux", "gnu", &cfg, |_| true).unwrap_err();
        assert_eq!(err, ProbeError::EmptyLdlibrary);
    }

    #[test]
    fn windows_gnu_empty_ldlibrary_is_still_an_error() {
        let err =
            probe_python_link("windows", "gnu", &PythonSysconfig::default(), |_| true).unwrap_err();
        assert_eq!(err, ProbeError::EmptyLdlibrary);
    }

    #[test]
    fn windows_msvc_empty_ldlibrary_uses_libdir() {
        let text = "\
LDLIBRARY\t\n\
LIBDIR\tD:\\custom\\libs\n\
BASE_PREFIX\tC:\\Python312\n\
PY_VERSION_NODOT\t312\n";
        let cfg = parse_sysconfig_lines(text);
        assert_eq!(cfg.ldlibrary, "");
        assert_eq!(cfg.py_version_nodot, "312");
        let mut seen = Vec::new();
        let link = probe_python_link("windows", "msvc", &cfg, |path| {
            seen.push(path.to_string());
            true
        })
        .unwrap();
        assert_eq!(seen, vec![r"D:\custom\libs\python312.lib".to_string()]);
        assert_eq!(
            link,
            PythonLink::Named {
                name: "python312".into(),
                search_dir: Some(r"D:\custom\libs".into()),
            }
        );
        assert_eq!(
            msvc_libpath_arg(r"D:\custom\libs"),
            r"/LIBPATH:D:\custom\libs"
        );
        assert_eq!(
            link_file(&link),
            "#[link(name = \"python312\")]\nunsafe extern \"C\" {}\n"
        );
    }

    #[test]
    fn windows_msvc_empty_ldlibrary_uses_base_prefix_libs() {
        let text = "\
LDLIBRARY\t\n\
LIBDIR\t\n\
BASE_PREFIX\tC:\\Python312\n\
PY_VERSION_NODOT\t312\n";
        let cfg = parse_sysconfig_lines(text);
        assert_eq!(cfg.ldlibrary, "");
        assert_eq!(cfg.libdir, "");
        let mut seen = Vec::new();
        let link = probe_python_link("windows", "msvc", &cfg, |path| {
            seen.push(path.to_string());
            path == r"C:\Python312\libs\python312.lib"
        })
        .unwrap();
        assert_eq!(seen, vec![r"C:\Python312\libs\python312.lib".to_string()]);
        assert_eq!(
            link,
            PythonLink::Named {
                name: "python312".into(),
                search_dir: Some(r"C:\Python312\libs".into()),
            }
        );
    }

    #[test]
    fn windows_msvc_falls_through_to_base_prefix_when_libdir_misses() {
        let cfg = PythonSysconfig {
            ldlibrary: String::new(),
            libdir: r"D:\missing".into(),
            base_prefix: r"C:\Python312\".into(),
            py_version_nodot: "312".into(),
        };
        let mut seen = Vec::new();
        let link = probe_python_link("windows", "msvc", &cfg, |path| {
            seen.push(path.to_string());
            path.ends_with(r"\libs\python312.lib")
        })
        .unwrap();
        assert_eq!(
            seen,
            vec![
                r"D:\missing\python312.lib".to_string(),
                r"C:\Python312\libs\python312.lib".to_string(),
            ]
        );
        assert_eq!(
            link,
            PythonLink::Named {
                name: "python312".into(),
                search_dir: Some(r"C:\Python312\libs".into()),
            }
        );
    }

    #[test]
    fn windows_msvc_skips_when_the_target_needs_no_link() {
        let cfg = PythonSysconfig {
            ldlibrary: String::new(),
            libdir: String::new(),
            base_prefix: r"C:\Python312".into(),
            py_version_nodot: "312".into(),
        };
        let link = probe_python_link("windows", "msvc", &cfg, |_| false).unwrap();
        assert_eq!(link, PythonLink::Skip);
        assert_eq!(link_file(&link), "");
    }

    #[test]
    fn windows_msvc_skips_when_py_version_nodot_is_empty() {
        let cfg = PythonSysconfig {
            base_prefix: r"C:\Python312".into(),
            ..PythonSysconfig::default()
        };
        let mut called = false;
        let link = probe_python_link("windows", "msvc", &cfg, |_| {
            called = true;
            true
        })
        .unwrap();
        assert!(!called);
        assert_eq!(link, PythonLink::Skip);
    }
}
