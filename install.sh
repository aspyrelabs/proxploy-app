#!/usr/bin/env bash
# Proxploy installer (Phase 9a).
#
# The one-liner is `curl -fsSL <install URL> | bash`, where the host comes from
# PROXPLOY_ENV (the WEB_BASE_URL case below). On a
# Proxmox node that means: create a CT and re-run this script inside it
# (the PVE-host half, below). Everywhere else: a plain Debian box, or
# inside the CT that half creates: this script IS the install: OS deps,
# system user, the versioned layout, fetch+verify+unpack a release, the env
# file, migrations, the updater, the systemd unit.
#
# Idempotent by design: a second run with the same flags must not duplicate
# the system user, must not rewrite /etc/proxploy/proxploy.env, must not
# touch the database, and must leave exactly one enabled unit.
set -euo pipefail

# ${BASH_SOURCE[0]:-} , not ${BASH_SOURCE[0]}: piped to bash there is no source
# file at all, and under `set -u` the bare form aborts on line 16 with
# "BASH_SOURCE[0]: unbound variable" before anything can explain itself.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || echo "$PWD")"

# PROXPLOY_ENV picks the domain pair, exactly the way config.py's
# API_BASE_URL_BY_ENV picks the licence server: dev is the .dev pair, prod is
# the .com pair. Never hardcode either one anywhere else in this script, and
# never search-and-replace between them: adding a THIRD environment should be
# one more line here and nothing else.
#
#   dev   web.proxploy.dev   api.proxploy.dev
#   prod  proxploy.com       api.proxploy.com
#
# Resolved before the bundle markers below deliberately: the guard inside them
# prints INSTALLER_URL, and under `set -u` an unbound variable would abort
# with that instead of the advice. The strict dev|prod check is further down,
# after common.sh gives us `die`, so an unrecognised value falls back to the
# dev host for that one message and is refused a few lines later.
: "${PROXPLOY_ENV:=prod}"
case "$PROXPLOY_ENV" in
  prod) WEB_BASE_URL="https://proxploy.com" ;;
  *)    WEB_BASE_URL="https://web.proxploy.dev" ;;
esac
# Where the published single-file installer lives. The PVE half re-fetches
# itself from here when it has no file of its own to push.
INSTALLER_URL="${INSTALLER_URL:-$WEB_BASE_URL/install.sh}"

# >>> BUNDLE:common.sh >>>
# packaging/bundle_install.sh replaces everything between these two markers
# with the contents of packaging/lib/common.sh, and THAT single file is what
# gets published at the install URL. Piped to bash there is no directory to
# source from, so the published installer cannot have this dependency at all.
# The two-file form below is what runs from a checkout, and is what keeps
# common.sh a real file for packaging/proxploy-update and build_release.sh.
# shellcheck source=packaging/lib/common.sh
if [ ! -r "$SCRIPT_DIR/packaging/lib/common.sh" ]; then
  printf 'error: %s\n' \
    "install.sh could not find packaging/lib/common.sh beside it." \
    "" \
    "This copy is the unbundled one from a source checkout, which needs that" \
    "file. The published installer has it spliced in and needs nothing:" \
    "" \
    "  curl -fsSL $INSTALLER_URL | bash" >&2
  exit 1
fi
. "$SCRIPT_DIR/packaging/lib/common.sh"
# <<< BUNDLE:common.sh <<<

SHAPE=""
CHANNEL=""
VERSION=""
PUBKEY=""
CTID=""
STORAGE=""
TEMPLATE_STORAGE=""
BRIDGE=""
FQDN=""
PVE_ONLY=0
DRY_RUN=0
DRY_PARSE=0

# Default channel for the bare one-liner (`curl -fsSL $INSTALLER_URL | bash`,
# no flags). --channel overrides this for a staging build or the test
# harnesses' file:// fixtures.
#
# The same site that serves this script, which is why it derives from
# WEB_BASE_URL rather than naming a host of its own. Not GitHub Releases: the
# source repo is private, and private release assets need an authenticated
# fetch that an installer has no credential for. Matches config.py's
# _release_channel_url, so the installer and the in-app updater read the same
# three files from the same place.
DEFAULT_CHANNEL="$WEB_BASE_URL/releases/latest"

