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

exec backend/venv/bin/uvicorn --factory proxploy.main:create_app \
  --host 0.0.0.0 --port 8000
