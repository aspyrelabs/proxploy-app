"""All Proxploy entities, schema per docs/04-data-model.md, portable SQLite/Postgres subset."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index,
    Integer, JSON, LargeBinary, Text, UniqueConstraint,
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


class TotpRecoveryCode(Base):
    """One row per recovery code (Phase 8 Task 8 amendment, see
    docs/notes/phase-8-scale.md: the plan's zero-migration design packed
    these inside `users.totp_secret_enc`; a real column replaces that so
    burning a code is an ordinary UPDATE, never a decrypt-mutate-re-encrypt
    of a blob shared with a concurrent TOTP verify). `code_hash_enc` is the
    argon2 hash (services/authn.py::hash_password's idiom, never the raw
    code) Fernet-encrypted at rest via SecretStore, same as
    `totp_secret_enc`. Burning sets `used_at`; the atomic single-use
    guarantee is `UPDATE ... WHERE id = ? AND used_at IS NULL`
    (services/consoletickets.py::redeem_ticket's exact pattern)."""
    __tablename__ = "totp_recovery_codes"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    code_hash_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)


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
    # Why the last poll cycle was not clean, in one sentence, or NULL when it
    # was. Set for BOTH shapes of trouble: a cycle that failed outright (status
    # goes unreachable) and one that lost only an optional read (status stays
    # connected). "unreachable" with no reason is undiagnosable, which is how a
    # missing Sys.Audit privilege looked exactly like a dead node.
    last_error: Mapped[str | None] = mapped_column(Text)
    pve_version: Mapped[str | None] = mapped_column(Text)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime)
    ssh_host_key_fingerprint: Mapped[str | None] = mapped_column(Text)
    node_shell_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Whether the stored token lacks Sys.PowerMgmt (host reboot/power off),
    # recomputed at enrolment and by POST /hosts/{id}/test, same idiom as
    # last_error above. NULL means "not checked yet" -- distinct from False
    # ("checked, and granted") -- so a host enrolled before this existed
    # reads as unknown rather than a false "granted". Informational only: it
    # is never used to refuse a power attempt, only to warn ahead of one
    # (services/pveum.py NODE_POWER_PRIVILEGE, doc 08 §2/§9).
    node_power_missing: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))
    # The pools this host's operator chose, remembered so the question is asked
    # once rather than on every install. NULL means "not chosen yet", which is
    # deliberately distinct from any pool name: services/appstore.py's
    # resolution order treats NULL as "fall through", and a stored name as an
    # answer to re-validate. Per content type, because a node can have one
    # rootdir candidate and several vztmpl ones.
    default_container_storage: Mapped[str | None] = mapped_column(Text)
    default_template_storage: Mapped[str | None] = mapped_column(Text)


