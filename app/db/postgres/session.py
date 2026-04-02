from __future__ import annotations
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager

from app.config.settings import settings

# Engine que dita como nossa aplicacao conecta no Postgres do Azure.
# A gente mandou um pool_pre_ping ai no meio pq qnd a database reseta no cloud 
# a porta fecha mas o back as vezes tenta a antiga e crasha, isso contorna.
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    connect_args={"connect_timeout": 10},
)

# Sessao base do SQLAlchemy p instanciar conexoes a partir dela...
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

@contextmanager
def get_session() -> Session:
    # Usado as vezes qnd precisamos gerar sessao assincrona ou rodando 
    # via CLI/background jobs, nao dependendo do FastAPI fazer o bind (db: Session)
    db: Session = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
