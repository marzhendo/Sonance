import os
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


# Engine dan session factory dikonfigurasi saat runtime via SONANCE_DATABASE_URL.
# Untuk keperluan testing, engine di-override lewat fixture conftest.py.
def make_engine(database_url: str):
    """Buat SQLAlchemy engine dari URL yang diberikan."""
    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    return create_engine(database_url, connect_args=connect_args)


def make_session_factory(engine):
    """Buat session factory yang terikat ke engine tertentu."""
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


_session_factory = None


def get_session_factory():
    """Mengembalikan session factory default aplikasi."""
    global _session_factory
    if _session_factory is None:
        database_url = os.environ.get("SONANCE_DATABASE_URL", "sqlite:///./sonance.db")
        engine = make_engine(database_url)
        _session_factory = make_session_factory(engine)
    return _session_factory


def get_db() -> Generator[Session, None, None]:
    """Dependency FastAPI untuk menyediakan session database."""
    factory = get_session_factory()
    db = factory()
    try:
        yield db
    finally:
        db.close()