# Defaulted above (it has to be, the install URL derives from it). Validated
# here rather than there because `die` arrives with common.sh.
#
# The default is prod. It was dev while the licence server at
# api.proxploy.com was not yet answering, and the cost of leaving it that way
# one release too long was real: the installer published at proxploy.com
# pulled its own payload from web.proxploy.dev and licensed against
# api.proxploy.dev, so a production install ran on dev infrastructure without
# saying so. api.proxploy.com answers now. `export PROXPLOY_ENV=dev` is how to
# install against the dev pair.
case "$PROXPLOY_ENV" in
  dev|prod) ;;
  *) die "PROXPLOY_ENV must be dev or prod, got: $PROXPLOY_ENV" ;;
esac

# The release public key, compiled in rather than fetched. This is what
# makes the no-argument one-liner possible: there is nothing unpacked yet
# for this script to read a key out of, so the key has to arrive WITH the
# script. That is sound because the script itself arrives over TLS from a
# host the user already chose to trust: the same trust the curl already
# places. Replacing this block is the first step of a key rotation.
RELEASE_PUBKEY_PEM='-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAJqEnPBMju159D0/dRLAVrfwIJZzdgHjhahCt8abJqx0=
-----END PUBLIC KEY-----'

usage() {
  cat >&2 <<'EOF'
Usage: install.sh [--shape systemd|lxc] [--channel <url>] [--version <v>]
                   [--pubkey <pem>] [--dry-parse]
       install.sh [--pve-only] [--dry-run] [--channel <url>] [--version <v>]
                   [--ctid <n>] [--storage <name>] [--template-storage <name>]
                   [--bridge <name>]

  --shape    Install shape: systemd (plain host/VM) or lxc (Proxmox CT).
             Omit and it is worked out: on a Proxmox node (pct + /etc/pve
             present) this creates a CT and runs the installer inside it;
             anywhere else it installs here, as lxc inside a container and
             systemd otherwise. Pass it only to override that.
  --channel  Base URL of a release channel holding manifest.json,
             manifest.json.sig and the tarball (file:// or https://).
             Default: the latest GitHub release of aspyrelabs/proxploy-app
  --version  The version to install; must match the channel's manifest.
             Default: whatever version the fetched manifest.json reports.
  --pubkey   Path to the release public key (PEM) to verify the manifest
             signature against. Default: the release key compiled into
             this script. Pass this to verify against a different key.
  --dry-parse Exit 0 immediately after argument validation and defaulting
             prints the resolved shape/channel/version/pubkey and never
             fetches, installs, or requires root. For testing the argument
             handling itself.
  --ctid     CT id to create. Default: first free id >= 150.
  --storage  PVE storage for the CT's rootfs. Default: first storage that
             supports rootdir content.
  --template-storage
             PVE storage the Debian CT template is read from, and downloaded
             to when it is not there yet. Default: first storage that supports
             vztmpl content. Rarely the same pool as --storage: on a stock
             Proxmox install rootdir is local-lvm and vztmpl is local.
  --bridge   PVE network bridge for the CT. Default: vmbr0.
  --hostname Public DNS name Caddy should request a Let's Encrypt cert for.
             Omit for a LAN install with no public hostname: Caddy still
             serves TLS, via its own self-signed CA (`tls internal`), on
             https://<this host's primary IP>/.
  --pve-only Force the PVE-host path (skip auto-detection) and stop after
             creating and staging the CT, never recurse into the
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
    --template-storage) TEMPLATE_STORAGE="$2"; shift 2 ;;
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
# PVE_CONF_DIR is the same kind of seam INSTALLER_URL already is in this file:
# a default that is right everywhere real and overridable so the harness can
# reach the `pct exec` handoff, which --pve-only returns before ever touching.
is_pve_host() {
  command -v pct >/dev/null 2>&1 && [ -d "${PVE_CONF_DIR:-/etc/pve}" ]
}

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

# Two pools, not one. A CT rootfs needs `rootdir` content and a CT template
# needs `vztmpl`, and on a stock Proxmox install no single pool carries both:
# local-lvm is rootdir+images, local is vztmpl+iso+backup. Picking the rootdir
# pool and then reading the template catalogue out of it is what broke the
# advertised one-liner on a real node. services/appstore.py's _STORAGE_CLASSES
# keeps the same two content types apart on the API side; this is that split.
resolve_storage() {
  [ -n "$STORAGE" ] && return 0
  STORAGE=$(pvesm status -content rootdir | awk 'NR>1{print $1; exit}')
  [ -n "$STORAGE" ] || die "could not find a storage with rootdir content; pass --storage"
}

resolve_template_storage() {
  [ -n "$TEMPLATE_STORAGE" ] && return 0
  TEMPLATE_STORAGE=$(pvesm status -content vztmpl | awk 'NR>1{print $1; exit}')
  [ -n "$TEMPLATE_STORAGE" ] \
    || die "could not find a storage with vztmpl content; pass --template-storage"
}

resolve_bridge() { [ -n "$BRIDGE" ] || BRIDGE="vmbr0"; }

# resolve_version: no-op when --version was already given (every existing
# harness passes it explicitly and never reaches the fetch_to call below).
# Otherwise fetch the channel's manifest.json and read its version out, 
# the same manifest_field extraction proxploy-update and verify_release()
# use, so there is exactly one manifest field parser in this codebase.
# --dry-parse never touches the network: this is called before root, curl
# availability, or a real channel can be assumed, so it substitutes a
# placeholder instead of fetching.
# ponytail: an installer with no --version fetches manifest.json twice
# (once here, once in step 4 below): a second small GET, not worth
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
    # ponytail: dry-run never calls pveam: nothing is downloaded and
    # nothing reads a real template catalog, so the harness needs no pveam
    # stub. A real (non-dry) run always takes the branch below instead.
    TEMPLATE="$storage:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst"
    return 0
  fi
  # `|| TEMPLATE=""`, and no 2>/dev/null: under `set -euo pipefail` a failing
  # pveam here aborted the whole installer with its reason discarded, which
  # read as "creating CT ..." followed by a silent exit and nothing created.
  # Let it say why, and fall through to the download branch either way.
  TEMPLATE=$(pveam list "$storage" | awk '/debian-12-standard/{print $1; exit}') || TEMPLATE=""
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
# follow. ponytail: fixed 60s ceiling: generous for DHCP+boot on a fresh CT;
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
  resolve_template_storage
  resolve_bridge
  log "PVE host: creating CT $CTID (storage=$STORAGE" \
      "template-storage=$TEMPLATE_STORAGE bridge=$BRIDGE)"
  resolve_template "$TEMPLATE_STORAGE"

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

  # Always the published installer, never a local file. This used to push
  # $SCRIPT_DIR/install.sh when one was readable, and neither half of that was
  # safe. Piped, BASH_SOURCE[0] is unset and $0 is "bash", so SCRIPT_DIR
  # degrades to the operator's cwd: on a node with an old checkout's
  # install.sh sitting in /root, `curl ... | bash` shipped THAT into the CT,
  # which then died on `/root/packaging/lib/common.sh: No such file or
  # directory`. From a checkout it was worse and unconditional: the unbundled
  # install.sh needs common.sh beside it, and a fresh CT has no checkout to
  # find it in. Only the bundled file at INSTALLER_URL stands alone in a CT,
  # so fetch that every time. Override INSTALLER_URL to stage a build.
  # Shell access to the CT. `pct create` sets no password and no key, so root
  # is locked: the Proxmox console prompts for a login that cannot be
  # satisfied, and nothing anywhere says so. Rather than invent a password and
  # print a secret into a terminal, hand the CT the keys that already open this
  # node, so whoever administers the host administers the container. If root
  # here has no authorized_keys, nothing is copied and `pct enter` (named in
  # the closing lines below) stays the way in.
  if [ -s /root/.ssh/authorized_keys ]; then
    log "copying this node's root authorized_keys into CT $CTID"
    pct exec "$CTID" -- mkdir -p -m 0700 /root/.ssh
    pct push "$CTID" /root/.ssh/authorized_keys /root/.ssh/authorized_keys \
      --perms 0600
  else
    log "this node's root has no authorized_keys, so CT $CTID gets none;" \
        "pct enter $CTID is the way in"
  fi

  log "fetching the installer to push into CT $CTID from $INSTALLER_URL"
  local installer
  installer=$(mktemp)
  fetch_to "$INSTALLER_URL" "$installer"
  pct push "$CTID" "$installer" /root/install.sh --perms 0755

  if [ "$PVE_ONLY" -eq 1 ]; then
    log "CT $CTID is up with the installer staged at /root/install.sh;" \
        "--pve-only set, not running it"
    return 0
  fi

  log "running the in-container installer inside CT $CTID"
  # Built as an array, because two of these are conditional.
  #
  # --pubkey: PUBKEY is still empty here. The block that fills it from
  # RELEASE_PUBKEY_PEM lives below the PVE branch, which exits before ever
  # reaching it, so this used to send a literal `--pubkey ""`. It survived
  # only because the in-container half re-derives an empty PUBKEY from its own
  # bundled key: one dropped empty argument anywhere along pct exec and the
  # parser reads `--pubkey` with no $2 and dies on "unbound variable" under
  # `set -u`. And a PATH to a temp file on the HOST would be meaningless
  # inside the CT anyway. Send the flag only when there is something to send.
  #
  # --hostname: accepted on the PVE path and then silently dropped, so
  # `--hostname proxploy.example.com` created the CT and left Caddy on the
  # self-signed LAN fallback with no ACME cert and no word about why. Caddy is
  # configured by the in-container half, so the name has to reach it.
  local args=(--shape lxc --channel "$CHANNEL" --version "$VERSION")
  [ -z "$PUBKEY" ] || args+=(--pubkey "$PUBKEY")
  [ -z "$FQDN" ] || args+=(--hostname "$FQDN")
  # PROXPLOY_SELF_CTID lets the in-container half's env file record which CT
  # Proxploy runs in, so main.py can persist self.ctid at boot (Task 4) and
  # services/selfguard.py can recognise Proxploy's own container.
  pct exec "$CTID" -- env "PROXPLOY_SELF_CTID=$CTID" bash /root/install.sh \
    "${args[@]}"

  local ip
  ip=$(pct exec "$CTID" -- hostname -I 2>/dev/null | awk '{print $1}')
  log "Proxploy is installed in CT $CTID."
  [ -z "$ip" ] || log "Browse to https://$ip/ and create the first account:" \
      "you pick the email and password there, nothing is preset."
  # Said out loud because the alternative is a console login prompt with no
  # answer. root in the CT has no password by design; this is the way in.
  log "For a shell in the container: pct enter $CTID (root has no password)."
  log "To set one: pct exec $CTID -- bash -c 'echo root:PASS | chpasswd'"
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

# Not a Proxmox host, so this box IS the install target. Which of the two
# shapes it is, is a thing to look up rather than a thing to ask: the advertised
# one-liner passes no flags, and someone who made their own CT and ran it
# inside would otherwise be stopped by a question the URL never mentions.
#
# The two labels differ only as a record. Nothing in this script branches on
# them past writing PROXPLOY_INSTALL_SHAPE, and services/updater.py puts both
# in CAN_SELF_APPLY; the distinction that matters there is `docker`, which
# this script never installs. So a wrong guess costs a wrong word in the env
# file, not a broken install, which is why guessing beats refusing.
detect_shape() {
  local v=""
  # systemd-detect-virt is systemd's own answer and this installer requires
  # systemd anyway. --container, not bare: a VM is not what is being asked.
  if command -v systemd-detect-virt >/dev/null 2>&1; then
    v=$(systemd-detect-virt --container 2>/dev/null) || v=""
  fi
  # Present in an LXC container even when systemd-detect-virt is not installed
  # yet (step 1 has not run; a minimal template may lack it).
  if [ -z "$v" ] || [ "$v" = "none" ]; then
    [ -r /run/systemd/container ] && v=$(cat /run/systemd/container 2>/dev/null)
  fi
  case "$v" in
    lxc|lxc-libvirt|systemd-nspawn) printf 'lxc' ;;
    *) printf 'systemd' ;;
  esac
}

