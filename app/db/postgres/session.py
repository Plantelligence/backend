"""Gerenciamento de sessoes do SQLAlchemy com inicializacao postergada do engine."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlalchemy.orm import Session

_engine = None
_session_local = None


def get_engine():
    """Inicializa o engine do banco na primeira chamada e reutiliza nas seguintes."""
    global _engine, _session_local
    if _engine is None:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.config.settings import settings

        try:
            _engine = create_engine(
                settings.database_url,
                pool_pre_ping=True,
                pool_size=10,
                max_overflow=20,
                connect_args={"connect_timeout": 10},
            )
            _session_local = sessionmaker(
                bind=_engine, autocommit=False, autoflush=False
            )
            print(f"[db] Engine criado: {settings.database_url[:40]}...")
        except Exception as exc:
            print(f"[db] ERRO ao criar engine: {exc}")
            raise RuntimeError(f"Banco de dados indisponivel: {exc}") from exc

    return _engine


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Abre uma sessao do banco, faz commit ao sair e rollback em caso de erro."""
    if _session_local is None:
        get_engine()

    db: Session = _session_local()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


class _LazyEngine:
    """Proxy para o engine do SQLAlchemy, inicializado sob demanda no primeiro acesso."""

    def __getattr__(self, name: str):
        return getattr(get_engine(), name)

    def __repr__(self) -> str:
        return repr(get_engine())


engine = _LazyEngine()
