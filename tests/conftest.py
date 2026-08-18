"""Shared test fixtures.

The suite now REQUIRES a real PostgreSQL. Two independent reasons:

1. ``app/config.py`` raises at import time unless ``DATABASE_URL`` is a
   PostgreSQL URL, and ``app/database.py`` builds the engine at module scope --
   so merely importing the application needs a valid URL and the psycopg driver.
2. The models use ``postgresql.JSONB``, which SQLite cannot create.

Point ``TEST_DATABASE_URL`` at a throwaway database and run pytest:

    ./scripts/dev-up.sh
    export TEST_DATABASE_URL=postgresql+psycopg://cem_user:change-me@localhost:5432/cem_master_test
    pytest

Without it the whole directory is skipped rather than failing, so a fresh clone
does not look broken. Note that skipped tests protect nothing -- CI must set the
variable, and the report header below says so on every run.
"""

from __future__ import annotations

import os

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "").strip()


def pytest_report_header() -> str:
    if TEST_DATABASE_URL:
        # Never print the URL itself; it carries a password.
        return "cem tests: PostgreSQL configured via TEST_DATABASE_URL"
    return (
        "cem tests: TEST_DATABASE_URL is not set -- database-backed tests "
        f"({', '.join(NEEDS_DATABASE)}) are SKIPPED. "
        "Rollup tests still run. See tests/conftest.py."
    )


# Tests that import the application or touch the database. Everything else --
# notably the indexer's rollup arithmetic -- is pure computation and must stay
# runnable without PostgreSQL, because that is the cheapest and most valuable
# part of the suite to be able to run anywhere.
NEEDS_DATABASE = [
    "test_migrations.py",
    "test_spots.py",
    "test_indexer_writer.py",
]

if not TEST_DATABASE_URL:
    # Skip only the database-dependent modules. Using
    # pytest.skip(allow_module_level=True) inside a conftest instead surfaces as
    # an internal traceback, which reads like a crash rather than a skip.
    collect_ignore = NEEDS_DATABASE

else:
    # Must be set BEFORE importing anything from app: get_settings() is
    # lru_cached and app.database creates the engine at import time.
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    os.environ.setdefault("CORS_ORIGINS", "http://localhost:8000")
    os.environ.setdefault("CEM_MASTER_API_KEY", "")

    from collections.abc import Generator

    import pytest
    from fastapi.testclient import TestClient

    from app.database import Base, engine
    from app.main import app
    import app.models  # noqa: F401  (registers the tables on Base.metadata)

    @pytest.fixture()
    def client() -> Generator[TestClient, None, None]:
        """A client against a freshly built schema.

        Built with ``create_all`` rather than the migration chain because it is
        much faster per test and the schema is identical --
        ``tests/test_migrations.py`` is what guarantees the two agree.
        """
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        try:
            with TestClient(app) as test_client:
                yield test_client
        finally:
            Base.metadata.drop_all(bind=engine)
