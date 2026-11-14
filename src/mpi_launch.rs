//! How tests start `mpirun`.
//!
//! Open MPI refuses extra ranks unless `--oversubscribe` is present.
//! MPICH rejects that flag, so it is added only when `mpirun --help`
//! documents it. A live job's rank variables are removed so a nested
//! launch is not told it is already rank 0 of another world.

use std::process::{Command, Output};

/// `mpirun`, plus `--oversubscribe` on Open MPI.
pub fn mpi_launcher() -> Vec<String> {
    let mut argv = vec!["mpirun".to_string()];
    if Command::new("mpirun")
        .arg("--help")
        .output()
        .ok()
        .is_some_and(|out| {
            let text = String::from_utf8_lossy(&out.stdout);
            let err = String::from_utf8_lossy(&out.stderr);
            text.contains("oversubscribe") || err.contains("oversubscribe")
        })
    {
        argv.push("--oversubscribe".to_string());
    }
    argv
}

/// A `mpirun` command with the launcher flags and a clean rank environment.
pub fn mpi_command() -> Command {
    let mut cmd = Command::new("mpirun");
    for arg in mpi_launcher().into_iter().skip(1) {
        cmd.arg(arg);
    }
    for key in [
        "OMPI_COMM_WORLD_RANK",
        "OMPI_COMM_WORLD_SIZE",
        "OMPI_COMM_WORLD_LOCAL_RANK",
        "OMPI_COMM_WORLD_LOCAL_SIZE",
        "OMPI_COMM_WORLD_NODE_RANK",
        "OMPI_UNIVERSE_SIZE",
        "PMI_RANK",
        "PMI_SIZE",
        "PMI_FD",
        "PMIX_RANK",
        "PMIX_NAMESPACE",
        "HYDRA_CONTROL_FD",
        "HYDI_CONTROL_FD",
        "MPI_LOCALRANKID",
        "MPI_LOCALNRANKS",
    ] {
        cmd.env_remove(key);
    }
    cmd
}

/// Panic with the child's stderr. `status()` alone hides the Open MPI slot error.
pub fn assert_success(output: &Output, label: &str) {
    assert!(
        output.status.success(),
        "{label} failed: {}\n{}",
        output.status,
        String::from_utf8_lossy(&output.stderr)
    );
}
