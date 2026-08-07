from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """The Pentagon — ZugaShield's security-posture dashboard.

    port 8019 here is the source of truth — PORT_REGISTRY.md points at this line.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "The Pentagon"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8019

    # Dashboard SQLite file. Relative paths resolve against the backend dir so
    # `python -m uvicorn main:app` from backend/ and launchd (WorkingDirectory
    # = backend dir) agree on the location.
    pentagon_db_path: str = "data/pentagon.db"

    # --- upstream data sources ---
    # AgentPool's write-time rail — the only LIVE, persisted block/allow counter
    # in the fleet today (SQLite-backed, public GET, no auth).
    agentpool_base_url: str = "https://agentpool-mcp-production.up.railway.app"

    # ZugaShield repo root (this file lives at <repo>/dashboard/backend/config.py,
    # so the repo is two parents up). The catalog + version collectors read files
    # from here; overridable in case the dashboard runs detached from the repo.
    zugashield_repo_path: str = ""

    # GitHub repo the security issues live in (open-vulns collector).
    github_repo: str = "Zuga-Technologies/ZugaShield"

    # A collector whose last successful run is older than this reads as stale.
    stale_after_seconds: int = 1800

    # Write auth for POST /api/pentagon/redteam-run. When set, the endpoint
    # requires a matching X-Pentagon-Key header (so red-team coverage can't be
    # forged by anyone who can reach the public URL). Empty = open (dev only).
    pentagon_write_key: str = ""

    @property
    def db_path(self) -> Path:
        p = Path(self.pentagon_db_path)
        if not p.is_absolute():
            p = Path(__file__).resolve().parent / p
        return p

    @property
    def repo_path(self) -> Path:
        if self.zugashield_repo_path:
            return Path(self.zugashield_repo_path)
        # <repo>/dashboard/backend/config.py -> <repo>
        return Path(__file__).resolve().parents[2]


settings = Settings()
