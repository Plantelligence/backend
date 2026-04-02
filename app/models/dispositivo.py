import uuid
from sqlalchemy import Column, String, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from app.db.postgres import Base

class Dispositivo(Base):
    # Criando tabela dispositivos passando a classe Base como parâmetro
    __tablename__ = "dispositivos"

    # colunas da tabela dispositivo
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    nome = Column(String, nullable=False)
    tipo = Column(String, nullable=False)
    identificador = Column(String, unique=True, nullable=False)
    ativo = Column(Boolean, default=True)

    # chave estrangeira para a tabela estufa
    # ondelete="CASCADE" significa que se a estufa for deletada, todos os dispositivos 
    # relacionados a ela serão deletados também
    estufa_id = Column(String, ForeignKey("estufas.id", ondelete="CASCADE"), nullable=False)

    # relacionamento com a tabela estufa
    estufa = relationship("Estufa", back_populates="dispositivos")

    # relacionamento com a tabela alertas
    alertas = relationship("Alertas", back_populates="dispositivo", cascade="all, delete-orphan")

    # relacionamento com a tabela historico
    historicos = relationship("Historico", back_populates="dispositivo", cascade="all, delete-orphan")
    