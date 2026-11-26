//! Which libpython the `python` feature's test binary should link.
//!
//! The extension module is built with PyO3's `extension-module` feature, so
//! the cdylib does not link libpython. The Rust test binary does. Linux and
//! macOS take the stem of sysconfig `LDLIBRARY`. Windows CPython leaves that
//! variable empty. MSVC uses `pythonXY.lib`, or `pythonXYt.lib` when the
//! build is free-threaded. `py_version_nodot` stays `313` on 3.13t.

/// sysconfig / `sys` values the probe reads. Empty strings mean "unset".
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct PythonSysconfig {
    pub ldlibrary: String,
    pub libdir: String,
    pub base_prefix: String,
    pub py_version_nodot: String,
    /// `py_version_nodot_plat`, for example `313`, `313t`, or `313t-32`.
    pub py_version_nodot_plat: String,
    /// `ABIFLAGS` or `abiflags`.
    pub abiflags: String,
    /// `Py_GIL_DISABLED` as text (`1`, `0`, or empty).
    pub py_gil_disabled: String,
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
            "PY_VERSION_NODOT_PLAT" => cfg.py_version_nodot_plat = value.to_string(),
            "ABIFLAGS" | "abiflags" => cfg.abiflags = value.to_string(),
            "PY_GIL_DISABLED" => cfg.py_gil_disabled = value.to_string(),
            _ => {}
        }
    }
    cfg
}

/// Decide the test-binary link for `target_os` / `target_env`.
///
/// `exists` is consulted only for Windows MSVC import libraries. An empty
/// `LDLIBRARY` on Linux or macOS is [`ProbeError::EmptyLdlibrary`]. On MSVC,
/// a missing import library is [`PythonLink::Skip`]: the wheel does not link
/// libpython, and there is no import library for this target. A free-threaded
/// build looks for `pythonXYt.lib` and does not accept `pythonXY.lib`.
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
///
/// A free-threaded build probes `pythonXYt.lib` first and does not fall
/// back to `pythonXY.lib`. A GIL build probes only `pythonXY.lib`.
fn find_msvc_import_lib(
    cfg: &PythonSysconfig,
    exists: &mut impl FnMut(&str) -> bool,
) -> Option<MsvcImportLib> {
    let ver = cfg.py_version_nodot.trim();
    if ver.is_empty() {
        return None;
    }
    let stem = if msvc_free_threaded(cfg) {
        format!("python{ver}t")
    } else {
        format!("python{ver}")
    };
    let file = format!("{stem}.lib");
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
                name: stem,
                dir: win_parent(&path),
            });
        }
    }
    None
}

/// `py_version_nodot` has no `t`. Any one of the plat suffix, `ABIFLAGS`,
/// or `Py_GIL_DISABLED` marks a free-threaded Windows build.
fn msvc_free_threaded(cfg: &PythonSysconfig) -> bool {
    plat_has_free_thread_suffix(&cfg.py_version_nodot, &cfg.py_version_nodot_plat)
        || abi_flags_free_threaded(&cfg.abiflags)
        || gil_disabled(&cfg.py_gil_disabled)
}

fn plat_has_free_thread_suffix(nodot: &str, plat: &str) -> bool {
    let nodot = nodot.trim();
    let plat = plat.trim();
    if nodot.is_empty() {
        return false;
    }
    match plat.strip_prefix(nodot) {
        Some(rest) => rest.starts_with('t'),
        None => false,
    }
}

fn abi_flags_free_threaded(flags: &str) -> bool {
    flags.trim().contains('t')
}

fn gil_disabled(value: &str) -> bool {
    value.trim() == "1"
}

/// Windows interpreters, in the order they are tried.
///
/// `PYO3_PYTHON` when it names a program, then `python3`, then `python`.
/// An empty `PYO3_PYTHON` is ignored. `python3` is often missing on
/// Windows, or it is the Microsoft Store alias. Linux and macOS are not
/// this list: they still call `python3`.
pub fn windows_interpreter_candidates(pyo3_python: Option<&str>) -> Vec<String> {
    let mut candidates = Vec::new();
    if let Some(program) = pyo3_python
        .map(str::trim)
        .filter(|program| !program.is_empty())
    {
        candidates.push(program.to_string());
    }
    candidates.push("python3".to_string());
    candidates.push("python".to_string());
    candidates
}

