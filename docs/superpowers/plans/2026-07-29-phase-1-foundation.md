# Phase 1: Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This is an unattended run: no human checkpoints, on ambiguity make the best spec-supported call, note it in the commit message, and keep going.

**Goal:** Land Phase 1 of `docs/10-build-sequence.md`: repo scaffolds for all four properties, DB bootstrap + full-schema migration 0001, local auth (argon2 + DB sessions + CSRF + rate limiting), SecretStore, the dormant entitlement layer (all 81 flags ON) in both proxploy-app and proxploy-api, host onboarding with proxmoxer connectivity check + SSH key enrolment, append-only audit log, settings service, the app shell + onboarding wizard v1 frontend, and the Phase-1 test infrastructure (proxmoxer fake layer, app↔api contract test, CI with the executor-isolation and license-audit checks and a wired disposable-PVE path).

**Architecture:** One Python 3.12+ FastAPI process (sync SQLAlchemy 2 sessions run in FastAPI's threadpool, async engines are YAGNI at Phase 1 scale), SQLite-WAL by default with Postgres via DSN, serving a React 19 + Vite SPA. proxploy-api is a second, tiny FastAPI service holding the Ed25519 signing key; the app bundles only public keys (a `kid`-keyed set). Specs: docs/00–11 in this repo are the approved source of truth; doc numbers cited per task.

**Tech Stack:** FastAPI, Uvicorn, Pydantic v2, SQLAlchemy 2, Alembic, argon2-cffi, cryptography (Fernet/MultiFernet + Ed25519), PyJWT (EdDSA), slowapi, httpx, proxmoxer / React 19, TypeScript, Vite, Tailwind v4, TanStack Query + Router, vitest.

## Global Constraints

- Python `>=3.12` (box has 3.14.4); Node 22; npm (not pnpm/yarn).
- All API routes under `/api/v1`; errors are RFC 9457 `application/problem+json` (doc 05).
- Never hand-roll crypto: `cryptography` Fernet/MultiFernet, `argon2-cffi`, `PyJWT` EdDSA, stdlib `secrets` + `hmac.compare_digest` only (doc 08 §10).
- Every flag key from doc 01 §17 (exactly 81) registered day 0, all resolving ON; unknown keys fail closed to `False` (doc 07 §2).
- Licenses: MIT/BSD/Apache-2.0/ISC/MPL-2.0(link)/PSF/PostgreSQL/Public-Domain allowed; LGPL/AGPL/BUSL never linked (doc 00 §3, doc 03). paramiko is rejected; asyncssh is NOT needed in Phase 1 (SSH keygen uses `cryptography`; the executor arrives Phase 4).
- The fixed nav is exactly: Cluster · Apps · App Store · Virtual Machines · Storage · Network · Backups · Settings (doc 01 §0).
- Design tokens are the prototype's verbatim values (doc 06 §c). Dark is canonical; light is a `[data-theme]` variable swap.
- Git: every repo commits directly to `main` (user standing rule). `git init -b main`; no branches, no PRs.
- No module outside `backend/proxploy/executor/` may ever import `asyncssh` or call an SSH-key SecretStore accessor, CI-enforced from Phase 1 even though `executor/` doesn't exist yet (docs 08 §4, 09).
- Working directories: `~/workspace/aspyrelabs/proxploy/proxploy-app` (app), `…/proxploy-api`, `…/proxploy-web`, `…/proxploy-docs`. All commands below give the repo-relative path; run them from the right repo root.
- Backend venv: `backend/.venv` in proxploy-app, `.venv` in proxploy-api. Test commands assume it.
- No live PVE and no Docker on this box: unit tests use the fake PVE layer; the disposable-PVE and Postgres CI legs are wired but env-gated.

## File structure (what Phase 1 creates)

```
proxploy-app/
├── backend/
│   ├── pyproject.toml, alembic.ini, .gitignore
│   ├── proxploy/
│   │   ├── __init__.py, main.py, config.py, db.py, middleware.py
│   │   ├── api/ __init__.py, deps.py, auth.py, hosts.py, entitlements.py,
│   │   │        audit.py, settings.py, meta.py
│   │   ├── services/ __init__.py, audit.py, authn.py, proxmox.py,
│   │   │             license_client.py, settings.py
│   │   ├── entitlements/ __init__.py, registry.py, client.py, keys.py
│   │   ├── secretstore/ __init__.py
│   │   ├── models/ __init__.py
│   │   └── migrations/ (alembic env + versions/0001_*.py)
│   ├── scripts/ check_executor_isolation.py
│   └── tests/ conftest.py, fakes/pve.py, fixtures/pve/*.json,
│              contract/entitlement_token.fixture.json, test_*.py
├── frontend/
│   ├── package.json, vite.config.ts, tsconfig.json, index.html
│   └── src/ main.tsx, router.tsx, theme.ts, styles/tokens.css,
│        api/client.ts, api/hooks.ts,
│        components/ AppShell.tsx, SidebarNav.tsx, Topbar.tsx, TierPill.tsx,
│                    ThemeToggle.tsx, LockVeil.tsx, EmptyState.tsx, ui/button.tsx,
│        routes/ login.tsx, onboarding.tsx, settings.tsx, placeholder.tsx
│        tests/ nav.test.tsx
└── .github/workflows/ci.yml

proxploy-api/
├── pyproject.toml, alembic.ini, .gitignore
├── proxploy_api/ __init__.py, main.py, config.py, db.py, signing.py, tiers.py,
│                 tiers.yaml, api/ __init__.py, licenses.py, entitlements.py,
│                 models/ __init__.py, migrations/
├── scripts/ gen_signing_key.py, create_license.py
├── tests/ conftest.py, contract/entitlement_token.fixture.json, test_*.py
└── .github/workflows/ci.yml

proxploy-web/  README.md.gitignore          (empty scaffold; content is Phase 9)
proxploy-docs/ README.md.gitignore          (empty scaffold; content is Phase 9)
```

---

### Task 1: Repo scaffolds + backend skeleton + health endpoint

Doc refs: 09 (layout), 10 Phase 1 (scaffolds), 05 (`/api/v1/meta/health`, problem+json).

**Files:**
- Create: `backend/pyproject.toml`, `backend/.gitignore`, `backend/proxploy/{__init__,config,main}.py`, `backend/proxploy/api/{__init__,meta}.py`, `backend/tests/{conftest.py,test_health.py}`
- Create: `../proxploy-web/{README.md,.gitignore}`, `../proxploy-docs/{README.md,.gitignore}` (git init those repos too)

**Interfaces:**
- Produces: `Settings` (pydantic-settings, env prefix `PROXPLOY_`), `get_settings()`, `create_app(settings=None, *, public_keys=None, proxmox_factory=None, license_client=None) -> FastAPI` (extra kwargs are wired in later tasks but accepted from day one so the signature never changes), `api_router` mounted at `/api/v1`, problem+json exception handler.

- [ ] **Step 1: git init all four repos**

```bash
cd ~/workspace/aspyrelabs/proxploy
for r in proxploy-app proxploy-api proxploy-web proxploy-docs; do git -C $r init -b main; done
printf '# proxploy-web\n\nproxploy.com marketing/landing/download site. Content lands in Phase 9 (docs/10 in proxploy-app).\n' > proxploy-web/README.md
printf 'node_modules/\ndist/\n' > proxploy-web/.gitignore
printf '# proxploy-docs\n\nProxploy documentation site. Content lands in Phase 9 (docs/10 in proxploy-app).\n' > proxploy-docs/README.md
printf 'node_modules/\ndist/\n' > proxploy-docs/.gitignore
git -C proxploy-web add -A && git -C proxploy-web commit -m "chore: empty scaffold (content deferred to Phase 9)"
git -C proxploy-docs add -A && git -C proxploy-docs commit -m "chore: empty scaffold (content deferred to Phase 9)"
```

- [ ] **Step 2: Write the failing test**

`backend/tests/conftest.py`:
```python
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path):
    from proxploy.config import Settings
    from proxploy.main import create_app

    s = Settings(
        db_url=f"sqlite:///{tmp_path}/proxploy.db",
        data_dir=tmp_path,
        master_key_file=tmp_path / "master.key",
    )
    app = create_app(s)
    with TestClient(app) as c:
        yield c
```

`backend/tests/test_health.py`:
```python
def test_health(client):
    r = client.get("/api/v1/meta/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_problem_json_shape(client):
    r = client.get("/api/v1/nope")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["status"] == 404
```

- [ ] **Step 3: Run it, expect import error**

```bash
cd proxploy-app/backend && python3 -m venv .venv && .venv/bin/pip -q install -e '.[dev]' 2>/dev/null; .venv/bin/python -m pytest tests/ -q
```
(First run fails because pyproject/package don't exist yet, that's the red state.)

- [ ] **Step 4: Implement**

`backend/pyproject.toml`:
```toml
[project]
name = "proxploy"
version = "0.1.0"
description = "Proxploy, Unraid's experience, for Proxmox"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.30",
  "pydantic-settings>=2.4",
  "sqlalchemy>=2.0",
  "alembic>=1.13",
  "argon2-cffi>=23.1",
  "cryptography>=43",
  "PyJWT>=2.9",
  "httpx>=0.27",
  "proxmoxer>=2.0",
  "requests>=2.32",
  "slowapi>=0.1.9",
]

[project.optional-dependencies]
dev = ["pytest>=8", "pip-licenses>=5", "psycopg[binary]>=3.2"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["proxploy*"]

[tool.pytest.ini_options]
markers = ["pve_integration: needs a disposable live PVE (PROXPLOY_TEST_PVE_* env)"]
```

`backend/.gitignore`:
```
.venv/
__pycache__/
*.egg-info/
data/
.pytest_cache/
```

`backend/proxploy/__init__.py`: `__version__ = "0.1.0"`

`backend/proxploy/config.py`:
```python
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PROXPLOY_")

    db_url: str = "sqlite:///./data/proxploy.db"
    data_dir: Path = Path("./data")
    master_key_file: Path = Path("./data/master.key")
    session_cookie: str = "pp_session"
    csrf_cookie: str = "pp_csrf"
    session_ttl_hours: int = 168
    cookie_secure: bool = False  # installer flips on when TLS terminates at the app
    api_base_url: str = "https://api.proxploy.com"


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

`backend/proxploy/api/__init__.py`:
```python
from fastapi import APIRouter

from proxploy.api import meta

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(meta.router)
```

`backend/proxploy/api/meta.py`:
```python
from fastapi import APIRouter

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/health")
def health():
    return {"status": "ok"}
```

`backend/proxploy/main.py`:
```python
import http.client

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from proxploy.config import Settings, get_settings


def create_app(
    settings: Settings | None = None,
    *,
    public_keys: dict[str, str] | None = None,
    proxmox_factory=None,
    license_client=None,
) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Proxploy", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.settings = settings

    from proxploy.api import api_router

    app.include_router(api_router)

    @app.exception_handler(StarletteHTTPException)
    async def problem_handler(request, exc):
        body = {
            "type": "about:blank",
            "title": http.client.responses.get(exc.status_code, "Error"),
            "status": exc.status_code,
        }
        if isinstance(exc.detail, dict):
            body.update(exc.detail)
        else:
            body["detail"] = exc.detail
        return JSONResponse(
            body, status_code=exc.status_code,
            media_type="application/problem+json", headers=exc.headers,
        )

    return app
```

- [ ] **Step 5: Run tests, expect PASS**

```bash
cd proxploy-app/backend && .venv/bin/pip -q install -e '.[dev]' && .venv/bin/python -m pytest tests/ -q
```

- [ ] **Step 6: Commit**

```bash
cd proxploy-app && printf 'logs/\n' >> .gitignore && git add -A && git commit -m "feat(backend): scaffold FastAPI app, health endpoint, problem+json errors"
```

---

### Task 2: Full data model + Alembic migration 0001

Doc refs: 04 (every table, verbatim columns), 10 Phase 1 ("Alembic migration 0001 with the full entity list from brief §9"; we create the **full** doc-04 entity list now, 24 tables; later phases alter, they don't bolt on the basics), 02 §3 (SQLite WAL).

**Files:**
- Create: `backend/proxploy/models/__init__.py`, `backend/proxploy/db.py`, `backend/alembic.ini`, `backend/proxploy/migrations/*` (alembic init + one autogenerated revision)
- Modify: `backend/proxploy/main.py` (lifespan runs `alembic upgrade head`)
- Test: `backend/tests/test_migrations.py`

**Interfaces:**
- Produces: `proxploy.models.Base` and model classes `User, SessionRow, ApiKey, Team, TeamMember, CasbinRule, Host, HostCredential, App, AppScript, Vm, CatalogEntry, Job, JobEvent, Schedule, NotificationChannel, AlertRule, Alert, MetricSample, MetricRollup, Backup, AuditEvent, EntitlementCache, AppSetting`; `proxploy.models.utcnow()`; `proxploy.db.make_engine(settings)`, `proxploy.db.run_migrations(settings)`; `app.state.engine`, `app.state.sessionmaker`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_migrations.py`:
```python
import os

import pytest
from sqlalchemy import create_engine, inspect

EXPECTED = {
    "users", "sessions", "api_keys", "teams", "team_members", "casbin_rules",
    "hosts", "host_credentials", "apps", "app_scripts", "vms", "catalog_entries",
    "jobs", "job_events", "schedules", "notification_channels", "alert_rules",
    "alerts", "metric_samples", "metric_rollups", "backups", "audit_events",
    "entitlement_cache", "settings",
}


def _upgraded_tables(db_url):
    from proxploy.config import Settings
    from proxploy.db import run_migrations

    run_migrations(Settings(db_url=db_url))
    eng = create_engine(db_url)
    try:
        return set(inspect(eng).get_table_names())
    finally:
        eng.dispose()


def test_migration_0001_sqlite(tmp_path):
    tables = _upgraded_tables(f"sqlite:///{tmp_path}/m.db")
    assert EXPECTED <= tables


def test_sqlite_wal(tmp_path):
    from proxploy.config import Settings
    from proxploy.db import make_engine, run_migrations

    s = Settings(db_url=f"sqlite:///{tmp_path}/w.db")
    run_migrations(s)
    eng = make_engine(s)
    with eng.connect() as c:
        assert c.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"


@pytest.mark.skipif(not os.environ.get("PROXPLOY_TEST_PG_DSN"), reason="no Postgres DSN")
def test_migration_0001_postgres():
    tables = _upgraded_tables(os.environ["PROXPLOY_TEST_PG_DSN"])
    assert EXPECTED <= tables
```

- [ ] **Step 2: Run, FAIL (`No module named 'proxploy.db'`)**

`cd proxploy-app/backend && .venv/bin/python -m pytest tests/test_migrations.py -q`

- [ ] **Step 3: Write the models (full doc-04 schema)**

`backend/proxploy/models/__init__.py`:
```python
"""All Proxploy entities, schema per docs/04-data-model.md, portable SQLite/Postgres subset."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON,
    LargeBinary, Text, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

BigPK = BigInteger().with_variant(Integer, "sqlite")


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )


# --- Identity & access -----------------------------------------------------

class User(TimestampMixin, Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(Text)
    password_hash: Mapped[str | None] = mapped_column(Text)
    totp_secret_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    oidc_issuer: Mapped[str | None] = mapped_column(Text)
    oidc_sub: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)
    __table_args__ = (Index("ux_users_oidc", "oidc_issuer", "oidc_sub", unique=True),)


class SessionRow(TimestampMixin, Base):
    __tablename__ = "sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    ip: Mapped[str | None] = mapped_column(Text)
    user_agent: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)


class ApiKey(TimestampMixin, Base):
    __tablename__ = "api_keys"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    prefix: Mapped[str] = mapped_column(Text, nullable=False)
    key_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)


class Team(TimestampMixin, Base):
    __tablename__ = "teams"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)


class TeamMember(TimestampMixin, Base):
    __tablename__ = "team_members"
    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(Text, nullable=False)  # owner|admin|operator|viewer
    __table_args__ = (UniqueConstraint("team_id", "user_id", name="ux_team_members"),)


class CasbinRule(Base):
    __tablename__ = "casbin_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    ptype: Mapped[str | None] = mapped_column(Text)
    v0: Mapped[str | None] = mapped_column(Text)
    v1: Mapped[str | None] = mapped_column(Text)
    v2: Mapped[str | None] = mapped_column(Text)
    v3: Mapped[str | None] = mapped_column(Text)
    v4: Mapped[str | None] = mapped_column(Text)
    v5: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (Index("ix_casbin", "ptype", "v0", "v1"),)


# --- Infrastructure --------------------------------------------------------

class Host(TimestampMixin, Base):
    __tablename__ = "hosts"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    address: Mapped[str] = mapped_column(Text, nullable=False)
    node_name: Mapped[str | None] = mapped_column(Text)
    cluster_name: Mapped[str | None] = mapped_column(Text)
    verify_tls: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    tls_fingerprint: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="connected", nullable=False)
    pve_version: Mapped[str | None] = mapped_column(Text)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))


class HostCredential(TimestampMixin, Base):
    __tablename__ = "host_credentials"
    id: Mapped[int] = mapped_column(primary_key=True)
    host_id: Mapped[int] = mapped_column(ForeignKey("hosts.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text, nullable=False)  # api_token | ssh_key
    encrypted_blob: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    public_meta: Mapped[str | None] = mapped_column(Text)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)
    __table_args__ = (UniqueConstraint("host_id", "kind", name="ux_host_creds"),)


# --- Apps ------------------------------------------------------------------

class App(TimestampMixin, Base):
    __tablename__ = "apps"
    id: Mapped[int] = mapped_column(primary_key=True)
    host_id: Mapped[int] = mapped_column(ForeignKey("hosts.id", ondelete="RESTRICT"))
    ctid: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    catalog_slug: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    icon_initials: Mapped[str | None] = mapped_column(Text)
    icon_colors: Mapped[dict | None] = mapped_column(JSON)
    web_port: Mapped[int | None] = mapped_column(Integer)
    web_protocol: Mapped[str] = mapped_column(Text, default="http", nullable=False)
    web_path: Mapped[str] = mapped_column(Text, default="/", nullable=False)
    status_cached: Mapped[str | None] = mapped_column(Text)
    ip_cached: Mapped[str | None] = mapped_column(Text)
    cpu_pct_cached: Mapped[float | None] = mapped_column(Float)
    mem_bytes_cached: Mapped[int | None] = mapped_column(BigInteger)
    uptime_s_cached: Mapped[int | None] = mapped_column(Integer)
    update_available: Mapped[str | None] = mapped_column(Text)
    adopted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    __table_args__ = (UniqueConstraint("host_id", "ctid", name="ux_apps_host_ctid"),)


class AppScript(TimestampMixin, Base):
    __tablename__ = "app_scripts"
    id: Mapped[int] = mapped_column(primary_key=True)
    app_id: Mapped[int] = mapped_column(ForeignKey("apps.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)  # upstream | edited
    upstream_ref: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    __table_args__ = (UniqueConstraint("app_id", "version", name="ux_app_scripts"),)


class Vm(TimestampMixin, Base):
    __tablename__ = "vms"
    id: Mapped[int] = mapped_column(primary_key=True)
    host_id: Mapped[int] = mapped_column(ForeignKey("hosts.id", ondelete="CASCADE"))
    vmid: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text)
    os_type: Mapped[str | None] = mapped_column(Text)
    cpu_cores: Mapped[int | None] = mapped_column(Integer)
    mem_bytes: Mapped[int | None] = mapped_column(BigInteger)
    disk_bytes: Mapped[int | None] = mapped_column(BigInteger)
    uptime_s: Mapped[int | None] = mapped_column(Integer)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    __table_args__ = (UniqueConstraint("host_id", "vmid", name="ux_vms"),)


class CatalogEntry(TimestampMixin, Base):
    __tablename__ = "catalog_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    script_path: Mapped[str | None] = mapped_column(Text)
    website: Mapped[str | None] = mapped_column(Text)
    docs_url: Mapped[str | None] = mapped_column(Text)
    default_cpu: Mapped[int | None] = mapped_column(Integer)
    default_ram_mb: Mapped[int | None] = mapped_column(Integer)
    default_disk_gb: Mapped[int | None] = mapped_column(Integer)
    default_os: Mapped[str | None] = mapped_column(Text)
    default_os_version: Mapped[str | None] = mapped_column(Text)
    icon_url: Mapped[str | None] = mapped_column(Text)
    popularity: Mapped[int | None] = mapped_column(Integer)
    upstream_sha: Mapped[str | None] = mapped_column(Text)
    raw: Mapped[dict | None] = mapped_column(JSON)
    deprecated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    installable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    unsupported_reason: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime)


# --- Jobs & scheduling -----------------------------------------------------

class Job(TimestampMixin, Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, default="queued", nullable=False)
    target_type: Mapped[str | None] = mapped_column(Text)
    target_id: Mapped[int | None] = mapped_column(Integer)
    params: Mapped[dict | None] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    progress_pct: Mapped[int | None] = mapped_column(Integer)
    requested_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    schedule_id: Mapped[int | None] = mapped_column(ForeignKey("schedules.id"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    __table_args__ = (
        Index("ix_jobs_status", "status", "created_at"),
        Index("ix_jobs_target", "target_type", "target_id", "created_at"),
    )


class JobEvent(Base):
    __tablename__ = "job_events"
    id: Mapped[int] = mapped_column(BigPK, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    stream: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    __table_args__ = (UniqueConstraint("job_id", "seq", name="ux_job_events"),)


class Schedule(TimestampMixin, Base):
    __tablename__ = "schedules"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    job_kind: Mapped[str] = mapped_column(Text, nullable=False)
    cron: Mapped[str] = mapped_column(Text, nullable=False)
    timezone: Mapped[str] = mapped_column(Text, default="UTC", nullable=False)
    params: Mapped[dict | None] = mapped_column(JSON)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


# --- Notifications & alerting ----------------------------------------------

class NotificationChannel(TimestampMixin, Base):
    __tablename__ = "notification_channels"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str | None] = mapped_column(Text)
    url_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    events: Mapped[list] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime)


class AlertRule(TimestampMixin, Base):
    __tablename__ = "alert_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    metric: Mapped[str] = mapped_column(Text, nullable=False)
    target_type: Mapped[str] = mapped_column(Text, default="any", nullable=False)
    target_id: Mapped[int | None] = mapped_column(Integer)
    operator: Mapped[str] = mapped_column(Text, nullable=False)  # gt | lt
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    duration_s: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    severity: Mapped[str] = mapped_column(Text, default="warning", nullable=False)
    channel_ids: Mapped[list] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Alert(TimestampMixin, Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("alert_rules.id", ondelete="CASCADE"))
    target_type: Mapped[str | None] = mapped_column(Text)
    target_id: Mapped[int | None] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(Text, default="firing", nullable=False)
    value: Mapped[float | None] = mapped_column(Float)
    message: Mapped[str | None] = mapped_column(Text)
    fired_at: Mapped[datetime | None] = mapped_column(DateTime)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    acked_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    acked_at: Mapped[datetime | None] = mapped_column(DateTime)
    __table_args__ = (Index("ix_alerts_state", "state", "fired_at"),)


# --- Metrics ---------------------------------------------------------------

class MetricSample(Base):
    __tablename__ = "metric_samples"
    id: Mapped[int] = mapped_column(BigPK, primary_key=True)
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[int] = mapped_column(Integer, nullable=False)
    metric: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (Index("ix_samples", "target_type", "target_id", "metric", "ts"),)


class MetricRollup(TimestampMixin, Base):
    __tablename__ = "metric_rollups"
    id: Mapped[int] = mapped_column(BigPK, primary_key=True)
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[int] = mapped_column(Integer, nullable=False)
    metric: Mapped[str] = mapped_column(Text, nullable=False)
    resolution: Mapped[str] = mapped_column(Text, nullable=False)  # 5m | 1h
    bucket_ts: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    min: Mapped[float | None] = mapped_column(Float)
    max: Mapped[float | None] = mapped_column(Float)
    avg: Mapped[float | None] = mapped_column(Float)
    sample_count: Mapped[int | None] = mapped_column(Integer)
    __table_args__ = (
        UniqueConstraint("target_type", "target_id", "metric", "resolution",
                         "bucket_ts", name="ux_rollups"),
    )


# --- Backups ---------------------------------------------------------------

class Backup(TimestampMixin, Base):
    __tablename__ = "backups"
    id: Mapped[int] = mapped_column(primary_key=True)
    host_id: Mapped[int] = mapped_column(ForeignKey("hosts.id", ondelete="CASCADE"))
    storage: Mapped[str | None] = mapped_column(Text)
    volid: Mapped[str] = mapped_column(Text, nullable=False)
    guest_type: Mapped[str | None] = mapped_column(Text)
    guest_vmid: Mapped[int | None] = mapped_column(Integer)
    guest_name: Mapped[str | None] = mapped_column(Text)
    taken_at: Mapped[datetime | None] = mapped_column(DateTime)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    verify_state: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    __table_args__ = (
        UniqueConstraint("host_id", "volid", name="ux_backups"),
        Index("ix_backups_guest", "guest_type", "guest_vmid"),
    )


# --- Audit, entitlements, settings ----------------------------------------

class AuditEvent(Base):
    """Append-only. No ORM update/delete path exists anywhere in the app (doc 04)."""
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(BigPK, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    actor_type: Mapped[str] = mapped_column(Text, nullable=False)  # user|api_key|system
    actor_id: Mapped[int | None] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target_type: Mapped[str | None] = mapped_column(Text)
    target_id: Mapped[int | None] = mapped_column(Integer)
    params: Mapped[dict | None] = mapped_column(JSON)
    result: Mapped[str] = mapped_column(Text, default="ok", nullable=False)
    ip: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(Text)
    job_id: Mapped[int | None] = mapped_column(Integer)
    __table_args__ = (
        Index("ix_audit_ts", "ts"),
        Index("ix_audit_actor", "actor_type", "actor_id", "ts"),
        Index("ix_audit_target", "target_type", "target_id", "ts"),
    )


class EntitlementCache(TimestampMixin, Base):
    __tablename__ = "entitlement_cache"
    id: Mapped[int] = mapped_column(primary_key=True)  # always 1
    token: Mapped[str | None] = mapped_column(Text)  # Fernet ciphertext, base64 str
    tier: Mapped[str] = mapped_column(Text, default="builtin", nullable=False)
    features: Mapped[dict | None] = mapped_column(JSON)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    grace_until: Mapped[datetime | None] = mapped_column(DateTime)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime)


class AppSetting(TimestampMixin, Base):
    __tablename__ = "settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    value: Mapped[dict | list | str | int | bool | None] = mapped_column(JSON)
```

`backend/proxploy/db.py`:
```python
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from proxploy.config import Settings


def make_engine(settings: Settings):
    engine = create_engine(settings.db_url)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _rec):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
    return engine


def make_sessionmaker(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


def run_migrations(settings: Settings) -> None:
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    cfg.set_main_option("sqlalchemy.url", settings.db_url)
    command.upgrade(cfg, "head")
```

- [ ] **Step 4: Initialize Alembic and autogenerate 0001**

```bash
cd proxploy-app/backend
.venv/bin/alembic init proxploy/migrations
```
Replace `backend/alembic.ini`'s `script_location` line with `script_location = proxploy/migrations` and its `sqlalchemy.url` line with `sqlalchemy.url = sqlite:///./data/proxploy.db`. Replace `backend/proxploy/migrations/env.py` with:
```python
import os

from alembic import context
from sqlalchemy import engine_from_config, pool

from proxploy.models import Base

config = context.config
url = os.environ.get("PROXPLOY_DB_URL")
if url:
    config.set_main_option("sqlalchemy.url", url)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"),
                      target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(config.get_section(config.config_ini_section, {}),
                                     prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```
Then generate against a scratch DB and sanity-check the revision file mentions all 24 tables:
```bash
mkdir -p data
PROXPLOY_DB_URL=sqlite:///./data/scratch.db .venv/bin/alembic revision --autogenerate -m "0001 full entity list"
grep -c "create_table" proxploy/migrations/versions/*.py   # expect 24
rm -f data/scratch.db
```

- [ ] **Step 5: Wire migrations + engine into app startup**

In `backend/proxploy/main.py`, add a lifespan (replace the `app = FastAPI(...)` line and add imports):
```python
from contextlib import asynccontextmanager

from proxploy.db import make_engine, make_sessionmaker, run_migrations
```
```python
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        run_migrations(settings)
        app.state.engine = make_engine(settings)
        app.state.sessionmaker = make_sessionmaker(app.state.engine)
        yield
        app.state.engine.dispose()

    app = FastAPI(title="Proxploy", docs_url="/api/docs",
                  openapi_url="/api/openapi.json", lifespan=lifespan)
```

- [ ] **Step 6: Run all tests, expect PASS** (`.venv/bin/python -m pytest tests/ -q`)

- [ ] **Step 7: Commit**, `git add -A && git commit -m "feat(backend): full doc-04 schema, Alembic 0001, SQLite WAL, startup migrations"`

---

### Task 3: SecretStore (Fernet/MultiFernet, root-only key file)

Doc refs: 08 §3, 04 (encrypted blobs), 11 §9 (never silently regenerate a missing key).

**Files:**
- Create: `backend/proxploy/secretstore/__init__.py`
- Modify: `backend/proxploy/main.py` (lifespan creates key file before DB, sets `app.state.secretstore`)
- Test: `backend/tests/test_secretstore.py`

**Interfaces:**
- Produces: `SecretStore(key_file: Path)` with `.encrypt(data: bytes) -> tuple[bytes, int]` (ciphertext, key_version), `.decrypt(blob: bytes) -> bytes`, `.key_version: int`; classmethod `SecretStore.ensure_key_file(path: Path, db_file_exists: bool) -> None` (creates 0400 key; raises `MasterKeyMissing` if the DB already exists but the key doesn't); `.rotate()` = prepend a new key line to the file externally then call `SecretStore.reencrypt(blob) -> tuple[bytes, int]`; full rotation job is later-phase, the seam is `encrypt/decrypt/reencrypt`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_secretstore.py`:
```python
import os
import stat

import pytest


def test_roundtrip_and_perms(tmp_path):
    from proxploy.secretstore import SecretStore

    kf = tmp_path / "master.key"
    SecretStore.ensure_key_file(kf, db_file_exists=False)
    assert stat.S_IMODE(os.stat(kf).st_mode) == 0o400
    ss = SecretStore(kf)
    blob, ver = ss.encrypt(b"proxploy@pve!ro=SECRET")
    assert ver == 1 and blob != b"proxploy@pve!ro=SECRET"
    assert ss.decrypt(blob) == b"proxploy@pve!ro=SECRET"


def test_refuses_regenerate_over_existing_db(tmp_path):
    from proxploy.secretstore import MasterKeyMissing, SecretStore

    with pytest.raises(MasterKeyMissing):
        SecretStore.ensure_key_file(tmp_path / "master.key", db_file_exists=True)


def test_rotation_decrypts_old_and_reencrypts(tmp_path):
    from cryptography.fernet import Fernet

    from proxploy.secretstore import SecretStore

    kf = tmp_path / "master.key"
    SecretStore.ensure_key_file(kf, db_file_exists=False)
    old = SecretStore(kf)
    blob, _ = old.encrypt(b"s3cret")
    kf.chmod(0o600)
    kf.write_text(Fernet.generate_key().decode() + "\n" + kf.read_text())
    kf.chmod(0o400)
    new = SecretStore(kf)
    assert new.key_version == 2
    assert new.decrypt(blob) == b"s3cret"
    blob2, ver2 = new.reencrypt(blob)
    assert ver2 == 2 and new.decrypt(blob2) == b"s3cret"
```

- [ ] **Step 2: Run, FAIL (no module)**

- [ ] **Step 3: Implement**

`backend/proxploy/secretstore/__init__.py`:
```python
"""SecretStore seam (brief §5): Fernet/MultiFernet, master key in a root-only file.

OpenBao is the arm's-length swap-in; nothing outside this module may know the backend.
"""
from pathlib import Path

from cryptography.fernet import Fernet, MultiFernet


class MasterKeyMissing(RuntimeError):
    pass


class SecretStore:
    def __init__(self, key_file: Path):
        keys = [Fernet(line) for line in key_file.read_text().split() if line]
        if not keys:
            raise MasterKeyMissing(f"{key_file} contains no keys")
        self._fernet = MultiFernet(keys)
        self.key_version = len(keys)  # newest key is line 1; version = generation count

    @classmethod
    def ensure_key_file(cls, path: Path, db_file_exists: bool) -> None:
        if path.exists():
            return
        if db_file_exists:
            # Doc 11 §9: never silently regenerate a key over an existing DB, 
            # that would strand every stored credential as ambiguous ciphertext.
            raise MasterKeyMissing(
                f"master key {path} is missing but a database already exists. "
                "Restore the key file from backup, or delete the database to re-onboard."
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(mode=0o600)
        path.write_text(Fernet.generate_key().decode() + "\n")
        path.chmod(0o400)

    def encrypt(self, data: bytes) -> tuple[bytes, int]:
        return self._fernet.encrypt(data), self.key_version

    def decrypt(self, blob: bytes) -> bytes:
        return self._fernet.decrypt(blob)

    def reencrypt(self, blob: bytes) -> tuple[bytes, int]:
        return self._fernet.rotate(blob), self.key_version
```

In `main.py` lifespan, before `run_migrations(settings)`:
```python
        from proxploy.secretstore import SecretStore

        db_file = settings.db_url.removeprefix("sqlite:///")
        db_exists = settings.db_url.startswith("sqlite") and Path(db_file).exists()
        SecretStore.ensure_key_file(settings.master_key_file, db_file_exists=db_exists)
        app.state.secretstore = SecretStore(settings.master_key_file)
```
(add `from pathlib import Path` to main.py imports).

- [ ] **Step 4: Run tests, PASS**
- [ ] **Step 5: Commit**, `git add -A && git commit -m "feat(backend): SecretStore, Fernet/MultiFernet, 0400 key file, regeneration guard"`

---

### Task 4: Audit write helper (append-only, redacting)

Doc refs: 04 (`audit_events`), 08 §7, 10 Phase 1 ("append-only write helper wired into every state-changing route from day one").

**Files:**
- Create: `backend/proxploy/services/__init__.py` (empty), `backend/proxploy/services/audit.py`
- Test: `backend/tests/test_audit.py`

**Interfaces:**
- Produces: `write_audit(db, *, actor_type: str, action: str, actor_id: int | None = None, target_type: str | None = None, target_id: int | None = None, params: dict | None = None, result: str = "ok", ip: str | None = None, request_id: str | None = None, job_id: int | None = None) -> None` (adds + commits one `AuditEvent`; params pass through `redact()`); `redact(obj) -> obj` replaces values of sensitive keys with `"[redacted]"` recursively.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_audit.py`:
```python
def _db(tmp_path):
    from proxploy.config import Settings
    from proxploy.db import make_engine, make_sessionmaker, run_migrations

    s = Settings(db_url=f"sqlite:///{tmp_path}/a.db")
    run_migrations(s)
    return make_sessionmaker(make_engine(s))()


def test_write_audit_redacts_secrets(tmp_path):
    from proxploy.models import AuditEvent
    from proxploy.services.audit import write_audit

    db = _db(tmp_path)
    write_audit(db, actor_type="user", actor_id=1, action="host.create",
                target_type="host", target_id=2,
                params={"name": "pve-01", "token_secret": "abc",
                        "nested": {"password": "x"}})
    row = db.query(AuditEvent).one()
    assert row.action == "host.create" and row.result == "ok"
    assert row.params["name"] == "pve-01"
    assert row.params["token_secret"] == "[redacted]"
    assert row.params["nested"]["password"] == "[redacted]"


def test_no_update_or_delete_helpers():
    import proxploy.services.audit as m
    assert not any(n.startswith(("update", "delete")) for n in dir(m))
```

- [ ] **Step 2: Run, FAIL**

- [ ] **Step 3: Implement**

`backend/proxploy/services/audit.py`:
```python
"""Append-only audit writer (docs 04/08 §7). There is deliberately no update or
delete function in this module, archival is a Phase-8+ export job, never mutation."""
from proxploy.models import AuditEvent

REDACT_KEYS = {"password", "secret", "token_secret", "token", "key",
               "license_key", "refresh_credential", "totp"}


def redact(obj):
    if isinstance(obj, dict):
        return {k: "[redacted]" if k.lower() in REDACT_KEYS else redact(v)
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


def write_audit(db, *, actor_type: str, action: str, actor_id: int | None = None,
                target_type: str | None = None, target_id: int | None = None,
                params: dict | None = None, result: str = "ok",
                ip: str | None = None, request_id: str | None = None,
                job_id: int | None = None) -> None:
    db.add(AuditEvent(actor_type=actor_type, actor_id=actor_id, action=action,
                      target_type=target_type, target_id=target_id,
                      params=redact(params) if params else None, result=result,
                      ip=ip, request_id=request_id, job_id=job_id))
    db.commit()
```

- [ ] **Step 4: Run tests, PASS**
- [ ] **Step 5: Commit**, `git add -A && git commit -m "feat(backend): append-only audit writer with secret redaction"`

---

### Task 5: AuthN: argon2 passwords, DB sessions, CSRF, rate limiting, users + RBAC stub

Doc refs: 08 §5 (hardening table), 05 (auth endpoints), 10 Phase 1 (login/logout/me + `POST /api/v1/users`), 04 (`users`, `sessions`, `teams`, `team_members`).

**Files:**
- Create: `backend/proxploy/services/authn.py`, `backend/proxploy/middleware.py`, `backend/proxploy/api/deps.py`, `backend/proxploy/api/auth.py`
- Modify: `backend/proxploy/api/__init__.py`, `backend/proxploy/main.py`, `backend/tests/conftest.py`
- Test: `backend/tests/test_auth.py`

**Interfaces:**
- Produces (services.authn): `hash_password(pw: str) -> str`, `verify_password(hash: str, pw: str) -> bool`, `create_session(db, user, ip, user_agent, ttl_hours) -> str` (returns the raw cookie token), `resolve_session(db, raw: str) -> User | None`, `revoke_session(db, raw: str) -> None`.
- Produces (api.deps): `get_db(request)` dependency yielding a Session; `get_current_user(...) -> User` (401 problem when unauthenticated); `user_role(db, user) -> str`; `require_role(min_role: str)` returning a dependency that yields the User (403 when below); `ROLE_ORDER = {"viewer": 0, "operator": 1, "admin": 2, "owner": 3}`. `require_role` is the Phase-1 **RBAC stub**, the seam pycasbin replaces in Phase 8 (roles read from `team_members`, default team).
- Produces (middleware): `CSRFMiddleware`, double-submit: issues `pp_csrf` cookie when absent; on mutating `/api/*` requests without an `Authorization` header, requires header `X-CSRF-Token` equal (`hmac.compare_digest`) to the cookie.
- Produces (api.auth): `POST /api/v1/auth/login` (rate-limited `10/minute` per IP via slowapi), `POST /api/v1/auth/logout`, `GET /api/v1/auth/me`, `POST /api/v1/users`. First-ever user may be created unauthenticated and becomes `owner` of the auto-created `Default` team (doc 08 §8 forced first-run owner creation); afterwards `POST /users` requires admin, and granting `owner` requires owner.
- Produces (conftest helpers): `bootstrap_admin(client, email="admin@example.com", password="correct-horse-battery")` → creates first user + logs in, returns the client (cookies set); `csrf(client) -> dict` returns `{"X-CSRF-Token": ...}` after ensuring the cookie exists via a GET.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_auth.py`:
```python
def test_first_user_bootstrap_then_login_me_logout(client, csrf_header):
    # first user: unauthenticated create allowed, becomes owner
    r = client.post("/api/v1/users", json={
        "email": "admin@example.com", "password": "correct-horse-battery",
        "display_name": "Admin"}, headers=csrf_header(client))
    assert r.status_code == 201
    assert r.json()["role"] == "owner"

    # second unauthenticated create is rejected
    r = client.post("/api/v1/users", json={
        "email": "x@example.com", "password": "correct-horse-battery"},
        headers=csrf_header(client))
    assert r.status_code == 401

    r = client.post("/api/v1/auth/login", json={
        "email": "admin@example.com", "password": "correct-horse-battery"},
        headers=csrf_header(client))
    assert r.status_code == 200

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "admin@example.com"
    assert me.json()["role"] == "owner"

    assert client.post("/api/v1/auth/logout", headers=csrf_header(client)).status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401


def test_bad_password_rejected_and_audited(client, csrf_header):
    client.post("/api/v1/users", json={
        "email": "a@example.com", "password": "correct-horse-battery"},
        headers=csrf_header(client))
    r = client.post("/api/v1/auth/login", json={
        "email": "a@example.com", "password": "wrong-wrong-wrong"},
        headers=csrf_header(client))
    assert r.status_code == 401


def test_csrf_required_for_mutations(client):
    r = client.post("/api/v1/users", json={
        "email": "b@example.com", "password": "correct-horse-battery"})
    assert r.status_code == 403  # no X-CSRF-Token header


def test_login_rate_limited(client, csrf_header):
    for _ in range(10):
        client.post("/api/v1/auth/login", json={
            "email": "nobody@example.com", "password": "nope-nope-nope"},
            headers=csrf_header(client))
    r = client.post("/api/v1/auth/login", json={
        "email": "nobody@example.com", "password": "nope-nope-nope"},
        headers=csrf_header(client))
    assert r.status_code == 429


def test_admin_creates_user(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    r = client.post("/api/v1/users", json={
        "email": "op@example.com", "password": "correct-horse-battery",
        "role": "operator"}, headers=csrf_header(client))
    assert r.status_code == 201 and r.json()["role"] == "operator"
```

Append to `backend/tests/conftest.py`:
```python
@pytest.fixture
def csrf_header():
    def _get(client):
        if "pp_csrf" not in client.cookies:
            client.get("/api/v1/meta/health")
        return {"X-CSRF-Token": client.cookies["pp_csrf"]}
    return _get


@pytest.fixture
def bootstrap_admin(csrf_header):
    def _make(client, email="admin@example.com", password="correct-horse-battery"):
        client.post("/api/v1/users", json={"email": email, "password": password,
                                           "display_name": "Admin"},
                    headers=csrf_header(client))
        client.post("/api/v1/auth/login", json={"email": email, "password": password},
                    headers=csrf_header(client))
        return client
    return _make
```

- [ ] **Step 2: Run, FAIL (404s / missing modules)**

- [ ] **Step 3: Implement**

`backend/proxploy/services/authn.py`:
```python
import hashlib
import secrets
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from proxploy.models import SessionRow, User, utcnow

_ph = PasswordHasher()  # argon2id, library defaults (doc 08 §5)


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(hash_: str, pw: str) -> bool:
    try:
        return _ph.verify(hash_, pw)
    except VerifyMismatchError:
        return False


def _th(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def create_session(db, user: User, ip: str | None, user_agent: str | None,
                   ttl_hours: int) -> str:
    raw = secrets.token_urlsafe(32)
    db.add(SessionRow(user_id=user.id, token_hash=_th(raw), ip=ip,
                      user_agent=user_agent, last_seen_at=utcnow(),
                      expires_at=utcnow() + timedelta(hours=ttl_hours)))
    user.last_login_at = utcnow()
    db.commit()
    return raw


def resolve_session(db, raw: str) -> User | None:
    row = db.query(SessionRow).filter_by(token_hash=_th(raw)).one_or_none()
    if not row or row.revoked_at or row.expires_at < utcnow():
        return None
    user = db.get(User, row.user_id)
    return user if user and user.is_active else None


def revoke_session(db, raw: str) -> None:
    row = db.query(SessionRow).filter_by(token_hash=_th(raw)).one_or_none()
    if row and not row.revoked_at:
        row.revoked_at = utcnow()
        db.commit()
```

`backend/proxploy/middleware.py`:
```python
import hmac
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


class CSRFMiddleware(BaseHTTPMiddleware):
    """Double-submit CSRF (doc 08 §5). API-key (Authorization header) clients are exempt."""

    def __init__(self, app, cookie_name: str = "pp_csrf", secure: bool = False):
        super().__init__(app)
        self.cookie_name = cookie_name
        self.secure = secure

    async def dispatch(self, request, call_next):
        if (request.url.path.startswith("/api/") and request.method in MUTATING
                and "authorization" not in request.headers):
            cookie = request.cookies.get(self.cookie_name, "")
            header = request.headers.get("x-csrf-token", "")
            if not cookie or not hmac.compare_digest(cookie, header):
                return JSONResponse(
                    {"type": "about:blank", "title": "Forbidden", "status": 403,
                     "detail": "CSRF token missing or invalid"},
                    status_code=403, media_type="application/problem+json")
        response = await call_next(request)
        if self.cookie_name not in request.cookies:
            response.set_cookie(self.cookie_name, secrets.token_urlsafe(32),
                                samesite="lax", httponly=False, secure=self.secure)
        return response
```

`backend/proxploy/api/deps.py`:
```python
from fastapi import Depends, HTTPException, Request

from proxploy.models import Team, TeamMember, User
from proxploy.services.authn import resolve_session

ROLE_ORDER = {"viewer": 0, "operator": 1, "admin": 2, "owner": 3}


def get_db(request: Request):
    db = request.app.state.sessionmaker()
    try:
        yield db
    finally:
        db.close()


def get_current_user(request: Request, db=Depends(get_db)) -> User:
    raw = request.cookies.get(request.app.state.settings.session_cookie)
    user = resolve_session(db, raw) if raw else None
    if not user:
        raise HTTPException(401, "authentication required")
    return user


def user_role(db, user: User) -> str:
    roles = [m.role for m in db.query(TeamMember).filter_by(user_id=user.id)]
    return max(roles, key=lambda r: ROLE_ORDER.get(r, -1), default="viewer")


def require_role(min_role: str):
    """Phase-1 RBAC stub, the seam pycasbin replaces in Phase 8 (doc 08 §6)."""
    def dep(request: Request, db=Depends(get_db),
            user: User = Depends(get_current_user)) -> User:
        if ROLE_ORDER[user_role(db, user)] < ROLE_ORDER[min_role]:
            raise HTTPException(403, "insufficient role")
        return user
    return dep


def default_team(db) -> Team:
    team = db.query(Team).filter_by(slug="default").one_or_none()
    if not team:
        team = Team(name="Default", slug="default")
        db.add(team)
        db.commit()
    return team
```

`backend/proxploy/api/auth.py`:
```python
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from proxploy.api.deps import (ROLE_ORDER, default_team, get_current_user, get_db,
                               user_role)
from proxploy.models import TeamMember, User
from proxploy.services import authn
from proxploy.services.audit import write_audit

limiter = Limiter(key_func=get_remote_address)
router = APIRouter(prefix="/auth", tags=["auth"])
users_router = APIRouter(prefix="/users", tags=["users"])


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12)
    display_name: str | None = None
    role: str = "viewer"


def _user_out(db, user: User) -> dict:
    return {"id": user.id, "email": user.email, "display_name": user.display_name,
            "role": user_role(db, user)}


@router.post("/login")
@limiter.limit("10/minute")
def login(request: Request, body: LoginIn, response: Response, db=Depends(get_db)):
    settings = request.app.state.settings
    user = db.query(User).filter_by(email=body.email).one_or_none()
    ip = request.client.host if request.client else None
    if not user or not user.password_hash or not authn.verify_password(
            user.password_hash, body.password) or not user.is_active:
        write_audit(db, actor_type="user", actor_id=user.id if user else None,
                    action="auth.login", result="error", ip=ip)
        raise HTTPException(401, "invalid credentials")
    raw = authn.create_session(db, user, ip, request.headers.get("user-agent"),
                               settings.session_ttl_hours)
    write_audit(db, actor_type="user", actor_id=user.id, action="auth.login", ip=ip)
    response.set_cookie(settings.session_cookie, raw, httponly=True, samesite="lax",
                        secure=settings.cookie_secure)
    return {"ok": True, "user": _user_out(db, user)}


@router.post("/logout")
def logout(request: Request, response: Response, db=Depends(get_db),
           user: User = Depends(get_current_user)):
    settings = request.app.state.settings
    raw = request.cookies.get(settings.session_cookie)
    authn.revoke_session(db, raw)
    write_audit(db, actor_type="user", actor_id=user.id, action="auth.logout")
    response.delete_cookie(settings.session_cookie)
    return {"ok": True}


@router.get("/me")
def me(db=Depends(get_db), user: User = Depends(get_current_user)):
    return _user_out(db, user)


@users_router.post("", status_code=201)
def create_user(request: Request, body: UserIn, db=Depends(get_db)):
    first_run = db.query(User).count() == 0
    if first_run:
        role = "owner"  # doc 08 §8: forced owner-account creation on first visit
        actor_id = None
    else:
        raw = request.cookies.get(request.app.state.settings.session_cookie)
        actor = authn.resolve_session(db, raw) if raw else None
        if not actor:
            raise HTTPException(401, "authentication required")
        actor_role = user_role(db, actor)
        if ROLE_ORDER[actor_role] < ROLE_ORDER["admin"]:
            raise HTTPException(403, "insufficient role")
        if body.role == "owner" and actor_role != "owner":
            raise HTTPException(403, "only an owner may grant owner")
        role = body.role
        actor_id = actor.id
    if body.role not in ROLE_ORDER:
        raise HTTPException(422, "unknown role")
    if db.query(User).filter_by(email=body.email).one_or_none():
        raise HTTPException(409, "email already exists")
    user = User(email=body.email, display_name=body.display_name,
                password_hash=authn.hash_password(body.password))
    db.add(user)
    db.commit()
    db.add(TeamMember(team_id=default_team(db).id, user_id=user.id, role=role))
    db.commit()
    write_audit(db, actor_type="user", actor_id=actor_id, action="user.create",
                target_type="user", target_id=user.id, params={"email": body.email,
                "role": role})
    return _user_out(db, user)
```

Wire up in `backend/proxploy/api/__init__.py`:
```python
from fastapi import APIRouter

from proxploy.api import auth, meta

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(meta.router)
api_router.include_router(auth.router)
api_router.include_router(auth.users_router)
```

In `main.py` (inside `create_app`, after `app = FastAPI(...)`):
```python
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded

    from proxploy.api.auth import limiter
    from proxploy.middleware import CSRFMiddleware

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(CSRFMiddleware, cookie_name=settings.csrf_cookie,
                       secure=settings.cookie_secure)
```
Note: slowapi's limiter is module-level state shared across app instances; add
`limiter.reset()` at the top of the `client` fixture in conftest so tests stay
independent:
```python
    from proxploy.api.auth import limiter
    limiter.reset()
```
`EmailStr` needs `email-validator`, add `"email-validator>=2.0"` to pyproject dependencies and `pip install -e '.[dev]'` again.

- [ ] **Step 4: Run tests, PASS** (whole suite: `.venv/bin/python -m pytest tests/ -q`)
- [ ] **Step 5: Commit**, `git add -A && git commit -m "feat(backend): local auth, argon2, DB sessions, CSRF, per-IP rate limit, first-run owner bootstrap, RBAC stub"`

---

### Task 6: Audit read endpoint + login-audit wiring proof

Doc refs: 05 (`GET /api/v1/audit`), 10 Phase 1 DoD ("every subsequent route template already runs through auth, RBAC stub, audit").

**Files:**
- Create: `backend/proxploy/api/audit.py`
- Modify: `backend/proxploy/api/__init__.py`
- Test: `backend/tests/test_audit_api.py`

**Interfaces:**
- Produces: `GET /api/v1/audit?action=&actor=&from=&to=&page=&per_page=` (admin+), newest first, `X-Total-Count` header. No POST/PATCH/DELETE exist (doc 05).

- [ ] **Step 1: Write the failing test**

`backend/tests/test_audit_api.py`:
```python
def test_audit_requires_admin(client, csrf_header):
    assert client.get("/api/v1/audit").status_code == 401


def test_audit_lists_login_events(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    r = client.get("/api/v1/audit", params={"action": "auth.login"})
    assert r.status_code == 200
    events = r.json()
    assert any(e["action"] == "auth.login" and e["result"] == "ok" for e in events)
    assert "X-Total-Count" in r.headers
    # user.create was audited too (wiring proof for state-changing routes)
    r2 = client.get("/api/v1/audit", params={"action": "user.create"})
    assert len(r2.json()) == 1
```

- [ ] **Step 2: Run, FAIL (404)**

- [ ] **Step 3: Implement**

`backend/proxploy/api/audit.py`:
```python
from datetime import datetime

from fastapi import APIRouter, Depends, Response

from proxploy.api.deps import get_db, require_role
from proxploy.models import AuditEvent

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", dependencies=[Depends(require_role("admin"))])
def list_audit(response: Response, db=Depends(get_db), action: str | None = None,
               actor: int | None = None, from_: datetime | None = None,
               to: datetime | None = None, page: int = 1, per_page: int = 50):
    q = db.query(AuditEvent)
    if action:
        q = q.filter(AuditEvent.action == action)
    if actor is not None:
        q = q.filter(AuditEvent.actor_id == actor)
    if from_:
        q = q.filter(AuditEvent.ts >= from_)
    if to:
        q = q.filter(AuditEvent.ts <= to)
    response.headers["X-Total-Count"] = str(q.count())
    rows = (q.order_by(AuditEvent.ts.desc(), AuditEvent.id.desc())
             .offset((page - 1) * per_page).limit(per_page))
    return [{"id": r.id, "ts": r.ts.isoformat(), "actor_type": r.actor_type,
             "actor_id": r.actor_id, "action": r.action, "target_type": r.target_type,
             "target_id": r.target_id, "params": r.params, "result": r.result,
             "ip": r.ip, "job_id": r.job_id} for r in rows]
```

Add to `api/__init__.py`: `from proxploy.api import audit` … `api_router.include_router(audit.router)`.

- [ ] **Step 4: Run tests, PASS**
- [ ] **Step 5: Commit**, `git add -A && git commit -m "feat(backend): read-only audit endpoint (admin, filterable, paged)"`

---

### Task 7: Entitlement registry (all 81 flags) + client + `GET /api/v1/entitlements`

Doc refs: 01 §17 (canonical flag index, exactly 81 keys), 07 §2/§5/§6/§8 (client, verification, no-license path, failure matrix), 05 (entitlements endpoints).

**Files:**
- Create: `backend/proxploy/entitlements/__init__.py` (empty), `backend/proxploy/entitlements/registry.py`, `backend/proxploy/entitlements/keys.py`, `backend/proxploy/entitlements/client.py`, `backend/proxploy/api/entitlements.py`
- Modify: `backend/proxploy/config.py` (add `ent_extra_keys_file: Path | None = None`), `backend/proxploy/api/deps.py` (`get_entitlements`, `require_entitlement`), `backend/proxploy/api/__init__.py`, `backend/proxploy/main.py`
- Test: `backend/tests/test_entitlements.py`

**Interfaces:**
- Produces (registry): `FLAG_KEYS: tuple[str...]` (exactly the 81 doc-01 §17 keys), `DEFAULT_FEATURES: dict[str, bool]` (all `True`; the dormant built-in map).
- Produces (keys): `BUNDLED_PUBLIC_KEYS: dict[str, str]` (kid → PEM; dev key pasted in Task 9), `load_public_keys(settings) -> dict[str, str]` (bundled ∪ optional JSON file at `settings.ent_extra_keys_file`; the test/dev injection seam).
- Produces (client): `TokenInvalid(Exception)`; `EntitlementStatus` dataclass (`tier, source: "builtin"|"token", expires_at, grace_until, in_grace, clock_skew`); `Entitlements(public_keys: dict[str, str])` with `.verify(token) -> dict` (EdDSA + kid set, exp NOT enforced by JWT; grace window is ours), `.apply_claims(claims)`, `.reset_builtin()`, `.load(db, secretstore)`, `.enabled(key) -> bool` (pure dict lookup, unknown → `False`), `.snapshot() -> dict`, `.status() -> EntitlementStatus`.
- Produces (deps): `get_entitlements(request) -> Entitlements` (reads `app.state.entitlements`); `require_entitlement(key)` → dependency raising 403 `{"error": "entitlement_required", "feature": key}`.
- Produces (api): `GET /api/v1/entitlements` (any authenticated user) → `{"tier": str, "features": {key: bool}, "grace": null | {"expires_at", "grace_until", "in_grace"}}`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_entitlements.py`:
```python
from datetime import timedelta


def _keypair():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    priv = Ed25519PrivateKey.generate()
    priv_pem = priv.private_bytes(serialization.Encoding.PEM,
                                  serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption()).decode()
    pub_pem = priv.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return priv_pem, pub_pem


def _token(priv_pem, *, kid="t1", features=None, exp_delta_h=72, grace_delta_d=30):
    import jwt

    from proxploy.models import utcnow

    now = utcnow()
    claims = {"sub": "lic_x", "tier": "pro",
              "features": features if features is not None else {"hosts.multi": True},
              "iat": int(now.timestamp()),
              "exp": int((now + timedelta(hours=exp_delta_h)).timestamp()),
              "grace_until": int((now + timedelta(days=grace_delta_d)).timestamp())}
    return jwt.encode(claims, priv_pem, algorithm="EdDSA", headers={"kid": kid})


def test_registry_is_exactly_81_all_on():
    from proxploy.entitlements.registry import DEFAULT_FEATURES, FLAG_KEYS

    assert len(FLAG_KEYS) == 81 and len(set(FLAG_KEYS)) == 81
    for probe in ("hosts.multi", "store.install", "jobs.engine", "ent.client",
                  "platform.error_report", "terminal.node"):
        assert probe in FLAG_KEYS
    assert DEFAULT_FEATURES == {k: True for k in FLAG_KEYS}


def test_builtin_path_unknown_key_fails_closed():
    from proxploy.entitlements.client import Entitlements

    ent = Entitlements(public_keys={})
    assert ent.enabled("hosts.multi") is True
    assert ent.enabled("not.a.flag") is False
    assert ent.status().source == "builtin"


def test_token_path_and_grace():
    from proxploy.entitlements.client import Entitlements, TokenInvalid

    priv, pub = _keypair()
    ent = Entitlements(public_keys={"t1": pub})
    ent.apply_claims(ent.verify(_token(priv, features={"hosts.multi": False,
                                                       "apps.list": True})))
    assert ent.enabled("apps.list") is True
    assert ent.enabled("hosts.multi") is False       # token is authoritative
    assert ent.enabled("store.install") is False     # unknown-to-token: fail closed

    # past exp, inside grace: still honored, flagged in status (doc 07 §8)
    ent.apply_claims(ent.verify(_token(priv, exp_delta_h=-1)))
    assert ent.status().in_grace is True

    # past grace: dead
    import pytest
    with pytest.raises(TokenInvalid):
        ent.apply_claims(ent.verify(_token(priv, exp_delta_h=-2000, grace_delta_d=-1)))

    # unknown kid rejected
    with pytest.raises(TokenInvalid):
        ent.verify(_token(priv, kid="unknown"))


def test_entitlements_endpoint(client, csrf_header, bootstrap_admin):
    assert client.get("/api/v1/entitlements").status_code == 401
    bootstrap_admin(client)
    r = client.get("/api/v1/entitlements")
    assert r.status_code == 200
    body = r.json()
    assert body["tier"] == "builtin" and body["grace"] is None
    assert len(body["features"]) == 81
    assert all(body["features"].values())
```

- [ ] **Step 2: Run, FAIL (no `proxploy.entitlements`)**

- [ ] **Step 3: Implement**

`backend/proxploy/entitlements/registry.py`: the full doc-01 §17 index, one flag per feature, all ON while dormant:
```python
"""Canonical entitlement flag registry (doc 01 §17). 81 keys, all ON while dormant.
A feature without a key does not merge (doc 07 §3); keys never change once shipped."""

FLAG_KEYS: tuple[str, ...] = (
    "hosts.onboard", "hosts.ssh_executor", "hosts.single", "hosts.multi", "hosts.manage",
    "cluster.overview", "cluster.node_detail", "cluster.activity_feed", "ui.global_search",
    "apps.list", "apps.detail", "apps.lifecycle", "apps.open_ui", "apps.logs",
    "apps.console", "apps.script_edit", "apps.graphs", "apps.adopt", "apps.reconfigure",
    "apps.uninstall",
    "store.catalog", "store.search", "store.refresh", "store.install", "store.install_log",
    "store.updates", "store.update", "store.update_all", "store.auto_update",
    "vms.list", "vms.lifecycle", "vms.console", "vms.snapshots", "vms.create",
    "vms.clone", "vms.graphs",
    "storage.view", "storage.content", "storage.manage",
    "network.view", "network.guest_config", "network.host_config",
    "backups.pbs", "backups.run", "backups.schedule", "backups.restore",
    "backups.notify", "backups.retention",
    "migrate.cross_host", "migrate.preflight",
    "metrics.collect", "metrics.history",
    "alerts.rules", "alerts.manage",
    "notify.channels", "notify.routing", "notify.inapp",
    "jobs.engine", "jobs.stream", "jobs.history", "sched.windows",
    "terminal.ct", "terminal.node",
    "auth.local", "auth.totp", "auth.oidc", "rbac.roles", "teams.rbac", "api.tokens",
    "secrets.store", "audit.log", "audit.retention",
    "ent.client", "ent.manage",
    "platform.onboarding", "platform.self_update", "platform.install", "api.rest",
    "ui.theme", "platform.settings", "platform.error_report",
)

DEFAULT_FEATURES: dict[str, bool] = {k: True for k in FLAG_KEYS}
```

`backend/proxploy/entitlements/keys.py`:
```python
"""kid-keyed set of valid Ed25519 public keys (docs 07 §4, 09). The app bundles a
SET so key rotation is an overlap window, not a flag day. Private keys never
exist in this repo."""
import json

BUNDLED_PUBLIC_KEYS: dict[str, str] = {
    # "dev-2026-07": pasted in Task 9 from proxploy-api's gen_signing_key.py output
}


def load_public_keys(settings) -> dict[str, str]:
    keys = dict(BUNDLED_PUBLIC_KEYS)
    if settings.ent_extra_keys_file and settings.ent_extra_keys_file.exists():
        keys.update(json.loads(settings.ent_extra_keys_file.read_text()))
    return keys
```

`backend/proxploy/entitlements/client.py`:
```python
"""Entitlements client (docs 00 §7, 07). OpenFeature-shaped; dormant = all-on.
Resolution: valid signed token within grace → its features claim; otherwise the
built-in default map. Unknown keys are False, fail closed (doc 07 §2)."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt

from proxploy.entitlements.registry import DEFAULT_FEATURES
from proxploy.models import EntitlementCache, utcnow

LEEWAY = timedelta(seconds=300)  # bounded clock-skew leeway (doc 07 §8)


class TokenInvalid(Exception):
    pass


def _ts(v: int) -> datetime:
    return datetime.fromtimestamp(v, tz=timezone.utc).replace(tzinfo=None)


@dataclass
class EntitlementStatus:
    tier: str
    source: str  # builtin | token
    expires_at: datetime | None = None
    grace_until: datetime | None = None
    in_grace: bool = False
    clock_skew: bool = False


class Entitlements:
    def __init__(self, public_keys: dict[str, str]):
        self._keys = public_keys
        self._features: dict[str, bool] = dict(DEFAULT_FEATURES)
        self._status = EntitlementStatus(tier="builtin", source="builtin")

    def verify(self, token: str) -> dict:
        """Signature + shape only. exp is OURS to interpret (grace window), so
        PyJWT's exp check is disabled and grace is enforced in apply_claims."""
        try:
            kid = jwt.get_unverified_header(token).get("kid")
            pem = self._keys.get(kid)
            if not pem:
                raise TokenInvalid(f"unknown signing key id {kid!r}")
            claims = jwt.decode(token, pem, algorithms=["EdDSA"],
                                options={"verify_exp": False})
        except jwt.PyJWTError as e:
            raise TokenInvalid(str(e)) from e
        for req in ("sub", "tier", "features", "iat", "exp", "grace_until"):
            if req not in claims:
                raise TokenInvalid(f"missing claim {req}")
        return claims

    def apply_claims(self, claims: dict) -> None:
        now = utcnow()
        grace_until = _ts(claims["grace_until"])
        if now > grace_until + LEEWAY:
            raise TokenInvalid("token past grace_until")
        exp = _ts(claims["exp"])
        self._features = {k: bool(v) for k, v in claims["features"].items()}
        self._status = EntitlementStatus(
            tier=claims["tier"], source="token", expires_at=exp,
            grace_until=grace_until, in_grace=now > exp,
            clock_skew=_ts(claims["iat"]) > now + LEEWAY)

    def reset_builtin(self) -> None:
        self._features = dict(DEFAULT_FEATURES)
        self._status = EntitlementStatus(tier="builtin", source="builtin")

    def load(self, db, secretstore) -> None:
        row = db.get(EntitlementCache, 1)
        if not row or not row.token:
            self.reset_builtin()
            return
        try:
            token = secretstore.decrypt(row.token.encode()).decode()
            self.apply_claims(self.verify(token))
            row.last_verified_at = utcnow()
            db.commit()
        except (TokenInvalid, Exception):
            # doc 07 §8: past grace / bad cache → free-tier floor, never a bricked install
            self.reset_builtin()

    def enabled(self, key: str) -> bool:
        return self._features.get(key, False)

    def snapshot(self) -> dict[str, bool]:
        return dict(self._features)

    def status(self) -> EntitlementStatus:
        return self._status
```

`backend/proxploy/api/entitlements.py`:
```python
from fastapi import APIRouter, Depends

from proxploy.api.deps import get_current_user, get_entitlements

router = APIRouter(prefix="/entitlements", tags=["entitlements"])


@router.get("", dependencies=[Depends(get_current_user)])
def entitlements(ent=Depends(get_entitlements)):
    st = ent.status()
    grace = None
    if st.source == "token":
        grace = {"expires_at": st.expires_at.isoformat(),
                 "grace_until": st.grace_until.isoformat(), "in_grace": st.in_grace}
    return {"tier": st.tier, "features": ent.snapshot(), "grace": grace}
```

Append to `backend/proxploy/api/deps.py`:
```python
def get_entitlements(request: Request):
    return request.app.state.entitlements


def require_entitlement(key: str):
    """Doc 07 §2 backend enforcement, stack after auth/role deps on every gated route."""
    def dep(request: Request):
        if not request.app.state.entitlements.enabled(key):
            raise HTTPException(403, {"error": "entitlement_required", "feature": key})
    return dep
```

Wire in `main.py` `create_app(...)` (before lifespan definition so state exists pre-startup):
```python
    from proxploy.entitlements.client import Entitlements
    from proxploy.entitlements.keys import load_public_keys

    app.state.entitlements = Entitlements(public_keys or load_public_keys(settings))
```
and inside the lifespan, after `app.state.sessionmaker = ...`:
```python
        with app.state.sessionmaker() as db:
            app.state.entitlements.load(db, app.state.secretstore)
```
Add `ent_extra_keys_file: Path | None = None` to `Settings`. Register the router in `api/__init__.py`: `api_router.include_router(entitlements.router)`.

- [ ] **Step 4: Run tests, PASS** (`.venv/bin/python -m pytest tests/ -q`)
- [ ] **Step 5: Commit**, `git add -A && git commit -m "feat(backend): entitlement registry (81 flags, all ON), Ed25519 client with grace window, /api/v1/entitlements"`

---

### Task 8: proxploy-api: dormant licensing resolver

Doc refs: 07 §4/§9 (endpoints, tables, signing custody), 09 (repo layout, tiers.yaml as the arming switch), 10 Phase 1 (`licenses` + `issued_tokens` created now, resolver returns "all entitled").

Repo: `~/workspace/aspyrelabs/proxploy/proxploy-api` (already `git init -b main` from Task 1).

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `proxploy_api/{__init__,config,db,main,signing,tiers}.py`, `proxploy_api/tiers.yaml`, `proxploy_api/models/__init__.py`, `proxploy_api/api/{__init__,licenses,entitlements}.py`, `proxploy_api/migrations/*` (alembic, autogenerated 0001), `scripts/gen_signing_key.py`, `scripts/create_license.py`, `tests/{conftest.py,test_licensing.py}`

**Interfaces:**
- Produces (HTTP, the doc-09 contract, verbatim paths): `POST /v1/licenses/activate` `{license_key, install_id}` → `{token, refresh_credential}` (404 unknown/revoked key; 409 already bound to a different install); `POST /v1/entitlements/refresh` `{refresh_credential}` → `{token}` (403 unknown/revoked); `POST /v1/licenses/revoke` `{refresh_credential}` → `{revoked: true}`; `GET /v1/health` → `{status: "ok"}`.
- Produces (signing): `sign_token(*, private_pem: str, kid: str, license_id: str, tier: str, features: dict, ttl_hours=72, grace_days=30) -> tuple[str, dict]` (returns JWT + its claims).
- Produces (tiers): `resolve_features(tier: str, tiers_path: Path) -> dict[str, bool]`; dormant: every tier → all 81 keys `True` (`tiers.yaml` is the arming switch; editing it later is config, never refactor).
- Produces (scripts): `gen_signing_key.py --kid dev-2026-07` writes `var/signing/<kid>.key` (0400) and prints the public PEM; `create_license.py --tier pro` inserts a license row and prints the key.

- [ ] **Step 1: Write the failing test**

`tests/conftest.py`:
```python
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PROXPLOY_API_DB_URL", f"sqlite:///{tmp_path}/api.db")
    key = tmp_path / "sign.key"
    subprocess.run([sys.executable, str(REPO / "scripts/gen_signing_key.py"),
                    "--kid", "test-kid", "--out", str(key)], check=True)
    monkeypatch.setenv("PROXPLOY_API_SIGNING_KEY_FILE", str(key))
    monkeypatch.setenv("PROXPLOY_API_KID", "test-kid")
    from proxploy_api.config import get_settings
    get_settings.cache_clear()
    from proxploy_api.main import create_app
    with TestClient(create_app()) as c:
        yield c
    get_settings.cache_clear()


@pytest.fixture
def license_key(tmp_path):
    out = subprocess.run(
        [sys.executable, str(REPO / "scripts/create_license.py"), "--tier", "pro",
         "--db-url", f"sqlite:///{tmp_path}/api.db"],
        check=True, capture_output=True, text=True)
    return out.stdout.strip()
```

`tests/test_licensing.py`:
```python
import jwt


def _pub_pem(client):
    return client.app.state.public_pem


def test_health(client):
    assert client.get("/v1/health").json() == {"status": "ok"}


def test_activate_refresh_revoke_cycle(client, license_key):
    r = client.post("/v1/licenses/activate",
                    json={"license_key": license_key, "install_id": "inst-1"})
    assert r.status_code == 200
    token, cred = r.json()["token"], r.json()["refresh_credential"]

    claims = jwt.decode(token, _pub_pem(client), algorithms=["EdDSA"])
    assert claims["tier"] == "pro"
    assert len(claims["features"]) == 81 and all(claims["features"].values())
    assert claims["grace_until"] > claims["exp"] > claims["iat"]
    assert jwt.get_unverified_header(token)["kid"] == "test-kid"

    # re-activate same install ok, different install 409
    assert client.post("/v1/licenses/activate", json={
        "license_key": license_key, "install_id": "inst-1"}).status_code == 200
    assert client.post("/v1/licenses/activate", json={
        "license_key": license_key, "install_id": "inst-2"}).status_code == 409

    r2 = client.post("/v1/entitlements/refresh", json={"refresh_credential": cred})
    assert r2.status_code == 200 and "token" in r2.json()

    assert client.post("/v1/licenses/revoke",
                       json={"refresh_credential": cred}).json() == {"revoked": True}
    assert client.post("/v1/entitlements/refresh",
                       json={"refresh_credential": cred}).status_code == 403


def test_unknown_license_404(client):
    assert client.post("/v1/licenses/activate", json={
        "license_key": "PPL-NOPE", "install_id": "i"}).status_code == 404
```

- [ ] **Step 2: Run, FAIL** (`cd proxploy-api && python3 -m venv .venv && .venv/bin/pip -q install -e '.[dev]'.venv/bin/python -m pytest tests/ -q`, red because nothing exists)

- [ ] **Step 3: Implement**

`pyproject.toml` (name `proxploy-api`, package `proxploy_api`, same build backend/style as Task 1): dependencies `fastapi>=0.115, uvicorn[standard]>=0.30, pydantic-settings>=2.4, sqlalchemy>=2.0, alembic>=1.13, PyJWT>=2.9, cryptography>=43, PyYAML>=6`; dev extra `pytest>=8, httpx>=0.27`. `.gitignore`: `.venv/`, `__pycache__/`, `*.egg-info/`, `data/`, `var/`, `.pytest_cache/` (; `var/` keeps the private signing key out of git, doc 09).

`proxploy_api/config.py` (env prefix `PROXPLOY_API_`, `@lru_cache get_settings()` like the app): `db_url: str = "sqlite:///./data/api.db"`, `signing_key_file: Path = Path("./var/signing/dev-2026-07.key")`, `kid: str = "dev-2026-07"`, `token_ttl_hours: int = 72`, `grace_days: int = 30`, `tiers_file: Path | None = None` (None → packaged `tiers.yaml`).

`proxploy_api/models/__init__.py` (doc 07 §4 verbatim):
```python
from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

BigPK = BigInteger().with_variant(Integer, "sqlite")


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class License(Base):
    __tablename__ = "licenses"
    id: Mapped[int] = mapped_column(primary_key=True)
    license_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    tier: Mapped[str] = mapped_column(Text, default="free", nullable=False)
    install_id: Mapped[str | None] = mapped_column(Text)
    refresh_credential_hash: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="active", nullable=False)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow,
                                                 onupdate=utcnow, nullable=False)


class IssuedToken(Base):
    __tablename__ = "issued_tokens"
    id: Mapped[int] = mapped_column(BigPK, primary_key=True)
    license_id: Mapped[int] = mapped_column(ForeignKey("licenses.id"), nullable=False)
    kid: Mapped[str] = mapped_column(Text, nullable=False)
    jti: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    grace_until: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
```

`proxploy_api/db.py`: same `make_engine/make_sessionmaker/run_migrations` shape as the app's (no WAL pragma needed; keep the FK pragma for sqlite). `alembic init proxploy_api/migrations`, same `env.py` treatment (env override `PROXPLOY_API_DB_URL`, `target_metadata = Base.metadata`), then `PROXPLOY_API_DB_URL=sqlite:///./data/scratch.db .venv/bin/alembic revision --autogenerate -m "0001 licenses + issued_tokens"` and delete the scratch DB. `grep -c create_table` expects 2.

`proxploy_api/signing.py`:
```python
"""Ed25519 signing (doc 07 §5). The private key lives in a root-only file/KMS on
Aspyre infra with an offline encrypted backup, never in this repo (doc 09)."""
import secrets
from datetime import timedelta
from pathlib import Path

import jwt

from proxploy_api.models import utcnow


def load_private_pem(path: Path) -> str:
    return path.read_text()


def sign_token(*, private_pem: str, kid: str, license_id: str, tier: str,
               features: dict, ttl_hours: int = 72, grace_days: int = 30):
    now = utcnow()
    claims = {
        "sub": license_id, "tier": tier, "features": features,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=ttl_hours)).timestamp()),
        "grace_until": int((now + timedelta(days=grace_days)).timestamp()),
        "jti": secrets.token_urlsafe(12),
    }
    return jwt.encode(claims, private_pem, algorithm="EdDSA",
                      headers={"kid": kid}), claims
```

`proxploy_api/tiers.yaml`: **the arming switch** (doc 07 §7). Dormant state: one rule, all entitled:
```yaml
# Tier → features mapping. INERT while dormant: all_entitled resolves every tier
# to every flag ON. Arming Pro later = editing this file. Never a refactor.
all_entitled: true
# The canonical 81-key registry (doc 01 §17), kept in lockstep with
# proxploy-app's entitlements/registry.py (each repo asserts count == 81):
features:
  - hosts.onboard
  - hosts.ssh_executor
  - hosts.single
  - hosts.multi
  - hosts.manage
  - cluster.overview
  - cluster.node_detail
  - cluster.activity_feed
  - ui.global_search
  - apps.list
  - apps.detail
  - apps.lifecycle
  - apps.open_ui
  - apps.logs
  - apps.console
  - apps.script_edit
  - apps.graphs
  - apps.adopt
  - apps.reconfigure
  - apps.uninstall
  - store.catalog
  - store.search
  - store.refresh
  - store.install
  - store.install_log
  - store.updates
  - store.update
  - store.update_all
  - store.auto_update
  - vms.list
  - vms.lifecycle
  - vms.console
  - vms.snapshots
  - vms.create
  - vms.clone
  - vms.graphs
  - storage.view
  - storage.content
  - storage.manage
  - network.view
  - network.guest_config
  - network.host_config
  - backups.pbs
  - backups.run
  - backups.schedule
  - backups.restore
  - backups.notify
  - backups.retention
  - migrate.cross_host
  - migrate.preflight
  - metrics.collect
  - metrics.history
  - alerts.rules
  - alerts.manage
  - notify.channels
  - notify.routing
  - notify.inapp
  - jobs.engine
  - jobs.stream
  - jobs.history
  - sched.windows
  - terminal.ct
  - terminal.node
  - auth.local
  - auth.totp
  - auth.oidc
  - rbac.roles
  - teams.rbac
  - api.tokens
  - secrets.store
  - audit.log
  - audit.retention
  - ent.client
  - ent.manage
  - platform.onboarding
  - platform.self_update
  - platform.install
  - api.rest
  - ui.theme
  - platform.settings
  - platform.error_report
tiers: {}   # filled in the day Aspyre decides to sell; ignored while all_entitled
```

`proxploy_api/tiers.py`:
```python
from pathlib import Path

import yaml

DEFAULT_PATH = Path(__file__).parent / "tiers.yaml"


def resolve_features(tier: str, tiers_path: Path | None = None) -> dict[str, bool]:
    data = yaml.safe_load((tiers_path or DEFAULT_PATH).read_text())
    if data.get("all_entitled"):
        return {k: True for k in data["features"]}
    return dict(data["tiers"].get(tier, {}))
```

`proxploy_api/api/licenses.py`:
```python
import hashlib
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from proxploy_api.models import IssuedToken, License, utcnow
from proxploy_api.signing import sign_token
from proxploy_api.tiers import resolve_features

router = APIRouter(prefix="/v1/licenses", tags=["licenses"])


def get_db(request: Request):
    db = request.app.state.sessionmaker()
    try:
        yield db
    finally:
        db.close()


def _h(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class ActivateIn(BaseModel):
    license_key: str
    install_id: str


class CredentialIn(BaseModel):
    refresh_credential: str


def mint(request: Request, db, lic: License) -> str:
    settings = request.app.state.settings
    token, claims = sign_token(
        private_pem=request.app.state.private_pem, kid=settings.kid,
        license_id=f"lic_{lic.id}", tier=lic.tier,
        features=resolve_features(lic.tier, settings.tiers_file),
        ttl_hours=settings.token_ttl_hours, grace_days=settings.grace_days)
    from datetime import datetime, timezone

    def ts(v):
        return datetime.fromtimestamp(v, tz=timezone.utc).replace(tzinfo=None)

    db.add(IssuedToken(license_id=lic.id, kid=settings.kid, jti=claims["jti"],
                       issued_at=ts(claims["iat"]), expires_at=ts(claims["exp"]),
                       grace_until=ts(claims["grace_until"])))
    db.commit()
    return token


@router.post("/activate")
def activate(request: Request, body: ActivateIn, db=Depends(get_db)):
    lic = db.query(License).filter_by(license_key=body.license_key,
                                      status="active").one_or_none()
    if not lic:
        raise HTTPException(404, "unknown or revoked license key")
    if lic.install_id and lic.install_id != body.install_id:
        raise HTTPException(409, "license already activated on another install")
    cred = secrets.token_urlsafe(32)
    lic.install_id = body.install_id
    lic.refresh_credential_hash = _h(cred)
    lic.issued_at = lic.issued_at or utcnow()
    db.commit()
    return {"token": mint(request, db, lic), "refresh_credential": cred}


@router.post("/revoke")
def revoke(body: CredentialIn, db=Depends(get_db)):
    lic = db.query(License).filter_by(
        refresh_credential_hash=_h(body.refresh_credential)).one_or_none()
    if not lic:
        raise HTTPException(403, "unknown refresh credential")
    lic.status = "revoked"
    lic.revoked_at = utcnow()
    db.commit()
    return {"revoked": True}
```

`proxploy_api/api/entitlements.py`:
```python
from fastapi import APIRouter, Depends, HTTPException, Request

from proxploy_api.api.licenses import CredentialIn, _h, get_db, mint
from proxploy_api.models import License

router = APIRouter(prefix="/v1/entitlements", tags=["entitlements"])


@router.post("/refresh")
def refresh(request: Request, body: CredentialIn, db=Depends(get_db)):
    lic = db.query(License).filter_by(
        refresh_credential_hash=_h(body.refresh_credential),
        status="active").one_or_none()
    if not lic:
        raise HTTPException(403, "unknown or revoked refresh credential")
    return {"token": mint(request, db, lic)}
```

`proxploy_api/main.py`:
```python
from contextlib import asynccontextmanager

from cryptography.hazmat.primitives import serialization
from fastapi import FastAPI

from proxploy_api.config import get_settings
from proxploy_api.db import make_engine, make_sessionmaker, run_migrations


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        run_migrations(settings)
        app.state.engine = make_engine(settings)
        app.state.sessionmaker = make_sessionmaker(app.state.engine)
        app.state.private_pem = settings.signing_key_file.read_text()
        priv = serialization.load_pem_private_key(
            app.state.private_pem.encode(), password=None)
        app.state.public_pem = priv.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        yield
        app.state.engine.dispose()

    app = FastAPI(title="proxploy-api", lifespan=lifespan)
    app.state.settings = settings

    from proxploy_api.api import entitlements, licenses
    app.include_router(licenses.router)
    app.include_router(entitlements.router)

    @app.get("/v1/health")
    def health():
        return {"status": "ok"}

    return app
```

`scripts/gen_signing_key.py`:
```python
#!/usr/bin/env python3
"""Generate the Ed25519 signing keypair. Private key → 0400 file (NEVER commit);
public PEM → stdout, to be pasted into proxploy-app entitlements/keys.py."""
import argparse
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

p = argparse.ArgumentParser()
p.add_argument("--kid", required=True)
p.add_argument("--out", default=None)
a = p.parse_args()

out = Path(a.out or f"var/signing/{a.kid}.key")
out.parent.mkdir(parents=True, exist_ok=True)
priv = Ed25519PrivateKey.generate()
out.touch(mode=0o600)
out.write_bytes(priv.private_bytes(serialization.Encoding.PEM,
                                   serialization.PrivateFormat.PKCS8,
                                   serialization.NoEncryption()))
out.chmod(0o400)
print(priv.public_key().public_bytes(
    serialization.Encoding.PEM,
    serialization.PublicFormat.SubjectPublicKeyInfo).decode())
```

`scripts/create_license.py`:
```python
#!/usr/bin/env python3
"""Insert a license row (dev/support tool; there is no sales flow while dormant)."""
import argparse
import secrets

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from proxploy_api.config import get_settings
from proxploy_api.db import run_migrations
from proxploy_api.models import License

p = argparse.ArgumentParser()
p.add_argument("--tier", default="pro")
p.add_argument("--db-url", default=None)
a = p.parse_args()

settings = get_settings()
if a.db_url:
    settings = settings.model_copy(update={"db_url": a.db_url})
run_migrations(settings)
key = "PPL-" + "-".join(secrets.token_hex(2).upper() for _ in range(4))
with Session(create_engine(settings.db_url)) as db:
    db.add(License(license_key=key, tier=a.tier))
    db.commit()
print(key)
```

- [ ] **Step 4: Run tests, PASS** (`.venv/bin/python -m pytest tests/ -q` in proxploy-api)
- [ ] **Step 5: Commit (proxploy-api repo)**, `git add -A && git commit -m "feat: dormant licensing resolver, activate/refresh/revoke, Ed25519 signing, licenses+issued_tokens, tiers.yaml arming switch"`

---

### Task 9: app↔api contract fixture + contract tests + license activation path + background refresh

Doc refs: 09 §SHARED CONTRACT ("a contract test in each repo asserting its serialization matches a shared static fixture, fails loudly on drift"), 07 §5 (lifecycle), 10 Phase 1 (test-infrastructure deliverable (c); dormant-api-signed token verified by `Entitlements.enabled()`, the DoD line).

**Files:**
- Create (BOTH repos, byte-identical): `proxploy-app/backend/tests/contract/entitlement_token.fixture.json` and `proxploy-api/tests/contract/entitlement_token.fixture.json`
- Create (app): `backend/tests/contract/test_contract.py`, `backend/proxploy/services/license_client.py`, `backend/tests/test_license_flow.py`, `backend/tests/test_e2e_entitlement.py`
- Create (api): `tests/contract/test_contract.py`
- Modify (app): `backend/proxploy/entitlements/keys.py` (paste dev public key), `backend/proxploy/api/entitlements.py` (license endpoints), `backend/proxploy/main.py` (refresh task), `backend/proxploy/api/deps.py` (no change; uses `require_role("owner")`)

**Interfaces:**
- Fixture shape: `{"kid": "test-fixture-1", "claims": {sub, tier, features, iat, exp, grace_until}, "private_key_pem": "...", "public_key_pem": "..."}`. The keypair is **TEST-ONLY** (committed on purpose so both repos share one fixture; it never signs anything outside tests).
- Produces (app, services.license_client): `LicenseClient(base_url: str)` with `.activate(license_key: str, install_id: str) -> dict {token, refresh_credential}` and `.refresh(refresh_credential: str) -> dict {token}` (httpx, 10 s timeout, raises `LicenseApiError` on non-2xx). Injected via the existing `create_app(license_client=...)` kwarg; default built from `settings.api_base_url`.
- Produces (app, api.entitlements): `POST /api/v1/entitlements/license` `{license_key}` (owner) → activates against proxploy-api, stores token (SecretStore-encrypted) + claims into `entitlement_cache` row 1, stores `license.refresh_credential.enc` + `license.install_id` in `settings` table, reloads the in-memory client, audits `entitlement.license.set`; `DELETE .../license` (owner) → clears row + settings keys, back to builtin, audits; `POST .../refresh` (owner) → forced refresh via the same store-and-reload helper `apply_new_token(app, db, token)`.
- Produces (app, main): background task `entitlement_refresh_loop` started in lifespan **only when** a refresh credential exists (doc 07 §6: unlicensed = zero network calls, the job is not even registered); retries with jittered backoff, refreshes at ~half the exp window.

- [ ] **Step 1: Write the shared fixture (both repos, identical bytes)**

`tests/contract/entitlement_token.fixture.json` (this exact content in **both** repos, the claims sample is doc 07 §9's table rendered concrete; the keypair was generated once for this plan and is test-only):
```json
{
  "_comment": "Shared app<->api entitlement-token contract fixture (doc 09). TEST-ONLY keypair - never used outside contract tests. Do not edit without amending docs/09 in proxploy-app and updating BOTH repos in the same change.",
  "kid": "test-fixture-1",
  "claims": {
    "sub": "lic_01HTESTFIXTURE",
    "tier": "pro",
    "features": {"hosts.multi": true, "store.install": true, "auth.oidc": false},
    "iat": 1690000000,
    "exp": 1690259200,
    "grace_until": 1692592000
  },
  "private_key_pem": "-----BEGIN PRIVATE KEY-----\nMC4CAQAwBQYDK2VwBCIEIFneR1tFGj+1+w3hwJLWPU6e01fJVoQtS/qszF4UPjK5\n-----END PRIVATE KEY-----\n",
  "public_key_pem": "-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEAwGxpY83XmGduLOnfz/4EG3SrK2leHuTQ0c6z8nDT/tM=\n-----END PUBLIC KEY-----\n"
}
```

- [ ] **Step 2: Write the failing contract tests**

App side, `backend/tests/contract/test_contract.py`:
```python
"""app-side entitlement contract test (doc 09): the app must deserialize a token
built from the shared fixture exactly. Fails loudly on drift, not at runtime."""
import json
from pathlib import Path

import jwt

FIXTURE = json.loads((Path(__file__).parent / "entitlement_token.fixture.json").read_text())


def test_app_verifies_fixture_token_and_claims_roundtrip():
    from proxploy.entitlements.client import Entitlements

    token = jwt.encode(FIXTURE["claims"], FIXTURE["private_key_pem"],
                       algorithm="EdDSA", headers={"kid": FIXTURE["kid"]})
    ent = Entitlements(public_keys={FIXTURE["kid"]: FIXTURE["public_key_pem"]})
    claims = ent.verify(token)
    assert claims == FIXTURE["claims"]
    assert jwt.get_unverified_header(token) == {"alg": "EdDSA", "typ": "JWT",
                                                "kid": FIXTURE["kid"]}


def test_fixture_features_keys_are_known_flags():
    from proxploy.entitlements.registry import FLAG_KEYS

    assert set(FIXTURE["claims"]["features"]) <= set(FLAG_KEYS)
```

API side, `proxploy-api/tests/contract/test_contract.py`:
```python
"""api-side entitlement contract test (doc 09): sign_token must emit exactly the
fixture's claim set (plus jti) with the EdDSA/kid header the app expects."""
import json
from pathlib import Path

import jwt

FIXTURE = json.loads((Path(__file__).parent / "entitlement_token.fixture.json").read_text())


def test_api_signs_tokens_matching_fixture_shape():
    from proxploy_api.signing import sign_token

    token, claims = sign_token(
        private_pem=FIXTURE["private_key_pem"], kid=FIXTURE["kid"],
        license_id=FIXTURE["claims"]["sub"], tier=FIXTURE["claims"]["tier"],
        features=FIXTURE["claims"]["features"])
    decoded = jwt.decode(token, FIXTURE["public_key_pem"], algorithms=["EdDSA"],
                         options={"verify_exp": False})
    assert set(decoded) == set(FIXTURE["claims"]) | {"jti"}
    for k in ("sub", "tier", "features"):
        assert decoded[k] == FIXTURE["claims"][k]
    assert isinstance(decoded["iat"], int) and isinstance(decoded["exp"], int)
    assert decoded["grace_until"] > decoded["exp"] > decoded["iat"]
    assert jwt.get_unverified_header(token)["kid"] == FIXTURE["kid"]
```

Run both, Expected: app test FAILS only if Task 7 drifted (it should pass immediately; that is fine, the fixture is the regression tripwire, note it and move on); api test PASSES likewise. If either fails, the (de)serialization drifted from doc 09; fix the code, never the fixture.

- [ ] **Step 3: Generate + bundle the dev signing key**

```bash
cd ~/workspace/aspyrelabs/proxploy/proxploy-api
.venv/bin/python scripts/gen_signing_key.py --kid dev-2026-07   # writes var/signing/dev-2026-07.key
```
Paste the printed public PEM into `proxploy-app/backend/proxploy/entitlements/keys.py`:
```python
BUNDLED_PUBLIC_KEYS: dict[str, str] = {
    "dev-2026-07": """-----BEGIN PUBLIC KEY-----
<the printed base64 line>
-----END PUBLIC KEY-----
""",
}
```

- [ ] **Step 4: Write the failing license-flow test (app)**

`backend/tests/test_license_flow.py`:
```python
import json


class StubLicenseClient:
    def __init__(self, fixture_path):
        fx = json.loads(fixture_path.read_text())
        self._fx = fx
        self.activations = []

    def _mint(self):
        import jwt

        from proxploy.models import utcnow
        claims = dict(self._fx["claims"])
        now = int(utcnow().timestamp())
        claims.update(iat=now, exp=now + 72 * 3600, grace_until=now + 30 * 86400)
        return jwt.encode(claims, self._fx["private_key_pem"], algorithm="EdDSA",
                          headers={"kid": self._fx["kid"]})

    def activate(self, license_key, install_id):
        self.activations.append((license_key, install_id))
        return {"token": self._mint(), "refresh_credential": "cred-123"}

    def refresh(self, refresh_credential):
        assert refresh_credential == "cred-123"
        return {"token": self._mint()}


def test_license_set_refresh_remove(tmp_path, csrf_header, bootstrap_admin):
    from pathlib import Path

    from fastapi.testclient import TestClient

    from proxploy.api.auth import limiter
    from proxploy.config import Settings
    from proxploy.main import create_app

    fx_path = Path(__file__).parent / "contract" / "entitlement_token.fixture.json"
    fx = json.loads(fx_path.read_text())
    stub = StubLicenseClient(fx_path)
    limiter.reset()
    s = Settings(db_url=f"sqlite:///{tmp_path}/lic.db", data_dir=tmp_path,
                 master_key_file=tmp_path / "master.key")
    app = create_app(s, public_keys={fx["kid"]: fx["public_key_pem"]},
                     license_client=stub)
    with TestClient(app) as client:
        bootstrap_admin(client)

        r = client.post("/api/v1/entitlements/license",
                        json={"license_key": "PPL-TEST"}, headers=csrf_header(client))
        assert r.status_code == 200
        assert stub.activations[0][0] == "PPL-TEST"

        ent = client.get("/api/v1/entitlements").json()
        assert ent["tier"] == "pro" and ent["grace"]["in_grace"] is False
        assert ent["features"]["auth.oidc"] is False   # token map is authoritative

        assert client.post("/api/v1/entitlements/refresh",
                           headers=csrf_header(client)).status_code == 200

        assert client.delete("/api/v1/entitlements/license",
                             headers=csrf_header(client)).status_code == 200
        ent = client.get("/api/v1/entitlements").json()
        assert ent["tier"] == "builtin" and len(ent["features"]) == 81
```

Run, FAIL (404 on the license endpoints).

- [ ] **Step 5: Implement license client + endpoints + refresh loop**

`backend/proxploy/services/license_client.py`:
```python
"""The ONLY app→Aspyre call path (doc 02 §8): activate / refresh / (revoke later).
Never called unless a license is configured."""
import httpx


class LicenseApiError(RuntimeError):
    pass


class LicenseClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def _post(self, path: str, payload: dict) -> dict:
        try:
            r = httpx.post(f"{self.base_url}{path}", json=payload, timeout=10)
        except httpx.HTTPError as e:
            raise LicenseApiError(str(e)) from e
        if r.status_code >= 400:
            raise LicenseApiError(f"{path} -> {r.status_code}: {r.text[:200]}")
        return r.json()

    def activate(self, license_key: str, install_id: str) -> dict:
        return self._post("/v1/licenses/activate",
                          {"license_key": license_key, "install_id": install_id})

    def refresh(self, refresh_credential: str) -> dict:
        return self._post("/v1/entitlements/refresh",
                          {"refresh_credential": refresh_credential})
```

Extend `backend/proxploy/api/entitlements.py` (imports: `uuid`, `Request`, `HTTPException`, `require_role`, `get_db`, models `AppSetting, EntitlementCache`, `write_audit`, `TokenInvalid`, `datetime helpers from client`):
```python
def _setting(db, key, default=None):
    row = db.query(AppSetting).filter_by(key=key).one_or_none()
    return row.value if row else default


def _set_setting(db, key, value):
    row = db.query(AppSetting).filter_by(key=key).one_or_none()
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))
    db.commit()


def apply_new_token(request: Request, db, token: str) -> None:
    """Verify, then persist (encrypted) + reload the in-memory client."""
    from proxploy.entitlements.client import _ts

    ent = request.app.state.entitlements
    claims = ent.verify(token)
    ent.apply_claims(claims)
    ss = request.app.state.secretstore
    enc, _ = ss.encrypt(token.encode())
    row = db.get(EntitlementCache, 1)
    if not row:
        row = EntitlementCache(id=1)
        db.add(row)
    row.token = enc.decode()
    row.tier = claims["tier"]
    row.features = claims["features"]
    row.issued_at = _ts(claims["iat"])
    row.expires_at = _ts(claims["exp"])
    row.grace_until = _ts(claims["grace_until"])
    row.fetched_at = row.last_verified_at = utcnow()
    db.commit()


@router.post("/license")
def set_license(request: Request, body: LicenseIn, db=Depends(get_db),
                user=Depends(require_role("owner"))):
    install_id = _setting(db, "license.install_id")
    if not install_id:
        install_id = str(uuid.uuid4())
        _set_setting(db, "license.install_id", install_id)
    lc = request.app.state.license_client
    try:
        out = lc.activate(body.license_key, install_id)
    except LicenseApiError as e:
        write_audit(db, actor_type="user", actor_id=user.id,
                    action="entitlement.license.set", result="error")
        raise HTTPException(502, f"licensing service: {e}")
    apply_new_token(request, db, out["token"])
    enc, _ = request.app.state.secretstore.encrypt(out["refresh_credential"].encode())
    _set_setting(db, "license.refresh_credential.enc", enc.decode())
    write_audit(db, actor_type="user", actor_id=user.id,
                action="entitlement.license.set")
    return {"ok": True, "tier": request.app.state.entitlements.status().tier}


@router.post("/refresh")
def force_refresh(request: Request, db=Depends(get_db),
                  user=Depends(require_role("owner"))):
    enc = _setting(db, "license.refresh_credential.enc")
    if not enc:
        raise HTTPException(409, "no license configured")
    cred = request.app.state.secretstore.decrypt(enc.encode()).decode()
    try:
        out = request.app.state.license_client.refresh(cred)
    except LicenseApiError as e:
        raise HTTPException(502, f"licensing service: {e}")
    apply_new_token(request, db, out["token"])
    write_audit(db, actor_type="user", actor_id=user.id, action="entitlement.refresh")
    return {"ok": True}


@router.delete("/license")
def remove_license(request: Request, db=Depends(get_db),
                   user=Depends(require_role("owner"))):
    row = db.get(EntitlementCache, 1)
    if row:
        row.token = None
        row.tier = "builtin"
        row.features = {}
    for key in ("license.refresh_credential.enc", "license.install_id"):
        db.query(AppSetting).filter_by(key=key).delete()
    db.commit()
    request.app.state.entitlements.reset_builtin()
    write_audit(db, actor_type="user", actor_id=user.id,
                action="entitlement.license.remove")
    return {"ok": True}
```
(`class LicenseIn(BaseModel): license_key: str`. Export `_ts` from `entitlements/client.py`, it already exists there.)

In `main.py` `create_app`: `app.state.license_client = license_client or LicenseClient(settings.api_base_url)`. In the lifespan, after entitlements load; start the background refresh **only when licensed** (doc 07 §6):
```python
        import asyncio

        async def _refresh_loop():
            import random

            from proxploy.api.entitlements import apply_new_token  # helper reuse
            while True:
                await asyncio.sleep(3600 * 24 + random.uniform(0, 600))  # ~half of 72h exp is fine at Phase 1 granularity; jittered
                try:
                    with app.state.sessionmaker() as db:
                        row = (db.query(AppSetting)
                               .filter_by(key="license.refresh_credential.enc").one_or_none())
                        if not row:
                            return
                        cred = app.state.secretstore.decrypt(row.value.encode()).decode()
                        out = app.state.license_client.refresh(cred)
                        # apply via a fake-request shim: the helper only needs .app
                        class _Req:  # noqa: N801, minimal shim
                            pass
                        req = _Req(); req.app = app
                        apply_new_token(req, db, out["token"])
                except Exception:
                    continue  # doc 07 §8: transient failure = keep serving, retry later

        with app.state.sessionmaker() as db:
            licensed = (db.query(AppSetting)
                        .filter_by(key="license.refresh_credential.enc").one_or_none())
        refresh_task = asyncio.create_task(_refresh_loop()) if licensed else None
        yield
        if refresh_task:
            refresh_task.cancel()
```
(Move the existing bare `yield` accordingly; `from proxploy.models import AppSetting` in main.py.)

- [ ] **Step 6: Run tests, PASS** (`pytest tests/ -q` in the app; `pytest tests/ -q` in proxploy-api)

- [ ] **Step 7: e2e, the DoD line, real dormant api process**

`backend/tests/test_e2e_entitlement.py`:
```python
"""DoD (doc 10 Phase 1): Entitlements.enabled() verifies a token signed by the
dormant proxploy-api, and falls back to the built-in map offline."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

API_REPO = Path(os.environ.get("PROXPLOY_API_REPO",
                Path(__file__).resolve().parents[3] / "proxploy-api"))

pytestmark = pytest.mark.e2e


@pytest.mark.skipif(not API_REPO.exists(), reason="proxploy-api checkout not found")
def test_roundtrip_against_real_dormant_api(tmp_path, csrf_header, bootstrap_admin):
    py = API_REPO / ".venv/bin/python"
    env = os.environ | {
        "PROXPLOY_API_DB_URL": f"sqlite:///{tmp_path}/api.db",
        "PROXPLOY_API_SIGNING_KEY_FILE": str(tmp_path / "e2e.key"),
        "PROXPLOY_API_KID": "e2e-kid",
    }
    pub_pem = subprocess.run(
        [py, str(API_REPO / "scripts/gen_signing_key.py"), "--kid", "e2e-kid",
         "--out", str(tmp_path / "e2e.key")],
        check=True, capture_output=True, text=True).stdout
    license_key = subprocess.run(
        [py, str(API_REPO / "scripts/create_license.py"), "--tier", "pro",
         "--db-url", env["PROXPLOY_API_DB_URL"]],
        check=True, capture_output=True, text=True, env=env).stdout.strip()

    proc = subprocess.Popen(
        [py, "-m", "uvicorn", "--factory", "proxploy_api.main:create_app",
         "--port", "8899"], cwd=API_REPO, env=env)
    try:
        for _ in range(50):
            try:
                if httpx.get("http://127.0.0.1:8899/v1/health").status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.2)
        else:
            pytest.fail("proxploy-api did not start")

        keys_file = tmp_path / "keys.json"
        keys_file.write_text(json.dumps({"e2e-kid": pub_pem}))

        from fastapi.testclient import TestClient

        from proxploy.api.auth import limiter
        from proxploy.config import Settings
        from proxploy.main import create_app

        limiter.reset()
        s = Settings(db_url=f"sqlite:///{tmp_path}/app.db", data_dir=tmp_path,
                     master_key_file=tmp_path / "master.key",
                     api_base_url="http://127.0.0.1:8899",
                     ent_extra_keys_file=keys_file)
        with TestClient(create_app(s)) as client:
            bootstrap_admin(client)
            r = client.post("/api/v1/entitlements/license",
                            json={"license_key": license_key},
                            headers=csrf_header(client))
            assert r.status_code == 200 and r.json()["tier"] == "pro"
            ent = client.get("/api/v1/entitlements").json()
            assert ent["tier"] == "pro" and len(ent["features"]) == 81
            assert all(ent["features"].values())  # dormant api: all entitled
    finally:
        proc.terminate()
        proc.wait(timeout=10)
```
Add `"e2e: cross-repo roundtrip against a local proxploy-api"` to the pytest markers list in pyproject. Run: `.venv/bin/python -m pytest tests/test_e2e_entitlement.py -q`, Expected: PASS (proxploy-api venv exists from Task 8).

- [ ] **Step 8: Commit (both repos)**

```bash
cd ~/workspace/aspyrelabs/proxploy/proxploy-api && git add -A && git commit -m "test: shared entitlement-token contract fixture + api-side contract test"
cd ~/workspace/aspyrelabs/proxploy/proxploy-app && git add -A && git commit -m "feat(backend): license activate/refresh/remove via proxploy-api, contract test, bundled dev pubkey, background refresh, e2e roundtrip"
```

---

### Task 10: Proxmox client layer + fake PVE test infrastructure

Doc refs: 02 §4 (one client layer, PVE-8-vs-9 branching isolated here), 03 (proxmoxer link), 10 Phase 1 test infrastructure (a) fake/fixture layer, (b) disposable-PVE integration path, 11 §7 (version drift).

**Files:**
- Create: `backend/proxploy/services/proxmox.py`, `backend/tests/fakes/__init__.py` (empty), `backend/tests/fakes/pve.py`, `backend/tests/fixtures/pve/version_pve8.json`, `backend/tests/fixtures/pve/version_pve9.json`, `backend/tests/fixtures/pve/permissions_full.json`, `backend/tests/test_proxmox.py`, `backend/tests/test_pve_integration.py`

**Interfaces:**
- Produces: `ProxmoxError(RuntimeError)`; `parse_token_id("user@realm!name") -> tuple[str, str]` (user-with-realm, token name; raises `ProxmoxError` on bad shape); `ProxmoxClient(address, token_id, token_secret, verify_tls=True, tls_fingerprint=None, factory=None)` with `.version() -> {"version": str, "release": str}` and `.permissions() -> dict` (both raise `ProxmoxError` on any transport/auth failure); `default_factory(**kw)` (real proxmoxer); `tls_fingerprint_sha256(host, port=8006) -> str` ("AA:BB:…" of the presented cert; used when `verify_tls=False` with a pinned fingerprint, doc 08 §2).
- Produces (fakes): `FakePVE(version={...}, permissions={...}, fail=False)` mimicking the proxmoxer attribute surface used (`api.version.get()`, `api.access.permissions.get()`); `make_fake_factory(fake) -> factory` matching the `factory` kwarg; recorded JSON fixtures with a docstring explaining how to re-record from a live PVE (`pvesh get /version --output-format json`).
- The app factory kwarg `proxmox_factory` (accepted since Task 1) reaches this layer: `create_app(proxmox_factory=...)` → `app.state.proxmox_factory` → hosts routes (Task 11) build `ProxmoxClient(..., factory=app.state.proxmox_factory)`.

- [ ] **Step 1: Write the failing test**

`backend/tests/fixtures/pve/version_pve8.json`: `{"version": "8.4.1", "release": "8.4", "repoid": "recorded-fixture"}`
`backend/tests/fixtures/pve/version_pve9.json`: `{"version": "9.0.3", "release": "9.0", "repoid": "recorded-fixture"}`
`backend/tests/fixtures/pve/permissions_full.json`: `{"/": {"Sys.Audit": 1, "VM.Audit": 1, "Datastore.Audit": 1}}`

`backend/tests/test_proxmox.py`:
```python
import json
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures" / "pve"


def test_parse_token_id():
    from proxploy.services.proxmox import ProxmoxError, parse_token_id

    assert parse_token_id("proxploy@pve!monitoring") == ("proxploy@pve", "monitoring")
    with pytest.raises(ProxmoxError):
        parse_token_id("no-bang-here")


@pytest.mark.parametrize("fixture", ["version_pve8.json", "version_pve9.json"])
def test_version_via_fake(fixture):
    from proxploy.services.proxmox import ProxmoxClient
    from tests.fakes.pve import FakePVE, make_fake_factory

    fake = FakePVE(version=json.loads((FIX / fixture).read_text()),
                   permissions=json.loads((FIX / "permissions_full.json").read_text()))
    c = ProxmoxClient("https://pve.local:8006", "proxploy@pve!mon", "s3cret",
                      factory=make_fake_factory(fake))
    v = c.version()
    assert v["release"] in ("8.4", "9.0")
    assert c.permissions()["/"]["Sys.Audit"] == 1
    assert fake.kwargs["user"] == "proxploy@pve"
    assert fake.kwargs["token_name"] == "mon"
    assert fake.kwargs["token_value"] == "s3cret"


def test_unreachable_raises_proxmox_error():
    from proxploy.services.proxmox import ProxmoxClient, ProxmoxError
    from tests.fakes.pve import FakePVE, make_fake_factory

    c = ProxmoxClient("https://pve.local:8006", "a@pve!b", "x",
                      factory=make_fake_factory(FakePVE(fail=True)))
    with pytest.raises(ProxmoxError):
        c.version()
```

`backend/tests/test_pve_integration.py` (the wired disposable-PVE path, runs only with env; CI matrix in Task 16):
```python
import os

import pytest

pytestmark = pytest.mark.pve_integration

REQUIRED = ("PROXPLOY_TEST_PVE_URL", "PROXPLOY_TEST_PVE_TOKEN_ID",
            "PROXPLOY_TEST_PVE_TOKEN_SECRET")


@pytest.mark.skipif(not all(os.environ.get(k) for k in REQUIRED),
                    reason="disposable PVE env not configured")
def test_live_version_and_permissions():
    from proxploy.services.proxmox import ProxmoxClient

    c = ProxmoxClient(os.environ["PROXPLOY_TEST_PVE_URL"],
                      os.environ["PROXPLOY_TEST_PVE_TOKEN_ID"],
                      os.environ["PROXPLOY_TEST_PVE_TOKEN_SECRET"],
                      verify_tls=os.environ.get("PROXPLOY_TEST_PVE_VERIFY", "0") == "1")
    v = c.version()
    assert v["release"].split(".")[0] in ("8", "9")  # supported window (doc 11 §7)
    assert isinstance(c.permissions(), dict)
```

- [ ] **Step 2: Run, FAIL (no `proxploy.services.proxmox`)**, also add an empty `backend/tests/__init__.py` and `backend/tests/fakes/__init__.py` so `from tests.fakes...` imports resolve.

- [ ] **Step 3: Implement**

`backend/tests/fakes/pve.py`:
```python
"""Fake PVE responder (doc 10 Phase 1 test infra (a)): mimics the exact proxmoxer
attribute surface Proxploy uses, fed by recorded fixtures under tests/fixtures/pve/.
Re-record on a live node with: pvesh get /version --output-format json
                               pvesh get /access/permissions --output-format json"""


class _Leaf:
    def __init__(self, value, fail):
        self._value, self._fail = value, fail

    def get(self):
        if self._fail:
            raise ConnectionError("fake PVE unreachable")
        return self._value


class _Access:
    def __init__(self, permissions, fail):
        self.permissions = _Leaf(permissions, fail)


class FakePVE:
    def __init__(self, version=None, permissions=None, fail=False):
        self.version = _Leaf(version or {"version": "8.4.1", "release": "8.4"}, fail)
        self.access = _Access(permissions or {}, fail)
        self.kwargs = {}


def make_fake_factory(fake: FakePVE):
    def factory(**kwargs):
        if fake.version._fail:
            raise ConnectionError("fake PVE unreachable")
        fake.kwargs = kwargs
        return fake
    return factory
```

`backend/proxploy/services/proxmox.py`:
```python
"""The ONE Proxmox client layer (docs 02 §4, 11 §7). Every proxmoxer call and every
PVE-8-vs-9 behavioural branch lives here, never in routers, pollers, or jobs.
(No version branches exist yet; when PVE 9 diverges, branch on self.version()["release"]
inside this module only.) Scoped API tokens, never root@pam passwords (doc 00 §8)."""
import hashlib
import socket
import ssl
from urllib.parse import urlparse

from proxploy.models import utcnow  # noqa: F401  (used by later phases' sync paths)


class ProxmoxError(RuntimeError):
    pass


def parse_token_id(token_id: str) -> tuple[str, str]:
    user, sep, name = token_id.partition("!")
    if not sep or "@" not in user or not name:
        raise ProxmoxError(
            f"token id {token_id!r} must look like user@realm!tokenname")
    return user, name


def default_factory(**kwargs):
    from proxmoxer import ProxmoxAPI

    return ProxmoxAPI(**kwargs)


def tls_fingerprint_sha256(host: str, port: int = 8006) -> str:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # we are fetching the cert to pin it, not trusting it
    with socket.create_connection((host, port), timeout=10) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as tls:
            der = tls.getpeercert(binary_form=True)
    digest = hashlib.sha256(der).hexdigest().upper()
    return ":".join(digest[i:i + 2] for i in range(0, len(digest), 2))


class ProxmoxClient:
    def __init__(self, address: str, token_id: str, token_secret: str,
                 verify_tls: bool = True, tls_fingerprint: str | None = None,
                 factory=None):
        self.address = address
        self.token_id = token_id
        self.token_secret = token_secret
        self.verify_tls = verify_tls
        self.tls_fingerprint = tls_fingerprint
        self._factory = factory or default_factory
        self._api = None

    def _connect(self):
        if self._api is not None:
            return self._api
        url = urlparse(self.address)
        host, port = url.hostname, url.port or 8006
        if not self.verify_tls and self.tls_fingerprint:
            seen = tls_fingerprint_sha256(host, port)
            if seen != self.tls_fingerprint.upper():
                raise ProxmoxError(
                    f"TLS fingerprint mismatch: pinned {self.tls_fingerprint}, got {seen}")
        user, token_name = parse_token_id(self.token_id)
        try:
            self._api = self._factory(host=host, port=port, user=user,
                                      token_name=token_name,
                                      token_value=self.token_secret,
                                      verify_ssl=self.verify_tls)
        except Exception as e:
            raise ProxmoxError(f"cannot connect to {self.address}: {e}") from e
        return self._api

    def version(self) -> dict:
        try:
            return self._connect().version.get()
        except ProxmoxError:
            raise
        except Exception as e:
            raise ProxmoxError(f"version check failed: {e}") from e

    def permissions(self) -> dict:
        try:
            return self._connect().access.permissions.get()
        except ProxmoxError:
            raise
        except Exception as e:
            raise ProxmoxError(f"permission read failed: {e}") from e
```
(The fake factory raising in `factory(...)` exercises the connect-failure path; `FakePVE(fail=True)` leaf raising exercises call-failure, both surface as `ProxmoxError`.)

In `main.py` `create_app`: `app.state.proxmox_factory = proxmox_factory` (may be `None` → `ProxmoxClient` uses `default_factory`).

- [ ] **Step 4: Run tests, PASS** (`pytest tests/test_proxmox.py -q`; integration file reports SKIPPED without env; that is the wired-but-gated state)
- [ ] **Step 5: Commit**, `git add -A && git commit -m "feat(backend): proxmox client layer (single branching point) + fake PVE fixture infra + gated live-PVE test"`

---

### Task 11: Host onboarding: probe, create (token + optional SSH enrolment), list, test

Doc refs: 10 Phase 1 (host onboarding bullet + DoD), 08 §2 (verification), §4 (SSH key handling, explicit consent), 05 (hosts endpoints; `hosts.multi` gates the 2nd+ host), 04 (`hosts`, `host_credentials`), 06 (wizard step 3 shows public key + authorize command).

**Files:**
- Create: `backend/proxploy/services/sshkeys.py`, `backend/proxploy/api/hosts.py`
- Modify: `backend/proxploy/api/__init__.py`
- Test: `backend/tests/test_hosts.py`

**Interfaces:**
- Produces (services.sshkeys): `generate_ed25519(comment: str) -> tuple[bytes, str]`; (private key PEM/PKCS8 bytes, one-line OpenSSH public key ending in ` comment`). Library-generated via `cryptography` (doc 08 §4, never shell out to ssh-keygen). **This module does not exist for anyone but the hosts-onboarding flow and, later, `executor/`**: the private key goes straight into SecretStore.
- Produces (api.hosts):
  - `POST /api/v1/hosts/probe` (admin) `{address, token_id, token_secret, verify_tls?, tls_fingerprint?}` → `{ok, version, release}` or 502 problem; the wizard's non-persisting "Test connection".
  - `POST /api/v1/hosts` (admin; **2nd+ host additionally requires `hosts.multi`**) `{name, address, token_id, token_secret, verify_tls?, tls_fingerprint?, ssh_enroll?, ssh_consent?}` → 201 `{id, name, address, node_name, pve_version, status, ssh_public_key?, authorized_keys_line?, consent_note?}`. Connectivity check first; credentials stored only through SecretStore; `ssh_enroll` without `ssh_consent: true` → 400 with the explicit consent copy.
  - `GET /api/v1/hosts` (viewer) → list (never any credential material; `public_meta` only).
  - `GET /api/v1/hosts/{id}` (viewer) → detail + `credentials: [{kind, public_meta, last_used_at}]`.
  - `POST /api/v1/hosts/{id}/test` (admin) → re-probe, updates `status/pve_version/last_seen_at`, audited.
- **This router is the route template** the DoD names: every mutation stacks `get_current_user → require_role → require_entitlement → work → write_audit`. Copy this stacking for every state-changing route in later phases.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_hosts.py`:
```python
import json
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures" / "pve"


@pytest.fixture
def pve_client(tmp_path, csrf_header, bootstrap_admin):
    """App wired to a FakePVE via the proxmox_factory seam."""
    from fastapi.testclient import TestClient

    from proxploy.api.auth import limiter
    from proxploy.config import Settings
    from proxploy.main import create_app
    from tests.fakes.pve import FakePVE, make_fake_factory

    fake = FakePVE(version=json.loads((FIX / "version_pve8.json").read_text()),
                   permissions=json.loads((FIX / "permissions_full.json").read_text()))
    limiter.reset()
    s = Settings(db_url=f"sqlite:///{tmp_path}/h.db", data_dir=tmp_path,
                 master_key_file=tmp_path / "master.key")
    app = create_app(s, proxmox_factory=make_fake_factory(fake))
    with TestClient(app) as c:
        bootstrap_admin(c)
        yield c, fake


HOST = {"name": "pve-01", "address": "https://10.0.0.5:8006",
        "token_id": "proxploy@pve!mon", "token_secret": "s3cret"}


def test_probe(pve_client, csrf_header):
    c, _ = pve_client
    r = c.post("/api/v1/hosts/probe", json=HOST | {"name": None},
               headers=csrf_header(c))
    assert r.status_code == 200 and r.json()["release"] == "8.4"


def test_create_host_with_ssh_enrolment(pve_client, csrf_header):
    c, _ = pve_client
    r = c.post("/api/v1/hosts", json=HOST | {"ssh_enroll": True, "ssh_consent": True},
               headers=csrf_header(c))
    assert r.status_code == 201
    body = r.json()
    assert body["pve_version"] == "8.4.1" and body["status"] == "connected"
    assert body["ssh_public_key"].startswith("ssh-ed25519 ")
    assert body["authorized_keys_line"].startswith("ssh-ed25519 ")
    assert "root on" in body["consent_note"]

    # credentials at rest: encrypted, public_meta only ever exposed
    detail = c.get(f"/api/v1/hosts/{body['id']}").json()
    kinds = {cred["kind"] for cred in detail["credentials"]}
    assert kinds == {"api_token", "ssh_key"}
    assert all("encrypted_blob" not in cred for cred in detail["credentials"])
    assert any(cred["public_meta"] == "proxploy@pve!mon"
               for cred in detail["credentials"])

    # audit rows exist (route-template proof)
    audit = c.get("/api/v1/audit", params={"action": "host.create"}).json()
    assert audit and audit[0]["params"]["token_secret"] == "[redacted]"


def test_ssh_enroll_requires_explicit_consent(pve_client, csrf_header):
    c, _ = pve_client
    r = c.post("/api/v1/hosts", json=HOST | {"ssh_enroll": True},
               headers=csrf_header(c))
    assert r.status_code == 400
    assert "consent" in r.json()["detail"].lower()


def test_unreachable_host_rejected_and_audited(pve_client, csrf_header):
    c, fake = pve_client
    fake.version._fail = True
    r = c.post("/api/v1/hosts", json=HOST, headers=csrf_header(c))
    assert r.status_code == 502
    fake.version._fail = False
    audit = c.get("/api/v1/audit", params={"action": "host.create"}).json()
    assert any(e["result"] == "error" for e in audit)


def test_second_host_gated_by_hosts_multi(pve_client, csrf_header):
    c, _ = pve_client
    assert c.post("/api/v1/hosts", json=HOST,
                  headers=csrf_header(c)).status_code == 201
    # simulate an armed tier without multi-host (dormant default is ON)
    c.app.state.entitlements._features["hosts.multi"] = False
    r = c.post("/api/v1/hosts", json=HOST | {"name": "pve-02"},
               headers=csrf_header(c))
    assert r.status_code == 403 and r.json()["feature"] == "hosts.multi"
    c.app.state.entitlements._features["hosts.multi"] = True
    assert c.post("/api/v1/hosts", json=HOST | {"name": "pve-02"},
                  headers=csrf_header(c)).status_code == 201


def test_host_test_endpoint_updates_status(pve_client, csrf_header):
    c, fake = pve_client
    hid = c.post("/api/v1/hosts", json=HOST, headers=csrf_header(c)).json()["id"]
    fake.version._fail = True
    r = c.post(f"/api/v1/hosts/{hid}/test", headers=csrf_header(c))
    assert r.status_code == 200 and r.json()["status"] == "unreachable"
    fake.version._fail = False
    assert c.post(f"/api/v1/hosts/{hid}/test",
                  headers=csrf_header(c)).json()["status"] == "connected"
```

- [ ] **Step 2: Run, FAIL (404s)**

- [ ] **Step 3: Implement**

`backend/proxploy/services/sshkeys.py`:
```python
"""Dedicated executor keypair generation (doc 08 §4): library-generated ed25519,
one keypair per host enrolment, private half exists ONLY as a SecretStore blob."""
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def generate_ed25519(comment: str) -> tuple[bytes, str]:
    priv = Ed25519PrivateKey.generate()
    private_pem = priv.private_bytes(serialization.Encoding.PEM,
                                     serialization.PrivateFormat.PKCS8,
                                     serialization.NoEncryption())
    public_line = priv.public_key().public_bytes(
        serialization.Encoding.OpenSSH,
        serialization.PublicFormat.OpenSSH).decode()
    return private_pem, f"{public_line} {comment}"
```

`backend/proxploy/api/hosts.py`:
```python
"""Host onboarding. ROUTE TEMPLATE (doc 10 Phase 1 DoD): every mutation stacks
auth -> RBAC stub -> entitlement -> work -> audit. Later phases copy this shape."""
import json as jsonlib

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from proxploy.api.deps import get_db, require_role
from proxploy.models import Host, HostCredential, User, utcnow
from proxploy.services.audit import write_audit
from proxploy.services.proxmox import ProxmoxClient, ProxmoxError
from proxploy.services.sshkeys import generate_ed25519

router = APIRouter(prefix="/hosts", tags=["hosts"])

CONSENT_NOTE = ("This key gives Proxploy a root shell on the node, used only for "
                "App Store install/update/migration scripts, exactly as if you ran "
                "them yourself as root on the node. Every use is audit-logged and its "
                "full output archived. Authorize it by adding the line to "
                "/root/.ssh/authorized_keys on the node.")


class ProbeIn(BaseModel):
    address: str
    token_id: str
    token_secret: str
    verify_tls: bool = True
    tls_fingerprint: str | None = None
    name: str | None = None


class HostIn(ProbeIn):
    name: str
    ssh_enroll: bool = False
    ssh_consent: bool = False


def _client(request: Request, body: ProbeIn) -> ProxmoxClient:
    return ProxmoxClient(body.address, body.token_id, body.token_secret,
                         verify_tls=body.verify_tls,
                         tls_fingerprint=body.tls_fingerprint,
                         factory=request.app.state.proxmox_factory)


@router.post("/probe")
def probe(request: Request, body: ProbeIn,
          user: User = Depends(require_role("admin"))):
    try:
        v = _client(request, body).version()
    except ProxmoxError as e:
        raise HTTPException(502, str(e))
    return {"ok": True, "version": v.get("version"), "release": v.get("release")}


@router.post("", status_code=201)
def create_host(request: Request, body: HostIn, db=Depends(get_db),
                user: User = Depends(require_role("admin"))):
    ent = request.app.state.entitlements
    if db.query(Host).count() >= 1 and not ent.enabled("hosts.multi"):
        raise HTTPException(403, {"error": "entitlement_required",
                                  "feature": "hosts.multi"})
    if body.ssh_enroll and not body.ssh_consent:
        raise HTTPException(400, "SSH enrolment requires explicit consent "
                                 "(ssh_consent: true). " + CONSENT_NOTE)
    if db.query(Host).filter_by(name=body.name).one_or_none():
        raise HTTPException(409, "host name already exists")

    audit_params = body.model_dump()  # write_audit redacts token_secret
    try:
        v = _client(request, body).version()
    except ProxmoxError as e:
        write_audit(db, actor_type="user", actor_id=user.id, action="host.create",
                    params=audit_params, result="error",
                    ip=request.client.host if request.client else None)
        raise HTTPException(502, str(e))

    host = Host(name=body.name, address=body.address, verify_tls=body.verify_tls,
                tls_fingerprint=body.tls_fingerprint, status="connected",
                pve_version=v.get("version"), last_seen_at=utcnow())
    db.add(host)
    db.commit()

    ss = request.app.state.secretstore
    blob, ver = ss.encrypt(jsonlib.dumps(
        {"token_id": body.token_id, "token_secret": body.token_secret}).encode())
    db.add(HostCredential(host_id=host.id, kind="api_token", encrypted_blob=blob,
                          key_version=ver, public_meta=body.token_id))

    out = {"id": host.id, "name": host.name, "address": host.address,
           "node_name": host.node_name, "pve_version": host.pve_version,
           "status": host.status}
    if body.ssh_enroll:
        private_pem, public_line = generate_ed25519(f"proxploy@{body.name}")
        sblob, sver = ss.encrypt(private_pem)
        db.add(HostCredential(host_id=host.id, kind="ssh_key", encrypted_blob=sblob,
                              key_version=sver, public_meta=public_line))
        out |= {"ssh_public_key": public_line,
                "authorized_keys_line": public_line,
                "consent_note": CONSENT_NOTE}
    db.commit()
    write_audit(db, actor_type="user", actor_id=user.id, action="host.create",
                target_type="host", target_id=host.id, params=audit_params,
                ip=request.client.host if request.client else None)
    return out


@router.get("")
def list_hosts(db=Depends(get_db), user: User = Depends(require_role("viewer"))):
    return [{"id": h.id, "name": h.name, "address": h.address,
             "node_name": h.node_name, "status": h.status,
             "pve_version": h.pve_version,
             "last_seen_at": h.last_seen_at.isoformat() if h.last_seen_at else None}
            for h in db.query(Host).order_by(Host.id)]


@router.get("/{host_id}")
def host_detail(host_id: int, db=Depends(get_db),
                user: User = Depends(require_role("viewer"))):
    h = db.get(Host, host_id)
    if not h:
        raise HTTPException(404, "no such host")
    creds = db.query(HostCredential).filter_by(host_id=h.id)
    return {"id": h.id, "name": h.name, "address": h.address,
            "node_name": h.node_name, "status": h.status,
            "pve_version": h.pve_version, "verify_tls": h.verify_tls,
            "credentials": [{"kind": c.kind, "public_meta": c.public_meta,
                             "last_used_at": c.last_used_at.isoformat()
                             if c.last_used_at else None} for c in creds]}


@router.post("/{host_id}/test")
def test_host(request: Request, host_id: int, db=Depends(get_db),
              user: User = Depends(require_role("admin"))):
    h = db.get(Host, host_id)
    if not h:
        raise HTTPException(404, "no such host")
    cred = db.query(HostCredential).filter_by(host_id=h.id, kind="api_token").one()
    tok = jsonlib.loads(request.app.state.secretstore.decrypt(cred.encrypted_blob))
    try:
        v = ProxmoxClient(h.address, tok["token_id"], tok["token_secret"],
                          verify_tls=h.verify_tls, tls_fingerprint=h.tls_fingerprint,
                          factory=request.app.state.proxmox_factory).version()
        h.status, h.pve_version, h.last_seen_at = "connected", v.get("version"), utcnow()
        cred.last_used_at = utcnow()
        result = "ok"
    except ProxmoxError:
        h.status, result = "unreachable", "error"
    db.commit()
    write_audit(db, actor_type="user", actor_id=user.id, action="host.test",
                target_type="host", target_id=h.id, result=result)
    return {"id": h.id, "status": h.status, "pve_version": h.pve_version}
```

Register in `api/__init__.py` (`from proxploy.api import hosts` … `api_router.include_router(hosts.router)`).

- [ ] **Step 4: Run tests, PASS** (whole suite)
- [ ] **Step 5: Commit**, `git add -A && git commit -m "feat(backend): host onboarding, probe, create with encrypted creds + consented SSH enrolment, list/detail/test; the audited route template"`

---

### Task 12: Settings service + settings/meta endpoints (wizard backend complete)

Doc refs: 05 (settings + `/meta/version`, `/meta/onboarding`), 10 Phase 1 ("Settings service + page skeleton; onboarding wizard v1"), 04 (`settings` table, `.enc` convention).

**Files:**
- Create: `backend/proxploy/services/settings.py`, `backend/proxploy/api/settings.py`
- Modify: `backend/proxploy/api/meta.py`, `backend/proxploy/api/__init__.py`
- Test: `backend/tests/test_settings_meta.py`

**Interfaces:**
- Produces (services.settings): `get_setting(db, key: str, default=None)`, `set_setting(db, key: str, value) -> None` (upsert + commit). Keys ending `.enc` hold SecretStore ciphertext and are **never** returned by the API.
- Produces (api.settings): `GET /api/v1/settings` (admin) → `{key: value}` excluding `.enc` keys; `PATCH /api/v1/settings` (admin) `{key: value...}` → upserts, rejects keys ending `.enc` (422; secrets go through their own flows), audits `settings.update` with changed keys.
- Produces (api.meta): `GET /api/v1/meta/version` (any authenticated) → `{version, db_backend}`; `GET /api/v1/meta/onboarding` (public, booleans only per doc 05) → `{admin_exists, host_added, complete}` where `complete = bool(get_setting(db, "onboarding.complete", False))`; the wizard finishes by `PATCH /api/v1/settings {"onboarding.complete": true}`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_settings_meta.py`:
```python
def test_onboarding_state_progression(client, csrf_header, bootstrap_admin):
    r = client.get("/api/v1/meta/onboarding")
    assert r.json() == {"admin_exists": False, "host_added": False, "complete": False}

    bootstrap_admin(client)
    assert client.get("/api/v1/meta/onboarding").json()["admin_exists"] is True

    r = client.patch("/api/v1/settings", json={"onboarding.complete": True},
                     headers=csrf_header(client))
    assert r.status_code == 200
    assert client.get("/api/v1/meta/onboarding").json()["complete"] is True


def test_settings_crud_hides_enc_and_audits(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    client.patch("/api/v1/settings", json={"catalog.source": "community-scripts"},
                 headers=csrf_header(client))
    body = client.get("/api/v1/settings").json()
    assert body["catalog.source"] == "community-scripts"
    assert not any(k.endswith(".enc") for k in body)

    r = client.patch("/api/v1/settings", json={"license.refresh_credential.enc": "x"},
                     headers=csrf_header(client))
    assert r.status_code == 422

    audit = client.get("/api/v1/audit", params={"action": "settings.update"}).json()
    assert audit and "catalog.source" in audit[0]["params"]["keys"]


def test_meta_version(client, csrf_header, bootstrap_admin):
    assert client.get("/api/v1/meta/version").status_code == 401
    bootstrap_admin(client)
    body = client.get("/api/v1/meta/version").json()
    assert body["version"] and body["db_backend"] == "sqlite"
```

- [ ] **Step 2: Run, FAIL**

- [ ] **Step 3: Implement**

`backend/proxploy/services/settings.py`:
```python
from proxploy.models import AppSetting


def get_setting(db, key: str, default=None):
    row = db.query(AppSetting).filter_by(key=key).one_or_none()
    return row.value if row else default


def set_setting(db, key: str, value) -> None:
    row = db.query(AppSetting).filter_by(key=key).one_or_none()
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))
    db.commit()
```
(Refactor Task 9's local `_setting/_set_setting` in `api/entitlements.py` to import these, one implementation.)

`backend/proxploy/api/settings.py`:
```python
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import RootModel

from proxploy.api.deps import get_db, require_role
from proxploy.models import AppSetting, User
from proxploy.services.audit import write_audit
from proxploy.services.settings import set_setting

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingsPatch(RootModel[dict[str, object]]):
    pass


@router.get("")
def list_settings(db=Depends(get_db), user: User = Depends(require_role("admin"))):
    return {r.key: r.value for r in db.query(AppSetting)
            if not r.key.endswith(".enc")}


@router.patch("")
def patch_settings(request: Request, body: SettingsPatch, db=Depends(get_db),
                   user: User = Depends(require_role("admin"))):
    if any(k.endswith(".enc") for k in body.root):
        raise HTTPException(422, "secret-bearing keys are managed by their own flows")
    for k, v in body.root.items():
        set_setting(db, k, v)
    write_audit(db, actor_type="user", actor_id=user.id, action="settings.update",
                params={"keys": sorted(body.root)})
    return {"ok": True}
```

Extend `backend/proxploy/api/meta.py`:
```python
from fastapi import Depends, Request

from proxploy import __version__
from proxploy.api.deps import get_current_user, get_db
from proxploy.models import Host, User
from proxploy.services.settings import get_setting


@router.get("/version")
def version(request: Request, user=Depends(get_current_user)):
    return {"version": __version__,
            "db_backend": request.app.state.engine.dialect.name}


@router.get("/onboarding")
def onboarding(db=Depends(get_db)):
    return {"admin_exists": db.query(User).count() > 0,
            "host_added": db.query(Host).count() > 0,
            "complete": bool(get_setting(db, "onboarding.complete", False))}
```

Register `settings.router` in `api/__init__.py`.

- [ ] **Step 4: Run tests, PASS**
- [ ] **Step 5: Commit**, `git add -A && git commit -m "feat(backend): settings service (+.enc hygiene) and meta version/onboarding, wizard backend complete"`

---

### Task 13: Frontend scaffold: Vite + React 19 + Tailwind v4 tokens + API client + Login

Doc refs: 06 §(c) (tokens, verbatim), 06 §(a) (`/login` flow design), 03 (frontend stack), 09 (frontend layout).

**Files:**
- Create: `frontend/` via Vite scaffold, then `frontend/src/styles/tokens.css`, `frontend/src/api/client.ts`, `frontend/src/components/ui/button.tsx`, `frontend/src/components/LoginForm.tsx`, `frontend/src/routes/login.tsx`, `frontend/src/router.tsx`, `frontend/src/main.tsx`, `frontend/src/tests/login.test.tsx`
- Modify: `frontend/vite.config.ts`, `frontend/package.json` (scripts), `frontend/index.html` (title "Proxploy", `data-theme="dark"` on `<html>`)

**Interfaces:**
- Produces: `api<T>(path, opts?) -> Promise<T>` throwing `ApiError {status, body}` (prefixes `/api/v1`, sends credentials, JSON, `X-CSRF-Token` from the `pp_csrf` cookie on mutations); `Button` (variants `primary | ghost | danger | go`, prototype amber gradient); `LoginForm({onSuccess})`; route tree in `router.tsx` (grown in Tasks 14–15); Tailwind theme vars `bg-ink, bg-panel, bg-panel-2, bg-elev, border-line, border-line-soft, text-text, text-text-2, text-text-3, *-amber/green/red/blue/violet/cyan, font-display/ui/mono, rounded-card/tile/ctl`.

- [ ] **Step 1: Scaffold + deps**

```bash
cd ~/workspace/aspyrelabs/proxploy/proxploy-app
npm create vite@latest frontend -- --template react-ts
cd frontend
npm i @tanstack/react-router @tanstack/react-query @fontsource/space-grotesk @fontsource/inter @fontsource/jetbrains-mono
npm i -D tailwindcss @tailwindcss/vite vitest jsdom @testing-library/react @testing-library/jest-dom
```
`package.json` scripts: `"test": "vitest run"`, keep `dev/build/preview`. `vite.config.ts`:
```ts
/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
  test: { environment: 'jsdom', globals: true, setupFiles: [] },
})
```

- [ ] **Step 2: Write the failing test**

`frontend/src/tests/login.test.tsx`:
```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { LoginForm } from '../components/LoginForm'

describe('tokens', () => {
  it('ships the prototype values verbatim (doc 06 §c)', () => {
    const css = readFileSync(new URL('../styles/tokens.css', import.meta.url), 'utf8')
    for (const hex of ['#0B0F16', '#121924', '#F5B544', '#3FCF8E', '#F26D6D',
                       '#5B9DF9', '#A78BFA', '#34D3C6', '#E8EDF4'])
      expect(css).toContain(hex)
    expect(css).toContain("'Space Grotesk'")
    expect(css).toContain("'JetBrains Mono'")
  })
})

describe('LoginForm', () => {
  it('renders brand + email/password fields', () => {
    render(<LoginForm onSuccess={() => {}} />)
    expect(screen.getByText(/Prox/)).toBeDefined()
    expect(screen.getByLabelText(/email/i)).toBeDefined()
    expect(screen.getByLabelText(/password/i)).toBeDefined()
  })
})
```
Run: `npm test`, Expected: FAIL (missing files).

- [ ] **Step 3: Implement**

`frontend/src/styles/tokens.css`: doc 06 §(c) verbatim plus base/body styles and the derived light block:
```css
@import "tailwindcss";

:root, [data-theme="dark"] {
  --ink:#0B0F16; --panel:#121924; --panel-2:#161F2A; --elev:#1B2531;
  --line:#243040; --line-soft:#1A2330;
  --text:#E8EDF4; --text-2:#93A0B1; --text-3:#5C6979;
  --amber:#F5B544; --amber-dim:rgba(245,181,68,.13);
  --green:#3FCF8E; --green-dim:rgba(63,207,142,.13);
  --red:#F26D6D;   --red-dim:rgba(242,109,109,.13);
  --blue:#5B9DF9;  --blue-dim:rgba(91,157,249,.12);
  --violet:#A78BFA; --cyan:#34D3C6;
}

[data-theme="light"] {
  --ink:#F5F7FA; --panel:#FFFFFF; --panel-2:#F0F3F7; --elev:#E7ECF2;
  --line:#D9E0E8; --line-soft:#E4E9EF;
  --text:#16202C; --text-2:#4E5D6E; --text-3:#8896A6;
  --amber:#C77E14; --amber-dim:rgba(199,126,20,.13);
  --green:#1F9D63; --green-dim:rgba(31,157,99,.13);
  --red:#D9463F;   --red-dim:rgba(217,70,63,.13);
  --blue:#2F6FE0;  --blue-dim:rgba(47,111,224,.12);
  --violet:#7C5CFB; --cyan:#0FA8A0;
}

@theme inline {
  --color-ink: var(--ink);
  --color-panel: var(--panel);
  --color-panel-2: var(--panel-2);
  --color-elev: var(--elev);
  --color-line: var(--line);
  --color-line-soft: var(--line-soft);
  --color-text: var(--text);
  --color-text-2: var(--text-2);
  --color-text-3: var(--text-3);
  --color-amber: var(--amber);   --color-amber-dim: var(--amber-dim);
  --color-green: var(--green);   --color-green-dim: var(--green-dim);
  --color-red: var(--red);       --color-red-dim: var(--red-dim);
  --color-blue: var(--blue);     --color-blue-dim: var(--blue-dim);
  --color-violet: var(--violet);
  --color-cyan: var(--cyan);
  --font-display: 'Space Grotesk', system-ui, sans-serif;
  --font-ui: 'Inter', system-ui, sans-serif;
  --font-mono: 'JetBrains Mono', ui-monospace, monospace;
  --radius-card: 14px;
  --radius-tile: 9px;
  --radius-ctl: 10px;
}

body {
  @apply bg-ink text-text font-ui text-[14px] leading-[1.45];
  background-image:
    radial-gradient(1100px 480px at 74% -8%, rgba(245,181,68,.06), transparent 60%),
    radial-gradient(760px 420px at 8% 4%, rgba(91,157,249,.05), transparent 55%);
  background-attachment: fixed;
}
```

`frontend/src/api/client.ts`:
```ts
export class ApiError extends Error {
  constructor(public status: number, public body: unknown) {
    super(`API ${status}`)
  }
}

function cookie(name: string): string {
  return document.cookie.split('; ').find(c => c.startsWith(name + '='))?.split('=')[1] ?? ''
}

const MUTATING = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

export async function api<T = unknown>(path: string, opts: RequestInit = {}): Promise<T> {
  const method = (opts.method ?? 'GET').toUpperCase()
  const headers: Record<string, string> = { ...(opts.headers as Record<string, string>) }
  if (opts.body != null) headers['Content-Type'] = 'application/json'
  if (MUTATING.has(method)) headers['X-CSRF-Token'] = cookie('pp_csrf')
  const r = await fetch('/api/v1' + path, { credentials: 'include', ...opts, method, headers })
  const body = r.status === 204 ? null : await r.json().catch(() => null)
  if (!r.ok) throw new ApiError(r.status, body)
  return body as T
}
```

`frontend/src/components/ui/button.tsx`:
```tsx
import type { ButtonHTMLAttributes } from 'react'

const variants = {
  primary: 'bg-[linear-gradient(150deg,#F5B544,#E79126)] text-[#20160a] font-semibold shadow-[0_6px_18px_rgba(245,181,68,.25)] hover:brightness-105',
  ghost: 'bg-panel-2 text-text border border-line hover:bg-elev',
  danger: 'bg-red-dim text-red border border-red/30 hover:bg-red/20',
  go: 'bg-amber-dim text-amber border border-amber/30 hover:bg-amber/20',
} as const

export function Button({ variant = 'primary', className = '', ...props }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: keyof typeof variants }) {
  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-ctl px-3.5 py-2 text-[13px] cursor-pointer transition disabled:opacity-50 disabled:cursor-not-allowed ${variants[variant]} ${className}`}
      {...props}
    />
  )
}
```

`frontend/src/components/LoginForm.tsx` (doc 06: centered `.card`, brand mark, `.finput`-style inputs, TOTP deferred to Phase 8):
```tsx
import { useState } from 'react'
import { api, ApiError } from '../api/client'
import { Button } from './ui/button'

export const inputCls =
  'w-full rounded-ctl border border-line bg-panel px-3 py-2 text-[13.5px] text-text placeholder:text-text-3 focus:border-amber focus:outline-none'

export function Brand() {
  return (
    <div className="flex items-center gap-2 font-display text-[17px] font-semibold">
      <span className="grid h-7 w-7 place-items-center rounded-tile bg-[linear-gradient(150deg,#F5B544,#E0862B)] text-[13px] font-bold text-[#20160a]">P</span>
      <span>Prox<b className="text-amber">ploy</b></span>
    </div>
  )
}

export function LoginForm({ onSuccess }: { onSuccess: () => void }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true); setError('')
    try {
      await api('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) })
      onSuccess()
    } catch (err) {
      setError(err instanceof ApiError && err.status === 401
        ? 'Invalid email or password.' : 'Sign-in failed, is the server reachable?')
    } finally { setBusy(false) }
  }

  return (
    <form onSubmit={submit} className="w-[360px] rounded-card border border-line-soft bg-panel p-7 shadow-2xl">
      <div className="mb-6 flex justify-center"><Brand /></div>
      <label className="mb-1 block text-[11px] uppercase tracking-wide text-text-3" htmlFor="email">Email</label>
      <input id="email" type="email" required value={email} onChange={e => setEmail(e.target.value)} className={inputCls + ' mb-4'} />
      <label className="mb-1 block text-[11px] uppercase tracking-wide text-text-3" htmlFor="password">Password</label>
      <input id="password" type="password" required value={password} onChange={e => setPassword(e.target.value)} className={inputCls + ' mb-5'} />
      {error && <p className="mb-3 text-[12.5px] text-red">{error}</p>}
      <Button type="submit" disabled={busy} className="w-full">{busy ? 'Signing in…' : 'Sign in'}</Button>
    </form>
  )
}
```

`frontend/src/routes/login.tsx`:
```tsx
import { createRoute, useNavigate } from '@tanstack/react-router'
import { rootRoute } from '../router'
import { LoginForm } from '../components/LoginForm'

export const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/login',
  component: LoginPage,
})

function LoginPage() {
  const navigate = useNavigate()
  return (
    <div className="grid min-h-screen place-items-center">
      <LoginForm onSuccess={() => navigate({ to: '/cluster' })} />
    </div>
  )
}
```

`frontend/src/router.tsx` (grown in Tasks 14–15, Task 13 state):
```tsx
import { Outlet, createRootRoute, createRouter } from '@tanstack/react-router'

export const rootRoute = createRootRoute({ component: () => <Outlet /> })

import { loginRoute } from './routes/login'

export const routeTree = rootRoute.addChildren([loginRoute])
export const router = createRouter({ routeTree })

declare module '@tanstack/react-router' {
  interface Register { router: typeof router }
}
```

`frontend/src/main.tsx`:
```tsx
import '@fontsource/space-grotesk/400.css'
import '@fontsource/space-grotesk/600.css'
import '@fontsource/space-grotesk/700.css'
import '@fontsource/inter/400.css'
import '@fontsource/inter/500.css'
import '@fontsource/inter/600.css'
import '@fontsource/jetbrains-mono/400.css'
import '@fontsource/jetbrains-mono/600.css'
import './styles/tokens.css'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from '@tanstack/react-router'
import { router } from './router'

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 15_000 } },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
)
```
Delete Vite's demo `App.tsx`, `App.css`, `index.css` imports; set `<html lang="en" data-theme="dark">` and `<title>Proxploy</title>` in `index.html`.

- [ ] **Step 4: Run, PASS** (`npm test` and `npm run build` both green)
- [ ] **Step 5: Commit**, `git add -A && git commit -m "feat(frontend): Vite+React19 scaffold, verbatim design tokens, API client with CSRF, login"`

---

### Task 14: App shell: sidebar nav, topbar, theme switch, entitlements hook, placeholders

Doc refs: 06 §(a) routes, §(b) `AppShell/SidebarNav/Topbar/TierPill/HealthFooter/EmptyState/LockVeil`, §(e) entitlement UI rules, 10 Phase 1 ("app shell UI: sidebar with the fixed nav, topbar, theme tokens, dark/light switch").

**Files:**
- Create: `frontend/src/components/{AppShell.tsx,SidebarNav.tsx,Topbar.tsx,ThemeToggle.tsx,TierPill.tsx,LockVeil.tsx,EmptyState.tsx}`, `frontend/src/api/hooks.ts`, `frontend/src/routes/placeholder.tsx`, `frontend/src/tests/nav.test.tsx`
- Modify: `frontend/src/router.tsx` (shell layout route + guards + the 8 nav routes)

**Interfaces:**
- Produces: `NAV` (exported const, two groups, 8 entries, fixed order per doc 01 §0); `useMe()`, `useEntitlements() -> {has(key), tier, grace, isLoading}` (TanStack Query over `/auth/me`, `/entitlements`; 5 min refetch for entitlements per doc 06 §d); `shellRoute` with `beforeLoad` guard: onboarding incomplete → `/onboarding`, no session → `/login`; `<LockVeil title subtitle>` wrapper (blur + amber lock, doc 06 §e; dormant phase never shows it, but it ships now); `PlaceholderPage({title, phase, note})` honest empty state; `ThemeToggle` flips `document.documentElement.dataset.theme` + persists to `localStorage.pp_theme`.

- [ ] **Step 1: Write the failing test**

`frontend/src/tests/nav.test.tsx`:
```tsx
import { describe, expect, it } from 'vitest'
import { NAV } from '../components/SidebarNav'

describe('fixed nav (doc 01 §0, never reshaped by tier/config/entitlement)', () => {
  it('is exactly the 8 pages in order', () => {
    const labels = NAV.flatMap(g => g.items.map(i => i.label))
    expect(labels).toEqual(['Cluster', 'Apps', 'App Store', 'Virtual Machines',
                            'Storage', 'Network', 'Backups', 'Settings'])
  })
  it('groups: Overview then Infrastructure', () => {
    expect(NAV.map(g => g.label)).toEqual(['Overview', 'Infrastructure'])
  })
})
```
Run `npm test`, FAIL.

- [ ] **Step 2: Implement**

`frontend/src/api/hooks.ts`:
```ts
import { useQuery } from '@tanstack/react-query'
import { api } from './client'

export type Me = { id: number; email: string; display_name: string | null; role: string }
export type Entitlements = {
  tier: string
  features: Record<string, boolean>
  grace: { expires_at: string; grace_until: string; in_grace: boolean } | null
}

export function useMe() {
  return useQuery({ queryKey: ['me'], queryFn: () => api<Me>('/auth/me') })
}

export function useEntitlements() {
  const q = useQuery({
    queryKey: ['entitlements'],
    queryFn: () => api<Entitlements>('/entitlements'),
    refetchInterval: 5 * 60_000,
  })
  return {
    ...q,
    tier: q.data?.tier ?? 'builtin',
    grace: q.data?.grace ?? null,
    has: (key: string) => q.data?.features[key] ?? false,
  }
}
```

`frontend/src/components/SidebarNav.tsx`:
```tsx
import { Link } from '@tanstack/react-router'
import { Brand } from './LoginForm'

export const NAV = [
  { label: 'Overview', items: [
    { label: 'Cluster', to: '/cluster' },
    { label: 'Apps', to: '/apps' },
    { label: 'App Store', to: '/store' },
    { label: 'Virtual Machines', to: '/vms' },
  ]},
  { label: 'Infrastructure', items: [
    { label: 'Storage', to: '/storage' },
    { label: 'Network', to: '/network' },
    { label: 'Backups', to: '/backups' },
    { label: 'Settings', to: '/settings' },
  ]},
] as const

export function SidebarNav() {
  return (
    <aside className="sticky top-0 flex h-screen w-[236px] shrink-0 flex-col border-r border-line-soft bg-panel/60 max-[720px]:hidden">
      <div className="px-4 py-4"><Brand /></div>
      <nav className="flex-1 overflow-y-auto px-2">
        {NAV.map(group => (
          <div key={group.label} className="mb-4">
            <div className="px-2 pb-1 text-[10.5px] font-semibold uppercase tracking-[.08em] text-text-3">{group.label}</div>
            {group.items.map(item => (
              <Link key={item.to} to={item.to}
                className="relative block rounded-tile px-3 py-2 text-[13.5px] text-text-2 hover:bg-panel-2 hover:text-text"
                activeProps={{ className: 'bg-panel-2 !text-text before:absolute before:left-0 before:top-1.5 before:bottom-1.5 before:w-[3px] before:rounded before:bg-amber' }}>
                {item.label}
              </Link>
            ))}
          </div>
        ))}
      </nav>
      <div className="border-t border-line-soft px-4 py-3 text-[12px] text-text-2">
        <span className="mr-2 inline-block h-2 w-2 rounded-full bg-green shadow-[0_0_6px_rgba(63,207,142,.6)]" />
        All systems healthy
      </div>
    </aside>
  )
}
```

`frontend/src/components/ThemeToggle.tsx`:
```tsx
import { useEffect, useState } from 'react'

export function ThemeToggle() {
  const [theme, setTheme] = useState(() => localStorage.getItem('pp_theme') ?? 'dark')
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('pp_theme', theme)
  }, [theme])
  return (
    <button aria-label="Toggle theme" title="Toggle theme"
      onClick={() => setTheme(t => (t === 'dark' ? 'light' : 'dark'))}
      className="rounded-ctl border border-line bg-panel-2 px-2.5 py-1.5 text-[12px] text-text-2 hover:bg-elev">
      {theme === 'dark' ? '☀︎ Light' : '☾ Dark'}
    </button>
  )
}
```

`frontend/src/components/TierPill.tsx`:
```tsx
import { Link } from '@tanstack/react-router'
import { useEntitlements } from '../api/hooks'

export function TierPill() {
  const { tier, grace } = useEntitlements()
  const label = tier === 'builtin' ? 'FREE · ALL FEATURES'
    : grace?.in_grace ? `${tier.toUpperCase()} · GRACE` : tier.toUpperCase()
  const cls = grace?.in_grace ? 'border-amber text-amber'
    : tier === 'builtin' ? 'border-line text-text-3' : 'border-amber/40 text-amber'
  return (
    <Link to="/settings" className={`rounded-full border px-2.5 py-1 font-mono text-[9.5px] tracking-[.08em] ${cls}`}>
      {label}
    </Link>
  )
}
```

`frontend/src/components/Topbar.tsx`:
```tsx
import { ThemeToggle } from './ThemeToggle'
import { TierPill } from './TierPill'
import { useMe } from '../api/hooks'

export function Topbar() {
  const { data: me } = useMe()
  return (
    <header className="sticky top-0 z-10 flex items-center justify-end gap-3 border-b border-line-soft bg-[rgba(11,15,22,.82)] px-5 py-2.5 backdrop-blur-[10px]">
      <TierPill />
      <ThemeToggle />
      <span className="grid h-8 w-8 place-items-center rounded-tile bg-[linear-gradient(150deg,#5B9DF9,#7C5CFB)] font-display text-[12px] font-semibold text-white">
        {(me?.display_name ?? me?.email ?? '?').slice(0, 1).toUpperCase()}
      </span>
    </header>
  )
}
```

`frontend/src/components/AppShell.tsx`:
```tsx
import { Outlet } from '@tanstack/react-router'
import { SidebarNav } from './SidebarNav'
import { Topbar } from './Topbar'

export function AppShell() {
  return (
    <div className="flex min-h-screen">
      <SidebarNav />
      <div className="min-w-0 flex-1">
        <Topbar />
        <main className="p-6"><Outlet /></main>
      </div>
    </div>
  )
}
```

`frontend/src/components/EmptyState.tsx` + `LockVeil.tsx`:
```tsx
export function EmptyState({ title, note }: { title: string; note: string }) {
  return (
    <div className="grid place-items-center rounded-card border border-dashed border-line py-20 text-center">
      <div>
        <h2 className="font-display text-[16px] text-text-2">{title}</h2>
        <p className="mt-1 max-w-md text-[12.5px] text-text-3">{note}</p>
      </div>
    </div>
  )
}
```
```tsx
// LockVeil.tsx, doc 06 §e rule 1: never hide gated features; veil them.
import type { ReactNode } from 'react'
import { Button } from './ui/button'
import { useNavigate } from '@tanstack/react-router'

export function LockVeil({ locked, title, subtitle, children }:
  { locked: boolean; title: string; subtitle: string; children: ReactNode }) {
  const navigate = useNavigate()
  if (!locked) return <>{children}</>
  return (
    <div className="relative overflow-hidden rounded-card">
      <div className="pointer-events-none blur-[1px]">{children}</div>
      <div className="absolute inset-0 grid place-items-center bg-[rgba(11,15,22,.72)] backdrop-blur-[3px]">
        <div className="text-center">
          <div className="mb-2 text-[22px] text-amber">🔒</div>
          <div className="font-display text-[15px] font-semibold">{title}</div>
          <p className="mb-3 mt-1 text-[12.5px] text-text-3">{subtitle}</p>
          <Button variant="go" onClick={() => navigate({ to: '/settings' })}>Unlock Pro</Button>
        </div>
      </div>
    </div>
  )
}
```

`frontend/src/routes/placeholder.tsx`:
```tsx
import { EmptyState } from '../components/EmptyState'

export function PlaceholderPage({ title, phase, note }:
  { title: string; phase: string; note: string }) {
  return (
    <div>
      <h1 className="mb-5 font-display text-[22px] font-semibold">{title}</h1>
      <EmptyState title={`${title} lands in ${phase}`} note={note} />
    </div>
  )
}
```

Rewrite `frontend/src/router.tsx`, shell route with guards + the 8 pages (Settings is replaced by the real page in Task 15):
```tsx
import { Outlet, createRootRoute, createRoute, createRouter, redirect } from '@tanstack/react-router'
import { api } from './api/client'
import { AppShell } from './components/AppShell'
import { PlaceholderPage } from './routes/placeholder'

export const rootRoute = createRootRoute({ component: () => <Outlet /> })

type Onboarding = { admin_exists: boolean; host_added: boolean; complete: boolean }

export const shellRoute = createRoute({
  id: 'shell',
  getParentRoute: () => rootRoute,
  component: AppShell,
  beforeLoad: async () => {
    const ob = await api<Onboarding>('/meta/onboarding')
    if (!ob.complete) throw redirect({ to: '/onboarding' })
    try { await api('/auth/me') } catch { throw redirect({ to: '/login' }) }
  },
})

const page = (path: string, title: string, phase: string, note: string) =>
  createRoute({
    getParentRoute: () => shellRoute,
    path,
    component: () => <PlaceholderPage title={title} phase={phase} note={note} />,
  })

export const indexRoute = createRoute({
  getParentRoute: () => rootRoute, path: '/',
  beforeLoad: () => { throw redirect({ to: '/cluster' }) },
})

export const clusterRoute = page('/cluster', 'Cluster', 'Phase 2 (Observe)',
  'Fleet rings, node cards and the live dashboard arrive with the poller subsystem.')
export const appsRoute = page('/apps', 'Apps', 'Phase 2 (Observe)',
  'Installed apps are discovered by the poller; the grid renders here.')
export const storeRoute = page('/store', 'App Store', 'Phase 4 (Store)',
  'The community-scripts catalog is fetched and cached server-side, never from the browser.')
export const vmsRoute = page('/vms', 'Virtual Machines', 'Phase 2 (Observe)',
  'The VM table renders from the poller cache.')
export const storageRoute = page('/storage', 'Storage', 'Phase 6 (Infra pages)',
  'Datastore cards and the content browser arrive in Phase 6.')
export const networkRoute = page('/network', 'Network', 'Phase 6 (Infra pages)',
  'Bridges, VLANs and throughput arrive in Phase 6.')
export const backupsRoute = page('/backups', 'Backups', 'Phase 6 (Infra pages)',
  'PBS integration arrives in Phase 6.')

import { loginRoute } from './routes/login'

export const routeTree = rootRoute.addChildren([
  indexRoute, loginRoute,
  shellRoute.addChildren([clusterRoute, appsRoute, storeRoute, vmsRoute,
                          storageRoute, networkRoute, backupsRoute]),
])
export const router = createRouter({ routeTree })

declare module '@tanstack/react-router' {
  interface Register { router: typeof router }
}
```

- [ ] **Step 3: Run, PASS** (`npm test`, `npm run build`)
- [ ] **Step 4: Commit**, `git add -A && git commit -m "feat(frontend): app shell, fixed 8-page nav, topbar, theme switch, entitlements hook, LockVeil, honest placeholders"`

---

### Task 15: Onboarding wizard v1 + Settings page

Doc refs: 06 §(a) (`/onboarding` 4-step flow design, Settings page contents), 10 Phase 1 ("onboarding wizard v1 (admin account → first host)"; DoD fresh-install line), 08 §4 (honest SSH copy).

**Files:**
- Create: `frontend/src/routes/onboarding.tsx`, `frontend/src/routes/settings.tsx`, `frontend/src/components/HostForm.tsx`, `frontend/src/tests/onboarding.test.tsx`
- Modify: `frontend/src/router.tsx` (add `onboardingRoute`, replace Settings placeholder with `settingsRoute`)

**Interfaces:**
- Produces: `HostForm({onCreated, probeFirst})`; shared by wizard step 2/3 and Settings "Add host": fields name/address/token id/token secret/verify-TLS toggle/SSH-enrol checkbox with consent copy; "Test connection" → `POST /hosts/probe`; submit → `POST /hosts`; on `ssh_enroll` success shows `authorized_keys_line` + copy button + `consent_note`. `onboardingRoute` (4 steps: admin → host+SSH → key display → done, finishing with `PATCH /settings {"onboarding.complete": true}` then navigate `/cluster`); `settingsRoute` (Plan card from `useEntitlements`, Hosts card listing `GET /hosts` + Add-host, General card honest Phase-7 stubs).

- [ ] **Step 1: Write the failing test**

`frontend/src/tests/onboarding.test.tsx`:
```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { HostForm } from '../components/HostForm'

vi.mock('@tanstack/react-router', () => ({ useNavigate: () => vi.fn() }))

describe('HostForm', () => {
  it('shows the honest root-consent copy with the SSH checkbox', () => {
    render(<HostForm onCreated={() => {}} />)
    expect(screen.getByLabelText(/address/i)).toBeDefined()
    expect(screen.getByLabelText(/token id/i)).toBeDefined()
    expect(screen.getByText(/root shell on the node/i)).toBeDefined()
    expect(screen.getByRole('button', { name: /test connection/i })).toBeDefined()
  })
})
```
Run, FAIL.

- [ ] **Step 2: Implement**

`frontend/src/components/HostForm.tsx`:
```tsx
import { useState } from 'react'
import { api, ApiError } from '../api/client'
import { Button } from './ui/button'
import { inputCls } from './LoginForm'

export type HostCreated = {
  id: number; name: string; ssh_public_key?: string
  authorized_keys_line?: string; consent_note?: string
}

const CONSENT_COPY = 'App Store installs run community scripts through a dedicated ' +
  'SSH key, a root shell on the node, exactly as if you ran them yourself. ' +
  'Optional: skip it and everything except installs/updates/migration still works.'

export function HostForm({ onCreated }: { onCreated: (h: HostCreated) => void }) {
  const [f, setF] = useState({ name: '', address: 'https://', token_id: '',
    token_secret: '', verify_tls: true, ssh_enroll: false })
  const [probe, setProbe] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const set = (k: string, v: unknown) => setF(s => ({ ...s, [k]: v }))
  const errText = (e: unknown) =>
    e instanceof ApiError ? String((e.body as any)?.detail ?? (e.body as any)?.title ?? e.message) : 'Request failed'

  async function testConnection() {
    setProbe(''); setError('')
    try {
      const r = await api<{ version: string; release: string }>('/hosts/probe', {
        method: 'POST', body: JSON.stringify(f) })
      setProbe(`Connected, PVE ${r.version}`)
    } catch (e) { setError(errText(e)) }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError('')
    try {
      onCreated(await api<HostCreated>('/hosts', {
        method: 'POST',
        body: JSON.stringify({ ...f, ssh_consent: f.ssh_enroll }) }))
    } catch (e) { setError(errText(e)) } finally { setBusy(false) }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      {([['name', 'Name', 'pve-01'], ['address', 'Address', 'https://10.0.0.5:8006'],
         ['token_id', 'API token id', 'proxploy@pve!monitoring'],
         ['token_secret', 'API token secret', '']] as const).map(([k, label, ph]) => (
        <div key={k}>
          <label htmlFor={k} className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">{label}</label>
          <input id={k} required placeholder={ph} className={inputCls}
            type={k === 'token_secret' ? 'password' : 'text'}
            value={f[k]} onChange={e => set(k, e.target.value)} />
        </div>
      ))}
      <label className="flex items-center gap-2 text-[13px] text-text-2">
        <input type="checkbox" checked={f.verify_tls}
          onChange={e => set('verify_tls', e.target.checked)} /> Verify TLS certificate
      </label>
      <label className="flex items-start gap-2 text-[13px] text-text-2">
        <input type="checkbox" checked={f.ssh_enroll}
          onChange={e => set('ssh_enroll', e.target.checked)} className="mt-0.5" />
        <span>Enable App Store installs (SSH key enrolment).
          <span className="block text-[12px] text-text-3">
            I understand this authorizes a root shell on the node: {CONSENT_COPY}
          </span>
        </span>
      </label>
      {probe && <p className="font-mono text-[12px] text-green">{probe}</p>}
      {error && <p className="text-[12.5px] text-red">{error}</p>}
      <div className="flex gap-2">
        <Button type="button" variant="ghost" onClick={testConnection}>Test connection</Button>
        <Button type="submit" disabled={busy}>{busy ? 'Adding…' : 'Add host'}</Button>
      </div>
    </form>
  )
}
```

`frontend/src/routes/onboarding.tsx`:
```tsx
import { useState } from 'react'
import { createRoute, redirect, useNavigate } from '@tanstack/react-router'
import { rootRoute } from '../router'
import { api } from '../api/client'
import { Brand, LoginForm, inputCls } from '../components/LoginForm'
import { HostForm, type HostCreated } from '../components/HostForm'
import { Button } from '../components/ui/button'

export const onboardingRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/onboarding',
  component: Wizard,
  beforeLoad: async () => {
    const ob = await api<{ complete: boolean }>('/meta/onboarding')
    if (ob.complete) throw redirect({ to: '/cluster' })
  },
})

const STEPS = ['Admin account', 'First host', 'Authorize installs', 'Done'] as const

function Wizard() {
  const navigate = useNavigate()
  const [step, setStep] = useState(0)
  const [host, setHost] = useState<HostCreated | null>(null)
  const [admin, setAdmin] = useState({ email: '', password: '', display_name: '' })
  const [error, setError] = useState('')

  async function createAdmin(e: React.FormEvent) {
    e.preventDefault(); setError('')
    try {
      await api('/users', { method: 'POST', body: JSON.stringify(admin) })
      await api('/auth/login', { method: 'POST',
        body: JSON.stringify({ email: admin.email, password: admin.password }) })
      setStep(1)
    } catch { setError('Could not create the admin account (password: 12+ characters).') }
  }

  async function finish() {
    await api('/settings', { method: 'PATCH',
      body: JSON.stringify({ 'onboarding.complete': true }) })
    navigate({ to: '/cluster' })
  }

  return (
    <div className="grid min-h-screen place-items-center">
      <div className="w-[520px] rounded-card border border-line-soft bg-panel p-7">
        <div className="mb-5 flex items-center justify-between">
          <Brand />
          <div className="flex gap-1.5">
            {STEPS.map((s, i) => (
              <span key={s} className={`rounded-full border px-2 py-0.5 font-mono text-[9.5px] ${i === step ? 'border-amber text-amber' : 'border-line text-text-3'}`}>{i + 1} {s}</span>
            ))}
          </div>
        </div>

        {step === 0 && (
          <form onSubmit={createAdmin} className="space-y-4">
            {([['email', 'Email', 'email'], ['display_name', 'Display name', 'text'],
               ['password', 'Password (12+ chars)', 'password']] as const).map(([k, label, type]) => (
              <div key={k}>
                <label htmlFor={k} className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">{label}</label>
                <input id={k} type={type} required={k !== 'display_name'} className={inputCls}
                  value={admin[k]} onChange={e => setAdmin(a => ({ ...a, [k]: e.target.value }))} />
              </div>
            ))}
            {error && <p className="text-[12.5px] text-red">{error}</p>}
            <Button type="submit" className="w-full">Create admin account</Button>
          </form>
        )}

        {step === 1 && <HostForm onCreated={h => { setHost(h); setStep(h.ssh_public_key ? 2 : 3) }} />}

        {step === 2 && host?.authorized_keys_line && (
          <div className="space-y-3">
            <p className="text-[13px] text-text-2">{host.consent_note}</p>
            <pre className="overflow-x-auto rounded-ctl bg-[#0a0e14] p-3 font-mono text-[11.5px] leading-[1.7] text-text-2">{`echo '${host.authorized_keys_line}' >> /root/.ssh/authorized_keys`}</pre>
            <div className="flex gap-2">
              <Button variant="ghost" onClick={() => navigator.clipboard.writeText(host.authorized_keys_line!)}>Copy key line</Button>
              <Button onClick={() => setStep(3)}>I have authorized it</Button>
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="space-y-4 text-center">
            <p className="text-[13.5px] text-text-2">
              {host ? `Host ${host.name} connected.` : 'Setup complete.'} Proxploy is ready.
            </p>
            <Button className="w-full" onClick={finish}>Open the dashboard</Button>
          </div>
        )}
      </div>
    </div>
  )
}
```

`frontend/src/routes/settings.tsx`:
```tsx
import { useState } from 'react'
import { createRoute } from '@tanstack/react-router'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { shellRoute } from '../router'
import { api } from '../api/client'
import { useEntitlements } from '../api/hooks'
import { HostForm } from '../components/HostForm'
import { Button } from '../components/ui/button'

export const settingsRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/settings',
  component: SettingsPage,
})

type HostRow = { id: number; name: string; address: string; status: string; pve_version: string | null }

function Card({ title, children, action }: { title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <section className="rounded-card border border-line-soft bg-panel p-5">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="font-display text-[15px] font-semibold">{title}</h2>{action}
      </div>
      {children}
    </section>
  )
}

function SettingsPage() {
  const { tier, grace } = useEntitlements()
  const qc = useQueryClient()
  const [adding, setAdding] = useState(false)
  const hosts = useQuery({ queryKey: ['hosts'], queryFn: () => api<HostRow[]>('/hosts') })

  return (
    <div className="max-w-3xl space-y-5">
      <h1 className="font-display text-[22px] font-semibold">Settings</h1>

      <Card title="Plan">
        <p className="text-[13.5px] text-text-2">
          <span className="font-mono text-amber">{tier === 'builtin' ? 'FREE' : tier.toUpperCase()}</span>
          {', '}all features are enabled. Licensing is dormant; entering a license key
          activates against the Proxploy licensing service.
          {grace?.in_grace && <span className="text-amber"> License refresh failing, working offline until {grace.grace_until}.</span>}
        </p>
      </Card>

      <Card title="Hosts" action={<Button variant="ghost" onClick={() => setAdding(a => !a)}>{adding ? 'Close' : 'Add host'}</Button>}>
        <table className="w-full text-left text-[13px]">
          <thead><tr className="text-[10.5px] uppercase tracking-wide text-text-3">
            <th className="pb-2">Host</th><th>Address</th><th>PVE</th><th>Status</th></tr></thead>
          <tbody>
            {(hosts.data ?? []).map(h => (
              <tr key={h.id} className="border-t border-line-soft hover:bg-panel-2">
                <td className="py-2 font-mono">{h.name}</td>
                <td className="font-mono text-text-2">{h.address}</td>
                <td className="text-text-2">{h.pve_version ?? ', '}</td>
                <td><span className={h.status === 'connected' ? 'text-green' : 'text-red'}>{h.status}</span></td>
              </tr>
            ))}
            {!hosts.data?.length && <tr><td colSpan={4} className="py-4 text-text-3">No hosts yet.</td></tr>}
          </tbody>
        </table>
        {adding && <div className="mt-4 border-t border-line-soft pt-4">
          <HostForm onCreated={() => { setAdding(false); qc.invalidateQueries({ queryKey: ['hosts'] }) }} />
        </div>}
      </Card>

      <Card title="General">
        <p className="text-[12.5px] text-text-3">
          Scheduled auto-updates, notifications and catalog sync configuration arrive in
          Phases 3–7; this page grows with them.
        </p>
      </Card>
    </div>
  )
}
```

In `router.tsx`: import `onboardingRoute` and `settingsRoute`, add `onboardingRoute` to the root children and `settingsRoute` to the shell children (there is no Settings placeholder to remove; it was never created in Task 14's `page()` list; verify the nav's `/settings` link now resolves).

- [ ] **Step 3: Run, PASS** (`npm test`, `npm run build`)

- [ ] **Step 4: Manual DoD walk-through against the real backend (fake-free, no PVE needed for the UI shell)**

```bash
cd backend && .venv/bin/uvicorn --factory proxploy.main:create_app --port 8000 &
cd ../frontend && npm run dev &
```
`curl -s http://127.0.0.1:8000/api/v1/meta/onboarding` → `admin_exists: false`. (With a real PVE host available this is the full DoD flow: wizard → admin → host + token → connectivity check → key display. Without one, the fake-backed pytest suite in Tasks 11–12 is the executable proof.) Kill both dev servers afterwards.

- [ ] **Step 5: Commit**, `git add -A && git commit -m "feat(frontend): onboarding wizard v1 (admin → host → SSH consent → done) + settings page (plan, hosts, add-host)"`

---

### Task 16: CI wiring: executor-isolation lint, license audit, Postgres leg, disposable-PVE path, SPA serving

Doc refs: 09 (import-graph CI check "from Phase 1, even though executor/ doesn't exist yet"), 03 §License verification protocol (CI license-audit step), 10 Phase 1 test infra (b) + DoD ("disposable-PVE integration path is wired"), 02 §3 (backend serves the built SPA).

**Files:**
- Create (app): `backend/scripts/check_executor_isolation.py`, `.github/workflows/ci.yml`
- Create (api): `.github/workflows/ci.yml`
- Modify (app): `backend/proxploy/main.py` (mount built SPA when present)
- Test: `backend/tests/test_isolation_lint.py`

**Interfaces:**
- Produces: `python backend/scripts/check_executor_isolation.py`, exit 0 when no module outside `backend/proxploy/executor/` imports `asyncssh` or references the SSH-key SecretStore accessor (`get_ssh_private_key`); exit 1 listing offenders. Runs in CI on every push; passes trivially until Phase 4 creates `executor/`.
- Produces: GitHub Actions workflows (the "wired" artifact, no remote exists yet on this box; they activate the day the repos are pushed).

- [ ] **Step 1: Write the failing test**

`backend/tests/test_isolation_lint.py`:
```python
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_executor_isolation.py"


def test_clean_tree_passes():
    r = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_violation_is_caught(tmp_path):
    pkg = tmp_path / "proxploy"
    (pkg / "services").mkdir(parents=True)
    (pkg / "services" / "evil.py").write_text("import asyncssh\n")
    (pkg / "executor").mkdir()
    (pkg / "executor" / "ok.py").write_text("import asyncssh\n")  # allowed here
    r = subprocess.run([sys.executable, str(SCRIPT), "--root", str(pkg)],
                       capture_output=True, text=True)
    assert r.returncode == 1
    assert "services/evil.py" in r.stdout
    assert "executor/ok.py" not in r.stdout
```
Run, FAIL (script missing).

- [ ] **Step 2: Implement the lint**

`backend/scripts/check_executor_isolation.py`:
```python
#!/usr/bin/env python3
"""Hard structural rule (docs 08 §4, 09): no module outside proxploy/executor/ may
import the SSH client (asyncssh) or call the SecretStore accessor that returns the
SSH private key. Mechanical enforcement, not convention. Wired from Phase 1, 
passes trivially until executor/ exists in Phase 4."""
import argparse
import ast
import sys
from pathlib import Path

FORBIDDEN_IMPORTS = {"asyncssh"}
FORBIDDEN_NAMES = {"get_ssh_private_key"}


def violations(root: Path):
    for py in sorted(root.rglob("*.py")):
        rel = py.relative_to(root)
        if rel.parts and rel.parts[0] == "executor":
            continue
        tree = ast.parse(py.read_text(), filename=str(py))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = {a.name.split(".")[0] for a in node.names}
                if names & FORBIDDEN_IMPORTS:
                    yield rel, node.lineno, "imports asyncssh"
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.split(".")[0] in FORBIDDEN_IMPORTS:
                    yield rel, node.lineno, "imports asyncssh"
            elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
                yield rel, node.lineno, f"references {node.id}"
            elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_NAMES:
                yield rel, node.lineno, f"references {node.attr}"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--root", default=str(Path(__file__).resolve().parents[1] / "proxploy"))
    args = p.parse_args()
    found = list(violations(Path(args.root)))
    for rel, line, why in found:
        print(f"EXECUTOR-ISOLATION VIOLATION: {rel}:{line} {why}")
    if found:
        print(f"\n{len(found)} violation(s). Only proxploy/executor/ may touch the "
              "SSH client or the SSH-key accessor (docs 08 §4, 09).")
        return 1
    print("executor isolation: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Serve the built SPA (single origin, doc 02 §3)**

In `main.py` `create_app`, after `app.include_router(api_router)`:
```python
    from pathlib import Path as _Path

    from fastapi.staticfiles import StaticFiles

    dist = _Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="spa")
```

- [ ] **Step 4: Workflows**

`proxploy-app/.github/workflows/ci.yml`:
```yaml
name: ci
on:
  push: {branches: [main]}
  workflow_dispatch:
  schedule: [{cron: "17 3 * * 1"}]   # weekly: catches upstream/licensing drift

jobs:
  backend:
    runs-on: ubuntu-latest
    defaults: {run: {working-directory: backend}}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.12"}
      - run: pip install -e '.[dev]'
      - run: python -m pytest tests/ -q -m "not pve_integration and not e2e"
      - run: python scripts/check_executor_isolation.py
      - name: license audit (doc 03 protocol, fails on anything outside brief §3)
        run: pip-licenses --partial-match --allow-only "MIT;MIT License;BSD;BSD License;Apache;Apache Software License;ISC;Python Software Foundation;PostgreSQL;Public Domain;Mozilla Public License 2.0;Eclipse Public License v2.0;The Unlicense;CMU License (MIT-CMU)"

  backend-postgres:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env: {POSTGRES_PASSWORD: pp, POSTGRES_DB: proxploy}
        ports: ["5432:5432"]
        options: >-
          --health-cmd pg_isready --health-interval 5s
          --health-timeout 5s --health-retries 10
    defaults: {run: {working-directory: backend}}
    env:
      PROXPLOY_TEST_PG_DSN: postgresql+psycopg://postgres:pp@localhost:5432/proxploy
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.12"}
      - run: pip install -e '.[dev]'
      - run: python -m pytest tests/test_migrations.py -q

  frontend:
    runs-on: ubuntu-latest
    defaults: {run: {working-directory: frontend}}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: {node-version: 22}
      - run: npm ci
      - run: npm test
      - run: npm run build
      - name: license audit (npm)
        run: >
          npx license-checker-rseidelsohn --production --onlyAllow
          "MIT;ISC;BSD-2-Clause;BSD-3-Clause;Apache-2.0;MPL-2.0;0BSD;CC0-1.0;Unlicense"

  pve-integration:
    # Doc 10 Phase 1 (b): disposable-PVE matrix. Wired now; runs when the repo
    # secrets point at throwaway PVE 8/9 boxes (doc 11 §7). The PVE 9 leg may be
    # added incrementally through Phase 2 per the DoD.
    if: github.event_name != 'push'
    runs-on: ubuntu-latest
    strategy: {matrix: {pve: [pve8, pve9]}}
    defaults: {run: {working-directory: backend}}
    env:
      PROXPLOY_TEST_PVE_URL: ${{ secrets[format('{0}_URL', matrix.pve)] }}
      PROXPLOY_TEST_PVE_TOKEN_ID: ${{ secrets[format('{0}_TOKEN_ID', matrix.pve)] }}
      PROXPLOY_TEST_PVE_TOKEN_SECRET: ${{ secrets[format('{0}_TOKEN_SECRET', matrix.pve)] }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.12"}
      - run: pip install -e '.[dev]'
      - name: run against disposable PVE (skips cleanly when secrets are absent)
        run: python -m pytest tests/ -q -m pve_integration
```

`proxploy-api/.github/workflows/ci.yml`:
```yaml
name: ci
on:
  push: {branches: [main]}
  workflow_dispatch:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.12"}
      - run: pip install -e '.[dev]'
      - run: python -m pytest tests/ -q   # includes the app<->api contract test
      - run: pip install pip-licenses && pip-licenses --partial-match --allow-only "MIT;MIT License;BSD;BSD License;Apache;Apache Software License;ISC;Python Software Foundation;Public Domain;Mozilla Public License 2.0;The Unlicense;CMU License (MIT-CMU)"
```

- [ ] **Step 5: Run everything, both repos**

```bash
cd ~/workspace/aspyrelabs/proxploy/proxploy-app/backend && .venv/bin/python -m pytest tests/ -q && .venv/bin/python scripts/check_executor_isolation.py
cd ../frontend && npm test && npm run build
cd ~/workspace/aspyrelabs/proxploy/proxploy-api && .venv/bin/python -m pytest tests/ -q
```
Expected: all PASS (pve_integration skipped, e2e passes locally).

- [ ] **Step 6: Commit (both repos)**

```bash
cd ~/workspace/aspyrelabs/proxploy/proxploy-app && git add -A && git commit -m "ci: executor-isolation lint, license audit, Postgres leg, wired disposable-PVE matrix; serve built SPA"
cd ~/workspace/aspyrelabs/proxploy/proxploy-api && git add -A && git commit -m "ci: tests + contract + license audit"
```

---

## Phase-1 Definition of Done: verification map (doc 10)

Run this checklist after Task 16; every line names its executable proof.

| DoD line (doc 10) | Proof |
|---|---|
| Fresh install: wizard creates admin, adds a PVE host with a scoped token, connectivity check passes, credentials round-trip encrypted | `tests/test_auth.py` (bootstrap), `tests/test_hosts.py::test_create_host_with_ssh_enrolment` (fake PVE; encrypted blobs asserted), wizard UI in Task 15. The *real*-PVE leg is `tests/test_pve_integration.py`, env-gated by design on this box. |
| Every subsequent route template runs through auth, RBAC stub, audit, and an entitlement check | `api/hosts.py` is the documented template; `test_hosts.py` asserts 401/403/audit/entitlement paths. |
| `Entitlements.enabled()` verifies a token signed by the dormant proxploy-api and falls back to the built-in map offline | `tests/test_e2e_entitlement.py` (real api subprocess), `tests/test_entitlements.py` (grace + builtin fallback), contract tests in both repos. |
| Alembic migrates SQLite and Postgres from empty to current | `tests/test_migrations.py`, SQLite locally; PG leg in the `backend-postgres` CI job (or locally with `PROXPLOY_TEST_PG_DSN`). |
| proxmoxer fake/fixture layer + app↔api contract test run in CI; disposable-PVE path wired | `tests/fakes/pve.py` + fixtures (backend job), `tests/contract/` in both workflows, `pve-integration` matrix job (dispatch/schedule, secrets-gated). |

Also confirm: `git -C proxploy-app log --oneline` shows one commit per task; `proxploy-web`/`proxploy-docs` each have their scaffold commit; `proxploy-api` has Tasks 8/9/16 commits. Append a dated completion note to `buildlog.md`.

## Execution notes (unattended run)

- **Order matters:** Tasks 1→12 are strictly sequential (each imports the last). 13–15 (frontend) depend only on Task 12's endpoints existing for the manual walk-through; 16 last.
- **If `npm create vite` prompts**, pass `--yes`/pipe `printf 'y\n'`; if the shadcn-style prompt for package name appears, accept defaults; the scaffold files are immediately overwritten per Task 13.
- **If autogenerate emits `BigInteger` vs `INTEGER` variant noise on SQLite**, keep the generated file as-is; the `BigPK` variant renders correctly; do not hand-edit types in 0001 beyond removing spurious `op.alter_column` no-ops.
- **Never edit migration 0001 after Task 2's commit.** Schema changes in later phases are new revisions.
- **Secrets hygiene tripwires:** no test may assert on a plaintext secret read back from the DB (only through SecretStore); `pp_session` cookie is HttpOnly; `.enc` settings never appear in `GET /api/v1/settings`.
- The three quality gates that must never regress while executing: `pytest -q` green in both repos, `check_executor_isolation.py` exit 0, frontend `npm run build` green.
