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
# A run with no --storage/--template-storage resolves both pools itself.
ln -s "$PWD/packaging/tests/fake-pvesm" "$tmp/pvesm"
export PATH="$tmp:$PATH"
: > "$FAKE_PCT_LOG"

# Every non-dry case pushes the published installer, so build one and serve it
# over file:// rather than reaching for web.proxploy.dev.
bash packaging/bundle_install.sh "$tmp/published-install.sh"
export INSTALLER_URL="file://$tmp/published-install.sh"

# --dry-run stops before running the in-container half, which needs a real CT.
./install.sh --pve-only --dry-run --ctid 150 --storage local-lvm --bridge vmbr0 \
             --channel "file://$PWD/packaging/tests/fixture-channel" --version 1.0.0

grep -q '^create 150' "$FAKE_PCT_LOG"      || { echo "FAIL: no create for 150"; exit 1; }
grep -q 'unprivileged 1' "$FAKE_PCT_LOG"   || { echo "FAIL: CT is not unprivileged"; exit 1; }
grep -q 'storage local-lvm' "$FAKE_PCT_LOG" || { echo "FAIL: storage not honoured"; exit 1; }
grep -q 'net0 .*bridge=vmbr0' "$FAKE_PCT_LOG" || { echo "FAIL: bridge not honoured"; exit 1; }
grep -q 'onboot 1' "$FAKE_PCT_LOG"         || { echo "FAIL: CT will not survive a reboot"; exit 1; }
echo "OK: pve half sends the expected create"

# --- the push: always the published bundle, never a local file -------------
# --pve-only (no --dry-run) runs create/start/push and stops before the
# in-container half. Whatever install.sh happens to sit beside the running
# script is NOT what may land in the CT: from a checkout it is the unbundled
# one, which needs packaging/lib/common.sh next to it and dies in a fresh CT
# with "/root/packaging/lib/common.sh: No such file or directory". Only the
# bundle at INSTALLER_URL stands alone, so that is what has to be pushed even
# when a readable install.sh is right there. file:// keeps it off the network;
# fetch_to treats it as a copy.
: > "$FAKE_PCT_LOG"
./install.sh --pve-only --ctid 151 --storage local-lvm --bridge vmbr0 \
             --channel "file://$PWD/packaging/tests/fixture-channel" --version 1.0.0
pushed=$(awk '/^push 151 /{print $3}' "$FAKE_PCT_LOG")
[ -n "$pushed" ] \
  || { echo "FAIL: the installer was never pushed into the CT"; cat "$FAKE_PCT_LOG"; exit 1; }
grep -q '^push 151 .* /root/install.sh --perms 0755' "$FAKE_PCT_LOG" \
  || { echo "FAIL: pushed to the wrong destination"; cat "$FAKE_PCT_LOG"; exit 1; }
[ "$pushed" != "$PWD/install.sh" ] \
  || { echo "FAIL: pushed the unbundled checkout install.sh into the CT"; exit 1; }
cmp -s "$pushed" "$tmp/published-install.sh" \
  || { echo "FAIL: pushed $pushed, which is not the published bundle"; exit 1; }
echo "OK: a checkout run still pushes the published bundle"

# The trap that shipped: piped, BASH_SOURCE[0] is unset and $0 is "bash", so
# SCRIPT_DIR collapses to the cwd. A stale install.sh in the operator's cwd
# (an old checkout copy left in /root on a node) used to be pushed as if it
# were this script. Plant one and prove it is ignored.
: > "$FAKE_PCT_LOG"
printf '%s\n' '#!/usr/bin/env bash' 'echo IMPOSTOR' > "$tmp/install.sh"
piped=$( cd "$tmp" && bash -s -- --pve-only --ctid 152 --storage local-lvm \
               --bridge vmbr0 \
               --channel "file://$OLDPWD/packaging/tests/fixture-channel" \
               --version 1.0.0 < "$tmp/published-install.sh" 2>&1 ) \
  || { echo "FAIL: the piped run exited $?:"; echo "$piped"; exit 1; }
pushed=$(awk '/^push 152 /{print $3}' "$FAKE_PCT_LOG")
grep -q '^push 152 .* /root/install.sh --perms 0755' "$FAKE_PCT_LOG" \
  || { echo "FAIL: a piped installer pushed nothing into the CT"; cat "$FAKE_PCT_LOG"; exit 1; }
grep -q IMPOSTOR "$pushed" \
  && { echo "FAIL: pushed the stale install.sh from the cwd"; exit 1; }
cmp -s "$pushed" "$tmp/published-install.sh" \
  || { echo "FAIL: pushed $pushed, which is not the published bundle"; exit 1; }
echo "OK: a stale install.sh in the cwd is never pushed into the CT"

# --- the advertised one-liner: no flags, both pools resolved here -----------
# The rootfs pool and the template pool are different pools on a stock node
# (local-lvm carries rootdir, local carries vztmpl). Resolving one and reading
# the template catalogue out of it made `pveam list local-lvm` exit non-zero,
# and `set -euo pipefail` + a discarded stderr turned that into "creating CT
# ..." followed by a silent exit with no CT created. fake-pvesm models the
# split and fake-pveam refuses the wrong pool, so that regression fails loudly.
: > "$FAKE_PCT_LOG"
bare=$( ./install.sh --pve-only --dry-run \
          --channel "file://$PWD/packaging/tests/fixture-channel" \
          --version 1.0.0 2>&1 ) \
  || { echo "FAIL: a flagless PVE run exited $?:"; echo "$bare"; exit 1; }
grep -q 'storage local-lvm' "$FAKE_PCT_LOG" \
  || { echo "FAIL: rootfs did not land on the rootdir pool"; cat "$FAKE_PCT_LOG"; exit 1; }
grep -q 'rootfs local-lvm:8' "$FAKE_PCT_LOG" \
  || { echo "FAIL: rootfs size/pool wrong"; cat "$FAKE_PCT_LOG"; exit 1; }
grep -q 'local:vztmpl/debian-12-standard' "$FAKE_PCT_LOG" \
  || { echo "FAIL: template did not come from the vztmpl pool"; cat "$FAKE_PCT_LOG"; exit 1; }
echo "OK: rootfs and template resolve to their own pools"

# Non-dry, so resolve_template really calls pveam with the pool it picked.
: > "$FAKE_PCT_LOG"
./install.sh --pve-only --ctid 153 \
             --channel "file://$PWD/packaging/tests/fixture-channel" \
             --version 1.0.0 >/dev/null 2>&1 \
  || { echo "FAIL: a flagless non-dry PVE run exited $?"; exit 1; }
grep -q '^create 153 local:vztmpl/debian-12-standard' "$FAKE_PCT_LOG" \
  || { echo "FAIL: pveam was asked for the wrong pool"; cat "$FAKE_PCT_LOG"; exit 1; }
echo "OK: the template catalogue is read from the vztmpl pool"
echo "PASS: pve half harness"
