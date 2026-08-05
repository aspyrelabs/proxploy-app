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
