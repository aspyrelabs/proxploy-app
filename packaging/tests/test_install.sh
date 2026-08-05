#!/usr/bin/env bash
# Runs the REAL installer in a REAL Debian container with systemd as PID 1.
# What this proves: the unit comes up, TLS serves the app, and a second run
# changes nothing. What it does not prove: `pct create` (test_pve_half.sh) or
# a real release channel (spec D4).
set -euo pipefail
cd "$(dirname "$0")/../.."
# shellcheck source=packaging/tests/lib.sh
. packaging/tests/lib.sh

CH=${CH:-/tmp/pp-channel}
[ -d "$CH" ] || bash packaging/tests/channel_fixture.sh "$CH"

name=pp-install-$$
cleanup() { docker rm -f "$name" >/dev/null 2>&1 || true; }
trap cleanup EXIT

container_start "$name"
install_in_container 1.0.0

docker exec "$name" systemctl is-active --quiet proxploy.service \
  || { echo "FAIL: proxploy.service is not active"; docker exec "$name" journalctl -u proxploy --no-pager | tail -40; exit 1; }
echo "OK: unit is active"

docker exec "$name" curl -fsS http://127.0.0.1:8000/api/v1/meta/health | grep -q '"ok"' \
  || { echo "FAIL: app does not answer"; exit 1; }
echo "OK: app answers on the loopback bind"

docker exec "$name" curl -fsSk https://127.0.0.1/api/v1/meta/health | grep -q '"ok"' \
  || { echo "FAIL: TLS front does not serve"; exit 1; }
echo "OK: TLS front serves"

# The API answering is not the same claim as "a stranger can browse to this
# and see the app" — that is the SPA at /, served as a static file, not a
# route. A non-editable pip install of the release once broke exactly this
# while /meta/health kept answering fine, so check for real page content,
# not just a 200.
docker exec "$name" curl -fsSk https://127.0.0.1/ | grep -q 'id="root"' \
  || { echo "FAIL: TLS front does not serve the SPA at /"; exit 1; }
echo "OK: TLS front serves the SPA"

# Idempotency: the second run must change nothing that matters. settings.key
# / settings.value are the real column names (backend/proxploy/models); the
# table also has NOT NULL created_at/updated_at with no DB-side default
# (they are Python-side defaults in the ORM), so the raw insert must supply
# them itself.
docker exec "$name" bash -c "sqlite3 /var/lib/proxploy/proxploy.db \
  \"insert into settings (key, value, created_at, updated_at) values ('harness.canary', '1', datetime('now'), datetime('now'))\""
before=$(docker exec "$name" md5sum /etc/proxploy/proxploy.env | cut -d' ' -f1)
install_in_container 1.0.0
after=$(docker exec "$name" md5sum /etc/proxploy/proxploy.env | cut -d' ' -f1)
[ "$before" = "$after" ] || { echo "FAIL: re-run rewrote proxploy.env"; exit 1; }
docker exec "$name" bash -c "sqlite3 /var/lib/proxploy/proxploy.db \
  \"select value from settings where key='harness.canary'\"" | grep -q 1 \
  || { echo "FAIL: re-run destroyed the database"; exit 1; }
docker exec "$name" systemctl is-active --quiet proxploy.service \
  || { echo "FAIL: re-run left the unit down"; exit 1; }
echo "OK: re-run is idempotent"
echo "PASS: install harness"
