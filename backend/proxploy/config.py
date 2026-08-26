from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# PROXPLOY_ENV picks the default API base URL below (dev is the default when
# unset or empty); an explicit PROXPLOY_API_BASE_URL always wins over this
# map, so the map only decides what happens when nobody said otherwise.
API_BASE_URL_BY_ENV: dict[str, str] = {
    "dev": "https://api.proxploy.dev",
    "prod": "https://api.proxploy.com",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PROXPLOY_")

    # Invalid values must raise at startup, not fall back: this is config at
    # a trust boundary, and a typo here must not silently point prod at dev.
    env: Literal["dev", "prod"] = "dev"
    db_url: str = "sqlite:///./data/proxploy.db"
    data_dir: Path = Path("./data")
    master_key_file: Path = Path("./data/master.key")
    session_cookie: str = "pp_session"
    # "Remember this device": how long a browser that has already proved the
    # second factor may skip the code step.
    trusted_cookie: str = "pp_trusted"
    trusted_device_ttl_days: int = 30
    csrf_cookie: str = "pp_csrf"
    session_ttl_hours: int = 168
    cookie_secure: bool = False  # installer flips on when TLS terminates at the app
    # Default derives from `env` (see API_BASE_URL_BY_ENV below); an explicit
    # PROXPLOY_API_BASE_URL keeps winning over that map. None here just means
    # "not explicitly set yet"; the validator below always resolves it.
    api_base_url: str | None = None
    # Trusts one more ROOT that can bless any signer, not one more signer
    # directly: a materially stronger grant than the old ent_extra_keys_file
    # name implied, hence the rename rather than a back-compat alias.
    ent_extra_roots_file: Path | None = None
    # GlitchTip (Sentry protocol) DSN for the `proxploy-app` project on
    # errors.aspyrelabs.com. Empty by default and it must STAY empty by
    # default: this app runs on someone else's hardware managing their
    # infrastructure, so crash reports leaving their network is their decision
    # to make, not a shipped default. The installer does not set it; an
    # operator who wants to send us crashes adds it to
    # /etc/proxploy/proxploy.env deliberately.
    sentry_dsn: str = ""
    # How old the App Store cache may get before the UI calls it stale (doc 01
    # "staleness indicator"). The catalog.refresh system schedule runs daily at
    # 04:00 UTC, so 48h means "two consecutive refreshes have not landed",
    # which is a real fault rather than one unlucky night.
    catalog_stale_after_s: float = 172800.0
    # Licensing lease. The heartbeat is what tells the service which
    # installation currently holds the seat, so it also bounds how long a
    # clone can run unnoticed. Configurable rather than scattered through the
    # code because the right value depends on how tolerant of an outage the
    # deployment needs to be.
    license_heartbeat_interval_s: float = 21600.0   # 6h, token exp is 72h
    # After this long without reaching the service, refuse to keep renewing
    # on the cached token alone. Well beyond grace_until, so it only bites an
    # install that has been unreachable for a season, which is the backstop
    # against permanently-offline copies rather than a check on outages.
    license_revalidation_days: float = 90.0

    poll_enabled: bool = True
    # 5s, not 30s. Everything a cycle reads out of /cluster/resources (node and
    # guest CPU, memory, status, and the guest netin/netout counters the guest
    # rates are diffed from) is as fresh as this number, so the tables and
    # cards move at 5s now. The two things that do NOT are deliberate and live
    # in pollers/__init__.py: node network throughput comes from PVE's RRD,
    # which buckets at 60s and cannot go faster whatever we do here, and
    # MetricSample recording stays on 30s so the charts' storage does not grow
    # sixfold to draw the same lines.
    poll_interval_s: float = 5.0
    poll_timeout_s: float = 20.0
    console_ticket_ttl_s: float = 30.0
    console_idle_timeout_s: float = 1800.0
    # An ISO is spooled to `data_dir/uploads` on its way to PVE (api/storage.py),
    # so this caps BOTH the request body and the transient free disk the
    # Proxploy host must have. 16 GiB covers a Windows Server ISO with room.
    storage_upload_max_bytes: int = 16 * 1024 ** 3
    # Wall-clock ceiling every Phase 6 job handler passes to
    # services/pvetask.py::await_task. services/lifecycle.py keeps its own
    # module constant instead: a start/stop that needs five minutes is a
    # different animal from a restore that needs fifty, and lifecycle's
    # timeout is already exercised by tests that monkeypatch it.
    # 3600s (1h), not lifecycle's 300s: every Phase 6 handler that reaches
    # this setting is disk-copy-bound (vm.clone, backup.run/restore/prune,
    # storage.upload) rather than a status flip, and a multi-hundred-GB clone
    # or vzdump routinely needs far longer than five minutes. 300s was
    # inherited from TASK_TIMEOUT_S's start/stop-shaped default and never
    # revisited for these: see BLOCKING 4 in the Phase 6 final review.
    pve_task_timeout_s: float = 3600.0
    backup_sync_stale_s: float = 900.0
    # Scheduler (doc 10 Phase 7). The tick is the resolution floor: a cron
    # expression cannot be finer than one minute, so 30s is already twice as
    # often as it needs to be and costs one indexed SELECT.
    scheduler_enabled: bool = True
    scheduler_tick_s: float = 30.0
    # Alert evaluation rides the poll cycle (services/alerts.py); off means the
    # poller still writes samples, nothing evaluates them.
    alerts_enabled: bool = True
    # OIDC JIT provisioning policy (doc 10 Task 10 + gap review). An IdP's user
    # population is not automatically the application's authorized population
    #, auto-admitting every directory identity is the accidental-access
    # failure mode. None (default) means a first-time OIDC sign-in provisions
    # the user but mints NO team_members row and leaves is_active=False: since
    # services/authz.py derives every permission from team_members and is
    # fail-closed, that account can do nothing until an admin activates it and
    # assigns a role through the existing users/teams API: deny-with-an-
    # explanation, not a silent lockout. Set this to opt into auto-provisioning
    # a real role instead; validated against ROLE_ORDER at first use
    # (services/oidc.py) and raises loudly (never silently falls back) on an
    # unknown value.
    oidc_default_role: str | None = None
    oidc_default_team_slug: str = "default"
    # Task 9: how long a pending-2FA token (issued by password-correct login
    # for a totp_enabled user) stays redeemable at POST /auth/totp before it
    # must be discarded and the user re-logs in with their password. Kept
    # short: this is a live login in progress, not a remember-me window.
    totp_pending_ttl_s: float = 300.0
    # Migration preflight (doc 08 §14, doc 11 §2): the only number honesty lets
    # us assume rather than measure: everything else in the estimate (transfer
    # size, strategy) comes from a live PVE call. 80 MB/s is a conservative LAN
    # sustained-transfer figure; the job itself reports MEASURED downtime once
    # it runs (services/migrate.py's est_note says so explicitly).
    migrate_assumed_bps: float = 80e6
    # Phase 9a. The release channel is a base URL holding manifest.json,
    # manifest.json.sig and the tarball. https:// in production; the test
    # harnesses point it at a file:// directory so no test ever needs the
    # network or a real release.
    release_channel_url: str = "https://github.com/aspyrelabs/proxploy-app/releases/latest/download"
    release_pubkey_file: Path | None = None   # None = the key shipped in the package
    # Set by the installer in /etc/proxploy/proxploy.env. Unset means a dev
    # checkout: check works, apply refuses, because there is no managed
    # layout to switch.
    install_shape: str | None = None
    update_script: Path = Path("/opt/proxploy/bin/proxploy-update")
    update_timeout_s: float = 600.0
    # Written by the installer from inside the CT it creates, so
    # services/selfguard.py can recognise Proxploy's own container.
    self_ctid: int | None = None

    @model_validator(mode="before")
    @classmethod
    def _default_api_base_url(cls, data: Any) -> Any:
        # Runs on the merged-but-unvalidated settings sources: if the caller
        # (init kwarg or PROXPLOY_API_BASE_URL) already supplied a value it
        # is left untouched. `env`'s own Literal validation still runs after
        # this and raises on an invalid value, regardless of what default we
        # pick here.
        if isinstance(data, dict) and data.get("api_base_url") is None:
            env = data.get("env", "dev")
            data = {**data, "api_base_url": API_BASE_URL_BY_ENV.get(env, API_BASE_URL_BY_ENV["dev"])}
        return data


@lru_cache
def get_settings() -> Settings:
    return Settings()
