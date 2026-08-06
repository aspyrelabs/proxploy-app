#!/usr/bin/env bash
# Proxploy installer (Phase 9a).
#
# The one-liner is `curl -fsSL https://proxploy.com/install.sh | bash`. On a
# Proxmox node that means: create a CT and re-run this script inside it
# (the PVE-host half, below). Everywhere else — a plain Debian box, or
# inside the CT that half creates — this script IS the install: OS deps,
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
CTID=""
STORAGE=""
BRIDGE=""
FQDN=""
PVE_ONLY=0
DRY_RUN=0
DRY_PARSE=0

# Default channel for the bare one-liner (`curl -fsSL https://proxploy.com/
# install.sh | bash`, no flags). --channel overrides this for a private
# channel, a staging build, or the test harnesses' file:// fixtures.
DEFAULT_CHANNEL="https://proxploy.com/releases/latest"

# The release public key, compiled in rather than fetched. This is what
# makes the no-argument one-liner possible: there is nothing unpacked yet
# for this script to read a key out of, so the key has to arrive WITH the
# script. That is sound because the script itself arrives over TLS from a
# host the user already chose to trust — the same trust the curl already
# places. Replacing this block is step 1 of
# docs/runbooks/publishing-a-release.md.
RELEASE_PUBKEY_PEM='-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAGZ/rStVno38RgOMWbVnHIRHHSk0WGVwhb4hMJnUkj/k=
-----END PUBLIC KEY-----'

usage() {
  cat >&2 <<'EOF'
Usage: install.sh [--shape systemd|lxc] [--channel <url>] [--version <v>]
                   [--pubkey <pem>] [--dry-parse]
       install.sh [--pve-only] [--dry-run] [--channel <url>] [--version <v>]
                   [--ctid <n>] [--storage <name>] [--bridge <name>]

  --shape    Install shape: systemd (plain host/VM) or lxc (Proxmox CT).
             Omit on a Proxmox node (pct + /etc/pve present) to instead
             create a CT and run the installer inside it.
  --channel  Base URL of a release channel holding manifest.json,
             manifest.json.sig and the tarball (file:// or https://).
             Default: https://proxploy.com/releases/latest
  --version  The version to install; must match the channel's manifest.
             Default: whatever version the fetched manifest.json reports.
  --pubkey   Path to the release public key (PEM) to verify the manifest
             signature against. Default: the release key compiled into
             this script. Pass this to verify against a different key.
  --dry-parse Exit 0 immediately after argument validation and defaulting
             — prints the resolved shape/channel/version/pubkey and never
             fetches, installs, or requires root. For testing the argument
             handling itself.
  --ctid     CT id to create. Default: first free id >= 150.
  --storage  PVE storage for the CT's rootfs. Default: first storage that
             supports rootdir content.
  --bridge   PVE network bridge for the CT. Default: vmbr0.
  --hostname Public DNS name Caddy should request a Let's Encrypt cert for.
             Omit for a LAN install with no public hostname: Caddy still
             serves TLS, via its own self-signed CA (`tls internal`), on
             https://<this host's primary IP>/.
  --pve-only Force the PVE-host path (skip auto-detection) and stop after
             creating and staging the CT — never recurse into the
             in-container half.
  --dry-run  PVE-host path only: stop right after `pct create`, before
             starting, pushing into, or execing inside the CT.
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --shape) SHAPE="$2"; shift 2 ;;
    --channel) CHANNEL="$2"; shift 2 ;;
    --version) VERSION="$2"; shift 2 ;;
    --pubkey) PUBKEY="$2"; shift 2 ;;
    --ctid) CTID="$2"; shift 2 ;;
    --storage) STORAGE="$2"; shift 2 ;;
    --bridge) BRIDGE="$2"; shift 2 ;;
    --hostname) FQDN="$2"; shift 2 ;;
    --pve-only) PVE_ONLY=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    --dry-parse) DRY_PARSE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

# --- PVE-host detection (Task 7) --------------------------------------------
# --pve-only forces this path (used by the fake-pct harness, which has no
# /etc/pve to auto-detect from). Otherwise: no --shape given, and this looks
# like a Proxmox node.
is_pve_host() { command -v pct >/dev/null 2>&1 && [ -d /etc/pve ]; }

# resolve_ctid/resolve_storage/resolve_bridge: each is a no-op when the
# matching flag was already given, so the harness (which passes all three)
# never touches pvesh/pvesm/pct list.
resolve_ctid() {
  [ -n "$CTID" ] && return 0
  if command -v pvesh >/dev/null 2>&1; then
    CTID=$(pvesh get /cluster/nextid 2>/dev/null) || CTID=""
  fi
  if [ -z "$CTID" ]; then
    local used candidate=150
    used=$(pct list 2>/dev/null | awk 'NR>1{print $1}')
    while printf '%s\n' "$used" | grep -qx "$candidate"; do
      candidate=$((candidate + 1))
    done
    CTID="$candidate"
  fi
}

resolve_storage() {
  [ -n "$STORAGE" ] && return 0
  STORAGE=$(pvesm status -content rootdir 2>/dev/null | awk 'NR>1{print $1; exit}')
  [ -n "$STORAGE" ] || die "could not find a storage with rootdir content; pass --storage"
}