if [ -z "$SHAPE" ]; then
  SHAPE=$(detect_shape)
  log "no --shape given, detected $SHAPE"
fi
case "$SHAPE" in
  systemd|lxc) ;;
  *) die "--shape must be systemd or lxc, got: $SHAPE" ;;
esac
# --- 0. platform ------------------------------------------------------------
# Refused UP FRONT, not discovered halfway. There was no check of either kind:
# the script installed whatever `python3` the distro shipped and only found out
# when pip refused the wheel, several minutes and one system user in, with an
# error about requires-python that names no fix. An Ubuntu 22.04 box (Python
# 3.10) is the case that made this worth writing; it is still widely deployed.
#
# The PYTHON check is the authoritative one, because it is the actual
# requirement (backend/pyproject.toml: requires-python = ">=3.11"). The OS
# check exists to say so earlier and in the operator's own vocabulary.
#
# Version FLOORS rather than a list of blessed releases: a hardcoded allowlist
# has to be edited every time Debian or Ubuntu ships, and the edit is exactly
# what nobody remembers to do. Debian 12 and Ubuntu 24.04 are the oldest
# releases carrying Python 3.11 or newer, so anything at or above them passes
# and anything newer keeps passing without a code change.
#
#   Debian 12 bookworm  3.11    oldest supported
#   Debian 13 trixie    3.13
#   Ubuntu 24.04 LTS    3.12    oldest supported
#   Ubuntu 25.04        3.13
#   Ubuntu 26.04 LTS    3.14
#   Debian 11           3.9     refused
#   Ubuntu 22.04 LTS    3.10    refused
PY_MIN_MAJOR=3
PY_MIN_MINOR=11

