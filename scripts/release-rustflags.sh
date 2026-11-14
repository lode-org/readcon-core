#!/usr/bin/env bash
# Remap $CARGO_HOME and the source directory for a release or wheel build.
#
# Usage (sourced):
#   source scripts/release-rustflags.sh
#   release_rustflags ROOT_DIR
#
# Cargo reads CARGO_ENCODED_RUSTFLAGS, which keeps Windows backslashes.
# RUSTFLAGS is the same list separated by spaces so a tool that only
# forwards that variable still passes the remaps.

release_rustflags() {
    local root="$1"
    local here triple
    here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    # shellcheck source=scripts/reproducible-rustflags.sh
    source "${here}/reproducible-rustflags.sh"
    case "${RUNNER_OS:-}" in
        Windows) triple="x86_64-pc-windows-msvc" ;;
        *) triple="x86_64-unknown-linux-gnu" ;;
    esac
    reproducible_rustflags "${root}" "${triple}"
    if [[ -n "${CARGO_ENCODED_RUSTFLAGS:-}" ]]; then
        RUSTFLAGS="${CARGO_ENCODED_RUSTFLAGS//$'\x1f'/ }"
        export RUSTFLAGS
    fi
    # maturin-action compiles in a container whose tree is /io and whose
    # cargo home is one of these prefixes. A prefix that is not on the
    # host simply does not match.
    local flag
    for flag in \
        "--remap-path-prefix=/io/=/src/" \
        "--remap-path-prefix=/usr/local/cargo/=/cargo-home/" \
        "--remap-path-prefix=/opt/cargo/=/cargo-home/"
    do
        case " ${RUSTFLAGS:-} " in
            *" ${flag} "*) continue ;;
        esac
        RUSTFLAGS="${RUSTFLAGS:+${RUSTFLAGS} }${flag}"
        if [[ -z "${CARGO_ENCODED_RUSTFLAGS:-}" ]]; then
            CARGO_ENCODED_RUSTFLAGS="${flag}"
        else
            CARGO_ENCODED_RUSTFLAGS="${CARGO_ENCODED_RUSTFLAGS}"$'\x1f'"${flag}"
        fi
    done
    export RUSTFLAGS CARGO_ENCODED_RUSTFLAGS
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    echo "source this script; it is not a command" >&2
    exit 2
fi
