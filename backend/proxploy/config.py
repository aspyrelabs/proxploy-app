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
    ent_extra_keys_file: Path | None = None
    catalog_slugs: list[str] = [
        "redis", "postgresql", "mysql", "mariadb", "mongodb",
        "jellyfin", "plex", "immich", "homeassistant", "homebridge", "zigbee2mqtt",
        "grafana", "prometheus", "uptimekuma", "gitea", "n8n",
        "pihole", "adguard", "nginxproxymanager", "wireguard",
        "docker", "paperless-ngx", "vaultwarden", "proxmox-backup-server",
    ]
    poll_enabled: bool = True
    poll_interval_s: float = 30.0
    poll_timeout_s: float = 20.0
    console_ticket_ttl_s: float = 30.0
    console_idle_timeout_s: float = 1800.0
    # An ISO is spooled to `data_dir/uploads` on its way to PVE (api/storage.py),
    # so this caps BOTH the request body and the transient free disk the
    # Proxploy host must have. 16 GiB covers a Windows Server ISO with room.
    storage_upload_max_bytes: int = 16 * 1024 ** 3
    # Wall-clock ceiling every Phase 6 job handler passes to
    # services/pvetask.py::await_task. services/lifecycle.py keeps its own
    # module constant instead — a start/stop that needs five minutes is a
    # different animal from a restore that needs fifty, and lifecycle's
    # timeout is already exercised by tests that monkeypatch it.
    pve_task_timeout_s: float = 300.0
    backup_sync_stale_s: float = 900.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