resolve_bridge() { [ -n "$BRIDGE" ] || BRIDGE="vmbr0"; }

# resolve_version: no-op when --version was already given (every existing
# harness passes it explicitly and never reaches the fetch_to call below).
# Otherwise fetch the channel's manifest.json and read its version out —
# the same manifest_field extraction proxploy-update and verify_release()
# use, so there is exactly one manifest field parser in this codebase.
# --dry-parse never touches the network: this is called before root, curl
# availability, or a real channel can be assumed, so it substitutes a
# placeholder instead of fetching.
# ponytail: an installer with no --version fetches manifest.json twice
# (once here, once in step 4 below) — a second small GET, not worth
# threading a shared work dir through both call sites for.
resolve_version() {
  [ -n "$VERSION" ] && return 0
  if [ "$DRY_PARSE" -eq 1 ]; then
    VERSION="(resolved from $CHANNEL/manifest.json at install time)"
    return 0
  fi
  local tmp
  tmp=$(mktemp -d)
  fetch_to "$CHANNEL/manifest.json" "$tmp/manifest.json"
  VERSION=$(manifest_field version "$tmp/manifest.json")
  rm -rf "$tmp"
  [ -n "$VERSION" ] || die "could not determine --version from $CHANNEL/manifest.json"
}

resolve_template() {  # resolve_template <storage> -> sets TEMPLATE
  local storage="$1"
  if [ "$DRY_RUN" -eq 1 ]; then
    # ponytail: dry-run never calls pveam — nothing is downloaded and
    # nothing reads a real template catalog, so the harness needs no pveam
    # stub. A real (non-dry) run always takes the branch below instead.
    TEMPLATE="$storage:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst"
    return 0
  fi
  TEMPLATE=$(pveam list "$storage" 2>/dev/null | awk '/debian-12-standard/{print $1; exit}')
  if [ -z "$TEMPLATE" ]; then
    log "downloading the Debian 12 CT template"
    pveam update
    local tmpl
    tmpl=$(pveam available --section system 2>/dev/null | awk '/debian-12-standard/{print $2; exit}')
    [ -n "$tmpl" ] || die "no debian-12-standard template found via pveam available"
    pveam download "$storage" "$tmpl"
    TEMPLATE="$storage:vztmpl/$tmpl"
  fi
}

# pve_wait_for_ready: pct exec only succeeds once the CT's init is up, so
# polling it is also a network-readiness proxy for the push/exec steps that
# follow. ponytail: fixed 60s ceiling — generous for DHCP+boot on a fresh CT;
# raise it if a slower storage backend needs more.
pve_wait_for_ready() {
  local ctid="$1" tries=0
  until pct exec "$ctid" -- true >/dev/null 2>&1; do
    tries=$((tries + 1))
    [ "$tries" -lt 30 ] || die "CT $ctid did not become ready within 60s"
    sleep 2
  done
}

pve_install() {
  resolve_ctid
  resolve_storage
  resolve_bridge
  log "PVE host: creating CT $CTID (storage=$STORAGE bridge=$BRIDGE)"
  resolve_template "$STORAGE"

  pct create "$CTID" "$TEMPLATE" \
    --hostname proxploy \
    --cores 2 \
    --memory 2048 \
    --storage "$STORAGE" \
    --rootfs "$STORAGE":8 \
    --unprivileged 1 \
    --features nesting=1 \
    --onboot 1 \
    --net0 name=eth0,bridge="$BRIDGE",ip=dhcp

  if [ "$DRY_RUN" -eq 1 ]; then
    log "dry run: CT $CTID created, stopping before start/push/exec"
    return 0
  fi

  log "starting CT $CTID"
  pct start "$CTID"
  pve_wait_for_ready "$CTID"

  log "pushing the installer into CT $CTID"
  pct push "$CTID" "$SCRIPT_DIR/install.sh" /root/install.sh --perms 0755

  if [ "$PVE_ONLY" -eq 1 ]; then
    log "CT $CTID is up with the installer staged at /root/install.sh;" \
        "--pve-only set, not running it"
    return 0
  fi

  log "running the in-container installer inside CT $CTID"
  # PROXPLOY_SELF_CTID lets the in-container half's env file record which CT
  # Proxploy runs in, so main.py can persist self.ctid at boot (Task 4) and
  # services/selfguard.py can recognise Proxploy's own container.
  pct exec "$CTID" -- env "PROXPLOY_SELF_CTID=$CTID" bash /root/install.sh \
    --shape lxc --channel "$CHANNEL" --version "$VERSION" --pubkey "$PUBKEY"

  local ip
  ip=$(pct exec "$CTID" -- hostname -I 2>/dev/null | awk '{print $1}')
  log "Proxploy is installed in CT $CTID."
  [ -z "$ip" ] || log "Browse to https://$ip/ to create the first account."
}

# --- argument defaults (Task 3, phase 9c) -----------------------------------
# The advertised one-liner takes no flags at all, so channel/version/pubkey
# all need usable defaults instead of the hard requirement this used to be.
[ -n "$CHANNEL" ] || CHANNEL="$DEFAULT_CHANNEL"

