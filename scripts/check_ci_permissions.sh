#!/usr/bin/env bash
# Structural gate: PR jobs must not inherit Pages or OIDC write tokens.
# Workflow-scope permissions stay read-only. Pages/OIDC live only on
# trusted-push jobs that do not execute untrusted PR code as their main work.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DOCS="$ROOT/.github/workflows/ci_docs.yml"
COV="$ROOT/.github/workflows/coverage.yml"
fail=0

die() { echo "ERROR: $*" >&2; fail=1; }
ok() { echo "OK: $*"; }

workflow_perm_block() {
  awk '
    /^permissions:/ {p=1; print; next}
    p && /^jobs:/ {exit}
    p {print}
  ' "$1"
}

[[ -f "$DOCS" ]] || die "missing $DOCS"
[[ -f "$COV" ]] || die "missing $COV"

docs_perm="$(workflow_perm_block "$DOCS")"
echo "$docs_perm" | grep -q 'pages:[[:space:]]*write' \
  && die "ci_docs.yml grants pages: write at workflow scope" \
  || ok "ci_docs.yml workflow-scope has no pages: write"
echo "$docs_perm" | grep -q 'id-token:[[:space:]]*write' \
  && die "ci_docs.yml grants id-token: write at workflow scope" \
  || ok "ci_docs.yml workflow-scope has no id-token: write"

# Deploy job keeps Pages + OIDC, and only runs on the default branch.
if awk '
  /^  deploy:/ {d=1}
  d && /^  [a-z].*:/ && !/^  deploy:/ {exit}
  d {print}
' "$DOCS" | grep -q 'pages:[[:space:]]*write'; then
  ok "ci_docs.yml deploy job has pages: write"
else
  die "ci_docs.yml deploy job missing pages: write"
fi
if awk '
  /^  deploy:/ {d=1}
  d && /^  [a-z].*:/ && !/^  deploy:/ {exit}
  d {print}
' "$DOCS" | grep -q 'id-token:[[:space:]]*write'; then
  ok "ci_docs.yml deploy job has id-token: write"
else
  die "ci_docs.yml deploy job missing id-token: write"
fi
if grep -qE "if:.*github\\.ref == 'refs/heads/main'" "$DOCS"; then
  ok "ci_docs.yml deploy restricted to main"
else
  die "ci_docs.yml deploy is not restricted to main"
fi

cov_perm="$(workflow_perm_block "$COV")"
echo "$cov_perm" | grep -q 'id-token:[[:space:]]*write' \
  && die "coverage.yml grants id-token: write at workflow scope" \
  || ok "coverage.yml workflow-scope has no id-token: write"

# OIDC stays on a trusted-push upload job, not on the generate jobs.
if grep -n 'id-token:[[:space:]]*write' "$COV" | grep -vq '^\s*#'; then
  ok "coverage.yml still grants id-token: write somewhere"
else
  die "coverage.yml lost id-token: write (OIDC upload needs it)"
fi
if awk '
  /^  [A-Za-z0-9_-]+:/ {job=$1}
  /id-token:[[:space:]]*write/ {print job}
' "$COV" | grep -q 'upload'; then
  ok "coverage.yml OIDC is on an upload job"
else
  die "coverage.yml id-token: write is not on a dedicated upload job"
fi
if grep -B20 'id-token:[[:space:]]*write' "$COV" | grep -qE 'github.event_name == .push.|refs/heads/main'; then
  ok "coverage.yml OIDC job is push/main gated"
else
  die "coverage.yml OIDC job is not restricted to trusted push"
fi

if [[ "$fail" -ne 0 ]]; then
  echo "check_ci_permissions: FAILED" >&2
  exit 1
fi
echo "check_ci_permissions: all checks passed"
