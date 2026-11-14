//! A cdylib built with `local_dynamic_tls` must dlopen after the process
//! static-TLS surplus is gone, and must not carry initial-exec relocations.

use std::path::PathBuf;
use std::process::Command;

fn cdylib() -> PathBuf {
    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let target = manifest.join("target").join("tls-cdylib");
    let status = Command::new("cargo")
        .args([
            "rustc",
            "--locked",
            "--release",
            "--lib",
            "--crate-type",
            "cdylib",
            "--features",
            "local_dynamic_tls",
            "--target-dir",
        ])
        .arg(&target)
        .arg("--manifest-path")
        .arg(manifest.join("Cargo.toml"))
        .status()
        .expect("cargo rustc");
    assert!(status.success(), "cdylib build failed");
    let so = target.join("release").join("libreadcon_core.so");
    assert!(so.is_file(), "missing {}", so.display());
    so
}

#[cfg(target_os = "linux")]
#[test]
fn a_late_dlopen_has_no_initial_exec_tls() {
    let so = cdylib();
    let dynamic = Command::new("readelf")
        .args(["-d", so.to_str().unwrap()])
        .output()
        .expect("readelf -d");
    assert!(dynamic.status.success());
    let dynamic = String::from_utf8_lossy(&dynamic.stdout);
    assert!(
        !dynamic.contains("STATIC_TLS"),
        "DF_STATIC_TLS still set:\n{dynamic}"
    );
    let relocs = Command::new("readelf")
        .args(["-r", so.to_str().unwrap()])
        .output()
        .expect("readelf -r");
    assert!(relocs.status.success());
    let relocs = String::from_utf8_lossy(&relocs.stdout);
    assert!(
        !relocs.contains("TPOFF"),
        "initial-exec TLS relocation remains:\n{relocs}"
    );

    let script = r#"
import ctypes, hashlib, sqlite3, ssl, sys
from pathlib import Path

so = Path(sys.argv[1])
work = Path(sys.argv[2])
try:
    import numpy  # TLS-heavy when it is installed
except ImportError:
    numpy = None

# Spend the static-TLS surplus on purpose-built initial-exec objects.
src = work / "filler.c"
src.write_text("__thread char slot[65536]; int bump(void) { slot[0] += 1; return slot[0]; }\n")
fillers = []
for i in range(64):
    path = work / f"filler-{i}.so"
    built = __import__("subprocess").run(
        ["gcc", "-shared", "-fPIC", "-ftls-model=initial-exec", "-o", str(path), str(src)],
        check=False,
    )
    if built.returncode != 0:
        raise SystemExit(f"filler compile failed: {built.returncode}")
    try:
        fillers.append(ctypes.CDLL(str(path)))
    except OSError as err:
        if "static TLS" not in str(err):
            raise
        break
else:
    raise SystemExit("64 initial-exec objects did not exhaust static TLS")

lib = ctypes.CDLL(str(so))
lib.rkr_symbol_to_z.argtypes = [ctypes.c_char_p]
lib.rkr_symbol_to_z.restype = ctypes.c_uint64
got = lib.rkr_symbol_to_z(b"Cu")
if got != 29:
    raise SystemExit(f"rkr_symbol_to_z(Cu)={got}")
print(f"dlopen-ok fillers={len(fillers)} numpy={numpy is not None}")
"#;
    let dir = tempfile::tempdir().expect("tempdir");
    let mut child = Command::new("python3");
    child.arg("-c").arg(script).arg(&so).arg(dir.path());
    let output = child.output().expect("python");
    assert!(
        output.status.success(),
        "late dlopen failed\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
}
