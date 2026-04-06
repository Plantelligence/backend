import uuid
from sqlalchemy import Column, String, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from app.db.postgres.Base import Base

class Dispositivo(Base):
    # Tabela de dispositivos da estufa.
    __tablename__ = "dispositivos"

    # Campos principais.
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    nome = Column(String, nullable=False)
    tipo = Column(String, nullable=False)
    identificador = Column(String, unique=True, nullable=False)
    ativo = Column(Boolean, default=True)

    # Relacao com estufa; exclusao em cascata.
    estufa_id = Column(String, ForeignKey("estufas.id", ondelete="CASCADE"), nullable=False)

    # Relacionamentos ORM.
    estufa = relationship("Estufa", back_populates="dispositivos")

    alertas = relationship("Alertas", back_populates="dispositivo", cascade="all, delete-orphan")

    historicos = relationship("Historico", back_populates="dispositivo", cascade="all, delete-orphan")
    