use std::ffi::CStr;

fn main() {
    assert!(!readcon_core::VERSION.is_empty());

    let cell = minimage::Cell::ortho(10.0, 10.0, 10.0).expect("valid cell");
    assert!((cell.dist2([0.2, 0.0, 0.0], [9.4, 0.0, 0.0]) - 0.64).abs() < 1e-12);

    let version = minimage::mi_version();
    assert!(!version.is_null());
    // SAFETY: minimage documents mi_version as a process-static,
    // NUL-terminated string.
    let version = unsafe { CStr::from_ptr(version) };
    assert_eq!(version.to_bytes(), b"0.1.2");
}