check_platform() {
  [ -r /etc/os-release ] || die "cannot read /etc/os-release, so this system\
 cannot be identified. Proxploy installs on Debian 12+ or Ubuntu 24.04+."
  # Sourced in a SUBSHELL, never into this scope. /etc/os-release defines
  # VERSION ("12 (bookworm)" on Debian 12), and this script already has a
  # VERSION of its own: the Proxploy release being installed, which names the
  # directory under /opt/proxploy/releases and the `current` symlink. Sourcing
  # it directly overwrote that, so the installer announced "Proxploy 12
  # (bookworm) installed", unpacked into a directory called `12 (bookworm)`
  # and pointed `current` at it, orphaning the release it had just verified.
  # Caught on a real Debian 12 box; nothing in the harness would have seen it.
  local os_line id ver like major
  # shellcheck disable=SC1091  # read at runtime on the target, not in this repo
  os_line=$(. /etc/os-release 2>/dev/null \
            && printf '%s\t%s\t%s' "${ID:-unknown}" "${VERSION_ID:-0}" "${ID_LIKE:-}")
  IFS="$(printf '\t')" read -r id ver like <<EOS
$os_line
EOS
  major="${ver%%.*}"

  case "$id" in
    debian)
      [ "$major" -ge 12 ] 2>/dev/null || die \
        "Debian $ver is too old: Proxploy needs Python 3.11 or newer and this\
 release ships an older one. Debian 12 (bookworm) or newer." ;;
    ubuntu)
      # Compared as a number so 24.04 < 25.04 < 26.04 sorts correctly and a
      # string compare cannot get 9.10 vs 24.04 wrong.
      awk -v v="$ver" 'BEGIN { exit !(v + 0 >= 24.04) }' || die \
        "Ubuntu $ver is too old: Proxploy needs Python 3.11 or newer and this\
 release ships an older one. Ubuntu 24.04 LTS or newer." ;;
    *)
      # Not refused: this installer only needs apt and systemd, and a Debian
      # derivative that has both may well be fine. The Python check below is
      # the real gate, so say what is unverified and carry on rather than
      # blocking someone whose system works.
      case "$like" in
        *debian*|*ubuntu*) log "note: $id $ver is not a tested platform;\
 continuing because it is Debian-based" ;;
        *) die "$id is not supported: Proxploy installs on Debian 12+ or\
 Ubuntu 24.04+, which is what its apt and systemd steps assume." ;;
      esac ;;
  esac

  # No python3 yet is NOT a failure: step 1 below apt-installs it, and the
  # platforms the case above accepted all ship 3.11 or newer. Refusing here
  # turned a minimal Debian 12, which is what a fresh container or a stripped
  # LXC template is, away from an installer that was about to install the very
  # thing it complained was missing. Only an already-present python3 that is
  # too old is worth refusing up front, which is what the probe below does.
  command -v python3 >/dev/null 2>&1 || return 0
  # Asked of the interpreter rather than parsed out of --version: the string
  # format is not a promise and this is the number that actually decides.
  if ! python3 - "$PY_MIN_MAJOR" "$PY_MIN_MINOR" <<'EOF'
