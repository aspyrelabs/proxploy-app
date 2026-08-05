#!/usr/bin/env bash
# Builds a signed Proxploy release: proxploy-<version>.tar.gz, manifest.json,
# manifest.json.sig — the artifact set packaging/tests/channel_fixture.sh
# serves and packaging/lib/common.sh's install_release() consumes.
#
# The tarball's top-level entries are backend/ and frontend/dist/ as
# siblings, no wrapping directory — that is what install_release() unpacks
# in place, and what backend/proxploy/main.py:24's
# `Path(__file__).resolve().parents[2] / "frontend" / "dist"` resolves once
# main.py sits at <release>/backend/proxploy/main.py.
set -euo pipefail

usage() {
  cat >&2 <<EOF
usage: $0 --version <semver> --key <ed25519-private-key.pem> --out <dir>
          [--channel <name>] [--notes-url <url>] [--poison]

  --version    the release version; overrides the staged
               backend/proxploy/__init__.py so the artifact, the manifest
               and the tag cannot disagree
  --key        Ed25519 private key (PEM) to sign manifest.json with
  --out        directory to write proxploy-<version>.tar.gz, manifest.json
               and manifest.json.sig into
  --channel    manifest "channel" field (default: stable)
  --notes-url  manifest "notes_url" field (default: none)
  --poison     insert a startup-raising line into the staged main.py —
               packaging/tests/channel_fixture.sh's rollback fixture, never
               for a real release
EOF
  exit 1
}

version=""
key=""
out=""
channel=stable
notes_url=""
poison=0

while [ $# -gt 0 ]; do
  case "$1" in
    --version) version="$2"; shift 2 ;;
    --key) key="$2"; shift 2 ;;
    --out) out="$2"; shift 2 ;;
    --channel) channel="$2"; shift 2 ;;
    --notes-url) notes_url="$2"; shift 2 ;;
    --poison) poison=1; shift ;;
    *) usage ;;
  esac
done

[ -n "$version" ] && [ -n "$key" ] && [ -n "$out" ] || usage
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "error: --version must be semver (x.y.z), got '$version'" >&2; exit 1; }
[ -f "$key" ] || { echo "error: --key '$key' not found" >&2; exit 1; }

log() { printf '  %s\n' "$*" >&2; }

script_dir="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$script_dir/.." && pwd)"
backend_dir="$root/backend"
frontend_dir="$root/frontend"

mkdir -p "$out"
out="$(cd "$out" && pwd)"

log "building frontend..."
( cd "$frontend_dir" && npm ci && npm run build )

stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT

log "staging backend/ (excluding .venv, __pycache__, tests/, dod_verify_*, mutants, egg-info)..."
mkdir -p "$stage/backend"
tar --exclude='.venv' --exclude='__pycache__' --exclude='tests' \
    --exclude='dod_verify_*' --exclude='mutants' --exclude='.pytest_cache' \
    --exclude='*.egg-info' --exclude='.git' \
    -cf - -C "$backend_dir" . | tar xf - -C "$stage/backend"

log "staging frontend/dist/..."
mkdir -p "$stage/frontend"
cp -r "$frontend_dir/dist" "$stage/frontend/dist"

log "overriding staged version to $version..."
printf '__version__ = "%s"\n' "$version" > "$stage/backend/proxploy/__init__.py"

if [ "$poison" -eq 1 ]; then
  log "poisoning staged main.py (rollback fixture only)..."
  sed -i '/^) -> FastAPI:$/a\    # POISONED BY channel_fixture.sh — intentional startup failure for the rollback harness (Task 13). Never in a real release.\n    raise RuntimeError("POISONED BY channel_fixture.sh")' \
    "$stage/backend/proxploy/main.py"
fi

tarball_name="proxploy-$version.tar.gz"
log "building $tarball_name..."
tar czf "$out/$tarball_name" -C "$stage" backend frontend

size=$(stat -c%s "$out/$tarball_name")
sha=$(sha256sum "$out/$tarball_name" | cut -d' ' -f1)
released_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)

json_escape() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }

notes_json="null"
if [ -n "$notes_url" ]; then
  notes_json="\"$(json_escape "$notes_url")\""
fi

log "writing manifest.json..."
cat > "$out/manifest.json" <<JSON
{
  "schema": 1,
  "version": "$(json_escape "$version")",
  "channel": "$(json_escape "$channel")",
  "released_at": "$released_at",
  "notes_url": $notes_json,
  "artifacts": {
    "tarball": {
      "name": "$tarball_name",
      "sha256": "$sha",
      "size": $size
    }
  }
}
JSON

log "signing manifest.json..."
openssl pkeyutl -sign -inkey "$key" -rawin -in "$out/manifest.json" -out "$out/manifest.json.sig"

cat "$out/manifest.json"
