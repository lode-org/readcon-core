#!/usr/bin/env bash
# Unique files and directories for the other scripts in this directory.
# GitHub Actions sets RUNNER_TEMP. Otherwise the directory is
# <repo>/build/scratch. Sourced, not executed.

scratch_root() {
    if [[ -n "${RUNNER_TEMP:-}" ]]; then
        printf '%s\n' "${RUNNER_TEMP}"
        return
    fi
    local here
    here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    printf '%s\n' "$(cd "${here}/.." && pwd)/build/scratch"
}

scratch_dir() {
    local root dir
    root="$(scratch_root)"
    mkdir -p "${root}"
    dir="${root}/d.${$}.${RANDOM}"
    mkdir "${dir}"
    printf '%s\n' "${dir}"
}

scratch_file() {
    local root file
    root="$(scratch_root)"
    mkdir -p "${root}"
    file="${root}/f.${$}.${RANDOM}${1:-}"
    : > "${file}"
    printf '%s\n' "${file}"
}
