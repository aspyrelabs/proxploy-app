#!/usr/bin/env bash
# Shared helpers for install.sh and proxploy-update. Sourced, never executed.
#
# Layout constants (Phase 9a plan, Task 6):
#   /opt/proxploy/releases/<version>/{backend/,frontend/dist/}
#   /opt/proxploy/releases/<version>/backend/venv/: one venv per release
#   /opt/proxploy/current -> releases/<version>
#   /opt/proxploy/bin/proxploy-update
#   /opt/proxploy/lib/common.sh: this file, installed
#   /var/lib/proxploy/{proxploy.db,master.key,uploads/,pre-update/}
#   /etc/proxploy/proxploy.env
#   /etc/systemd/system/proxploy.service
#
# This file only defines these constants and functions; every one of them is
# consumed by install.sh and packaging/proxploy-update, which source it: not
# by this file itself, so shellcheck's "appears unused" is a false positive
# for every constant below. This directive must precede the first command
# (set -euo pipefail included) to apply file-wide.
# shellcheck disable=SC2034
set -euo pipefail

PP_ROOT="${PP_ROOT:-/opt/proxploy}"
PP_RELEASES="$PP_ROOT/releases"
PP_CURRENT="$PP_ROOT/current"
PP_BIN="$PP_ROOT/bin"
PP_LIB="$PP_ROOT/lib"
PP_DATA="${PP_DATA:-/var/lib/proxploy}"
PP_ETC="${PP_ETC:-/etc/proxploy}"
PP_ENV="$PP_ETC/proxploy.env"
PP_USER=proxploy

log()  { printf '  %s\n' "$*" >&2; }
die()  { printf 'error: %s\n' "$*" >&2; exit 1; }
need_root() { [ "$(id -u)" -eq 0 ] || die "run as root"; }

# manifest_field <key> <file>: pull a top-level string field out of
# manifest.json without a JSON parser: build_release.sh always writes one
# `"key": "value",` per line, so this sed is sufficient. install.sh,
# proxploy-update and verify_release() below all extracted fields this way
# independently before this was factored out; one copy so they can't drift.
manifest_field() {  # manifest_field <key> <file>
  sed -n "s/.*\"$1\": *\"\([^\"]*\)\".*/\1/p" "$2" | head -1
}

fetch_to() {  # fetch_to <url> <dest>
  local url="$1" dest="$2"
  case "$url" in
    file://*) cp "${url#file://}" "$dest" ;;
    *) curl -fsSL --retry 3 --retry-delay 2 -o "$dest" "$url" ;;
  esac
}

# verify_release: signature-then-checksum, in that order: same order as
# services/release.py (verify_manifest signs raw bytes before any parsing).
#
# Verified on this box (OpenSSL 3.5.5, `openssl pkeyutl -help 2>&1 | grep
# rawin` reports the flag): `pkeyutl -rawin` exists and is the documented way
# to verify a raw (non-prehashed) Ed25519 signature with openssl(1): Ed25519
# does its own internal hashing, so -rawin (no digest) is required, not just
# allowed. `-rawin` for pkeyutl shipped in OpenSSL 3.0.0, and Debian 12
# (bookworm) ships OpenSSL 3.0.11, so it is present on the target OS. This
# installer runs before any venv exists, so the pure-openssl path below is
# used; there is no Python fallback because none is needed.
verify_release() {  # verify_release <workdir> <pubkey-pem>
  local dir="$1" pub="$2"
  openssl pkeyutl -verify -pubin -inkey "$pub" -rawin \
      -in "$dir/manifest.json" -sigfile "$dir/manifest.json.sig" >/dev/null \
    || die "manifest signature is not valid, refusing to install"
  local want name
  name=$(manifest_field name "$dir/manifest.json")
  want=$(manifest_field sha256 "$dir/manifest.json")
  echo "$want  $dir/$name" | sha256sum -c - >/dev/null \
    || die "$name: sha256 mismatch, refusing to install"
}

# install_release: unpack a verified tarball into its own versioned release
# directory and build its own venv. Never touches $PP_DATA: releases are
# code only, data and secrets live outside releases/ by design.
#
# Assumes the tarball's top-level entries are `backend/` and `frontend/dist/`
# directly (no wrapping directory): the shape build_release.sh (Task 11)
# stages and tar's up, and the same shape packaging/docker/Dockerfile (Task
# 10) copies into its runtime image. main.py:167 resolves the frontend as
# `parents[2]/frontend/dist` relative to backend/proxploy/main.py, which only
# holds if backend/ and frontend/dist/ are siblings under the release dir.
install_release() {  # install_release <tarball> <version>
  local tarball="$1" version="$2" dest
  dest="$PP_RELEASES/$version"
  mkdir -p "$dest"
  tar xzf "$tarball" -C "$dest"
  python3 -m venv "$dest/backend/venv"
  "$dest/backend/venv/bin/pip" install --no-cache-dir --quiet --upgrade pip
  # -e (editable), not a regular install: a plain `pip install backend/` copies
  # proxploy/ into venv/lib/.../site-packages, so main.py's
  # `Path(__file__).resolve().parents[2] / "frontend" / "dist"` resolves under
  # site-packages instead of the release tree: the API still answers, but
  # `/` 404s because the SPA is never found. The release directory is
  # immutable and IS the install location, so keeping __file__ pointed at
  # $dest/backend/proxploy is correct here, not a dev-mode leftover.
  "$dest/backend/venv/bin/pip" install --no-cache-dir --quiet -e "$dest/backend"
}

# migrate_release: run a release's own alembic against the live database.
# alembic.ini's script_location is the relative path "proxploy/migrations",
# which alembic resolves against the current working directory, not the ini
# file's location: so this must run from inside backend/, or every caller
# hits "Path doesn't exist: proxploy/migrations" against its own cwd instead.
# Shared here so install.sh and proxploy-update can't drift out of sync on
# this again.
migrate_release() {  # migrate_release <release-dir, e.g. $PP_RELEASES/$version>
  ( cd "$1/backend" && ./venv/bin/alembic -c alembic.ini upgrade head )
}
