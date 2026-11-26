//! Link instructions for libpython in the Rust test binary.
//!
//! `LDLIBRARY` is a Makefile variable. Windows CPython leaves it empty or
//! sets it to `pythonXY.dll`, and `sys.abiflags` exists only on Unix.
//! Free-threaded builds add `t` (`python313t`). A macOS framework build
//! reports `Python.framework/Versions/X/Python` instead of `libpython`.

/// One instruction produced from the interpreter config.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum LinkDirective {
    /// `#[link(name = "...")]` inside the test binary only.
    TestLink { name: String },
    /// `cargo:rustc-link-search=framework=<prefix>`.
    FrameworkSearch { prefix: String },
    /// `cargo:rustc-link-lib=framework=<name>`.
    FrameworkLib { name: String },
    /// `cargo:warning=<message>`.
    Warning { message: String },
}

impl LinkDirective {
    /// Cargo directive line, when this is not a test-only `#[link]`.
    pub fn cargo_line(&self) -> Option<String> {
        match self {
            Self::TestLink { .. } => None,
            Self::FrameworkSearch { prefix } => {
                Some(format!("cargo:rustc-link-search=framework={prefix}"))
            }
            Self::FrameworkLib { name } => Some(format!("cargo:rustc-link-lib=framework={name}")),
            Self::Warning { message } => Some(format!("cargo:warning={message}")),
        }
    }
}

/// Link plan for this target.
///
/// `os` is `CARGO_CFG_TARGET_OS`. `version` is sysconfig `VERSION`
/// (`3.12` on Unix, `312` on Windows). `abiflags` is already resolved
/// (`""` or `"t"`, and Windows may use `"_d"`). `framework_prefix` is
/// sysconfig `PYTHONFRAMEWORKPREFIX`.
pub fn python_link_directives(
    os: &str,
    ldlibrary: &str,
    version: &str,
    abiflags: &str,
    framework_prefix: &str,
) -> Vec<LinkDirective> {
    let os = os.trim();
    let ldlibrary = ldlibrary.trim();
    let version = version.trim();
    let abiflags = abiflags.trim();
    let framework_prefix = framework_prefix.trim();

    if os == "windows" {
        let name = format!("python{}{abiflags}", version.replace('.', ""));
        return vec![LinkDirective::TestLink { name }];
    }

    if (os == "macos" || os == "darwin") && ldlibrary.contains(".framework/") {
        let mut directives = Vec::new();
        if !framework_prefix.is_empty() {
            directives.push(LinkDirective::FrameworkSearch {
                prefix: framework_prefix.to_string(),
            });
        }
        directives.push(LinkDirective::FrameworkLib {
            name: "Python".to_string(),
        });
        return directives;
    }

    let stem = unix_library_stem(ldlibrary);
    if !stem.is_empty() {
        return vec![LinkDirective::TestLink { name: stem }];
    }

    let name = format!("python{version}{abiflags}");
    vec![
        LinkDirective::Warning {
            message: format!("LDLIBRARY is empty; using {name}"),
        },
        LinkDirective::TestLink { name },
    ]
}

/// `libpython3.12.so` and `libpython3.12.dylib` both become `python3.12`.
fn unix_library_stem(ldlibrary: &str) -> String {
    let mut name = ldlibrary;
    if let Some(rest) = name.strip_prefix("lib") {
        name = rest;
    }
    for ext in [".so", ".a", ".dylib"] {
        if let Some((stem, _)) = name.split_once(ext) {
            name = stem;
            break;
        }
    }
    name.to_string()
}

#[cfg(test)]
mod tests {
    use super::{LinkDirective, python_link_directives};

    fn link_names(directives: &[LinkDirective]) -> Vec<String> {
        directives
            .iter()
            .filter_map(|directive| match directive {
                LinkDirective::TestLink { name } => Some(name.clone()),
                _ => None,
            })
            .collect()
    }

    fn cargo_lines(directives: &[LinkDirective]) -> Vec<String> {
        directives
            .iter()
            .filter_map(LinkDirective::cargo_line)
            .collect()
    }

    #[test]
    fn windows_import_library_is_python312() {
        for version in ["312", "3.12"] {
            let directives = python_link_directives("windows", "", version, "", "");
            assert_eq!(
                link_names(&directives),
                vec!["python312".to_string()],
                "{version}"
            );
            assert!(cargo_lines(&directives).is_empty(), "{version}");
        }
        let from_dll = python_link_directives("windows", "python312.dll", "3.12", "", "");
        assert_eq!(link_names(&from_dll), vec!["python312".to_string()]);
    }

    #[test]
    fn windows_free_threaded_import_library_is_python313t() {
        for version in ["313", "3.13"] {
            let directives = python_link_directives("windows", "", version, "t", "");
            assert_eq!(
                link_names(&directives),
                vec!["python313t".to_string()],
                "{version}"
            );
            assert!(cargo_lines(&directives).is_empty(), "{version}");
        }
        let from_dll = python_link_directives("windows", "python313t.dll", "313", "t", "");
        assert_eq!(link_names(&from_dll), vec!["python313t".to_string()]);
    }

    #[test]
    fn linux_ldlibrary_stem() {
        let directives = python_link_directives("linux", "libpython3.12.so", "3.12", "", "");
        assert_eq!(link_names(&directives), vec!["python3.12".to_string()]);
        assert!(cargo_lines(&directives).is_empty());

        let threaded = python_link_directives("linux", "libpython3.13t.so", "3.13", "t", "");
        assert_eq!(link_names(&threaded), vec!["python3.13t".to_string()]);
    }

    #[test]
    fn macos_framework_link_directives() {
        let directives = python_link_directives(
            "macos",
            "Python.framework/Versions/3.13/Python",
            "3.13",
            "",
            "/Library/Frameworks",
        );
        assert_eq!(
            cargo_lines(&directives),
            vec![
                "cargo:rustc-link-search=framework=/Library/Frameworks".to_string(),
                "cargo:rustc-link-lib=framework=Python".to_string(),
            ]
        );
        assert!(link_names(&directives).is_empty());

        let dylib = python_link_directives(
            "macos",
            "libpython3.12.dylib",
            "3.12",
            "",
            "/Library/Frameworks",
        );
        assert_eq!(link_names(&dylib), vec!["python3.12".to_string()]);
        assert!(cargo_lines(&dylib).is_empty());
    }

    #[test]
    fn empty_ldlibrary_falls_back_without_panic() {
        let linux = python_link_directives("linux", "", "3.12", "", "");
        assert_eq!(link_names(&linux), vec!["python3.12".to_string()]);
        assert_eq!(
            cargo_lines(&linux),
            vec!["cargo:warning=LDLIBRARY is empty; using python3.12".to_string()]
        );

        let threaded = python_link_directives("linux", "   ", "3.13", "t", "");
        assert_eq!(link_names(&threaded), vec!["python3.13t".to_string()]);
        assert_eq!(
            cargo_lines(&threaded),
            vec!["cargo:warning=LDLIBRARY is empty; using python3.13t".to_string()]
        );

        let macos = python_link_directives("macos", "", "3.12", "", "/Library/Frameworks");
        assert_eq!(link_names(&macos), vec!["python3.12".to_string()]);
        assert!(
            cargo_lines(&macos)
                .iter()
                .all(|line| line.starts_with("cargo:warning="))
        );
    }
}
