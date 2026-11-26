#!/usr/bin/env bash
# One case for the wrap-hash download and older measured-row checks.
# It fails when those scripts still skip a published 404, a missing
# sidecar, a truncated download, or an older row's record file.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
REAL_GIT="$(command -v git)"
fail=0

pass() { printf 'PASS %s\n' "$1"; }
bad() { printf 'FAIL %s\n' "$1" >&2; fail=1; }

write_wrap_bin() {
  local dir="$1"
  cat >"${dir}/git" <<EOF
#!/usr/bin/env bash
if [[ "\${1:-}" == "-C" && "\${3:-}" == "ls-remote" ]]; then
  printf '%s\n' "\${GIT_LS_OUT-}"
  exit 0
fi
exec $(printf '%q' "$REAL_GIT") "\$@"
EOF
  cat >"${dir}/curl" <<'EOF'
#!/usr/bin/env bash
out=""
url=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -o)
      out="$2"
      shift 2
      ;;
    -w|--connect-timeout|--max-time)
      shift 2
      ;;
    -*)
      shift
      ;;
    *)
      url="$1"
      shift
      ;;
  esac
done
if [[ "$url" == *.sha256 ]]; then
  printf 'sidecar\n' >"$out"
  if [[ "${CURL_MODE:-}" == "sidecar404" ]]; then
    printf '404'
    exit 0
  fi
  printf '200'
  exit 0
fi
printf 'partial-asset\n' >"$out"
case "${CURL_MODE:-}" in
  asset404)
    printf '404'
    exit 0
    ;;
  truncate)
    printf '200'
    exit 18
    ;;
  *)
    printf '200'
    exit 0
    ;;
esac
EOF
  chmod +x "${dir}/git" "${dir}/curl"
}

run_wrap() {
  local mode="$1"
  local dir
  dir="$(mktemp -d)"
  write_wrap_bin "$dir"
  set +e
  RUN_OUT="$(
    PATH="${dir}:${PATH}" \
      GIT_LS_OUT="0123456789abcdef0123456789abcdef01234567" \
      CURL_MODE="$mode" \
      bash "${ROOT}/scripts/check_wrap_hash.sh" 2>&1
  )"
  RUN_STATUS=$?
  set -e
  rm -rf "$dir"
}

run_wrap asset404
if [[ "$RUN_STATUS" -ne 0 ]] \
  && grep -q 'could not be downloaded' <<<"$RUN_OUT" \
  && ! grep -q 'wrap has' <<<"$RUN_OUT" \
  && ! grep -q 'not published yet' <<<"$RUN_OUT"; then
  pass "published tag with a missing asset"
else
  bad "published tag with a missing asset"
fi

run_wrap sidecar404
if grep -q 'sidecar compare skipped' <<<"$RUN_OUT" \
  && grep -q 'HTTP 404' <<<"$RUN_OUT"; then
  pass "sha256 sidecar 404 is reported"
else
  bad "sha256 sidecar 404 is reported"
fi

run_wrap truncate
if [[ "$RUN_STATUS" -ne 0 ]] \
  && grep -q 'could not be downloaded' <<<"$RUN_OUT" \
  && grep -q 'curl exit 18' <<<"$RUN_OUT" \
  && ! grep -q 'wrap has' <<<"$RUN_OUT"; then
  pass "truncated download is not a hash mismatch"
else
  bad "truncated download is not a hash mismatch"
fi

versions="${ROOT}/bench/h2h/versions.json"
versions_orig="$(mktemp)"
cp "$versions" "$versions_orig"
restore_versions() {
  cp "$versions_orig" "$versions"
}
trap restore_versions EXIT

tag_bin="$(mktemp -d)"
cat >"${tag_bin}/git" <<EOF
#!/usr/bin/env bash
if [[ "\${1:-}" == "rev-parse" && "\${2:-}" == "--verify" \
  && "\${3:-}" == 'refs/tags/v0.23.2^{commit}' ]]; then
  echo missing >&2
  exit 1
fi
exec $(printf '%q' "$REAL_GIT") "\$@"
EOF
chmod +x "${tag_bin}/git"
python3 - <<'PY'
import json
from pathlib import Path

path = Path("bench/h2h/versions.json")
payload = json.loads(path.read_text(encoding="utf-8"))
payload["record"] = "bench/h2h/does-not-exist.json"
path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY
set +e
older_out="$(PATH="${tag_bin}:${PATH}" bash "${ROOT}/scripts/check_version_sot.sh" 2>&1)"
older_status=$?
set -e
restore_versions
trap - EXIT
rm -rf "$tag_bin"
rm -f "$versions_orig"

if [[ "$older_status" -ne 0 ]] \
  && grep -q 'bench/h2h/does-not-exist.json' <<<"$older_out" \
  && grep -q 'absent' <<<"$older_out"; then
  pass "older row still checks its record file"
else
  bad "older row still checks its record file"
fi

if [[ "$fail" -ne 0 ]]; then
  printf 'develop_reds_rust_nits: FAILED\n' >&2
  exit 1
fi
printf 'develop_reds_rust_nits: all checks passed\n'
