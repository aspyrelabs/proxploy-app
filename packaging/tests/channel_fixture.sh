#!/usr/bin/env bash
# Builds a local, file-served release channel for the install/upgrade/
# rollback harnesses (Tasks 12-13) and the manifest round-trip check
# (Task 11 Step 3). Nothing here touches a real GitHub release — spec D4
# keeps publication out of implementation.
#
# Normal mode:   channel_fixture.sh <dir>
#   -> <dir>/release.pem                    the throwaway public key
#   -> <dir>/1.0.0/{proxploy-1.0.0.tar.gz,manifest.json,manifest.json.sig}
#   -> <dir>/1.0.1/{...}
#
# Poison mode:   channel_fixture.sh <dir> --poison <version>
#   Builds ONLY <dir>/<version>/, identical to a normal build except the
#   staged backend/proxploy/main.py raises on startup (see
#   build_release.sh's --poison). Used by test_upgrade_rollback.sh to prove
#   a bad update rolls itself back. Assumes <dir> already has a channel (and
#   therefore a key) from a prior normal-mode call.
set -euo pipefail

usage() { echo "usage: $0 <dir> [--poison <version>]" >&2; exit 1; }

dir="${1:-}"
[ -n "$dir" ] || usage
shift

poison_version=""
while [ $# -gt 0 ]; do
  case "$1" in
    --poison) poison_version="$2"; shift 2 ;;
    *) usage ;;
  esac
done

log() { printf '  %s\n' "$*" >&2; }

script_dir="$(cd "$(dirname "$0")" && pwd)"
build_release="$script_dir/../build_release.sh"
key="$script_dir/DEV_ONLY_release_key.pem"

mkdir -p "$dir"
dir="$(cd "$dir" && pwd)"

if [ ! -f "$key" ]; then
  log "generating throwaway Ed25519 release keypair (DEV ONLY, never committed)..."
  openssl genpkey -algorithm ed25519 -out "$key"
fi
openssl pkey -in "$key" -pubout -out "$dir/release.pem"

if [ -n "$poison_version" ]; then
  log "building poisoned release $poison_version..."
  bash "$build_release" --version "$poison_version" --key "$key" \
    --out "$dir/$poison_version" --notes-url "https://example.invalid/v$poison_version" \
    --poison
else
  log "building release 1.0.0..."
  bash "$build_release" --version 1.0.0 --key "$key" --out "$dir/1.0.0" \
    --notes-url "https://example.invalid/v1.0.0"
  log "building release 1.0.1..."
  bash "$build_release" --version 1.0.1 --key "$key" --out "$dir/1.0.1" \
    --notes-url "https://example.invalid/v1.0.1"
fi

echo "channel ready: $dir"
