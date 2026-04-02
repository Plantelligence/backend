import uuid
from sqlalchemy import Column, String, ForeignKey
from sqlalchemy.orm import relationship
from app.db.postgres.Base import Base

# Esse salva no postgres os alertas do clima/sensores que ficam salvos apos serem emitidos.
class Alertas(Base):
    __tablename__ = "alertas"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Info, geada, fogo..
    tipo = Column(String, nullable=False)
    # A mensagem amigavel q botamos pro app renderizar vermelho.
    mensagem = Column(String, nullable=False)
    
    # De onde veio as origens disso e qm mandou.
    estufa_id = Column(String, ForeignKey("estufas.id"), nullable=False)
    dispositivo_id = Column(String, ForeignKey("dispositivos.id"), nullable=False)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    
    # Setup de conexao de populates bidirecional do sqlalchemy pra pydantic lidar melhor com orm mode dps.
    estufa = relationship("Estufa", back_populates="alertas")
    dispositivo = relationship("Dispositivo", back_populates="alertas")
    user = relationship("User", back_populates="alertas")