/// First Windows interpreter for which `usable` returns true.
pub fn select_windows_interpreter(
    pyo3_python: Option<&str>,
    mut usable: impl FnMut(&str) -> bool,
) -> Option<String> {
    windows_interpreter_candidates(pyo3_python)
        .into_iter()
        .find(|candidate| usable(candidate))
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
        parse_sysconfig_lines, probe_python_link, select_windows_interpreter,
        windows_interpreter_candidates,
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
                ..PythonSysconfig::default()
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
            ..PythonSysconfig::default()
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
            ..PythonSysconfig::default()
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
            ..PythonSysconfig::default()
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

    fn msvc_text(body: &str) -> String {
        format!(
            "\
LDLIBRARY\t\n\
LIBDIR\tD:\\ft\\libs\n\
BASE_PREFIX\tC:\\Python313\n\
{body}"
        )
    }

    fn assert_named(link: &PythonLink, name: &str, dir: &str) {
        assert_eq!(
            link,
            &PythonLink::Named {
                name: name.into(),
                search_dir: Some(dir.into()),
            }
        );
        assert_eq!(
            link_file(link),
            format!("#[link(name = \"{name}\")]\nunsafe extern \"C\" {{}}\n")
        );
    }

    #[test]
    fn windows_msvc_free_threaded_libdir_links_python313t() {
        let text = msvc_text(
            "\
PY_VERSION_NODOT\t313\n\
PY_VERSION_NODOT_PLAT\t313t\n\
ABIFLAGS\t\n\
PY_GIL_DISABLED\t0\n",
        );
        let cfg = parse_sysconfig_lines(&text);
        assert_eq!(cfg.py_version_nodot, "313");
        assert_eq!(cfg.py_version_nodot_plat, "313t");
        let mut seen = Vec::new();
        let link = probe_python_link("windows", "msvc", &cfg, |path| {
            seen.push(path.to_string());
            true
        })
        .unwrap();
        assert_eq!(seen, vec![r"D:\ft\libs\python313t.lib".to_string()]);
        assert_named(&link, "python313t", r"D:\ft\libs");
    }

    #[test]
    fn windows_msvc_free_threaded_base_prefix_libs_links_python313t() {
        let text = "\
LDLIBRARY\t\n\
LIBDIR\tD:\\missing\n\
BASE_PREFIX\tC:\\Python313\\\n\
PY_VERSION_NODOT\t313\n\
PY_VERSION_NODOT_PLAT\t313t\n\
ABIFLAGS\tt\n\
PY_GIL_DISABLED\t1\n";
        let cfg = parse_sysconfig_lines(text);
        let mut seen = Vec::new();
        let link = probe_python_link("windows", "msvc", &cfg, |path| {
            seen.push(path.to_string());
            path.ends_with(r"\libs\python313t.lib")
        })
        .unwrap();
        assert_eq!(
            seen,
            vec![
                r"D:\missing\python313t.lib".to_string(),
                r"C:\Python313\libs\python313t.lib".to_string(),
            ]
        );
        assert_named(&link, "python313t", r"C:\Python313\libs");
    }

    #[test]
    fn windows_msvc_free_threaded_does_not_fall_back_to_the_gil_lib() {
        let text = msvc_text(
            "\
PY_VERSION_NODOT\t313\n\
PY_VERSION_NODOT_PLAT\t313t\n\
ABIFLAGS\tt\n\
PY_GIL_DISABLED\t1\n",
        );
        let cfg = parse_sysconfig_lines(&text);
        let mut seen = Vec::new();
        let link = probe_python_link("windows", "msvc", &cfg, |path| {
            seen.push(path.to_string());
            path.ends_with("python313.lib")
        })
        .unwrap();
        assert_eq!(link, PythonLink::Skip);
        assert_eq!(
            seen,
            vec![
                r"D:\ft\libs\python313t.lib".to_string(),
                r"C:\Python313\libs\python313t.lib".to_string(),
            ]
        );
    }

    #[test]
    fn windows_msvc_gil_build_does_not_pick_a_t_lib() {
        let text = "\
LDLIBRARY\t\n\
LIBDIR\tC:\\Python313\\libs\n\
BASE_PREFIX\tC:\\Python313\n\
PY_VERSION_NODOT\t313\n\
PY_VERSION_NODOT_PLAT\t313\n\
ABIFLAGS\t\n\
PY_GIL_DISABLED\t0\n";
        let cfg = parse_sysconfig_lines(text);
        assert_eq!(cfg.py_version_nodot, "313");
        assert_eq!(cfg.abiflags, "");
        assert_eq!(cfg.py_gil_disabled, "0");
        let mut seen = Vec::new();
        let link = probe_python_link("windows", "msvc", &cfg, |path| {
            seen.push(path.to_string());
            true
        })
        .unwrap();
        assert_eq!(seen, vec![r"C:\Python313\libs\python313.lib".to_string()]);
        assert_named(&link, "python313", r"C:\Python313\libs");

        let mut seen_only_t = Vec::new();
        let skipped = probe_python_link("windows", "msvc", &cfg, |path| {
            seen_only_t.push(path.to_string());
            path.ends_with("python313t.lib")
        })
        .unwrap();
        assert_eq!(skipped, PythonLink::Skip);
        assert!(!seen_only_t.is_empty());
        assert!(
            seen_only_t
                .iter()
                .all(|path| path.ends_with(r"python313.lib")),
            "{seen_only_t:?}"
        );
    }

    #[test]
    fn windows_msvc_free_threaded_signal_is_plat_or_abiflags_or_gil() {
        let cases = [
            (
                "314",
                "\
PY_VERSION_NODOT\t314\n\
PY_VERSION_NODOT_PLAT\t314t-32\n\
ABIFLAGS\t\n\
PY_GIL_DISABLED\t0\n",
                "python314t",
            ),
            (
                "313",
                "\
PY_VERSION_NODOT\t313\n\
PY_VERSION_NODOT_PLAT\t313\n\
ABIFLAGS\tt\n\
PY_GIL_DISABLED\t\n",
                "python313t",
            ),
            (
                "313",
                "\
PY_VERSION_NODOT\t313\n\
PY_VERSION_NODOT_PLAT\t\n\
abiflags\t\n\
PY_GIL_DISABLED\t1\n",
                "python313t",
            ),
        ];
        for (nodot, body, stem) in cases {
            let cfg = parse_sysconfig_lines(&msvc_text(body));
            assert_eq!(cfg.py_version_nodot, nodot, "{body}");
            let mut seen = Vec::new();
            let link = probe_python_link("windows", "msvc", &cfg, |path| {
                seen.push(path.to_string());
                true
            })
            .unwrap();
            let file = format!(r"D:\ft\libs\{stem}.lib");
            assert_eq!(seen, vec![file], "{body}");
            assert_named(&link, stem, r"D:\ft\libs");
        }
    }

    #[test]
    fn windows_interpreter_order_is_pyo3_python_then_python3_then_python() {
        assert_eq!(
            windows_interpreter_candidates(Some(r"C:\py313t\python.exe")),
            vec![
                r"C:\py313t\python.exe".to_string(),
                "python3".to_string(),
                "python".to_string(),
            ]
        );
        assert_eq!(
            windows_interpreter_candidates(Some(" \t")),
            vec!["python3".to_string(), "python".to_string()]
        );
        assert_eq!(
            windows_interpreter_candidates(None),
            vec!["python3".to_string(), "python".to_string()]
        );

        let mut seen = Vec::new();
        let chosen = select_windows_interpreter(None, |program| {
            seen.push(program.to_string());
            program == "python"
        });
        assert_eq!(chosen.as_deref(), Some("python"));
        assert_eq!(seen, vec!["python3".to_string(), "python".to_string()]);

        let mut seen_first = Vec::new();
        let chosen = select_windows_interpreter(Some(r"D:\py\python.exe"), |program| {
            seen_first.push(program.to_string());
            true
        });
        assert_eq!(chosen.as_deref(), Some(r"D:\py\python.exe"));
        assert_eq!(seen_first, vec![r"D:\py\python.exe".to_string()]);

        let chosen = select_windows_interpreter(Some(r"D:\missing\python.exe"), |program| {
            program == "python"
        });
        assert_eq!(chosen.as_deref(), Some("python"));
        assert_eq!(select_windows_interpreter(None, |_| false), None);
    }
}
