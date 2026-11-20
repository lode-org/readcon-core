//! Decide which libstdc++ `std::string` the linked libchemfiles was built with.
//!
//! The official Linux prebuilt archive is GCC 4.8.5. Its `std::string` is the
//! copy-on-write ABI (`Atom` is 80 bytes). A from-source or distro build uses
//! this compiler's cxx11 string (`Atom` is 128 bytes). The scan walks atoms
//! inline, so the shim has to match the archive that will actually be linked.

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum StringAbi {
    /// Old libstdc++ `std::string`, mangled as `Ss`.
    Cow,
    /// `__cxx11` `std::basic_string`.
    Cxx11,
    /// No string marker. libc++ and MSVC look like this; the ABI macro is a no-op there.
    Unknown,
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

pub fn library_file_names() -> &'static [&'static str] {
    &[
        "libchemfiles.a",
        "libchemfiles.so",
        "libchemfiles.dylib",
        "chemfiles.lib",
    ]
}
