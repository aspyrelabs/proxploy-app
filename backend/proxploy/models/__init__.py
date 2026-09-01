"""All Proxploy entities, portable SQLite/Postgres subset."""
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


def to_iso(dt: datetime | None) -> str | None:
    """The one way to serialize a datetime for an API response.

    Every timestamp column here is stored as naive UTC (see utcnow above), so
    a bare dt.isoformat() carries no offset, and a browser's `new Date("...")`
    reads an offset-less string as LOCAL time. That silently shifts every
    timestamp in the UI by the viewer's own timezone. Naive input gets a
    literal "Z" appended. A value that already carries a timezone is left as
    isoformat() renders it, so this never double-suffixes. None stays None.
    """
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.isoformat()
    return dt.isoformat() + "Z"


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )



class User(TimestampMixin, Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(Text)
    password_hash: Mapped[str | None] = mapped_column(Text)
    totp_secret_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Time step of the last code accepted for this user, so the same code
    # cannot be presented twice inside its validity window (RFC 6238 5.2).
    totp_last_step: Mapped[int | None] = mapped_column(BigInteger)
    oidc_issuer: Mapped[str | None] = mapped_column(Text)
    oidc_sub: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Reset to 0 on any successful login. `locked_until` in the future is the
    # only thing that refuses one, so clearing it is what unlocks an account.
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0,
                                                    server_default="0", nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)
    __table_args__ = (Index("ux_users_oidc", "oidc_issuer", "oidc_sub", unique=True),)


