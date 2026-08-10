import os
import tempfile
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
db_file.close()

os.environ["DATABASE_URL"] = f"sqlite:///{db_file.name}"
os.environ["CORS_ORIGINS"] = "http://localhost:8000"
os.environ["CEM_MASTER_API_KEY"] = ""

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    with TestClient(app) as test_client:
        yield test_client


def pytest_sessionfinish(session, exitstatus):
    try:
        os.unlink(db_file.name)
    except FileNotFoundError:
        pass
