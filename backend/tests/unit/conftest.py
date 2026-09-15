"""
conftest.py untuk unit tests.

Alias fixtures dari conftest.py level atas agar test_models.py yang
menggunakan nama fixture `session` dan `engine` tidak perlu diubah.

Fixtures yang di-alias:
  session → db_session (dari backend/tests/conftest.py)
  engine  → db_engine  (dari backend/tests/conftest.py)
"""
import pytest


@pytest.fixture
def session(db_session):
    """Alias db_session → session untuk kompatibilitas test_models.py."""
    return db_session


@pytest.fixture(scope="module")
def engine(db_engine):
    """Alias db_engine → engine untuk kompatibilitas test_models.py."""
    return db_engine
