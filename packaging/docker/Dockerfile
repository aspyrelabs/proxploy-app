FROM node:22-slim AS web
WORKDIR /src
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
RUN adduser --system --group proxploy \
 && apt-get update && apt-get install -y --no-install-recommends sqlite3 \
 && rm -rf /var/lib/apt/lists/* \
 && mkdir -p /var/lib/proxploy && chown proxploy:proxploy /var/lib/proxploy
WORKDIR /opt/proxploy/current
COPY backend/ backend/
COPY --from=web /src/dist/ frontend/dist/
# Editable install: a regular `pip install ./backend` copies proxploy/ into
# venv/lib/.../site-packages, which moves __file__ away from backend/ and
# breaks main.py's parents[2]/frontend/dist lookup (proven by an initial
# build of this image where the health endpoint 404'd on `/`). `-e` keeps
# __file__ pointing at backend/proxploy/main.py so parents[2] still lands on
# /opt/proxploy/current, the sibling of frontend/dist copied in above.
RUN python -m venv backend/venv && backend/venv/bin/pip install --no-cache-dir -e ./backend
# The app never self-applies an update in this shape (spec D3) — the UI shows
# the compose command instead. This is the flag that makes that true.
ENV PROXPLOY_IN_DOCKER=1 \
    PROXPLOY_DATA_DIR=/var/lib/proxploy \
    PROXPLOY_DB_URL=sqlite:////var/lib/proxploy/proxploy.db \
    PROXPLOY_MASTER_KEY_FILE=/var/lib/proxploy/master.key
VOLUME /var/lib/proxploy
USER proxploy
EXPOSE 8000
COPY packaging/docker/entrypoint.sh /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
