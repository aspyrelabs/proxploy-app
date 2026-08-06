#!/usr/bin/env bash
# Runs the REAL updater in a REAL Debian container with systemd as PID 1.
# What this proves: an update applies (1.0.0 -> 1.0.1, data survives, a
# pre-update backup is taken), and a bad update undoes itself (a poisoned
# 1.0.2 fails and the container ends on 1.0.1, healthy, with data intact).
# What it does not prove: `pct create` (test_pve_half.sh) or a real release
# channel (spec D4).
set -euo pipefail
cd "$(dirname "$0")/../.."
# shellcheck source=packaging/tests/lib.sh
. packaging/tests/lib.sh

CH=${CH:-/tmp/pp-channel}
[ -d "$CH" ] || bash packaging/tests/channel_fixture.sh "$CH"
[ -f "$CH/1.0.2/manifest.json" ] || bash packaging/tests/channel_fixture.sh "$CH" --poison 1.0.2

name=pp-upgrade-$$
cleanup() { docker rm -f "$name" >/dev/null 2>&1 || true; }
trap cleanup EXIT

container_start "$name"

# 1. install 1.0.0 and seed a row we can look for afterwards. settings.key /
# settings.value are the real column names (backend/proxploy/models); the
# table also has NOT NULL created_at/updated_at with no DB-side default
# (they are Python-side defaults in the ORM), so the raw insert must supply
# them itself — same as test_install.sh's canary insert.
install_in_container 1.0.0
docker exec "$name" bash -c "sqlite3 /var/lib/proxploy/proxploy.db \
  \"insert into settings (key, value, created_at, updated_at) values ('harness.canary', 'keep-me', datetime('now'), datetime('now'))\""

# 2. upgrade to 1.0.1
docker exec "$name" /opt/proxploy/bin/proxploy-update --to 1.0.1 \
  --channel file:///channel/1.0.1

docker exec "$name" readlink /opt/proxploy/current | grep -q '1\.0\.1' \
  || { echo "FAIL: current does not point at 1.0.1"; exit 1; }
docker exec "$name" curl -fsS http://127.0.0.1:8000/api/v1/meta/health | grep -q ok \
  || { echo "FAIL: app is down after upgrade"; exit 1; }
docker exec "$name" bash -c "sqlite3 /var/lib/proxploy/proxploy.db \
  \"select value from settings where key='harness.canary'\"" | grep -q keep-me \
  || { echo "FAIL: upgrade lost data"; exit 1; }
docker exec "$name" test -f /var/lib/proxploy/pre-update/1.0.0/proxploy.db \
  || { echo "FAIL: no pre-update backup was taken"; exit 1; }
# The API answering is not the same claim as "a stranger can browse to this
# and see the app" — that is the SPA at /, served as a static file, not a
# route. install_release() is shared between install.sh and
# proxploy-update, but the updater has its own call site (Task 9), and a
# non-editable pip install there would silently break exactly this while
# /meta/health kept answering fine (the same failure mode test_install.sh
# guards against on the installer's own call site).
docker exec "$name" curl -fsSk https://127.0.0.1/ | grep -q 'id="root"' \
  || { echo "FAIL: TLS front does not serve the SPA at / after upgrade"; exit 1; }
echo "OK: 1.0.0 -> 1.0.1 upgrade, data intact, backup present, SPA serves"

# 3. try the poisoned 1.0.2 — it must fail AND put us back on 1.0.1
if docker exec "$name" /opt/proxploy/bin/proxploy-update --to 1.0.2 \
     --channel file:///channel/1.0.2; then
  echo "FAIL: poisoned release reported success"; exit 1
fi
docker exec "$name" readlink /opt/proxploy/current | grep -q '1\.0\.1' \
  || { echo "FAIL: did not roll back to 1.0.1"; exit 1; }
docker exec "$name" curl -fsS http://127.0.0.1:8000/api/v1/meta/health | grep -q ok \
  || { echo "FAIL: app is down after rollback — the worst outcome"; exit 1; }
docker exec "$name" bash -c "sqlite3 /var/lib/proxploy/proxploy.db \
  \"select value from settings where key='harness.canary'\"" | grep -q keep-me \
  || { echo "FAIL: rollback lost data"; exit 1; }
docker exec "$name" curl -fsSk https://127.0.0.1/ | grep -q 'id="root"' \
  || { echo "FAIL: TLS front does not serve the SPA at / after rollback"; exit 1; }
echo "OK: poisoned 1.0.2 rejected, rolled back to 1.0.1, app healthy, SPA serves"
echo "PASS: upgrade + rollback harness"