import sys
sys.exit(0 if sys.version_info[:2] >= (int(sys.argv[1]), int(sys.argv[2])) else 1)
EOF
  then
    # Asked in its own statement rather than inline in the die: a $( ) holding
    # single-quoted Python that itself holds double quotes, inside a
    # double-quoted string, is valid bash that shellcheck cannot parse, and it
    # took the whole file's static checking down with it.
    have=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
    die "python3 $have is too old: Proxploy needs 3.11 or newer." \
        "Debian 12+ or Ubuntu 24.04+ ships one."
  fi
}

resolve_version
if [ -z "$PUBKEY" ]; then
  # No bundled default existed before this: RELEASE_PUBKEY_PEM (near the
  # top of this file) is what makes the no-argument one-liner possible.
  PUBKEY=$(mktemp)
  printf '%s\n' "$RELEASE_PUBKEY_PEM" > "$PUBKEY"
fi

if [ "$DRY_PARSE" -eq 1 ]; then
  log "dry parse ok: shape=$SHAPE env=$PROXPLOY_ENV installer=$INSTALLER_URL" \
      "channel=$CHANNEL version=$VERSION pubkey=$PUBKEY"
  exit 0
fi

need_root
check_platform

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

# Everything below installs out of the release just unpacked, not out of
# $SCRIPT_DIR: a piped installer has no directory, and these four files are
# covered by the manifest signature here in a way a working-tree copy never
# was. build_release.sh stages packaging/ into the tarball for this.
PP_PKG="$PP_RELEASES/$VERSION/packaging"
[ -d "$PP_PKG" ] || die "release $VERSION has no packaging/ directory;\
 it predates the installer reading its own support files out of the release"

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
# Which peers are trusted to set X-Forwarded-For. The default, 127.0.0.1, is
# already where this installer puts Caddy. Uncomment only if yours is elsewhere.
# FORWARDED_ALLOW_IPS=127.0.0.1
PROXPLOY_ENV=$PROXPLOY_ENV
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
  # config.py's Settings has no env_file: it only reads PROXPLOY_* from the
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
  log "no existing database, the app will migrate and generate its master key on first boot"
