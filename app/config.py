import os
from functools import lru_cache
from pathlib import Path


class Settings:
    def __init__(self) -> None:
        self.app_name = "CEM Master Backend"
        # Root of the compute app's data volume, shared read-only with this
        # service in the cluster. Only the indexer reads it; the API never does.
        # Optional, because the API must start without it -- a missing DATA_DIR
        # should fail the indexer, not take the whole site down.
        data_dir = os.getenv("DATA_DIR", "").strip()
        self.data_dir: Path | None = Path(data_dir).resolve() if data_dir else None
        # Base URL for FileBrowser share links, as a BROWSER must reach it --
        # e.g. http://localhost:8097. Deliberately not the compute backend's
        # FILEBROWSER_BASE_URL, which is the container-internal address
        # (http://filebrowser:80) and is unreachable from a visitor's machine.
        #
        # The compute app stores only the share hash in job.json; the URL is
        # built from it. Blank means job artifacts are listed by filename with
        # no download link, which is the correct default -- a broken link is
        # worse than an absent one.
        self.filebrowser_public_url: str = os.getenv(
            "FILEBROWSER_PUBLIC_URL", ""
        ).strip().rstrip("/")
        self.database_url = os.getenv("DATABASE_URL", "").strip()
        if not self.database_url:
            raise RuntimeError(
                "DATABASE_URL is required; point it at the PostgreSQL service named cem-database"
            )
        if self.database_url.startswith("postgresql://"):
            self.database_url = self.database_url.replace(
                "postgresql://", "postgresql+psycopg://", 1
            )
        if not self.database_url.startswith("postgresql+psycopg://"):
            raise RuntimeError("CEM Master requires a PostgreSQL DATABASE_URL")
        self.cors_origins = self._parse_cors_origins(
            os.getenv(
                "CORS_ORIGINS",
                "http://localhost:8000,http://127.0.0.1:8000,http://localhost:5500,http://127.0.0.1:5500",
            )
        )
        self.api_key = os.getenv("CEM_MASTER_API_KEY", "").strip()

    @staticmethod
    def _parse_cors_origins(value: str) -> list[str]:
        origins = [origin.strip() for origin in value.split(",") if origin.strip()]
        return origins or ["*"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
