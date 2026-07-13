"""Tests for POST /api/v1/integration/threads."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from app.gateway.auth import create_access_token, hash_password
from app.gateway.auth.errors import AuthErrorCode
from app.gateway.auth.models import User
from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.csrf_middleware import CSRFMiddleware
from app.gateway.routers import integration
from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore

_JWT_SECRET = "test-secret-key-for-jwt-testing-minimum-32-chars"


class _MemoryAuthProvider:
    def __init__(self) -> None:
        self._users_by_email: dict[str, User] = {}
        self._users_by_id: dict[str, User] = {}

    async def get_user(self, user_id: str) -> User | None:
        return self._users_by_id.get(user_id)

    async def get_user_by_email(self, email: str) -> User | None:
        return self._users_by_email.get(email.lower())

    async def create_user(self, email: str, password: str | None = None, system_role: str = "user", needs_setup: bool = False) -> User:
        if email.lower() in self._users_by_email:
            raise ValueError("exists")
        user = User(
            email=email.lower(),
            password_hash=hash_password(password or ""),
            system_role=system_role,
            needs_setup=needs_setup,
            id=uuid4(),
        )
        self._users_by_email[user.email] = user
        self._users_by_id[str(user.id)] = user
        return user

    async def authenticate(self, credentials: dict) -> User | None:
        email = (credentials.get("email") or "").lower()
        password = credentials.get("password")
        user = self._users_by_email.get(email)
        if user is None or password is None:
            return None
        from app.gateway.auth import verify_password

        if not verify_password(password, user.password_hash):
            return None
        return user


def _build_app(provider: _MemoryAuthProvider | None = None) -> FastAPI:
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.add_middleware(CSRFMiddleware)
    store = InMemoryStore()
    checkpointer = InMemorySaver()
    app.state.store = store
    app.state.checkpointer = checkpointer
    app.state.thread_store = MemoryThreadMetaStore(store)
    app.include_router(integration.router)
    app.state._test_provider = provider or _MemoryAuthProvider()
    return app


def _set_cookie_headers(response) -> list[str]:
    raw = response.headers.get_list("set-cookie") if hasattr(response.headers, "get_list") else []
    if not raw:
        single = response.headers.get("set-cookie")
        return [single] if single else []
    return raw


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_JWT_SECRET", _JWT_SECRET)
    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "")


@pytest.fixture
def provider() -> _MemoryAuthProvider:
    return _MemoryAuthProvider()


@pytest.fixture
def client(provider: _MemoryAuthProvider) -> TestClient:
    app = _build_app(provider)
    with patch("app.gateway.routers.integration.get_local_provider", return_value=provider), patch(
        "app.gateway.deps.get_local_provider", return_value=provider
    ):
        with TestClient(app) as test_client:
            yield test_client


def test_integration_threads_requires_credentials(client: TestClient) -> None:
    response = client.post("/api/v1/integration/threads", json={"metadata": {}})
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == AuthErrorCode.NOT_AUTHENTICATED


def test_integration_threads_jit_creates_user_thread_and_session_cookies(
    client: TestClient, provider: _MemoryAuthProvider
) -> None:
    response = client.post(
        "/api/v1/integration/threads",
        json={"username": "zhangsan", "password": "Integr8Pass!", "metadata": {"source": "verify"}},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["thread_id"]
    assert body["status"] == "idle"
    assert body["metadata"]["source"] == "verify"
    assert "access_token" not in body
    assert "csrf_token" not in body
    assert "user_id" not in body

    cookies = _set_cookie_headers(response)
    assert any("access_token=" in c for c in cookies)
    assert any("csrf_token=" in c for c in cookies)
    assert response.cookies.get("access_token")
    assert response.cookies.get("csrf_token")

    user = provider._users_by_email["zhangsan@58.com"]
    assert user is not None


def test_integration_threads_valid_token_creates_thread_without_reissue(client: TestClient, provider: _MemoryAuthProvider) -> None:
    user = User(
        email="lisi@58.com",
        password_hash=hash_password("Integr8Pass!"),
        system_role="user",
        id=uuid4(),
    )
    provider._users_by_email[user.email] = user
    provider._users_by_id[str(user.id)] = user
    token = create_access_token(str(user.id), token_version=user.token_version)

    response = client.post(
        "/api/v1/integration/threads",
        cookies={"access_token": token},
        json={"metadata": {}},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["thread_id"]
    assert set(body.keys()) == {"thread_id", "status", "created_at", "updated_at", "metadata", "values", "interrupts"}
    assert "access_token" not in body
    cookies = _set_cookie_headers(response)
    assert not any("access_token=" in c for c in cookies)
    assert any("csrf_token=" in c for c in cookies)


def test_integration_threads_expired_token_only_returns_401(client: TestClient, provider: _MemoryAuthProvider) -> None:
    user_id = str(uuid4())
    token = create_access_token(user_id, expires_delta=timedelta(seconds=-1))
    user = User(email="wangwu@58.com", password_hash="x", system_role="user", id=user_id)
    provider._users_by_id[user_id] = user

    response = client.post(
        "/api/v1/integration/threads",
        cookies={"access_token": token},
        json={},
    )
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == AuthErrorCode.TOKEN_EXPIRED


def test_integration_threads_valid_token_with_password_starts_new_session(
    client: TestClient, provider: _MemoryAuthProvider
) -> None:
    user = User(
        email="validpwd@58.com",
        password_hash=hash_password("Integr8Pass!"),
        system_role="user",
        id=uuid4(),
    )
    provider._users_by_email[user.email] = user
    provider._users_by_id[str(user.id)] = user
    old_token = create_access_token(str(user.id), token_version=user.token_version)

    response = client.post(
        "/api/v1/integration/threads",
        cookies={"access_token": old_token},
        json={"username": "validpwd", "password": "Integr8Pass!"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["thread_id"]
    assert "access_token" not in body
    cookies = _set_cookie_headers(response)
    assert any("access_token=" in c for c in cookies)
    assert any("csrf_token=" in c for c in cookies)
    assert response.cookies.get("access_token")


def test_integration_threads_cookie_token_creates_thread(client: TestClient, provider: _MemoryAuthProvider) -> None:
    user = User(
        email="cookie@58.com",
        password_hash=hash_password("Integr8Pass!"),
        system_role="user",
        id=uuid4(),
    )
    provider._users_by_email[user.email] = user
    provider._users_by_id[str(user.id)] = user
    token = create_access_token(str(user.id), token_version=user.token_version)

    response = client.post(
        "/api/v1/integration/threads",
        cookies={"access_token": token},
        json={},
    )
    assert response.status_code == 200, response.text
    assert response.json()["thread_id"]


def test_integration_threads_expired_token_with_password_recovers(client: TestClient, provider: _MemoryAuthProvider) -> None:
    user = User(
        email="zhaoliu@58.com",
        password_hash=hash_password("Integr8Pass!"),
        system_role="user",
        id=uuid4(),
    )
    provider._users_by_email[user.email] = user
    provider._users_by_id[str(user.id)] = user
    expired = create_access_token(str(user.id), expires_delta=timedelta(seconds=-1), token_version=user.token_version)

    response = client.post(
        "/api/v1/integration/threads",
        cookies={"access_token": expired},
        json={"username": "zhaoliu", "password": "Integr8Pass!"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["thread_id"]
    assert any("access_token=" in c for c in _set_cookie_headers(response))


def test_integration_threads_wrong_password_returns_401(client: TestClient, provider: _MemoryAuthProvider) -> None:
    user = User(
        email="qianqi@58.com",
        password_hash=hash_password("Integr8Pass!"),
        system_role="user",
        id=uuid4(),
    )
    provider._users_by_email[user.email] = user
    provider._users_by_id[str(user.id)] = user

    response = client.post(
        "/api/v1/integration/threads",
        json={"username": "qianqi", "password": "WrongPass12!"},
    )
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == AuthErrorCode.INVALID_CREDENTIALS


def test_cookie_token_allows_protected_routes(client: TestClient, provider: _MemoryAuthProvider) -> None:
    app = client.app
    app.add_api_route("/api/whoami", lambda: {"ok": True}, methods=["GET"])

    user = User(
        email="sunba@58.com",
        password_hash=hash_password("Integr8Pass!"),
        system_role="user",
        id=uuid4(),
    )
    provider._users_by_email[user.email] = user
    provider._users_by_id[str(user.id)] = user
    token = create_access_token(str(user.id), token_version=user.token_version)

    response = client.get("/api/whoami", cookies={"access_token": token})
    assert response.status_code == 200