fi

# --- 7. install the updater and its shared library --------------------------
log "installing the updater"
install -m 0755 "$PP_PKG/proxploy-update" "$PP_BIN/proxploy-update"
install -m 0644 "$PP_PKG/lib/common.sh" "$PP_LIB/common.sh"

# --- 7b. the update-request wrapper and its path unit ------------------------
# proxploy-update-run is root owned and NOT writable by the proxploy user:
# the app can only ask for a version by writing the request file, and this
# is the only thing that ever reads it. Skipped on a re-run once installed,
# same as the env file in step 5, so an operator's own edits to the path
# unit survive an install run from a newer release.
if [ -f "$PP_BIN/proxploy-update-run" ]; then
  log "the update-request wrapper is already installed, leaving it alone"
else
  log "installing the update-request wrapper and its path unit"
  install -m 0755 "$PP_PKG/proxploy-update-run" "$PP_BIN/proxploy-update-run"
  install -m 0644 "$PP_PKG/proxploy-update.path" \
    /etc/systemd/system/proxploy-update.path
  install -m 0644 "$PP_PKG/proxploy-update.service" \
    /etc/systemd/system/proxploy-update.service
  systemctl daemon-reload
  systemctl enable --now proxploy-update.path
fi

# --- 8. point current at this release (atomic-ish symlink swap) -------------
log "switching current -> releases/$VERSION"
ln -sfn "$PP_RELEASES/$VERSION" "$PP_CURRENT.tmp"
mv -T "$PP_CURRENT.tmp" "$PP_CURRENT"

# --- 9. systemd unit ----------------------------------------------------------
log "installing the systemd unit"
install -m 0644 "$PP_PKG/proxploy.service" \
  /etc/systemd/system/proxploy.service
systemctl daemon-reload
# enable is idempotent; --now only starts a unit that is not already
# running, so a second run never restarts (and never disturbs) a live service.
systemctl enable --now proxploy.service

