#!/usr/bin/env bash
# Structural gate: packaging/wrapdb/readcon-core.wrap source_hash matches
# the published cxx tarball SHA used in the wrap file and consumer docs.
# Does not compile. Run from the repository root.
set -euo pipefail
# shellcheck source=scripts/scratch.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scratch.sh"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
fail=0

die() { echo "ERROR: $*" >&2; fail=1; }
ok() { echo "OK: $*"; }

WRAP="$ROOT/packaging/wrapdb/readcon-core.wrap"
WRAP_IN="$ROOT/packaging/wrapdb/readcon-core.wrap.in"

[[ -f "$WRAP" ]] || die "missing packaging/wrapdb/readcon-core.wrap"
[[ -f "$WRAP_IN" ]] || die "missing packaging/wrapdb/readcon-core.wrap.in"

cargo_ver="$(cd "$ROOT" && python3 -c 'import sys; sys.path.insert(0, "scripts"); from version_sot import read_version; print(read_version(), end="")')"
[[ -n "$cargo_ver" ]] || die "could not read VERSION"

wrap_kv() {
  local key="$1"
  sed -n "s/^${key}[[:space:]]*=[[:space:]]*//p" "$WRAP" | head -1
}

directory="$(wrap_kv directory)"
source_url="$(wrap_kv source_url)"
source_filename="$(wrap_kv source_filename)"
source_hash_raw="$(wrap_kv source_hash)"
source_hash="${source_hash_raw#sha256:}"

if [[ "$directory" == "readcon-core-cxx-${cargo_ver}" ]]; then
  ok "wrap directory is readcon-core-cxx-${cargo_ver}"
else
  die "wrap directory '${directory}' is not readcon-core-cxx-${cargo_ver}"
fi

expected_url="https://github.com/lode-org/readcon-core/releases/download/v${cargo_ver}/readcon-core-cxx-${cargo_ver}.tar.gz"
if [[ "$source_url" == "$expected_url" ]]; then
  ok "wrap source_url is the published v${cargo_ver} cxx tarball"
else
  die "wrap source_url '${source_url}' is not ${expected_url}"
fi

if [[ "$source_filename" == "readcon-core-cxx-${cargo_ver}.tar.gz" ]]; then
  ok "wrap source_filename is readcon-core-cxx-${cargo_ver}.tar.gz"
else
  die "wrap source_filename '${source_filename}' is not readcon-core-cxx-${cargo_ver}.tar.gz"
fi

if [[ "$source_hash" =~ ^[0-9a-f]{64}$ ]]; then
  ok "wrap source_hash is a 64-char sha256"
else
  die "wrap source_hash '${source_hash_raw}' is not a 64-char sha256"
fi

sidecar="$(tr -d '[:space:]' < "$ROOT/packaging/wrapdb/readcon-core.sha256")"
if [[ "$sidecar" == "$source_hash" ]]; then
  ok "sha256 sidecar matches the wrap"
else
  die "sha256 sidecar '${sidecar}' does not match wrap '${source_hash}'"
fi

