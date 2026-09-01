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

# macOS metadata must never reach the tarball, and the reason is not tidiness.
# Apple's tar stores a file's extended attributes as an AppleDouble sidecar
# named `._<name>`. Built on a Mac, this release shipped
# `._c8f2a4b71d90_catalog_upstream_metadata.py` and two more like it inside
# proxploy/migrations/versions/. alembic globs that directory for *.py and
# imports what it finds, an AppleDouble file is binary, and the app died on
# every fresh install with "ValueError: source code string cannot contain null
# bytes" while the installer reported success. It survived review because
# extracting on a Mac reabsorbs `._*` back into xattrs, so the files are
# invisible on the machine that built them and only exist on Linux, which is
# every machine that installs this.
#
# COPYFILE_DISABLE is the documented switch for Apple's tar; the flags below
# cover libarchive's own xattr and file-flag pax headers (the
# "Ignoring unknown extended header keyword LIBARCHIVE.xattr.com.apple.*" and
# SCHILY.fflags lines GNU tar prints during install). GNU tar has neither
# flag and needs neither, so they are probed rather than assumed.
export COPYFILE_DISABLE=1
tar_nometa=()
for flag in --no-mac-metadata --no-xattrs --no-fflags; do
  if tar "$flag" --version >/dev/null 2>&1; then tar_nometa+=("$flag"); fi
done

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

# `data` is the exclude that matters most here, and it was missing. It is the
# developer's own runtime directory: backend/data/proxploy.db holds every
# host_credential row (Proxmox API tokens and the SSH private keys that give
# root on those nodes) and backend/data/master.key is the Fernet key that
# decrypts them. Both shipped inside proxploy-1.0.0.tar.gz to a public URL,
# 29 MB of database and the key to it in the same archive, which is no
# encryption at all. On the target PROXPLOY_DATA_DIR points at
# /var/lib/proxploy, so nothing in a release ever reads this path: it is pure
# leak with no upside. The find guard below is what makes sure it stays out.
log "staging backend/ (excluding .venv, __pycache__, tests/, data/, dod_verify_*, mutants, egg-info)..."
mkdir -p "$stage/backend"
tar "${tar_nometa[@]}" \
    --exclude='.venv' --exclude='__pycache__' --exclude='tests' \
    --exclude='./data' --exclude='./data/*' \
    --exclude='dod_verify_*' --exclude='mutants' --exclude='.pytest_cache' \
    --exclude='.ruff_cache' --exclude='.mypy_cache' --exclude='.coverage' \
    --exclude='./scripts' --exclude='./scripts/*' --exclude='.gitignore' \
    --exclude='*.egg-info' --exclude='.git' --exclude='._*' \
    --exclude='.DS_Store' \
    -cf - -C "$backend_dir" . | tar "${tar_nometa[@]}" -xf - -C "$stage/backend"

log "staging frontend/dist/..."
mkdir -p "$stage/frontend"
# cp -r on macOS copies xattrs too, which become AppleDouble files in the
# tarball exactly like the backend tree did. Same tar-to-tar pipe as above.
mkdir -p "$stage/frontend/dist"
tar "${tar_nometa[@]}" --exclude='._*' --exclude='.DS_Store' \
    -cf - -C "$frontend_dir/dist" . \
  | tar "${tar_nometa[@]}" -xf - -C "$stage/frontend/dist"

# The installer reads proxploy-update, common.sh, proxploy.service and the
# Caddyfile template out of the unpacked release rather than out of its own
# directory, which is what lets a piped one-liner (curl | bash) work at all:
# it has no directory. Shipping them here also puts them under the manifest
# signature, where copying them from an unsigned working tree never was.
#
# An ALLOWLIST, not an exclude list, and that distinction is the whole lesson
# of this file. Excluding what should not ship means every file nobody thought
# to name ships by default: that is how backend/data/proxploy.db and its master
# key reached a public URL, and it also shipped publishing-a-release.md (the
# signing-key runbook, which names where the private key lives), this script
# including its --poison flag, and packaging/docker/. Naming what SHOULD ship
# means a new file in packaging/ is invisible to a release until someone adds
# it here on purpose. These seven are the complete set install.sh and
# proxploy-update read; `grep PP_PKG install.sh` and the UPD_PKG block in
# proxploy-update are the check.
log "staging packaging/ (only the seven files a target reads)..."
for rel in proxploy-update proxploy-update-run lib/common.sh proxploy.service \
           proxploy-update.path proxploy-update.service caddy/Caddyfile.tmpl; do
  src="$root/packaging/$rel"
  [ -f "$src" ] || { echo "error: packaging/$rel is missing" >&2; exit 1; }
  mkdir -p "$stage/packaging/$(dirname "$rel")"
  cat "$src" > "$stage/packaging/$rel"
done
chmod 0755 "$stage/packaging/proxploy-update" "$stage/packaging/proxploy-update-run"

log "overriding staged version to $version..."
printf '__version__ = "%s"\n' "$version" > "$stage/backend/proxploy/__init__.py"

# An installed release verifies the NEXT release's manifest against the pubkey
# it shipped with (proxploy-update reads release_pubkey.pem out of
# $PP_CURRENT), so that file has to be the public half of whatever key signed
# the release carrying it. Deriving it here guarantees that. Maintaining it as
# a hand-committed file did not: the checked-in placeholder matched only a
# gitignored local key, so the upgrade harness verified fine on the one box
# holding that key and failed everywhere else with "manifest signature is
# not valid".
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

# The staged tree is what gets signed, so it is what has to be clean. Checked
# rather than trusted: the excludes above are three separate tar calls and any
# one of them regressing puts binary files back into migrations/versions/,
# where the only symptom is a crash on someone else's machine.
strays=$(find "$stage" \( -name '._*' -o -name '.DS_Store' \) -print)
[ -z "$strays" ] || {
  printf 'error: macOS metadata reached the staged release:\n%s\n' "$strays" >&2
  exit 1
}

# A release must carry no secret and no database, ever. Named patterns rather
# than "did the data/ exclude work", because the next leak will arrive by a
# path nobody predicted: a stray .env, a key copied in for a test, a database
# opened somewhere new. Refuse to sign it.
secrets=$(find "$stage" \( -name '*.key' -o -name '*.db' -o -name '*.db-wal' \
                        -o -name '*.db-shm' -o -name '*.sqlite*' -o -name '.env' \
                        -o -name '*.env' -o -name 'id_rsa*' -o -name 'id_ed25519*' \) \
          -not -name 'release_pubkey.pem' -print)
[ -z "$secrets" ] || {
  printf 'error: refusing to sign a release containing secrets or databases:\n%s\n' \
    "$secrets" >&2
  exit 1
}

tarball_name="proxploy-$version.tar.gz"
log "building $tarball_name..."
tar "${tar_nometa[@]}" -czf "$out/$tarball_name" -C "$stage" backend frontend packaging

# And check the artifact itself, not just the tree it came from: the flags
# above are probed, so on a tar that has none of them this is the only thing
# standing between a Mac build and a broken install.
strays=$(tar tzf "$out/$tarball_name" | grep -E '(^|/)(\._|\.DS_Store)' || true)
[ -z "$strays" ] || {
  printf 'error: macOS metadata reached %s:\n%s\n' "$tarball_name" "$strays" >&2
  exit 1
}

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
