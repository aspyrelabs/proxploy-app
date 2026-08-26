#!/usr/bin/env bash
# Builds a signed Proxploy release: proxploy-<version>.tar.gz, manifest.json,
# manifest.json.sig, plus the bundled single-file install.sh that gets served
# at the install URL: the artifact set packaging/tests/channel_fixture.sh
# serves and packaging/lib/common.sh's install_release() consumes.
#
# The tarball's top-level entries are backend/ and frontend/dist/ as
# siblings, no wrapping directory: that is what install_release() unpacks
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
  --out        directory to write proxploy-<version>.tar.gz, manifest.json,
               manifest.json.sig and the bundled install.sh into
  --channel    manifest "channel" field (default: stable)
  --notes-url  manifest "notes_url" field (default: none)
  --poison     insert a startup-raising line into the staged main.py, 
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

if [ -z "$version" ] || [ -z "$key" ] || [ -z "$out" ]; then usage; fi
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "error: --version must be semver (x.y.z), got '$version'" >&2; exit 1; }
[ -f "$key" ] || { echo "error: --key '$key' not found" >&2; exit 1; }

log() { printf '  %s\n' "$*" >&2; }

# This script runs on whoever is cutting the release's own machine, unlike
# install.sh and common.sh which only ever run on the Debian target and can
# assume GNU coreutils. macOS ships BSD versions under the same names, so the
# two places it matters get a fallback rather than a "command not found" after
# the frontend build has already burned two minutes.
file_size() {  # file_size <path>
  stat -c%s "$1" 2>/dev/null || stat -f%z "$1"
}
file_sha256() {  # file_sha256 <path>
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | cut -d' ' -f1
  else
    shasum -a 256 "$1" | cut -d' ' -f1   # macOS
  fi
}

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

# The installer reads proxploy-update, common.sh, proxploy.service and the
# Caddyfile template out of the unpacked release rather than out of its own
# directory, which is what lets a piped one-liner (curl | bash) work at all:
# it has no directory. Shipping them here also puts them under the manifest
# signature, where copying them from an unsigned working tree never was.
# tests/ is the harness, not part of an install.
log "staging packaging/ (excluding tests/)..."
mkdir -p "$stage/packaging"
tar --exclude='tests' --exclude='.DS_Store' -cf - -C "$root/packaging" . | tar xf - -C "$stage/packaging"

log "overriding staged version to $version..."
printf '__version__ = "%s"\n' "$version" > "$stage/backend/proxploy/__init__.py"

# An installed release verifies the NEXT release's manifest against the pubkey
# it shipped with (proxploy-update reads release_pubkey.pem out of
# $PP_CURRENT), so that file has to be the public half of whatever key signed
# the release carrying it. Deriving it here guarantees that. Maintaining it as
# a hand-committed file did not: the checked-in placeholder matched only
# packaging/tests/DEV_ONLY_release_key.pem, which is gitignored, so the
# upgrade harness verified fine on the one box holding that key and failed
# everywhere else with "manifest signature is not valid".
log "baking the public half of --key into the release..."
openssl pkey -in "$key" -pubout -out "$stage/backend/proxploy/release_pubkey.pem"

if [ "$poison" -eq 1 ]; then
  log "poisoning staged main.py (rollback fixture only)..."
  # python3, not `sed -i`: GNU's `a\` append syntax is not BSD sed's, and
  # this runs on the machine cutting the release, which may be either.
  python3 - "$stage/backend/proxploy/main.py" <<'POISON'
import sys
path = sys.argv[1]
lines = open(path).read().splitlines(keepends=True)
out, marker = [], ") -> FastAPI:\n"
for line in lines:
    out.append(line)
    if line == marker:
        out.append('    # POISONED BY channel_fixture.sh, intentional startup '
                   'failure for the rollback harness (Task 13). '
                   'Never in a real release.\n')
        out.append('    raise RuntimeError("POISONED BY channel_fixture.sh")\n')
open(path, "w").writelines(out)
POISON
fi

tarball_name="proxploy-$version.tar.gz"
log "building $tarball_name..."
tar czf "$out/$tarball_name" -C "$stage" backend frontend packaging

size=$(file_size "$out/$tarball_name")
sha=$(file_sha256 "$out/$tarball_name")
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

# The single file served at the install URL. Not in the manifest and not
# signed: it is the thing that arrives BEFORE there is a key to check anything
# against, so its only trust is the TLS the user's curl already provides. It
# is built here so the published installer and the release it installs are
# never a version apart.
log "bundling install.sh..."
bash "$script_dir/bundle_install.sh" "$out/install.sh"

log "signing manifest.json..."
openssl pkeyutl -sign -inkey "$key" -rawin -in "$out/manifest.json" -out "$out/manifest.json.sig"

cat "$out/manifest.json"
