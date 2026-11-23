import pytest
from fastapi.testclient import TestClient

from app.core.config import settings


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """Point the app at an empty data directory for the duration of a test."""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    return tmp_path


@pytest.fixture
def client(data_dir, monkeypatch):
    """API client with forward-auth disabled (every caller is admin)."""
    monkeypatch.setattr(settings, "auth_enabled", False)
    import main

    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def authed_client(data_dir, monkeypatch):
    """API client that enforces Authentik forward-auth headers."""
    monkeypatch.setattr(settings, "auth_enabled", True)
    import main

    with TestClient(main.app) as c:
        yield c
