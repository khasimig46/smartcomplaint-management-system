import pytest

import routes.complaint_routes as cr
import services.auth as auth
from app import create_app


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(cr, "STORE", tmp_path / "store.json")
    monkeypatch.setattr(cr, "UPLOADS", tmp_path / "uploads")
    monkeypatch.setattr(auth, "USERS", tmp_path / "users.json")
    app = create_app()
    app.config.update(TESTING=True, SECRET_KEY="test-secret")
    return app


@pytest.fixture
def make_user(app):
    def _make(role="citizen", email=None, password="password123", **kw):
        email = email or f"{role}{len(auth.load_users())}@test.com"
        with app.app_context():
            return auth.create_user(kw.pop("name", role.title()), email, password, role=role, **kw)
    return _make


@pytest.fixture
def login(app):
    def _login(email, password="password123"):
        r = app.test_client().post("/auth/login", json={"email": email, "password": password})
        return {"Authorization": f"Bearer {r.get_json()['token']}"}
    return _login


@pytest.fixture
def citizen(make_user, login):
    """Auth headers for a logged-in citizen."""
    u = make_user("citizen", email="citizen@test.com")
    return login(u["email"])


def complaint_body(**overrides):
    body = {"title": "Water leakage", "description": "Water is leaking from the main pipe", "severity": "High"}
    body.update(overrides)
    return body