if command -v curl >/dev/null 2>&1 && command -v sha256sum >/dev/null 2>&1; then
  # The wrap URL names one archive. If that release exists, its bytes
  # must be this hash. Skipping the compare whenever HEAD was not the
  # tag let the v0.23.2 URL keep a hash the upload does not have.
  # A missing tag or an unreachable host means the archive is not
  # available yet. A 404 after refs/tags/vX was listed is a failed
  # download. A non-zero curl status after HTTP 200 is a download
  # failure, not a hash mismatch. A finished archive whose hash
  # differs still fails.
  compare_live=1
  tag_listed=0
  tag_published=0
  peeled=""
  if command -v git >/dev/null 2>&1 && git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    remote="$(git -C "$ROOT" remote get-url origin 2>/dev/null || true)"
    if [[ -n "$remote" ]]; then
      tag_listed=0
      peeled=""
      if peeled_out="$(git -C "$ROOT" ls-remote "$remote" "refs/tags/v${cargo_ver}^{}" 2>/dev/null)"; then
        tag_listed=1
        peeled="$(printf '%s\n' "$peeled_out" | awk 'NR==1 {print $1}')"
        if [[ -z "$peeled" ]]; then
          if peeled_out="$(git -C "$ROOT" ls-remote "$remote" "refs/tags/v${cargo_ver}" 2>/dev/null)"; then
            peeled="$(printf '%s\n' "$peeled_out" | awk 'NR==1 {print $1}')"
          else
            tag_listed=0
          fi
        fi
      fi
      if [[ "$tag_listed" -eq 1 && -n "$peeled" ]]; then
        tag_published=1
      elif [[ "$tag_listed" -eq 1 && -z "$peeled" ]]; then
        ok "v${cargo_ver} is not published; the wrap hash is the archive this tree will upload"
        compare_live=0
      elif [[ "$tag_listed" -eq 0 ]]; then
        ok "could not list refs/tags/v${cargo_ver}; the asset download decides"
      fi
    fi
  fi
  asset="$(scratch_file)"
  if [[ "$compare_live" -eq 0 ]]; then
    rm -f "$asset"
  else
    curl_status=0
    http_code="$(curl -sS -L --connect-timeout 20 --max-time 180 -o "$asset" -w '%{http_code}' "$source_url" 2>/dev/null)" || curl_status=$?
    if [[ "$curl_status" -ne 0 && "$http_code" == "200" ]]; then
      rm -f "$asset"
      die "v${cargo_ver} asset ${source_url} could not be downloaded (curl exit ${curl_status})"
    elif [[ "$http_code" == "200" ]]; then
      live="$(sha256sum "$asset" | awk '{print $1}')"
      rm -f "$asset"
      sidecar_file="$(scratch_file)"
      sidecar_status=0
      sidecar_code="$(curl -sS -L --connect-timeout 20 --max-time 60 -o "$sidecar_file" -w '%{http_code}' "${source_url}.sha256" 2>/dev/null)" || sidecar_status=$?
      sidecar_live=""
      if [[ "$sidecar_status" -ne 0 && "$sidecar_code" == "200" ]]; then
        ok "skipped ${source_url}.sha256 (download failed, curl exit ${sidecar_status}); sidecar compare skipped"
      elif [[ "$sidecar_code" == "200" ]]; then
        sidecar_live="$(awk '{print $1}' "$sidecar_file")"
      elif [[ "$sidecar_code" == "404" ]]; then
        ok "skipped ${source_url}.sha256 (HTTP 404); sidecar compare skipped"
      elif [[ "$sidecar_status" -ne 0 || -z "$sidecar_code" || "$sidecar_code" == "000" ]]; then
        ok "skipped ${source_url}.sha256 (unreachable, curl exit ${sidecar_status}); sidecar compare skipped"
      else
        ok "skipped ${source_url}.sha256 (HTTP ${sidecar_code}); sidecar compare skipped"
      fi
      rm -f "$sidecar_file"
      if [[ -n "$sidecar_live" && "$sidecar_live" != "$live" ]]; then
        die "published ${source_url}.sha256 is '${sidecar_live}', asset is '${live}'"
      elif [[ -n "$sidecar_live" ]]; then
        ok "published .sha256 matches the asset"
      fi
      if [[ "$live" == "$source_hash" ]]; then
        ok "published asset ${source_url} matches wrap source_hash"
      else
        die "published asset ${source_url} is '${live}', wrap has '${source_hash}'"
      fi
    elif [[ "$http_code" == "404" ]]; then
      rm -f "$asset"
      if [[ "$tag_listed" -eq 1 && "$tag_published" -eq 1 ]]; then
        die "v${cargo_ver} is published but ${source_url} could not be downloaded"
      else
        ok "v${cargo_ver} asset returned HTTP 404; skipping live hash compare"
      fi
    elif [[ -z "$http_code" || "$http_code" == "000" ]]; then
      rm -f "$asset"
      ok "could not reach ${source_url} (curl exit ${curl_status}); skipping live hash compare"
    elif [[ "$curl_status" -ne 0 ]]; then
      rm -f "$asset"
      die "v${cargo_ver} asset ${source_url} could not be downloaded (curl exit ${curl_status})"
    else
      rm -f "$asset"
      die "v${cargo_ver} asset ${source_url} returned HTTP ${http_code}"
    fi
  fi
fi

generated="$(sed -e "s/@VERSION@/${cargo_ver}/g" -e "s/@SHA256@/${source_hash}/g" "$WRAP_IN")"
if [[ "$generated" == "$(cat "$WRAP")" ]]; then
  ok "wrap.in substitutes to packaging/wrapdb/readcon-core.wrap"
else
  die "packaging/wrapdb/readcon-core.wrap does not match wrap.in + Cargo.toml + source_hash"
fi

DOC_FILES=(
  "docs/source/getting-started.rst"
  "docs/source/bindings.rst"
  "docs/orgmode/getting-started.org"
  "docs/orgmode/bindings.org"
)
for rel in "${DOC_FILES[@]}"; do
  f="$ROOT/$rel"
  [[ -f "$f" ]] || { die "missing $rel"; continue; }
  if grep -qE "URL_HASH SHA256=${source_hash}|SHA256=${source_hash}" "$f"; then
    ok "$rel documents SHA256=${source_hash}"
  else
    die "$rel does not document the wrap source_hash ${source_hash}"
  fi
  if [[ "$rel" == docs/orgmode/* ]]; then
    name_pat="readcon-core-cxx-@READCON_VERSION@.tar.gz"
  else
    name_pat="readcon-core-cxx-${cargo_ver}.tar.gz"
  fi
  if grep -q -F "$name_pat" "$f"; then
    ok "$rel names the cxx tarball (${name_pat})"
  else
    die "$rel does not name ${name_pat}"
  fi
done

if [[ "$fail" -ne 0 ]]; then
  echo "check_wrap_hash: FAILED" >&2
  exit 1
fi
echo "check_wrap_hash: all checks passed"
