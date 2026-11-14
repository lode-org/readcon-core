//! How tests start `mpirun`.
//!
//! `mpirun --help` does not mention `--oversubscribe`, so Open MPI is
//! recognized from the version line and only then gets that flag. A test
//! in this process may already have called `MPI_Init`, which exports
//! `OMPI_MCA_ess=singleton`. A nested `mpirun` then exits 1 and writes
//! nothing. Every `OMPI_`, `PMIX_`, and `PMI_` variable is removed first.
//! `--bind-to` and a BTL are not added. The CI job sets `UCX_TLS=tcp`,
//! and `mpiexec --oversubscribe -n` is enough for its 1-to-4-rank steps.

use std::process::{Command, Output};

fn open_mpi() -> bool {
    Command::new("mpirun")
        .arg("--version")
        .output()
        .ok()
        .is_some_and(|out| {
            let text = String::from_utf8_lossy(&out.stdout);
            let err = String::from_utf8_lossy(&out.stderr);
            text.contains("Open MPI") || err.contains("Open MPI")
        })
}

/// `mpirun`, plus `--oversubscribe` when the launcher is Open MPI.
///
/// MPICH rejects that flag. A two- or four-core runner cannot place the
/// eight-rank file test without it, and the short `--help` text never
/// names it.
pub(crate) fn mpi_launcher() -> Vec<String> {
    let mut argv = vec!["mpirun".to_string()];
    if open_mpi() {
        argv.push("--oversubscribe".to_string());
    }
    argv
}

/// A `mpirun` command with the launcher flags and a clean rank environment.
pub(crate) fn mpi_command() -> Command {
    let mut cmd = Command::new("mpirun");
    for arg in mpi_launcher().into_iter().skip(1) {
        cmd.arg(arg);
    }
    // `MPI_Init` in this process exports `OMPI_MCA_ess=singleton`. The
    // named rank variables are not that one, and leaving it set makes
    // `mpirun` exit 1 with empty stdout and stderr.
    for (key, _) in std::env::vars() {
        if key.starts_with("OMPI_") || key.starts_with("PMIX_") || key.starts_with("PMI_") {
            cmd.env_remove(key);
        }
    }
    cmd
}

/// Panic with the child's stdout and stderr.
///
/// A missing slot is reported on stderr. `OMPI_MCA_ess=singleton` exits 1
/// and prints neither stream, so an empty capture is itself the diagnosis.
pub(crate) fn assert_success(output: &Output, label: &str) {
    assert!(
        output.status.success(),
        "{label} failed: {}\nstdout:\n{}\nstderr:\n{}",
        output.status,
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
}
