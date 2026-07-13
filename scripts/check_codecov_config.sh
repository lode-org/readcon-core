#!/usr/bin/env bash
# Structural gate: Codecov multi-flag coverage wiring stays intact.
# Asserts root codecov.yml + .github/workflows/coverage.yml encode rust/python/
# julia/fortran flags, soft-fail uploads, and CODECOV_TOKEN (no hard-fail).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COV_YML="$ROOT/codecov.yml"
WF="$ROOT/.github/workflows/coverage.yml"
fail=0

die() { echo "ERROR: $*" >&2; fail=1; }
ok() { echo "OK: $*"; }

[[ -f "$COV_YML" ]] || die "missing $COV_YML"
[[ -f "$WF" ]] || die "missing $WF"

for flag in rust python julia fortran; do
  if grep -qE "name:[[:space:]]*${flag}" "$COV_YML"; then
    ok "codecov.yml flag $flag"
  else
    die "codecov.yml missing flag $flag"
  fi
done

grep -q 'informational: true' "$COV_YML" || die "codecov.yml missing informational: true"
grep -q 'carryforward: true' "$COV_YML" || die "codecov.yml missing carryforward: true"
grep -q 'layout:.*"reach,diff,flags,files"' "$COV_YML" \
  || grep -q "layout: 'reach,diff,flags,files'" "$COV_YML" \
  || grep -q 'flags' "$COV_YML" || die "codecov.yml comment layout missing flags"
ok "codecov.yml statuses/carryforward/comment"

# Active (uncommented) codecov-action uploads with distinct flags
for flag in rust python julia fortran; do
  if grep -E "flags:[[:space:]]*${flag}" "$WF" | grep -vq '^\s*#'; then
    ok "coverage.yml upload flags: $flag"
  else
    die "coverage.yml missing active flags: $flag"
  fi
done

grep -q 'codecov/codecov-action' "$WF" || die "coverage.yml missing codecov-action"
# No hard-fail on token issues
if grep -E 'fail_ci_if_error:[[:space:]]*true' "$WF" | grep -vq '^\s*#'; then
  die "coverage.yml has fail_ci_if_error: true (want soft-fail false)"
fi
grep -q 'fail_ci_if_error: false' "$WF" || die "coverage.yml missing fail_ci_if_error: false"
grep -q 'secrets.CODECOV_TOKEN' "$WF" || die "coverage.yml missing secrets.CODECOV_TOKEN"
# Header documents token source
grep -q 'CODECOV_TOKEN' "$WF" || die "coverage.yml missing CODECOV_TOKEN docs"
grep -q 'app.codecov.io' "$WF" || die "coverage.yml missing app.codecov.io note"
ok "coverage.yml soft-fail token + docs"

# Real generators, not stubs
grep -q 'cargo llvm-cov' "$WF" || die "missing cargo llvm-cov"
grep -q 'pytest' "$WF" || die "missing pytest coverage step"
grep -q 'Coverage' "$WF" || die "missing Julia Coverage.jl"
grep -q 'lcov' "$WF" || die "missing fortran lcov/gcov"
ok "real coverage generators referenced"

if [[ "$fail" -ne 0 ]]; then
  echo "check_codecov_config: FAILED" >&2
  exit 1
fi
echo "check_codecov_config: all checks passed"
