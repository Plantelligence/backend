import uuid
from sqlalchemy import Column, String, ForeignKey
from sqlalchemy.orm import relationship
from app.db.postgres.Base import Base

class Historico(Base):
    __tablename__ = "historicos"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    acao = Column(String, nullable=False)
    origem = Column(String, nullable=False)
    estufa_id = Column(String, ForeignKey("estufas.id"), nullable=False)
    dispositivo_id = Column(String, ForeignKey("dispositivos.id"), nullable=False)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    estufa = relationship("Estufa", back_populates="historicos")
    dispositivo = relationship("Dispositivo", back_populates="historicos")
    user = relationship("User", back_populates="historicos")