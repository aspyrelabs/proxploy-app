#!/usr/bin/env bash
# Proxploy installer (Phase 9a).
#
# The one-liner is `curl -fsSL https://proxploy.com/install.sh | bash`. On a
# Proxmox node that means: create a CT and re-run this script inside it
# (Task 7 — not yet implemented here). Everywhere else — a plain Debian box,
# or inside the CT Task 7 creates — this script IS the install: OS deps,
# system user, the versioned layout, fetch+verify+unpack a release, the env
# file, migrations, the updater, the systemd unit.
#
# Idempotent by design: a second run with the same flags must not duplicate
# the system user, must not rewrite /etc/proxploy/proxploy.env, must not
# touch the database, and must leave exactly one enabled unit.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=packaging/lib/common.sh
. "$SCRIPT_DIR/packaging/lib/common.sh"

SHAPE=""
CHANNEL=""
VERSION=""
PUBKEY=""

usage() {
  cat >&2 <<'EOF'
Usage: install.sh --shape systemd|lxc --channel <url> --version <v> --pubkey <pem>

  --shape    Install shape: systemd (plain host/VM) or lxc (Proxmox CT).
  --channel  Base URL of a release channel holding manifest.json,
             manifest.json.sig and the tarball (file:// or https://).
  --version  The version to install; must match the channel's manifest.
  --pubkey   Path to the release public key (PEM) to verify the manifest
             signature against. There is no bundled default: nothing is
             unpacked yet for this script to read a key out of.
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --shape) SHAPE="$2"; shift 2 ;;
    --channel) CHANNEL="$2"; shift 2 ;;
    --version) VERSION="$2"; shift 2 ;;
    --pubkey) PUBKEY="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

if [ -z "$SHAPE" ]; then
  # Task 7 adds PVE-host detection here: when no --shape is given and this
  # is a Proxmox node (`command -v pct` + `/etc/pve`), create a CT and
  # re-invoke this script inside it with --shape lxc. Until that lands,
  # --shape is required.
  usage
  die "--shape is required (systemd|lxc) until the PVE-host half (Task 7) lands"
fi
case "$SHAPE" in
  systemd|lxc) ;;
  *) die "--shape must be systemd or lxc, got: $SHAPE" ;;
esac
[ -n "$CHANNEL" ] || { usage; die "--channel is required"; }
[ -n "$VERSION" ] || { usage; die "--version is required"; }
[ -n "$PUBKEY" ]  || { usage; die "--pubkey is required"; }

need_root

# --- 1. OS dependencies -----------------------------------------------------
# Idempotent: apt/dpkg already skip installed packages. sqlite3 is required
# by proxploy-update's `sqlite3 ... .backup` step (Task 9), not by the app
# itself, but it must be present from day one so the first update can back up
# safely.
log "installing OS dependencies"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv curl openssl ca-certificates sqlite3

# --- 2. system user ----------------------------------------------------------
if ! id -u "$PP_USER" >/dev/null 2>&1; then
  log "creating system user $PP_USER"
  useradd --system --no-create-home --home-dir "$PP_DATA" \
          --shell /usr/sbin/nologin "$PP_USER"
else
  log "system user $PP_USER already exists"
fi

# --- 3. layout ---------------------------------------------------------------
log "creating layout under $PP_ROOT and $PP_DATA"
mkdir -p "$PP_RELEASES" "$PP_BIN" "$PP_LIB" "$PP_ETC" \
         "$PP_DATA/uploads" "$PP_DATA/pre-update"
chown -R "$PP_USER:$PP_USER" "$PP_DATA"

# --- 4. fetch + verify + unpack the release ---------------------------------
if [ -d "$PP_RELEASES/$VERSION" ]; then
  log "release $VERSION is already unpacked, skipping fetch"
else
  work=$(mktemp -d)
  trap 'rm -rf "$work"' EXIT
  log "fetching $VERSION from $CHANNEL"
  fetch_to "$CHANNEL/manifest.json"     "$work/manifest.json"
  fetch_to "$CHANNEL/manifest.json.sig" "$work/manifest.json.sig"
  tarball=$(sed -n 's/.*"name": *"\([^"]*\)".*/\1/p' "$work/manifest.json" | head -1)
  [ -n "$tarball" ] || die "manifest.json has no artifact name"
  fetch_to "$CHANNEL/$tarball" "$work/$tarball"
  verify_release "$work" "$PUBKEY"

  log "installing $VERSION"
  install_release "$work/$tarball" "$VERSION"
  rm -rf "$work"
  trap - EXIT
fi

# --- 5. env file (written once; an update must never clobber operator settings) --
if [ -f "$PP_ENV" ]; then
  log "$PP_ENV already exists, leaving it alone"
else
  log "writing $PP_ENV"
  cat > "$PP_ENV" <<EOF
PROXPLOY_DB_URL=sqlite:////var/lib/proxploy/proxploy.db
PROXPLOY_DATA_DIR=/var/lib/proxploy
PROXPLOY_MASTER_KEY_FILE=/var/lib/proxploy/master.key
PROXPLOY_INSTALL_SHAPE=$SHAPE
PROXPLOY_COOKIE_SECURE=true
PROXPLOY_UPDATE_SCRIPT=/opt/proxploy/bin/proxploy-update
EOF
  chown root:"$PP_USER" "$PP_ENV"
  chmod 0640 "$PP_ENV"
fi

# --- 6. database migration --------------------------------------------------
# alembic upgrade head is idempotent — a no-op when already at head — so this
# runs every time, including on a re-run against an already-migrated DB.
log "running database migrations"
set -a
# shellcheck source=/dev/null
. "$PP_ENV"
set +a
"$PP_RELEASES/$VERSION/backend/venv/bin/alembic" \
  -c "$PP_RELEASES/$VERSION/backend/alembic.ini" upgrade head

# --- 7. install the updater and its shared library --------------------------
log "installing the updater"
install -m 0755 "$SCRIPT_DIR/packaging/proxploy-update" "$PP_BIN/proxploy-update"
install -m 0644 "$SCRIPT_DIR/packaging/lib/common.sh" "$PP_LIB/common.sh"

# --- 8. point current at this release (atomic-ish symlink swap) -------------
log "switching current -> releases/$VERSION"
ln -sfn "$PP_RELEASES/$VERSION" "$PP_CURRENT.tmp"
mv -T "$PP_CURRENT.tmp" "$PP_CURRENT"

# --- 9. systemd unit ----------------------------------------------------------
log "installing the systemd unit"
install -m 0644 "$SCRIPT_DIR/packaging/proxploy.service" \
  /etc/systemd/system/proxploy.service
systemctl daemon-reload
# enable is idempotent; --now only starts a unit that is not already
# running, so a second run never restarts (and never disturbs) a live service.
systemctl enable --now proxploy.service

# --- 10. TLS -------------------------------------------------------------------
configure_tls() {
  # Task 8 implements this for real: install Caddy, render
  # packaging/caddy/Caddyfile.tmpl to /etc/caddy/Caddyfile, `systemctl
  # enable --now caddy`. Deliberately a no-op stub here — the unit above
  # already binds the app to 127.0.0.1 only, so an install that stops before
  # Task 8 has no public front, not an insecure one.
  log "TLS is not configured yet (Task 8) — app is reachable on 127.0.0.1:8000 only"
}
configure_tls

# --- 11. done ------------------------------------------------------------------
log "Proxploy $VERSION installed."
log "Once Task 8 wires up Caddy, browse to https://<this-host>/ to create the first account."