if [ "$PVE_ONLY" -eq 1 ] || { [ -z "$SHAPE" ] && is_pve_host; }; then
  resolve_version
  if [ "$DRY_PARSE" -eq 1 ]; then
    log "dry parse ok: shape=pve-host channel=$CHANNEL version=$VERSION"
    exit 0
  fi
  pve_install
  exit 0
fi

if [ -z "$SHAPE" ]; then
  usage
  die "--shape is required (systemd|lxc) — this does not look like a Proxmox host, so it cannot be auto-detected"
fi
case "$SHAPE" in
  systemd|lxc) ;;
  *) die "--shape must be systemd or lxc, got: $SHAPE" ;;
esac
resolve_version
if [ -z "$PUBKEY" ]; then
  # No bundled default existed before this: RELEASE_PUBKEY_PEM (near the
  # top of this file) is what makes the no-argument one-liner possible.
  PUBKEY=$(mktemp)
  printf '%s\n' "$RELEASE_PUBKEY_PEM" > "$PUBKEY"
fi

if [ "$DRY_PARSE" -eq 1 ]; then
  log "dry parse ok: shape=$SHAPE channel=$CHANNEL version=$VERSION pubkey=$PUBKEY"
  exit 0
fi

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
  tarball=$(manifest_field name "$work/manifest.json")
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
# Only if a database already exists (a re-run, or an already-onboarded box
# being pointed at a new release). On a genuinely fresh install there is no
# database yet, and proxploy/main.py's lifespan generates the master key
# ONLY when no database exists (secretstore/__init__.py's ensure_key_file:
# db present + key absent is treated as key loss, not first boot, and it
# refuses to start rather than silently strand every encrypted credential).
# Migrating here first would create the database before the app ever runs,
# turning every fresh install into that refusal. So on first install this
# step is a no-op by design; the app runs its own migration (main.py calls
# run_migrations() right after generating the key) the first time it boots,
# started by `systemctl enable --now` a few steps down. alembic upgrade
# head is idempotent, so re-running it here on an existing DB is safe.
if [ -f "$PP_DATA/proxploy.db" ]; then
  log "running database migrations"
  # config.py's Settings has no env_file — it only reads PROXPLOY_* from the
  # process environment. The app itself gets those from systemd's
  # EnvironmentFile=, but this manual invocation needs them sourced by hand,
  # or alembic's env.py falls back to the default relative sqlite path and
  # fails with "unable to open database file".
  set -a
  # shellcheck source=/dev/null
  . "$PP_ENV"
  set +a
  migrate_release "$PP_RELEASES/$VERSION"
else
  log "no existing database — the app will migrate and generate its master key on first boot"
fi

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
# Caddy is arm's-length (doc 00:47): installed from its own official Debian
# repo and run as its own systemd service. We write config; we never vendor,
# link, or import its code.
configure_tls() {
  if command -v caddy >/dev/null 2>&1; then
    log "caddy already installed"
  else
    log "installing caddy from its official Debian repo"
    apt-get install -y -qq debian-keyring debian-archive-keyring gnupg apt-transport-https
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
      | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
      > /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -qq
    apt-get install -y -qq caddy
  fi

  local site_address tls_directive
  if [ -n "$FQDN" ]; then
    # A public hostname: empty tls directive means Caddy manages certs via
    # ACME (Let's Encrypt) on its own.
    site_address="$FQDN"
    tls_directive=""
  else
    # No public hostname: still get TLS, just via Caddy's own CA, so a LAN
    # install is never left serving plaintext. The browser warning is the
    # honest cost of a self-signed cert, not a reason to skip TLS.
    local ip
    ip=$(hostname -I 2>/dev/null | awk '{print $1}')
    [ -n "$ip" ] || die "could not determine this host's primary IP for the self-signed TLS fallback; pass --hostname"
    # 127.0.0.1 is listed alongside the primary IP, not instead of it: Caddy
    # matches a request to a site block by SNI/Host, so a bare IP-only site
    # address answers that IP but sends a TLS-level "internal error" (no
    # matching site) to anything that connects via 127.0.0.1 or localhost —
    # including this box's own health checks and an admin who SSHes in and
    # browses locally. `tls internal` happily issues one cert covering every
    # address listed here.
    site_address="https://$ip, https://127.0.0.1"
    tls_directive="internal"
  fi

  log "writing /etc/caddy/Caddyfile for $site_address"
  sed -e "s|{\$PROXPLOY_SITE_ADDRESS}|$site_address|g" \
      -e "s|{\$PROXPLOY_TLS_DIRECTIVE}|$tls_directive|g" \
      "$SCRIPT_DIR/packaging/caddy/Caddyfile.tmpl" > /etc/caddy/Caddyfile

  # PROXPLOY_COOKIE_SECURE=true is already in the env block written in step 5
  # above; verified there rather than written a second time here.

  systemctl enable --now caddy
}
configure_tls

# --- 11. done ------------------------------------------------------------------
log "Proxploy $VERSION installed."
log "Browse to https://<this-host>/ to create the first account."
