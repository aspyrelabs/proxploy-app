#!/usr/bin/env bash
# The PVE half cannot run against real Proxmox on this machine. It CAN be
# held to the exact arguments it would send, which is what actually goes
# wrong: a bad storage pick, a missing bridge, a privileged container.
set -euo pipefail
cd "$(dirname "$0")/../.."

tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
export FAKE_PCT_LOG="$tmp/pct.log"
# The fake lives at packaging/tests/fake-pct (not "pct"), so `command -v pct`
# would not find it just by adding packaging/tests to PATH. Symlink it under
# its real name in a PATH-only tmp dir instead.
ln -s "$PWD/packaging/tests/fake-pct" "$tmp/pct"
# A non-dry run reads the template catalogue; --dry-run alone never does.
ln -s "$PWD/packaging/tests/fake-pveam" "$tmp/pveam"
export PATH="$tmp:$PATH"
: > "$FAKE_PCT_LOG"

# --dry-run stops before running the in-container half, which needs a real CT.
./install.sh --pve-only --dry-run --ctid 150 --storage local-lvm --bridge vmbr0 \
             --channel "file://$PWD/packaging/tests/fixture-channel" --version 1.0.0

grep -q '^create 150' "$FAKE_PCT_LOG"      || { echo "FAIL: no create for 150"; exit 1; }
grep -q 'unprivileged 1' "$FAKE_PCT_LOG"   || { echo "FAIL: CT is not unprivileged"; exit 1; }
grep -q 'storage local-lvm' "$FAKE_PCT_LOG" || { echo "FAIL: storage not honoured"; exit 1; }
grep -q 'net0 .*bridge=vmbr0' "$FAKE_PCT_LOG" || { echo "FAIL: bridge not honoured"; exit 1; }
grep -q 'onboot 1' "$FAKE_PCT_LOG"         || { echo "FAIL: CT will not survive a reboot"; exit 1; }
echo "OK: pve half sends the expected create"

# --- the push, including the piped case ------------------------------------
# --pve-only (no --dry-run) runs create/start/push and stops before the
# in-container half. The bundled installer arrives down a pipe, so on a real
# Proxmox node there is no $SCRIPT_DIR/install.sh to push into the CT: the
# half has to re-fetch itself from the install URL. file:// keeps that off the
# network; fetch_to treats it as a copy.
: > "$FAKE_PCT_LOG"
./install.sh --pve-only --ctid 151 --storage local-lvm --bridge vmbr0 \
             --channel "file://$PWD/packaging/tests/fixture-channel" --version 1.0.0
grep -q '^push 151 .*install.sh /root/install.sh' "$FAKE_PCT_LOG" \
  || { echo "FAIL: the installer was never pushed into the CT"; cat "$FAKE_PCT_LOG"; exit 1; }
echo "OK: pve half pushes the installer it ran from"

bash packaging/bundle_install.sh "$tmp/published-install.sh"
: > "$FAKE_PCT_LOG"
piped=$( cd "$tmp" && INSTALLER_URL="file://$tmp/published-install.sh" \
    bash -s -- --pve-only --ctid 152 --storage local-lvm --bridge vmbr0 \
               --channel "file://$OLDPWD/packaging/tests/fixture-channel" \
               --version 1.0.0 < "$tmp/published-install.sh" 2>&1 )
case "$piped" in
  *"no local installer to push"*) ;;
  *) echo "FAIL: the piped run did not re-fetch the installer:"; echo "$piped"; exit 1 ;;
esac
# The pushed path is a mktemp name, so only the destination is assertable here.
grep -q '^push 152 .* /root/install.sh --perms 0755' "$FAKE_PCT_LOG" \
  || { echo "FAIL: a piped installer pushed nothing into the CT"; cat "$FAKE_PCT_LOG"; exit 1; }
echo "OK: a piped installer re-fetches itself to push into the CT"
echo "PASS: pve half harness"
