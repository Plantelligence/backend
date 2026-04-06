from __future__ import annotations
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager

from app.config.settings import settings
import app.models  # noqa: F401

# pool_pre_ping descarta conexões quebradas antes de usar
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    connect_args={"connect_timeout": 10},
)

# expire_on_commit=False evita DetachedInstanceError ao serializar objetos após commit
SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


def get_engine():
    return engine

@contextmanager
def get_session() -> Session:
    # sessão para uso fora do ciclo de dependência do FastAPI
    db: Session = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
