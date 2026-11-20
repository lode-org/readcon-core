#!/usr/bin/env bash
# Run the branch-green gates against every commit in a series.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
BASE="${1:-e8d5953f72838b43493a08ab3351631069f6281d}"
TIP="${2:-HEAD}"
VERSIONS="paper/cpc/data/spec/versions.json"
EXPECTED_VERSIONS_BLOB="3cdbaad50a0fe753bdab3c3bc62e47efbe65f8fa"
RECORD_PATHS=(
    paper/cpc/data
    paper/cpc/bench/results
    paper/cpc/evidence/results
    bench/fidelity/results
    bench/h2h/versions.json
)

if [[ "$(git -C "$ROOT" rev-parse "$BASE:$VERSIONS")" != "$EXPECTED_VERSIONS_BLOB" ]]; then
    echo "$BASE has an unexpected $VERSIONS blob" >&2
    exit 1
fi

# shellcheck source=scripts/scratch.sh
source "$ROOT/scripts/scratch.sh"
scratch="$(scratch_dir)"
trap 'git -C "$ROOT" worktree remove --force "$scratch/worktree" >/dev/null 2>&1 || true; rm -rf "$scratch"' EXIT

while read -r commit; do
    worktree="$scratch/worktree"
    echo "=== checking $commit ==="
    git -C "$ROOT" worktree add --quiet --detach "$worktree" "$commit"

    actual="$(git -C "$worktree" rev-parse "HEAD:$VERSIONS")"
    if [[ "$actual" != "$EXPECTED_VERSIONS_BLOB" ]]; then
        echo "$commit rewrites $VERSIONS as $actual" >&2
        exit 1
    fi

    while read -r status path; do
        [[ -z "$status" ]] && continue
        case "$status" in
            A)
                tip_blob="$(git -C "$ROOT" rev-parse "$TIP:$path")"
                commit_blob="$(git -C "$ROOT" rev-parse "$commit:$path")"
                if [[ "$commit_blob" != "$tip_blob" ]]; then
                    echo "$path changes after its append-only addition" >&2
                    exit 1
                fi
                ;;
            *)
                echo "$commit changes existing record $path ($status)" >&2
                exit 1
                ;;
        esac
    done < <(
        git -C "$ROOT" diff --name-status "$BASE..$commit" -- "${RECORD_PATHS[@]}"
    )

    python3 - "$worktree" <<'PY'
import json
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1])
version = (root / "VERSION").read_text().strip()
path = root / "paper/cpc/data/spec" / f"spec-measurement-{version}.json"
if not path.is_file():
    print(f"PENDING: {path.name} has not been measured")
    raise SystemExit(0)
record = json.loads(path.read_text())
commit = record["measured_at"]["commit"]

def git(*args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True
    )
    if done.returncode:
        raise SystemExit(done.stderr)
    return done.stdout.strip()

if git("show", f"{commit}:VERSION") != record["tree"]["release"]:
    raise SystemExit(f"{path.name} does not match {commit}:VERSION")
if git("rev-parse", f"{commit}:{record['spec']}") != record["tree"]["spec_blob"]:
    raise SystemExit(f"{path.name} does not match {commit}:{record['spec']}")
release_tag = f"v{record['tree']['release']}"
if record["tree"]["tagged"] or release_tag in {entry["tag"] for entry in record["tags"]}:
    raise SystemExit(f"{path.name} falsely claims the pending {release_tag} tag")
print(f"OK: {path.name} records untagged measurement commit {commit}")
PY

    if [[ "${READCON_HISTORY_RECORDS_ONLY:-0}" == "1" ]]; then
        git -C "$ROOT" worktree remove --force "$worktree"
        echo "=== record history passed $commit ==="
        continue
    fi

    (
        cd "$worktree"
        export RUSTUP_TOOLCHAIN="${RUSTUP_TOOLCHAIN:-1.88.0}"
        export CC="${CC:-gcc}"
        export CXX="${CXX:-g++}"
        export CMAKE_POLICY_VERSION_MINIMUM="${CMAKE_POLICY_VERSION_MINIMUM:-3.5}"
        cargo fmt --all -- --check
        cargo clippy --locked --all-targets \
            --features capi,parallel,chemfiles,zstd,grammar,metatensor,mimalloc-allocator,benchmark \
            -- -D warnings
        cargo test --locked
        cargo test --locked --features capi
        bash scripts/run_doc_examples.sh
        bash scripts/check_cxx_wrap_pin.sh
    )

    git -C "$ROOT" worktree remove --force "$worktree"
    echo "=== passed $commit ==="
done < <(git -C "$ROOT" rev-list --reverse "$BASE..$TIP")
