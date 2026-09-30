import os
import tempfile

from cryptography.fernet import Fernet

_db_dir = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_db_dir}/test.db"
os.environ["JWT_SECRET"] = "test-secret-that-is-at-least-32-bytes-long"
os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ["TUYA_MODE"] = "mock"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.integrations.tuya import get_tuya_client  # noqa: E402
from app.main import app  # noqa: E402
from app.ratelimit import limiter  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_state():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    get_tuya_client.cache_clear()
    limiter.reset()
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def owner_headers(client):
    client.post("/auth/bootstrap", json={"username": "owner", "password": "password123"})
    token = client.post("/auth/login", json={"username": "owner", "password": "password123"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