# `systemctl enable --now` returns as soon as the process is spawned. A unit
# that starts, throws during startup and gets picked back up by
# Restart=on-failure therefore exits 0 here, which is how this installer came
# to print "Proxploy 1.0.0 installed. Browse to https://<this-host>/" over a
# service that had never served a request, leaving the 502 for the operator to
# discover. A crashlooping unit alternates activating and failed and is never
# `active`, so waiting for `active` is what separates the two.
wait_for_service() {  # wait_for_service <unit>
  local unit="$1" tries=0
  until [ "$(systemctl is-active "$unit" 2>/dev/null)" = "active" ]; do
    tries=$((tries + 1))
    if [ "$tries" -ge 30 ]; then
      log "$unit never came up. Its last 30 log lines:"
      journalctl -u "$unit" -n 30 --no-pager >&2 || true
      die "$unit is $(systemctl is-active "$unit" 2>/dev/null) after 60s, so\
 this install is not usable. The log above says why."
    fi
    sleep 2
  done
}
wait_for_service proxploy.service

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
    # --retry: these two are the only third-party fetches in the whole install,
    # and a blip on dl.cloudsmith.io aborts it under `set -e` with curl's exit
    # 35 after everything else has already succeeded. Seen in CI 2026-08-25,
    # passing and failing 28 minutes apart with no change in between. A home
    # server on a flaky link hits the same thing, and retrying a GET of a
    # public key is safe.
    curl -1sLf --retry 5 --retry-delay 2 --retry-all-errors \
      'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
      | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf --retry 5 --retry-delay 2 --retry-all-errors \
      'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
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
    # matching site) to anything that connects via 127.0.0.1 or localhost, 
    # including this box's own health checks and an admin who SSHes in and
    # browses locally. `tls internal` happily issues one cert covering every
    # address listed here.
    site_address="https://$ip, https://127.0.0.1"
    tls_directive="internal"
  fi

  log "writing /etc/caddy/Caddyfile for $site_address"
  sed -e "s|{\$PROXPLOY_SITE_ADDRESS}|$site_address|g" \
      -e "s|{\$PROXPLOY_TLS_DIRECTIVE}|$tls_directive|g" \
      "$PP_PKG/caddy/Caddyfile.tmpl" > /etc/caddy/Caddyfile

  # PROXPLOY_COOKIE_SECURE=true is already in the env block written in step 5
  # above; verified there rather than written a second time here.

  # enable --now, THEN reload. `apt-get install caddy` above already enabled
  # and started the unit against the stock Debian Caddyfile, so `enable --now`
  # on its own is a no-op on a running service: it does not re-read config.
  # The file written a few lines up was therefore never loaded, Caddy kept
  # serving its default :80 site, nothing listened on 443, and the last line
  # this installer prints told the operator to browse to https://<host>/ and
  # get a refused connection. Seen on a clean Debian 12 CT: `caddy validate`
  # called the new file valid while the running process was still on :80.
  #
  # reload rather than restart: Caddy reloads config with no dropped
  # connections, and `|| systemctl restart caddy` covers a unit whose reload
  # is not wired up rather than leaving TLS down on a technicality.
  systemctl enable --now caddy
  systemctl reload caddy || systemctl restart caddy
}
configure_tls

# --- 11. prove it, then say so ----------------------------------------------
# Everything above can succeed and still leave nothing answering: Caddy running
# on its stock config, the app bound but refusing, a reverse_proxy pointed at a
# port nobody listens on. The line below tells the operator to open a URL, so
# open it first. Any HTTP status is a pass except a 5xx (Caddy reached nothing
# usable) and curl's 000 (nothing answered at all); a 404 still proves the
# whole chain from TLS to uvicorn is live.
verify_serving() {
  local code
  code=$(curl -sk -o /dev/null -m 10 -w '%{http_code}' "https://127.0.0.1/" \
         2>/dev/null) || code="000"
  case "$code" in
    000) log "nothing answered on https://127.0.0.1/. caddy is\
 $(systemctl is-active caddy 2>/dev/null), proxploy is\
 $(systemctl is-active proxploy 2>/dev/null)."
         die "the install finished but nothing is serving." ;;
    5*)  log "https://127.0.0.1/ answered $code. Caddy is up but got nothing\
 usable from the app on 127.0.0.1:8000. Its last 30 log lines:"
         journalctl -u proxploy -n 30 --no-pager >&2 || true
         die "the install finished but the app is not serving." ;;
  esac
  log "https://127.0.0.1/ answered $code"
}
verify_serving

log "Proxploy $VERSION installed."
log "Browse to https://<this-host>/ to create the first account."
