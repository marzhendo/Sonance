"""
Tests untuk Auth Guard.
Wave 2: Task 3.1.

Tests ini gagal dulu (Red), lalu auth guard diimplementasikan (Green).
"""
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers: buat mini app untuk test dependency
# ---------------------------------------------------------------------------

def make_app(token_override: str | None = None):
    """
    Buat FastAPI app minimal dengan satu route yang di-protect auth guard.
    token_override: jika diberikan, set env var SONANCE_API_TOKEN ke nilai ini.
    """
    if token_override is not None:
        os.environ["SONANCE_API_TOKEN"] = token_override
    elif "SONANCE_API_TOKEN" not in os.environ:
        os.environ["SONANCE_API_TOKEN"] = "test-secret-token"

    from backend.app.core.auth import verify_token
    app = FastAPI()

    @app.get("/protected")
    async def protected_route(user_id: str = pytest.importorskip("fastapi").Depends(verify_token)):
        return {"user_id": user_id, "ok": True}

    return app


# ===========================================================================
# Auth Guard Tests
# ===========================================================================

class TestVerifyToken:
    """
    Test dependency `verify_token` via FastAPI TestClient.
    Semua kondisi dari Requirement 8.
    """

    VALID_TOKEN = "test-secret-token"

    @pytest.fixture(autouse=True)
    def set_env(self, monkeypatch):
        """Set SONANCE_API_TOKEN sebelum setiap test."""
        monkeypatch.setenv("SONANCE_API_TOKEN", self.VALID_TOKEN)
        # Force re-import agar env var baru terpakai
        import importlib
        import backend.app.core.auth as auth_mod
        importlib.reload(auth_mod)

    def _client(self) -> TestClient:
        from backend.app.core.auth import verify_token
        from fastapi import Depends
        app = FastAPI()

        @app.get("/protected")
        async def route(user_id: str = Depends(verify_token)):
            return {"user_id": user_id, "ok": True}

        return TestClient(app, raise_server_exceptions=False)

    # --- Valid token ---

    def test_valid_token_returns_200(self):
        client = self._client()
        resp = client.get(
            "/protected",
            headers={"Authorization": f"Bearer {self.VALID_TOKEN}"},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_valid_token_returns_user_id(self):
        """verify_token harus mengembalikan user_id (string non-empty)."""
        client = self._client()
        resp = client.get(
            "/protected",
            headers={"Authorization": f"Bearer {self.VALID_TOKEN}"},
        )
        assert resp.status_code == 200
        assert resp.json()["user_id"]  # tidak kosong

    # --- Token absent ---

    def test_missing_authorization_header_returns_401(self):
        """Request tanpa header Authorization harus 401."""
        client = self._client()
        resp = client.get("/protected")
        assert resp.status_code == 401

    def test_missing_header_response_has_detail(self):
        client = self._client()
        resp = client.get("/protected")
        assert "detail" in resp.json()

    # --- Token empty ---

    def test_empty_bearer_token_returns_401(self):
        """Authorization: Bearer (tanpa token) harus 401."""
        client = self._client()
        resp = client.get("/protected", headers={"Authorization": "Bearer "})
        assert resp.status_code == 401

    def test_empty_string_token_returns_401(self):
        """Authorization: Bearer '' harus 401."""
        client = self._client()
        resp = client.get("/protected", headers={"Authorization": "Bearer"})
        assert resp.status_code == 401

    # --- Token mismatch ---

    def test_wrong_token_returns_401(self):
        """Token yang tidak cocok dengan SONANCE_API_TOKEN harus 401."""
        client = self._client()
        resp = client.get(
            "/protected",
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert resp.status_code == 401

    def test_almost_correct_token_returns_401(self):
        """Token yang hampir benar (satu karakter beda) harus 401."""
        client = self._client()
        almost = self.VALID_TOKEN[:-1] + "X"
        resp = client.get(
            "/protected",
            headers={"Authorization": f"Bearer {almost}"},
        )
        assert resp.status_code == 401

    def test_token_with_extra_space_returns_401(self):
        """Token dengan trailing space harus 401: tidak ada whitespace tolerance."""
        client = self._client()
        resp = client.get(
            "/protected",
            headers={"Authorization": f"Bearer {self.VALID_TOKEN} "},
        )
        assert resp.status_code == 401

    # --- Header format ---

    def test_non_bearer_scheme_returns_401(self):
        """Authorization: Basic ... harus 401."""
        client = self._client()
        resp = client.get(
            "/protected",
            headers={"Authorization": f"Basic {self.VALID_TOKEN}"},
        )
        assert resp.status_code == 401

    def test_raw_token_without_bearer_returns_401(self):
        """Token tanpa prefix 'Bearer ' harus 401."""
        client = self._client()
        resp = client.get(
            "/protected",
            headers={"Authorization": self.VALID_TOKEN},
        )
        assert resp.status_code == 401

    # --- 401 response shape ---

    def test_401_response_is_json(self):
        client = self._client()
        resp = client.get("/protected")
        assert resp.headers["content-type"].startswith("application/json")

    def test_401_has_detail_field(self):
        """Response 401 harus punya field 'detail'."""
        client = self._client()
        resp = client.get("/protected")
        body = resp.json()
        assert "detail" in body


class TestVerifyTokenAsDepends:
    """
    Verifikasi bahwa verify_token bisa dipakai sebagai FastAPI Depends
    dan bisa di-override di tests.
    """

    def test_dependency_overrideable(self):
        """verify_token harus bisa di-override via app.dependency_overrides."""
        from fastapi import Depends
        from backend.app.core.auth import verify_token

        app = FastAPI()

        @app.get("/route")
        async def route(user_id: str = Depends(verify_token)):
            return {"user_id": user_id}

        # Override dependency untuk test
        app.dependency_overrides[verify_token] = lambda: "test-user-id"

        client = TestClient(app)
        resp = client.get("/route")
        assert resp.status_code == 200
        assert resp.json()["user_id"] == "test-user-id"

    def test_verify_token_is_async_callable(self):
        """verify_token harus berupa async function (coroutine)."""
        import inspect
        from backend.app.core.auth import verify_token
        assert inspect.iscoroutinefunction(verify_token)
