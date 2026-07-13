#!/usr/bin/env bash
# Structural gate: Codecov multi-flag coverage wiring stays intact.
# Asserts root codecov.yml + .github/workflows/coverage.yml encode rust/python/
# julia/fortran flags, OIDC soft-fail uploads, and real generators.
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
grep -q 'flags' "$COV_YML" || die "codecov.yml comment layout missing flags"
ok "codecov.yml statuses/carryforward/comment"

for flag in rust python julia fortran; do
  if grep -E "flags:[[:space:]]*${flag}" "$WF" | grep -vq '^\s*#'; then
    ok "coverage.yml upload flags: $flag"
  else
    die "coverage.yml missing active flags: $flag"
  fi
done

grep -q 'codecov/codecov-action' "$WF" || die "coverage.yml missing codecov-action"
if grep -E 'fail_ci_if_error:[[:space:]]*true' "$WF" | grep -vq '^\s*#'; then
  die "coverage.yml has fail_ci_if_error: true (want soft-fail false)"
fi
grep -q 'fail_ci_if_error: false' "$WF" || die "coverage.yml missing fail_ci_if_error: false"
# lode-org uploads via Codecov GitHub App OIDC (not HaoZeke global upload token)
grep -q 'use_oidc: true' "$WF" || die "coverage.yml missing use_oidc: true"
grep -q 'id-token: write' "$WF" || die "coverage.yml missing id-token: write for OIDC"
grep -q 'app.codecov.io' "$WF" || die "coverage.yml missing app.codecov.io note"
ok "coverage.yml OIDC soft-fail + docs"

grep -qE 'cargo llvm-cov|run_coverage_rust\.sh' "$WF" || die "missing cargo llvm-cov / run_coverage_rust.sh"
grep -qE 'pytest|run_coverage_python\.sh' "$WF" || die "missing python coverage (pytest / run_coverage_python.sh)"
grep -q 'Coverage' "$WF" || die "missing Julia Coverage.jl"
grep -q 'lcov' "$WF" || die "missing fortran lcov/gcov"
# Expanded feature set so chemfiles/python/rpc are not false-zero
grep -qE 'chemfiles|run_coverage_rust' "$WF" || die "coverage should exercise chemfiles bindings"
# PyO3 surface must land under the python flag via instrumented LCOV
grep -qE 'run_coverage_python\.sh|python_lcov\.info' "$WF" || die "missing python.rs llvm-cov path"
ok "real coverage generators referenced"

if [[ "$fail" -ne 0 ]]; then
  echo "check_codecov_config: FAILED" >&2
  exit 1
fi
echo "check_codecov_config: all checks passed"
