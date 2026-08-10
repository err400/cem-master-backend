import os
from functools import lru_cache


class Settings:
    def __init__(self) -> None:
        self.app_name = "CEM Master Backend"
        self.database_url = os.getenv("DATABASE_URL", "sqlite:///./cem_master.db")
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