class TotpRecoveryCode(Base):
    """One row per recovery code. A real column rather than packing these into
    `users.totp_secret_enc`, so burning a code is an ordinary UPDATE and never
    a decrypt-mutate-re-encrypt of a blob shared with a concurrent TOTP
    verify. `code_hash_enc` is the argon2 hash (never the raw code)
    Fernet-encrypted at rest via SecretStore, same as `totp_secret_enc`.
    Burning sets `used_at`; the atomic single-use guarantee is
    `UPDATE ... WHERE id = ? AND used_at IS NULL`
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


class TrustedDevice(TimestampMixin, Base):
    """A browser that has already proved the second factor, so the code step
    can be skipped on this device until `expires_at`.

    Same shape as `sessions` above and hashed the same way
    (services/authn.py::_th): a second, subtly different set of rules around a
    credential that BYPASSES two-factor is exactly where a hole opens.

    It is not a session and cannot become one. `resolve_session` reads the
    sessions table only, so this token grants nothing on its own: it is
    checked after a password has already been verified, and the most it can do
    is skip the code. Bound to `user_id`, so a device trusted for one account
    cannot skip the second factor on another.
    """
    __tablename__ = "trusted_devices"
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
    node_shell_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Whether the stored token lacks Sys.PowerMgmt (host reboot/power off),
    # recomputed at enrolment and by POST /hosts/{id}/test, same idiom as
    # last_error above. NULL means "not checked yet", distinct from False
    # ("checked, and granted"), so a host enrolled before this existed reads as
    # unknown rather than a false "granted". Informational only: never used to
    # refuse a power attempt, only to warn ahead of one (services/pveum.py
    # NODE_POWER_PRIVILEGE).
    node_power_missing: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Whether this host's cluster has quorum, read off the `quorate` field of
    # its /cluster/status cluster row every poll cycle. NULL for a standalone
    # node (no cluster row, so the question does not apply) and for a host not
    # polled since this existed; False ONLY when PVE said so.
    #
    # A health fact, not a privilege one: without quorum /etc/pve is read-only,
    # so every install, storage edit and guest config write fails, while
    # /cluster/resources and /version keep answering perfectly and every host
    # still reads `connected`. That is the lie this column stops telling.
    quorate: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # {capability: [missing privilege, ...]}, {} when every configured token is
    # fully granted, NULL when never probed. A capability mapped to null means
    # PVE refused /access/permissions for that token: "could not tell", not
    # clean. Refreshed by the poll loop on a slow cadence and by
    # POST /hosts/{id}/test, because a role gains privileges over time and an
    # old token's only other symptom is a 403 mid-job.
    capability_gaps: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))
    # When this host's operator acknowledged that installs run third-party
    # scripts as root here. Per host rather than per install: the acknowledgement
    # is about the host, and re-asking on every install is friction that
    # surfaces no new information. NULL means not acknowledged.
    install_consent_at: Mapped[datetime | None] = mapped_column(DateTime)


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



class InstallAnswer(TimestampMixin, Base):
    """An operator's answers to an install script's unguarded prompts, encrypted.

    Why a row rather than `jobs.params`: enqueue() redacts params by KEY NAME,
    and the names here come from whoever wrote the upstream community-scripts
    installer, not from us. Measured against the real catalog on 2026-08-27,
    11 of 15 prompts asking for something sensitive have a name the heuristic
    misses, including an admin password in `ziti_pwd` and an enrollment JWT in
    a variable called `prompt`. So the value never enters params at all; params
    carries `handle` and nothing else, and there is nothing left to redact.

    `app_id` is NULL until the install succeeds, because app.install is what
    CREATES the app: the row is staged by the route, bound to the app it built,
    and swept if that never happens. Same shape as the `spool_path` an upload
    route stages for its job, kept in the database instead of on disk because
    this is a secret.

    Kept after the install rather than deleted, because app.update re-runs the
    same script and hits the same prompts. An answer the operator gave once
    should not have to be typed again to apply a patch release.
    """
    __tablename__ = "install_answers"
    id: Mapped[int] = mapped_column(primary_key=True)
    handle: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    app_id: Mapped[int | None] = mapped_column(
        ForeignKey("apps.id", ondelete="CASCADE"), index=True)
    encrypted_blob: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class App(TimestampMixin, Base):
    __tablename__ = "apps"
    id: Mapped[int] = mapped_column(primary_key=True)
    host_id: Mapped[int] = mapped_column(ForeignKey("hosts.id", ondelete="RESTRICT"))
    # Physical column is `ct_id`: `ctid` is a PostgreSQL system column present
    # on every table, so `CREATE TABLE apps (... ctid ...)` is rejected outright
    # (`column name "ctid" conflicts with a system column name`). The Python
    # attribute, the API field and the frontend type all stay `ctid`.
    ctid: Mapped[int] = mapped_column("ct_id", Integer, nullable=False)
    # The node the CT actually runs on, refreshed every poll cycle. Before this
    # existed it was assumed to be the host's node, which is true while installs
    # pick the host and the migration handler repoints the row, and wrong the
    # moment a CT is migrated in the Proxmox UI instead. NULL falls back to
    # Host.node_name, so an unpolled row behaves exactly as before.
    node_name: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    catalog_slug: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    icon_initials: Mapped[str | None] = mapped_column(Text)
    icon_colors: Mapped[dict | None] = mapped_column(JSON)
    web_port: Mapped[int | None] = mapped_column(Integer)
    # NULL means nobody has told Proxploy, so the app itself is asked at open
    # time (services/webui.py). It was NOT NULL defaulting to "http", which
    # made every app claim plain HTTP as if someone had chosen it, and sent
    # the operator to http:// for the apps that only speak https.
    web_protocol: Mapped[str | None] = mapped_column(Text)
    # The URL the install script printed about itself, captured when the
    # install job finished (services/appstore.py). Kept whole and kept SEPARATE
    # from the three fields above, which is what makes "never overwrite what
    # the operator set" structural rather than a check that can be got wrong:
    # nothing derived from a log is written into a field a person owns. It is
    # evidence, so it is stored as the installer stated it.
    installed_url: Mapped[str | None] = mapped_column(Text)
    web_path: Mapped[str] = mapped_column(Text, default="/", nullable=False)
    status_cached: Mapped[str | None] = mapped_column(Text)
    ip_cached: Mapped[str | None] = mapped_column(Text)
    cpu_pct_cached: Mapped[float | None] = mapped_column(Float)
    mem_bytes_cached: Mapped[int | None] = mapped_column(BigInteger)
    uptime_s_cached: Mapped[int | None] = mapped_column(Integer)
    # Storage and network for the card, the table and the icon grid. All from
    # the /cluster/resources row the poller already parses, so none of this
    # costs a PVE call.
    disk_bytes_cached: Mapped[int | None] = mapped_column(BigInteger)
    disk_total_bytes_cached: Mapped[int | None] = mapped_column(BigInteger)
    # netin/netout are counters since the container booted, not rates. The raw
    # readings are kept because the next cycle's diff needs them, and
    # net_sampled_at because the gap between two cycles is not poll_interval_s:
    # the poll loop backs off exponentially on a failing host.
    # TimestampMixin.updated_at cannot stand in either, since any other write
    # to this row would move it and silently shorten the window.
    net_in_cached: Mapped[int | None] = mapped_column(BigInteger)
    net_out_cached: Mapped[int | None] = mapped_column(BigInteger)
    net_in_bps_cached: Mapped[float | None] = mapped_column(Float)
    net_out_bps_cached: Mapped[float | None] = mapped_column(Float)
    net_sampled_at: Mapped[datetime | None] = mapped_column(DateTime)
    update_available: Mapped[str | None] = mapped_column(Text)
    adopted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # When the poller first failed to find this app's CT in a cycle it was
    # willing to trust (pollers._absence_is_trustworthy). NULL means "last seen
    # present". Non-NULL is a countdown, not a verdict: the row is reaped only
    # once the absence survives APP_REAP_AFTER_S of further trustworthy cycles,
    # and any cycle that finds the CT again clears it back to NULL.
    missing_since: Mapped[datetime | None] = mapped_column(DateTime)
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
    # The node the guest actually RUNS on, which is not the polling host's node
    # on a cluster: /cluster/resources answers for the whole cluster from any
    # member. NULL means "not polled since this column existed"; callers fall
    # back to Host.node_name, which is the behaviour that predates it.
    node_name: Mapped[str | None] = mapped_column(Text)
    # A PVE TEMPLATE, per /cluster/resources' own flag. PVE allows a linked
    # clone only from one of these, and without knowing, the UI offered Linked
    # on every guest and PVE refused every time. NULL means not polled since
    # this column existed and is treated as "not a template".
    template: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    name: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text)
    # PVE's RAW ostype off the guest config ("l26", "win11", "w2k19",
    # "other"), never a collapsed "linux"/"windows": the client maps it for
    # display and the specific value is not recoverable once discarded. Read
    # once per VM by pollers._refresh_os_type, since an ostype is set at
    # creation and does not drift. NULL means not read yet, or a config read
    # PVE refused.
    os_type: Mapped[str | None] = mapped_column(Text)
    cpu_cores: Mapped[int | None] = mapped_column(Integer)
    # USED and ALLOCATED, in that order, and read the pair carefully: until
    # migration a1f4d80c3e69 this table had `mem_bytes` and `disk_bytes` and
    # both held the ALLOCATION (PVE's maxmem/maxdisk), while the identically
    # named columns on App held USAGE. The names now mean what they mean on
    # App, everywhere, and the allocation moved to the explicit
    # `*_total_bytes` columns beside them.
    mem_bytes: Mapped[int | None] = mapped_column(BigInteger)
    mem_total_bytes: Mapped[int | None] = mapped_column(BigInteger)
    # disk_bytes comes from the QEMU guest agent, not from /cluster/resources:
    # that row's `disk` is routinely 0 for a VM because the hypervisor sees a
    # block device and cannot see the filesystem on it. NULL is therefore the
    # normal, permanent state for a VM with no agent installed, and it is not
    # an error. disk_total_bytes is maxdisk and needs no agent.
    disk_bytes: Mapped[int | None] = mapped_column(BigInteger)
    disk_total_bytes: Mapped[int | None] = mapped_column(BigInteger)
    # Exactly App's column names, because pollers._update_net_rates writes
    # these by attribute and is shared between the two, and the same meaning
    # too: see the note on App.net_in_cached.
    net_in_cached: Mapped[int | None] = mapped_column(BigInteger)
    net_out_cached: Mapped[int | None] = mapped_column(BigInteger)
    net_in_bps_cached: Mapped[float | None] = mapped_column(Float)
    net_out_bps_cached: Mapped[float | None] = mapped_column(Float)
    net_sampled_at: Mapped[datetime | None] = mapped_column(DateTime)
    uptime_s: Mapped[int | None] = mapped_column(Integer)
    # Whether this VM's QEMU guest agent is installed and answering, the same
    # probe disk_bytes above comes from (see ProxmoxClient.agent_fsinfo).
    # THREE-valued, and the three have to stay apart because the distinction is
    # the entire value of the column:
    #   True  the agent answered.
    #   False Proxmox says this guest has no working agent. A real finding an
    #         operator can act on, and the reason disk_bytes is NULL for this
    #         VM: install the agent and both fill in.
    #   NULL  nobody knows. Never probed, or stopped (a guest that is not
    #         running cannot answer, and recording "not installed" for it would
    #         be a claim we did not make), or the host was unreachable.
    guest_agent_ok: Mapped[bool | None] = mapped_column(Boolean)
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
    # progress pings (services/catalog_telemetry.py documents why at length).
    # None means we have never had a number for this slug, which is different
    # from 0 and must stay different: telemetry is opt-in upstream, so absence
    # is silence, not evidence that nobody runs it.
    popularity: Mapped[int | None] = mapped_column(Integer)
    # When WE last read that number. Its own column because upstream caches
    # these aggregates for 23h, so the value can be a full day old and moves
    # in jumps; the Store labels it "as of" rather than implying it is live.
    popularity_synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Upstream's own dates for the SCRIPT: first published, last changed.
    # Distinct from `synced_at` (when we last discovered the row), `updated_at`
    # (when this DB row changed) and `upstream_updated_at` (when the PocketBase
    # RECORD was last edited, which a description fix bumps). Real columns
    # rather than reads out of raw["metadata"] because the Store SORTS on them,
    # and an ORDER BY over json_extract is neither indexable nor cheap.
    # `index=True` matches the indexes migration a4d70e9c31b8 already created
    # (`ix_catalog_entries_script_created` / `_updated`), so `alembic check`
    # stops proposing to drop two indexes the Store's sorts depend on.
    script_created: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    script_updated: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    # The tags community-scripts shows on a card. All FOUR are tri-state and
    # the third state is load bearing: NULL means WE DO NOT KNOW, never "no".
    # An `unlisted` row has no upstream record at all, so rendering it as "not
    # ARM" or "not updateable" would be a claim nothing supports; the UI must
    # show no chip there rather than a negative one.
    has_arm: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    updateable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    privileged: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    port: Mapped[int | None] = mapped_column(Integer)
    # Local icon mirror (services/catalog_icons.py), so the Store renders its
    # icons with no network at all. `icon_url` keeps upstream's URL, which is
    # what the sync writes and what the API falls back to.
    #
    # `icon_cache_path` is a BARE FILENAME relative to data_dir/icons, never a
    # path: it is built from our own slug plus an extension allowlist, and
    # api/catalog.py re-checks containment before opening it.
    # `icon_cache_source` is the upstream URL the cached bytes came FROM, which
    # is what makes a logo change detectable: when it stops matching
    # `icon_url`, the file is refetched rather than served forever.
    icon_cache_path: Mapped[str | None] = mapped_column(Text)
    icon_cache_source: Mapped[str | None] = mapped_column(Text)
    icon_cache_etag: Mapped[str | None] = mapped_column(Text)
    icon_cached_at: Mapped[datetime | None] = mapped_column(DateTime)
    # The evidence behind has_arm, e.g. ["amd64", "arm64"]. Kept alongside the
    # boolean rather than instead of it: the flag is what a chip renders, the
    # list is what an "arm64 only" answer needs, and deriving one from the
    # other at read time would put upstream's vocabulary into our query layer.
    architectures: Mapped[list | None] = mapped_column(JSON)
    upstream_sha: Mapped[str | None] = mapped_column(Text)
    raw: Mapped[dict | None] = mapped_column(JSON)
    # Tri-state on purpose (see the services/catalog.py header note): None
    # means "discovered but not yet classified", the state every ct/ row starts
    # in after a refresh. Discovery is 2 GitHub API calls flat and never
    # fetches a script pair; classification happens lazily, on card-open or
    # install-attempt, or via the low-priority backlog job.
    installable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    unsupported_reason: Mapped[str | None] = mapped_column(Text)
    # What the install script asks a human, recovered by
    # services/classifier.extract_prompts. Written in the SAME pass that sets
    # `installable` and against the same `upstream_sha`, so the verdict and the
    # questions behind it can never describe different versions of the script.
    # An install pins that sha too, which is what makes a positional-free,
    # variable-keyed answer safe: the script we ask about is the script we run.
    # NULL means never classified; [] means classified and it asks nothing.
    prompts: Mapped[list | None] = mapped_column(JSON)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Which upstream directory this came from: ct/vm/tools-pve/tools-addon/
    # turnkey, mechanical per the repo's own layout (services/catalog.py's
    # discover_tree). Only "ct" is ever installable or shown in the Store.
    entry_type: Mapped[str] = mapped_column(Text, nullable=False, default="ct")
    # Provenance for the presentation-only fields (name, description, category,
    # icon_url, website, docs_url) that services/catalog_metadata.py syncs from
    # upstream. "pocketbase" for the live source, "archive" for the frozen
    # cold-start fallback, either with a "-name-match" suffix when the row was
    # joined by normalized NAME rather than by slug (resolve_name_matches).
    # The suffix exists so a heuristic join is visible on the row itself, not
    # only in a log line.
    #
    # Both timestamps null is a NORMAL state, not an error: no upstream record
    # matched this slug. Such a row keeps its discovery-derived name and its
    # catalog_categories.py heuristic category and renders without a
    # description or icon.
    metadata_source: Mapped[str | None] = mapped_column(Text)
    metadata_synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Upstream's own last-modified stamp for the matched record, naive UTC.
    # Distinct from metadata_synced_at, which is when WE last read it.
    upstream_updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    # How upstream's catalog answers for this slug, resolved by the metadata
    # sync (services/catalog_metadata.py::resolve_upstream_state). Discovery
    # makes one row per ct/*.sh file; upstream's PocketBase is the catalog of
    # what THEY consider an app, and the two disagree in ways the Store has to
    # render differently:
    #
    #   "listed"     matched a live upstream record. The normal case.
    #   "delisted"   the record is there but flagged is_deleted, so it keeps a
    #                real name, description and logo and stays installable;
    #                the Store badges it as retired rather than hiding it.
    #   "unlisted"   no upstream record at all and not a variant: the script is
    #                still in the repo but upstream dropped the app. Also
    #                badged.
    #   "variant"    an alpine-<parent> row whose parent exists upstream and
    #                which has no record of its own, i.e. upstream models it as
    #                an install METHOD of the parent app. Kept in the catalog
    #                and installable, but hidden from the Store grid so
    #                Syncthing is one card, not two with one of them blank.
    #   "superseded" a rename leftover: unmatched upstream, not installable,
    #                and sharing a name with a row that IS listed. Also hidden
    #                from the grid.
    #
    # NULL means never synced. Visibility only: nothing here ever implies a
    # type or an installability decision, both of which belong to discovery and
    # the classifier.
    upstream_state: Mapped[str | None] = mapped_column(Text)



class Job(TimestampMixin, Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, default="queued", nullable=False)
    target_type: Mapped[str | None] = mapped_column(Text)
    target_id: Mapped[int | None] = mapped_column(Integer)
    # The name of the thing this job is about, read when the job is created.
    # Stored rather than looked up at render time because the destructive jobs
    # are exactly the ones whose row is gone by the time anyone reads the
    # history: "vm 3" a month after the delete names nothing anybody remembers.
    # NULL on older jobs and on targets with no name a person would recognise;
    # both render the old "vm 3" way.
    target_name: Mapped[str | None] = mapped_column(Text)
    params: Mapped[dict | None] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON)
    # What the node looked like before this job dispatched an effect, and
    # whether it dispatched one at all. Read only by reconciliation, after an
    # interruption, to ask the node what actually happened. NULL means nothing
    # had left the machine yet. Not folded into `result`: that is the outcome,
    # and _finish overwrites it on success.
    checkpoint: Mapped[dict | None] = mapped_column(JSON)
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



# Display label from the Apprise URL scheme. The single source of truth for
# `kind`'s allowlist: `notifier.kind_for()` imports this dict rather than
# defining its own copy, and migration 0002 imports
# `ALLOWED_NOTIFICATION_KINDS` to build the DB-level CHECK constraint, so one
# Python constant can never become two literals that drift. Tokens verified at
# apprise v1.12.0, not guessed: `http`/`https` are not real Apprise schemes
# (its generic-webhook plugins are the json/form/xml entries below), and MS
# Teams' current scheme is `workflow(s)` (Power Automate), not `msteams`.
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
    # The individual values the guided picker collected, as encrypted JSON, so
    # an edit can prefill instead of demanding the whole lot again to correct
    # one mistyped password. No new exposure: url_enc already carries every one
    # of these under the same key. NULL for a channel added by pasting a URL.
    fields_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
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
    # The datastore's PVE type ("pbs", "nfs", "dir", ...) as it was when this
    # archive was last synced. Recorded rather than looked up, because the
    # lookup used to be poller.snapshots, which is empty between boot and the
    # first poll: api/backups.py::_refuse_on_pbs then offered a full read-back
    # of an archive PBS already verifies. sync_host_backups is handed the type
    # by PVE anyway, so it writes it down.
    storage_type: Mapped[str | None] = mapped_column(Text)
    # Which node of the host's cluster this archive is ON, which is not always
    # the node Proxploy is enrolled at. A shared datastore (PBS, NFS, CephFS)
    # answers identically from every node and records the enrolled one; a
    # node-LOCAL dump dir holds different files per node under the SAME volid,
    # so the node is what tells those apart and is part of the key below. It is
    # also the node verify and restore have to run on.
    node: Mapped[str | None] = mapped_column(Text)
    # When Proxploy last checked this archive itself (services/backupjobs.py's
    # backup.verify / backup.test_restore). `verify_state` holds the verdict
    # whoever produced it: PBS writes it through the sync when PBS is the
    # datastore, we write it when nothing else will. NULL means nobody has.
    checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    notes: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    __table_args__ = (
        # (host, node, volid), not (host, volid): `local:backup/vzdump-lxc-110
        # -a.tar.zst` is a valid volid on every node of a cluster and means a
        # different file on each, so the pair collided and one node's archives
        # silently replaced the other's.
        UniqueConstraint("host_id", "node", "volid", name="ux_backups"),
        Index("ix_backups_guest", "guest_type", "guest_vmid"),
        # api/backups.py reads the newest rows with ORDER BY taken_at DESC
        # LIMIT. Without this the limit bounds the response and not the work:
        # the whole table is sorted on every 60s poll.
        Index("ix_backups_taken_at", "taken_at"),
    )



class AuditEvent(Base):
    """Append-only, with one deliberate exception. No ORM update path exists
    anywhere in the app (doc 04), and the only delete is api/audit.py::
    clear_audit: owner-only, typed-confirmed, and it writes its own audit.clear
    row AFTER the delete so the erasure has an author (doc 08 §7)."""
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(BigPK, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    actor_type: Mapped[str] = mapped_column(Text, nullable=False)  # user|api_key|system
    actor_id: Mapped[int | None] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target_type: Mapped[str | None] = mapped_column(Text)
    target_id: Mapped[int | None] = mapped_column(Integer)
    # Same capture-at-write-time rule as Job.target_name, and it matters more
    # here: the audit trail is the permanent record, and api/audit.py could
    # only ever label a row whose target still exists.
    target_name: Mapped[str | None] = mapped_column(Text)
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
    """One row per user: the bell tray's server-side memory of what has been
    cleared, so a clear survives a reload, a reboot, and a login from another
    browser or machine (a per-user fact, not a per-browser one).

    `cleared_through_job_id` is a watermark, not a growing list: "clear all"
    records the highest job id that existed at that moment, and every job at or
    below it counts as dismissed from then on. Job ids strictly increase
    (autoincrement primary key on `jobs`), so a job created AFTER a clear
    always has an id above the watermark and is never swallowed by it.

    `dismissed_job_ids` covers what the watermark cannot: a single item
    dismissed by its own card, whose job id is above the watermark. It stays
    bounded because the next "clear all" moves the watermark past it and the id
    gets pruned back out (see services/notification_dismissals.py).
    """
    __tablename__ = "notification_dismissals"
    id: Mapped[int] = mapped_column(primary_key=True)
    # Declared here rather than as `unique=True, index=True` on the column:
    # that spelling makes SQLAlchemy derive
    # `ix_notification_dismissals_user_id`, while migration d8a1c9f4b2e6 created
    # it as `ux_notification_dismissals_user_id`, this schema's convention for a
    # unique index. Same column and same uniqueness either way; naming it here
    # is what stops `alembic check` proposing a drop-and-recreate.
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    cleared_through_job_id: Mapped[int | None] = mapped_column(Integer)
    dismissed_job_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    __table_args__ = (
        Index("ux_notification_dismissals_user_id", "user_id", unique=True),)