class HostCredential(TimestampMixin, Base):
    __tablename__ = "host_credentials"
    id: Mapped[int] = mapped_column(primary_key=True)
    host_id: Mapped[int] = mapped_column(ForeignKey("hosts.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text, nullable=False)  # api_token | ssh_key
    encrypted_blob: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    public_meta: Mapped[str | None] = mapped_column(Text)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Set by POST /hosts/{id}/ssh/verify. NULL means "never confirmed working"
    #, which is exactly what the onboarding wizard's authorize step reads to
    # know whether it still has something to ask the operator for.
    ssh_verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    __table_args__ = (UniqueConstraint("host_id", "kind", name="ux_host_creds"),)


# --- Apps ------------------------------------------------------------------

class App(TimestampMixin, Base):
    __tablename__ = "apps"
    id: Mapped[int] = mapped_column(primary_key=True)
    host_id: Mapped[int] = mapped_column(ForeignKey("hosts.id", ondelete="RESTRICT"))
    # Physical column is `ct_id`: `ctid` is a PostgreSQL system column present
    # on every table, so `CREATE TABLE apps (... ctid ...)` is rejected outright
    # (`column name "ctid" conflicts with a system column name`). The Python
    # attribute, the API field and the frontend type all stay `ctid`.
    ctid: Mapped[int] = mapped_column("ct_id", Integer, nullable=False)
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
    # Table-level constraints name the *physical* column, hence "ct_id".
    __table_args__ = (UniqueConstraint("host_id", "ct_id", name="ux_apps_host_ctid"),)


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
    # Terminal install events (success + failed + aborted) from upstream's
    # telemetry service, NEVER their `total` field, which counts intermediate
    # progress pings: services/catalog_telemetry.py documents why at length.
    # None means we have never had a number for this slug, which is different
    # from 0 and must stay different: telemetry is opt-in upstream, so absence
    # is silence, not evidence that nobody runs it.
    popularity: Mapped[int | None] = mapped_column(Integer)
    # When WE last read that number. Its own column because upstream caches
    # these aggregates for 23h, so the value can be a full day old and moves
    # in jumps; the Store labels it "as of" rather than implying it is live.
    popularity_synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Upstream's own dates for the SCRIPT, distinct from every other timestamp
    # here: `synced_at` is when we last discovered the row, `updated_at` is
    # when this DB row changed, `upstream_updated_at` is when the PocketBase
    # RECORD was last edited (a description fix bumps it), and these two are
    # when the script itself was first published and last changed. They are
    # real columns rather than reads out of raw["metadata"] because the Store
    # SORTS on them, and an ORDER BY over json_extract is neither indexable
    # nor cheap over 585 rows.
    script_created: Mapped[datetime | None] = mapped_column(DateTime)
    script_updated: Mapped[datetime | None] = mapped_column(DateTime)
    # The tags community-scripts shows on a card. All FOUR are tri-state and
    # the third state is load bearing: NULL means WE DO NOT KNOW, never "no".
    # The 9 `unlisted` rows have no upstream record at all, so rendering them
    # as "not ARM" or "not updateable" would be a claim nothing supports; the
    # UI must show no chip there rather than a negative one.
    has_arm: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    updateable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    privileged: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    port: Mapped[int | None] = mapped_column(Integer)
    # Local icon mirror (services/catalog_icons.py), so the Store renders its
    # icons with no network at all. `icon_url` keeps upstream's URL, which is
    # what the sync writes and what the API falls back to; these four record
    # the cached copy beside it.
    #
    # `icon_cache_path` is a BARE FILENAME relative to data_dir/icons, never a
    # path: it is built from our own slug plus an extension allowlist, and
    # api/catalog.py re-checks containment before opening it.
    # `icon_cache_source` is the upstream URL the cached bytes came FROM, and
    # it is what makes a logo change detectable: when it stops matching
    # `icon_url`, the file is refetched rather than served forever.
    icon_cache_path: Mapped[str | None] = mapped_column(Text)
    icon_cache_source: Mapped[str | None] = mapped_column(Text)
    icon_cache_etag: Mapped[str | None] = mapped_column(Text)
    icon_cached_at: Mapped[datetime | None] = mapped_column(DateTime)
    # The evidence behind has_arm, e.g. ["amd64", "arm64"]. Kept alongside the
    # boolean rather than instead of it: the flag is what a chip renders, the
    # list is what an "arm64 only" answer needs, and deriving one from the
    # other at read time would put upstream's architecture vocabulary into our
    # query layer.
    architectures: Mapped[list | None] = mapped_column(JSON)
    upstream_sha: Mapped[str | None] = mapped_column(Text)
    raw: Mapped[dict | None] = mapped_column(JSON)
    # Tri-state on purpose (catalog expansion, see services/catalog.py header
    # note): None means "discovered but not yet classified", the state every
    # ct/ row starts in after a refresh. Discovery is 2 GitHub API calls flat
    # and never fetches a script pair; classification happens lazily, on
    # card-open or install-attempt, or via the low-priority backlog job.
    installable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    unsupported_reason: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Which upstream directory this came from: ct/vm/tools-pve/tools-addon/
    # turnkey, mechanical per the repo's own layout (services/catalog.py's
    # discover_tree). Only "ct" is ever installable or shown in the Store.
    entry_type: Mapped[str] = mapped_column(Text, nullable=False, default="ct")
    # Provenance for the presentation-only fields (name, description,
    # category, icon_url, website, docs_url) that
    # services/catalog_metadata.py syncs from upstream. "pocketbase" for the
    # live source, "archive" for the frozen cold-start fallback, and either
    # with a "-name-match" suffix when the row was joined by normalized NAME
    # rather than by slug (resolve_name_matches: upstream's catalog slug
    # sometimes differs from its own script filename, e.g. ct/apache-airflow.sh
    # against the record slugged `airflow`). The suffix exists so a heuristic
    # join is visible on the row itself, not only in a log line.
    #
    # Both timestamps null is a NORMAL state, not an error: it means no
    # upstream record matched this slug, which is true for 37 of our ct/ rows
    # (mostly alpine-* variants plus mysql). Such a row keeps its
    # discovery-derived name and its catalog_categories.py heuristic category
    # and simply renders without a description or icon.
    metadata_source: Mapped[str | None] = mapped_column(Text)
    metadata_synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Upstream's own last-modified stamp for the matched record, naive UTC.
    # Distinct from metadata_synced_at, which is when WE last read it.
    upstream_updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    # How upstream's catalog answers for this slug, resolved by the metadata
    # sync (services/catalog_metadata.py::resolve_upstream_state). Our
    # discovery makes one row per ct/*.sh file; upstream's PocketBase is the
    # catalog of what they consider an APP, and the two disagree in ways the
    # Store has to render differently:
    #
    #   "listed"   matched a live upstream record. The normal case.
    #   "delisted" upstream still HAS the record but flagged is_deleted, so it
    #              keeps a real name/description/logo and stays installable;
    #              the Store badges it as retired rather than hiding it.
    #   "unlisted" no upstream record at all and not a variant: the script is
    #              still in the repo but upstream dropped the app. Also badged.
    #   "variant"  an alpine-<parent> row whose parent exists upstream and
    #              which has no upstream record of its own, i.e. upstream
    #              models it as an install METHOD of the parent app rather
    #              than its own app. Kept in the catalog and installable, but
    #              hidden from the Store grid so Syncthing is one card, not
    #              two, one of them blank.
    #   "superseded" a rename leftover: unmatched upstream, not installable,
    #              and sharing a name with a row that IS listed. Upstream
    #              renamed netvisor to scanopy and left ct/netvisor.sh in the
    #              repo with no install script and an APP= line reading
    #              "Scanopy", so the grid showed two "Scanopy" cards, one
    #              working and one blank. Also hidden from the grid.
    #
    # NULL means never synced. A `deprecated` boolean used to sit beside
    # this column, dead since the first migration and never written; it was
    # dropped (c9a35b71e0d4) rather than overloaded, because a boolean
    # cannot carry five states and "deprecated" asserts a judgement
    # upstream has not made.
    # Visibility only: nothing here ever implies a type or an installability
    # decision, both of which belong to discovery and the classifier.
    upstream_state: Mapped[str | None] = mapped_column(Text)


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

# Display label from the Apprise URL scheme (doc 04 `notification_channels.kind`,
# unencrypted). This is the single source of truth for `kind`'s allowlist:
# `notifier.kind_for()` imports this dict rather than defining its own copy, and
# migration 0002 imports `ALLOWED_NOTIFICATION_KINDS` to build the DB-level
# CHECK constraint: one Python constant, never two literals that can drift.
# Tokens verified at v1.12.0 via `apprise.plugins.N_MGR.schemas()` / each
# plugin's `service_name`: not guessed. `http`/`https` are not real Apprise
# schemes (its generic-webhook plugins are the json/form/xml entries below);
# MS Teams' current scheme is `workflow(s)` (Power Automate), not `msteams`.
KIND_FROM_SCHEME = {
    "ntfy": "ntfy", "ntfys": "ntfy",
    "gotify": "gotify", "gotifys": "gotify",
    "mailto": "email", "mailtos": "email",
    "tgram": "telegram",
    "slack": "slack",
    "json": "webhook", "jsons": "webhook",
    "form": "webhook", "forms": "webhook",
    "xml": "webhook", "xmls": "webhook",
    "discord": "discord",
    "matrix": "matrix", "matrixs": "matrix",
    "mmost": "mattermost", "mmosts": "mattermost",
    "rocket": "rocketchat", "rockets": "rocketchat",
    "pover": "pushover",
    "pbul": "pushbullet",
    "signal": "signal", "signals": "signal",
    "workflow": "msteams", "workflows": "msteams",
    "twilio": "twilio",
    "whatsapp": "whatsapp",
    "zulip": "zulip",
    "apprise": "apprise", "apprises": "apprise",
    "ses": "ses",
    "sendgrid": "sendgrid",
}

# "webhook" is also `kind_for`'s fallback for an unrecognised-but-legitimate
# scheme, so it belongs in the allowlist even though it's already present as
# a value above (json/form/xml).
ALLOWED_NOTIFICATION_KINDS = frozenset(KIND_FROM_SCHEME.values()) | {"webhook"}


def notification_kind_check_sql(column: str = "kind") -> str:
    """CHECK-constraint condition text for `column`, closed over
    `ALLOWED_NOTIFICATION_KINDS`. Shared verbatim by the model's
    `__table_args__` below and migration 0002 so the DB-enforced set can
    never independently drift from the Python constant it's built from."""
    values = ", ".join(f"'{v}'" for v in sorted(ALLOWED_NOTIFICATION_KINDS))
    return f"{column} IS NULL OR {column} IN ({values})"


class NotificationChannel(TimestampMixin, Base):
    __tablename__ = "notification_channels"
    __table_args__ = (
        CheckConstraint(notification_kind_check_sql(),
                        name="ck_notification_channels_kind_allowlist"),
    )
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


class ConsoleTicket(Base):
    """Single-use, short-TTL. Only `token_hash` is stored, never the raw,
    browser-facing ticket (SessionRow's exact pattern, doc 04). `upstream_ticket`
    IS stored in the clear: it's Proxmox's own short-TTL ticket, never reaches
    the browser (doc 02 §5), and is meaningless without a live upstream socket
    to present it to within its own few-second window."""
    __tablename__ = "console_tickets"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[int] = mapped_column(Integer, nullable=False)
    node: Mapped[str] = mapped_column(Text, nullable=False)
    guest_kind: Mapped[str | None] = mapped_column(Text)
    vmid: Mapped[int | None] = mapped_column(Integer)
    upstream_user: Mapped[str] = mapped_column(Text, nullable=False)
    upstream_ticket: Mapped[str] = mapped_column(Text, nullable=False)
    upstream_port: Mapped[str] = mapped_column(Text, nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime)


class EntitlementCache(TimestampMixin, Base):
    __tablename__ = "entitlement_cache"
    id: Mapped[int] = mapped_column(primary_key=True)  # always 1
    token: Mapped[str | None] = mapped_column(Text)  # Fernet ciphertext, base64 str
    # NOT encrypted, unlike token: a cert is a signed public key, public by
    # construction (handed to every install), so encrypting it buys nothing
    # and adds a way for a master-key problem to take out verification.
    cert: Mapped[str | None] = mapped_column(Text)
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


class NotificationDismissal(TimestampMixin, Base):
    """One row per user: the bell tray's server-side memory of what has
    already been cleared, so a clear survives a reload, a reboot, and a
    login from a different browser or machine (a per-user fact, not a
    per-browser one -- see docs/notes/persist-cleared-notifications-report.md).

    `cleared_through_job_id` is a watermark, not a growing list: "clear all"
    records the highest job id that existed at the moment of the clear, and
    every job at or below it counts as dismissed from then on, however many
    thousands of jobs that eventually covers. Job ids are a strictly
    increasing sequence (autoincrement primary key on `jobs`), so a job
    created AFTER a clear always has an id above the watermark and is never
    swallowed by it.

    `dismissed_job_ids` covers what the watermark cannot: a single item
    dismissed by its own card, whose job id is above the watermark. It stays
    bounded because the next "clear all" moves the watermark up past it and
    the id gets pruned back out (see services/notification_dismissals.py).
    """
    __tablename__ = "notification_dismissals"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True)
    cleared_through_job_id: Mapped[int | None] = mapped_column(Integer)
    dismissed_job_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
