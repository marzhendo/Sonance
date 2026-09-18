"""
Auth Guard untuk Sonance API.
Wave 2: Task 3.1.

Implementasi:
  - Token-based auth menggunakan SONANCE_API_TOKEN (ADR-001).
  - Token dikirim via header Authorization: Bearer <token> untuk REST endpoints.
    (Query param hanya dipakai untuk WebSocket, sesuai ADR-002.)
  - Single-user v1: tidak ada multi-tenant, tidak ada JWT expiry/refresh.
  - user_id dikembalikan sebagai string konstan dari config (satu user per instalasi).

Kondisi yang ditangani (Requirement 8):
  1. Token absent (header tidak ada)         → HTTP 401
  2. Token empty (Bearer tanpa value)        → HTTP 401
  3. Token mismatch (tidak cocok env var)    → HTTP 401
  4. Token valid                             → kembalikan user_id

Penggunaan di router:
  @router.get("/voice-profiles")
  async def list_profiles(user_id: str = Depends(verify_token)):
      ...

Override di tests:
  app.dependency_overrides[verify_token] = lambda: "test-user-id"
"""
import os
import secrets

from fastapi import Header, HTTPException, status


_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Token autentikasi tidak valid atau tidak ada.",
    headers={"WWW-Authenticate": "Bearer"},
)


async def verify_token(authorization: str = Header(default=None)) -> str:
    """
    FastAPI dependency: validasi API token dari header Authorization.

    Returns:
        user_id (str): identifier user yang terautentikasi.

    Raises:
        HTTPException 401: jika token absent, empty, atau tidak cocok.
    """
    expected_token = os.environ.get("SONANCE_API_TOKEN", "")

    # Kondisi 1: header tidak ada sama sekali
    if authorization is None:
        raise _UNAUTHORIZED

    # Parse "Bearer <token>"
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise _UNAUTHORIZED

    provided_token = parts[1]

    # Kondisi 2: token kosong setelah "Bearer "
    if not provided_token:
        raise _UNAUTHORIZED

    # Kondisi 3 & 4: compare dengan constant-time comparison untuk mencegah timing attack
    if not expected_token or not secrets.compare_digest(provided_token, expected_token):
        raise _UNAUTHORIZED

    # Single-user v1: user_id dikembalikan sebagai fixed identifier.
    # Saat multi-user diimplementasikan, ganti ini dengan lookup dari DB.
    return _get_user_id()


def _get_user_id() -> str:
    """
    Kembalikan user_id untuk single-user v1.
    Bisa dikonfigurasi via env var SONANCE_USER_ID, atau default ke "default-user".
    """
    return os.environ.get("SONANCE_USER_ID", "default-user")
