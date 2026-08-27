from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# PROXPLOY_ENV picks the domain pair below (dev is the default when unset or
# empty); an explicit PROXPLOY_API_BASE_URL / PROXPLOY_RELEASE_CHANNEL_URL
# always wins over these maps, so they only decide what happens when nobody
# said otherwise.
#
# install.sh carries the same two-row table in its WEB_BASE_URL case, because
# it has to resolve the install URL before any of this Python exists. Those
# two are the ONLY places either domain is written down: adding a third
# environment is one line in each, never a search-and-replace.
API_BASE_URL_BY_ENV: dict[str, str] = {
    "dev": "https://api.proxploy.dev",
    "prod": "https://api.proxploy.com",
}
WEB_BASE_URL_BY_ENV: dict[str, str] = {
    "dev": "https://web.proxploy.dev",
    "prod": "https://proxploy.com",
}


def _release_channel_url(env: str) -> str:
    """Where `proxploy-update` and services/updater.py look for a release.

    The same site that serves install.sh, under a path holding the newest
    manifest.json, manifest.json.sig and tarball. Deliberately not GitHub
    Releases: the source repo is private, and private release assets need an
    authenticated fetch that an installer has no credential for.
    """
    base = WEB_BASE_URL_BY_ENV.get(env, WEB_BASE_URL_BY_ENV["dev"])
    return f"{base}/releases/latest"


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
    license_heartbeat_interval_s: float = 3600.0    # 1h, token exp is 72h
    # After this long without reaching the service, refuse to keep renewing
    # on the cached token alone. Well beyond grace_until, so it only bites an
    # install that has been unreachable for a season, which is the backstop
    # against permanently-offline copies rather than a check on outages.
    license_revalidation_days: float = 90.0

    poll_enabled: bool = True
    # 5s, not 30s: guest CPU/mem/status/net counters (and the rates diffed from
    # them) are as fresh as this. Node net throughput (PVE RRD, 60s buckets)
    # and MetricSample recording (30s) deliberately stay coarser — see
    # pollers/__init__.py.
    poll_interval_s: float = 5.0
    poll_timeout_s: float = 20.0
    console_ticket_ttl_s: float = 30.0
    console_idle_timeout_s: float = 1800.0
    # An ISO is spooled to `data_dir/uploads` on its way to PVE (api/storage.py),
    # so this caps BOTH the request body and the transient free disk the
    # Proxploy host must have. 16 GiB covers a Windows Server ISO with room.
    storage_upload_max_bytes: int = 16 * 1024 ** 3
    # Wall-clock ceiling for Phase 6 handlers passed to pvetask.await_task.
    # 3600s (1h), not lifecycle's 300s: these are disk-copy-bound (vm.clone,
    # backup.run/restore/prune, storage.upload), so multi-hundred-GB clones
    # need far more than five minutes.
    pve_task_timeout_s: float = 3600.0
    backup_sync_stale_s: float = 900.0
    # The scheduler tick is the resolution floor: a cron expression cannot be
    # finer than one minute, so 30s is already twice as often as it needs to be.
    scheduler_enabled: bool = True
    scheduler_tick_s: float = 30.0
    # Alert evaluation rides the poll cycle (services/alerts.py); off means the
    # poller still writes samples, nothing evaluates them.
    alerts_enabled: bool = True
    # OIDC JIT provisioning. None (default) is fail-closed: first sign-in mints
    # no team_members row and leaves is_active=False, so (authz deriving every
    # permission from team_members) the account can do nothing until an admin
    # activates it — deny with an explanation, not a silent lockout. Set a role
    # to opt into auto-provisioning; validated against ROLE_ORDER and raises
    # loudly on an unknown value.
    oidc_default_role: str | None = None
    oidc_default_team_slug: str = "default"
    # How long a pending-2FA token stays redeemable before the user re-logs in.
    # Kept short: this is a live login in progress, not a remember-me window.
    totp_pending_ttl_s: float = 300.0
    # Migration preflight: the only number assumed rather than measured (the
    # rest comes from a live PVE call); 80 MB/s is a conservative LAN figure,
    # and the job reports MEASURED downtime once it runs.
    migrate_assumed_bps: float = 80e6
    # Base URL holding manifest.json, manifest.json.sig and the tarball.
    # Defaults from `env` (see _release_channel_url); an explicit
    # PROXPLOY_RELEASE_CHANNEL_URL keeps winning, which is how the harnesses
    # point it at a file:// directory so no test needs the network.
    release_channel_url: str | None = None
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
    def _default_urls_from_env(cls, data: Any) -> Any:
        # Runs on the merged-but-unvalidated settings sources: if the caller
        # (init kwarg or PROXPLOY_API_BASE_URL) already supplied a value it
        # is left untouched. `env`'s own Literal validation still runs after
        # this and raises on an invalid value, regardless of what default we
        # pick here.
        if not isinstance(data, dict):
            return data
        env = data.get("env", "dev")
        if data.get("api_base_url") is None:
            data = {**data, "api_base_url": API_BASE_URL_BY_ENV.get(env, API_BASE_URL_BY_ENV["dev"])}
        if data.get("release_channel_url") is None:
            data = {**data, "release_channel_url": _release_channel_url(env)}
        return data


@lru_cache
def get_settings() -> Settings:
    return Settings()
