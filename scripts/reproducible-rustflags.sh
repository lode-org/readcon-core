#!/usr/bin/env bash
# Rustc flags that keep a second build of one tree identical.
#
# Usage (sourced, so the caller keeps the variables):
#   source scripts/reproducible-rustflags.sh
#   reproducible_rustflags ROOT_DIR TARGET
#
# CARGO_ENCODED_RUSTFLAGS is the unit-separator form. A Windows path keeps
# its backslashes; RUSTFLAGS would eat them. RUSTFLAGS is folded in and
# then unset, because cargo ignores it once the encoded form is set.
#
# Windows MSVC gets link.exe /Brepro (deterministic PE timestamp and
# CodeView GUID) and /PDBALTPATH so the DLL names the PDB file only.
# cl.exe gets /Brepro through CFLAGS when a cc crate runs. Cargo home,
# rustup home, the crate root, and GITHUB_WORKSPACE are remapped. Longer
# prefixes are listed first so a cargo home under the crate root matches
# the cargo-home label.

# Bash nested functions cannot see a parent's local array. The remap
# list is global for that reason and cleared on every call.
REPRO_PAIRS=()

reproducible_rustflags() {
    local root="$1"
    local target="$2"
    REPRO_PAIRS=()

    has_flag() {
        local want="$1"
        local part
        local IFS=$'\x1f'
        for part in ${CARGO_ENCODED_RUSTFLAGS:-}; do
            if [[ "$part" == "$want" ]]; then
                return 0
            fi
        done
        return 1
    }

    add_flag() {
        local flag="$1"
        case "$flag" in
            --remap-path-prefix=*|link-arg=*)
                if has_flag "$flag"; then
                    return 0
                fi
                ;;
        esac
        if [[ -z "${CARGO_ENCODED_RUSTFLAGS:-}" ]]; then
            CARGO_ENCODED_RUSTFLAGS="$flag"
        else
            CARGO_ENCODED_RUSTFLAGS="${CARGO_ENCODED_RUSTFLAGS}"$'\x1f'"${flag}"
        fi
    }

    # Cargo ignores RUSTFLAGS when the encoded list is already set.
    if [[ -z "${CARGO_ENCODED_RUSTFLAGS:-}" && -n "${RUSTFLAGS:-}" ]]; then
        local word
        # shellcheck disable=SC2086
        for word in $RUSTFLAGS; do
            add_flag "$word"
        done
    fi

    normalize_prefix() {
        local p="$1"
        while [[ "$p" == */ && ${#p} -gt 1 ]]; do
            p="${p%/}"
        done
        while [[ "$p" == *\\ && ${#p} -gt 3 ]]; do
            p="${p%\\}"
        done
        printf '%s' "$p"
    }

    add_remap() {
        local path label sep
        path="$(normalize_prefix "$1")"
        label="$2"
        [[ -n "$path" && "$path" != "/" && "$path" != "." ]] || return 0
        if [[ "$path" =~ ^[A-Za-z]:\\?$ ]]; then
            return 0
        fi
        if [[ "$path" == *\\* ]]; then
            sep='\'
            REPRO_PAIRS+=("${path}${sep}"$'\t'"${label}/")
            REPRO_PAIRS+=("${path//\\//}/"$'\t'"${label}/")
        else
            REPRO_PAIRS+=("${path}/"$'\t'"${label}/")
        fi
    }

    native_forms() {
        local path="$1"
        local label="$2"
        [[ -n "$path" ]] || return 0
        add_remap "$path" "$label"
        if command -v cygpath >/dev/null 2>&1; then
            add_remap "$(cygpath -w "$path")" "$label"
            add_remap "$(cygpath -u "$path")" "$label"
        fi
    }

    local cargo_home="${CARGO_HOME:-}"
    if [[ -z "$cargo_home" ]]; then
        if [[ -n "${USERPROFILE:-}" ]]; then
            cargo_home="${USERPROFILE}\\.cargo"
        elif [[ -n "${HOME:-}" ]]; then
            cargo_home="${HOME}/.cargo"
        fi
    fi
    native_forms "$cargo_home" "/cargo-home"
    if [[ -n "${RUSTUP_HOME:-}" ]]; then
        native_forms "$RUSTUP_HOME" "/rustup"
    fi
    native_forms "$root" "/src"
    if [[ -n "${GITHUB_WORKSPACE:-}" ]]; then
        native_forms "$GITHUB_WORKSPACE" "/workspace"
    fi

    if [[ ${#REPRO_PAIRS[@]} -gt 0 ]]; then
        local sorted line path label
        sorted="$(
            printf '%s\n' "${REPRO_PAIRS[@]}" | python3 -c '
import sys
rows = []
for line in sys.stdin:
    line = line.rstrip("\n")
    if not line:
        continue
    path, label = line.split("\t", 1)
    rows.append((path, label))
rows.sort(key=lambda item: (-len(item[0]), item[0]))
seen = set()
for path, label in rows:
    if path in seen:
        continue
    seen.add(path)
    sys.stdout.write(path + "\t" + label + "\n")
'
        )"
        while IFS= read -r line; do
            [[ -n "$line" ]] || continue
            path="${line%%$'\t'*}"
            label="${line#*$'\t'}"
            add_flag "--remap-path-prefix=${path}=${label}"
        done <<< "$sorted"
    fi

    case "$target" in
        *windows-msvc*)
            add_flag "-C"
            add_flag "link-arg=/Brepro"
            add_flag "-C"
            add_flag "link-arg=/PDBALTPATH:%_PDB%"
            case " ${CFLAGS:-} " in
                *" /Brepro "*|*" /Brepro") ;;
                *) CFLAGS="${CFLAGS:+$CFLAGS }/Brepro" ;;
            esac
            case " ${CXXFLAGS:-} " in
                *" /Brepro "*|*" /Brepro") ;;
                *) CXXFLAGS="${CXXFLAGS:+$CXXFLAGS }/Brepro" ;;
            esac
            export CFLAGS CXXFLAGS
            ;;
    esac

    unset RUSTFLAGS
    export CARGO_ENCODED_RUSTFLAGS
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    echo "source this script; it is not a command" >&2
    exit 2
fi
