import os
import tempfile

from cryptography.fernet import Fernet

_db_dir = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_db_dir}/test.db"
os.environ["CATALOG_DATABASE_URL"] = f"sqlite:///{_db_dir}/catalog/catalog.db"
os.environ["JWT_SECRET"] = "test-secret-that-is-at-least-32-bytes-long"
os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ["TUYA_MODE"] = "mock"

from app.config import Settings  # noqa: E402

# Tests must not pick up the owner's real backend/.env (API keys, voice tuning).
Settings.model_config["env_file"] = None

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import catalog_models  # noqa: E402,F401  (register catalog tables)
from app.db import Base, CatalogBase, catalog_engine, engine  # noqa: E402
from app.integrations.tuya import get_tuya_client  # noqa: E402
from app.main import app  # noqa: E402
from app.ratelimit import limiter  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_state():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    CatalogBase.metadata.drop_all(catalog_engine)
    CatalogBase.metadata.create_all(catalog_engine)
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
