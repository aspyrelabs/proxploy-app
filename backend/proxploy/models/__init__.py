"""All Proxploy entities — schema per docs/04-data-model.md, portable SQLite/Postgres subset."""
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
