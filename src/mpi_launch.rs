//! How tests start `mpirun`.
//!
//! Open MPI refuses extra ranks unless `--oversubscribe` is present.
//! MPICH rejects that flag, so it is added only when `mpirun --help`
//! documents it. A live job's rank variables are removed so a nested
//! launch is not told it is already rank 0 of another world.

use std::process::{Command, Output};

fn open_mpi() -> bool {
    // `mpirun --help` is a one-screen summary and does not mention
    // `--oversubscribe`. The version line does name Open MPI.
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

/// `mpirun`, plus the Open MPI flags a GitHub runner needs.
///
/// Ubuntu runners expose a verbs device UCX cannot use, and their cgroup
/// rejects the default bind. `--bind-to none` and the `tcp,self` BTL keep
/// `MPI_Init` from exiting 1. MPICH does not get these flags.
pub(crate) fn mpi_launcher() -> Vec<String> {
    let mut argv = vec!["mpirun".to_string()];
    if open_mpi() {
        argv.extend(
            [
                "--oversubscribe",
                "--bind-to",
                "none",
                "--mca",
                "pml",
                "ob1",
                "--mca",
                "btl",
                "tcp,self",
            ]
            .into_iter()
            .map(str::to_string),
        );
    }
    argv
}

/// A `mpirun` command with the launcher flags and a clean rank environment.
pub(crate) fn mpi_command() -> Command {
    let mut cmd = Command::new("mpirun");
    for arg in mpi_launcher().into_iter().skip(1) {
        cmd.arg(arg);
    }
    for (key, _) in std::env::vars() {
        if key.starts_with("OMPI_") || key.starts_with("PMIX_") || key.starts_with("PMI_") {
            cmd.env_remove(key);
        }
    }
    cmd
}

/// Panic with the child's stdout and stderr. Open MPI prints the slot error on stdout.
pub(crate) fn assert_success(output: &Output, label: &str) {
    assert!(
        output.status.success(),
        "{label} failed: {}\nstdout:\n{}\nstderr:\n{}",
        output.status,
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
}
