#!/usr/bin/env bash
# Unit-level coverage for packaging/proxploy-update-run: the root-owned
# wrapper that turns an update request file into a call to proxploy-update.
# Runs in a plain (non-systemd) Debian container so `chown proxploy:proxploy`
# has a real user to target, without paying for a full install.sh run
# (channel_fixture.sh plus a real signed release) that
# test_upgrade_rollback.sh already covers end to end. proxploy-update itself
# is replaced with a stub that records its own arguments, so this proves the
# WRAPPER's request handling and channel derivation, not the real updater.
set -euo pipefail
cd "$(dirname "$0")/../.."

command -v docker >/dev/null 2>&1 || { echo "SKIP: docker not available"; exit 0; }

name=pp-wrapper-$$
cleanup() { docker rm -f "$name" >/dev/null 2>&1 || true; }
trap cleanup EXIT

docker run -d --name "$name" debian:12 sleep infinity >/dev/null
docker exec "$name" useradd --system --no-create-home --home-dir /var/lib/proxploy \
  --shell /usr/sbin/nologin proxploy
docker exec "$name" mkdir -p /opt/proxploy/bin /opt/proxploy/lib \
  /opt/proxploy/releases /var/lib/proxploy/updates

docker cp packaging/lib/common.sh "$name:/opt/proxploy/lib/common.sh"
docker cp packaging/proxploy-update-run "$name:/opt/proxploy/bin/proxploy-update-run"
docker exec "$name" chmod 0755 /opt/proxploy/bin/proxploy-update-run
docker exec "$name" chown -R proxploy:proxploy /var/lib/proxploy

# A stub proxploy-update: records the arguments it was handed instead of
# running a real release, since only the hand-off from the wrapper is under
# test here.
docker exec "$name" bash -c "cat > /opt/proxploy/bin/proxploy-update <<'STUB'
#!/bin/sh
echo \"\$@\" > /tmp/proxploy-update.args
STUB
chmod 0755 /opt/proxploy/bin/proxploy-update"

set_installed() {  # set_installed <version>
  docker exec "$name" bash -c \
    "mkdir -p /opt/proxploy/releases/$1 && ln -sfn /opt/proxploy/releases/$1 /opt/proxploy/current"
}
request() {  # request <content>
  docker exec "$name" bash -c "printf '%s' '$1' > /var/lib/proxploy/update-request"
}
run_wrapper() {
  docker exec "$name" rm -f /tmp/proxploy-update.args
  docker exec "$name" /opt/proxploy/bin/proxploy-update-run
}

# --- a valid version runs, and below 1.2.0 derives the dev channel ---------
set_installed 1.1.0
request "1.5.0"
run_wrapper
args=$(docker exec "$name" cat /tmp/proxploy-update.args)
[ "$args" = "--to 1.5.0 --channel https://web.proxploy.dev/releases/latest" ] \
  || { echo "FAIL: installed 1.1.0 gave wrapper args: $args"; exit 1; }
echo "OK: a valid version runs and installed < 1.2.0 derives the dev channel"

# --- at 1.2.0 the channel moves to prod -------------------------------------
set_installed 1.2.0
request "1.2.1"
run_wrapper
args=$(docker exec "$name" cat /tmp/proxploy-update.args)
[ "$args" = "--to 1.2.1 --channel https://proxploy.com/releases/latest" ] \
  || { echo "FAIL: installed 1.2.0 gave wrapper args: $args"; exit 1; }
echo "OK: installed at 1.2.0 derives the prod channel"

# --- 1.10.0 must not be mistaken for older than 1.2.0 by a string compare --
set_installed 1.10.0
request "1.10.1"
run_wrapper
args=$(docker exec "$name" cat /tmp/proxploy-update.args)
[ "$args" = "--to 1.10.1 --channel https://proxploy.com/releases/latest" ] \
  || { echo "FAIL: installed 1.10.0 gave wrapper args: $args (sort -V was not used)"; exit 1; }
echo "OK: 1.10.0 sorts above 1.2.0 (sort -V, not a string compare)"

# --- a malformed version is refused and records a terminal status ----------
docker exec "$name" rm -f /var/lib/proxploy/updates/invalid-request.status
request "not-a-version"
run_wrapper
docker exec "$name" test ! -s /tmp/proxploy-update.args \
  || { echo "FAIL: a malformed version still reached proxploy-update"; exit 1; }
status=$(docker exec "$name" cat /var/lib/proxploy/updates/invalid-request.status)
case "$status" in
  *'"state": "failed"'*) ;;
  *) echo "FAIL: malformed request did not write a terminal status: $status"; exit 1 ;;
esac
owner=$(docker exec "$name" stat -c '%U' /var/lib/proxploy/updates/invalid-request.status)
[ "$owner" = proxploy ] \
  || { echo "FAIL: the status file the app must read is owned by $owner, not proxploy"; exit 1; }
echo "OK: a malformed version is refused, never reaches proxploy-update, and leaves a terminal status the app can read"

echo "PASS: update wrapper harness"
