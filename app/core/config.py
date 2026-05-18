"""
App-level settings read from environment variables.
Operational config (TAK URL, credentials) is stored in SQLite, not here.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"

    # Data directory (DB + uploaded certs)
    data_dir: Path = Path("data")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "config.db"

    @property
    def certs_dir(self) -> Path:
        return self.data_dir / "certs"

    @property
    def packages_dir(self) -> Path:
        return self.data_dir / "packages"

    # CORS
    cors_origins: list[str] = ["*"]

    # Debug
    debug: bool = False

    # Auth — when False, skip Authentik header check and treat all callers as admin.
    # Intended for private LAN / single-operator deploys without a forward-auth proxy.
    auth_enabled: bool = True


settings = Settings()
