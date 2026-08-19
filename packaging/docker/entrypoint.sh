#!/usr/bin/env bash
# Container entrypoint: exec uvicorn. Runs as the non-root `proxploy` user
# (set by the Dockerfile's USER directive) inside /opt/proxploy/current.
#
# No separate `alembic upgrade head` step here: proxploy.main:create_app's
# lifespan already calls run_migrations() itself (backend/proxploy/db.py),
# in the correct order (master key ensured, THEN migrate). A standalone
# pre-migration step run from the shell creates the sqlite file (a side
# effect of `alembic upgrade head` connecting) before the key exists, which
# trips SecretStore's "database exists but no key" guard on every fresh
# volume: proved by running this image against an empty volume during
# Task 10 verification. Let the app migrate itself.
set -euo pipefail

# --proxy-headers matches the systemd unit (packaging/proxploy.service) so the
# two deployment shapes behave the same way. In the compose shape the port is
# published directly, so the peer uvicorn sees is the bridge network gateway,
# not 127.0.0.1: FORWARDED_ALLOW_IPS's default trusts nothing there, making
# the flag a no-op unless an operator fronts the container with their own
# proxy and sets FORWARDED_ALLOW_IPS to that proxy's address as the container
# sees it.
exec backend/venv/bin/uvicorn --factory proxploy.main:create_app \
  --host 0.0.0.0 --port 8000 --proxy-headers
