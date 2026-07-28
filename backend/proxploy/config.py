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


@lru_cache
def get_settings() -> Settings:
    return Settings()
